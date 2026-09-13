import io
import json
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

import database.db as db
from database.db import CATEGORIES
from services import gemini
from services.gemini import _generate as real_generate

DEMO = {"email": "demo@spendly.com", "password": "demo123"}
NITISH = {"name": "Nitish Kumar", "email": "nitish@example.com", "password": "password123"}
TODAY = date(2026, 9, 12)
UBER_REPLY = {
    "amount": 23.5,
    "category": "Transport",
    "date": "2026-09-11",
    "description": "Uber ride",
}
BUSY = "Gemini is busy right now. Try again in a minute."


def sign_in(client):
    return client.post("/login", data=DEMO)


def sign_in_new_user(client):
    client.post("/register", data=NITISH)
    return client.post(
        "/login", data={"email": NITISH["email"], "password": NITISH["password"]}
    )


def demo_user_id():
    return db.get_user_by_email(DEMO["email"])["id"]


def expense_section(response):
    section = response.data.split(b'class="expense-section"', 1)[1]
    return section.split(b"</section>", 1)[0]


def input_tag(section, field_id):
    return section.split(f'id="{field_id}"'.encode(), 1)[1].split(b">", 1)[0]


def expense_count():
    conn = db.get_db()
    count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    conn.close()
    return count


def ai_request_rows():
    conn = db.get_db()
    rows = conn.execute("SELECT user_id, source FROM ai_requests ORDER BY id").fetchall()
    conn.close()
    return [tuple(row) for row in rows]


def autofill_note(client, note="Spent 23.50 on an Uber yesterday", **fields):
    return client.post("/expenses/autofill", data={"note": note, **fields})


def autofill_receipt(client, image=b"fake image bytes", filename="receipt.jpg", mime_type="image/jpeg"):
    return client.post(
        "/expenses/autofill",
        data={"receipt": (io.BytesIO(image), filename, mime_type)},
        content_type="multipart/form-data",
    )


class FakeGemini:
    def __init__(self):
        self.calls = []
        self.reply = json.dumps(UBER_REPLY)

    def __call__(self, contents, today):
        self.calls.append((contents, today))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def fake_gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini, "_generate", fake)
    return fake


class FakeModels:
    def __init__(self):
        self.outcome = '{"amount": 1}'
        self.request = None

    def generate_content(self, **request):
        self.request = request
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return SimpleNamespace(text=self.outcome)


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    state = {"options": None, "models": FakeModels()}

    def make_client(**options):
        state["options"] = options
        return SimpleNamespace(models=state["models"])

    monkeypatch.setattr(gemini.genai, "Client", make_client)
    return state


# ------------------------------------------------------------------ #
# Cleaning model output                                                #
# ------------------------------------------------------------------ #

def test_a_complete_reply_fills_every_field():
    assert gemini.normalize_expense(UBER_REPLY, TODAY) == {
        "amount": "23.50",
        "category": "Transport",
        "date": "2026-09-11",
        "description": "Uber ride",
    }


@pytest.mark.parametrize("amount, expected", [(12, "12.00"), (9.999, "10.00"), (1000000, "1000000.00")])
def test_amounts_are_formatted_to_two_places(amount, expected):
    assert gemini.normalize_expense({"amount": amount}, TODAY)["amount"] == expected


@pytest.mark.parametrize(
    "amount", [None, "23.50", True, 0, 0.004, -5, 1000000.01, float("nan"), float("inf")]
)
def test_unusable_amounts_are_left_blank(amount):
    assert gemini.normalize_expense({"amount": amount}, TODAY)["amount"] == ""


@pytest.mark.parametrize("category", ["Groceries", "food", None, ["Food"]])
def test_unknown_categories_are_left_blank(category):
    assert gemini.normalize_expense({"category": category}, TODAY)["category"] == ""


@pytest.mark.parametrize("value", [None, "", "yesterday", "2026-02-30", "09/11/2026", 20260911])
def test_unusable_dates_fall_back_to_today(value):
    assert gemini.normalize_expense({"date": value}, TODAY)["date"] == "2026-09-12"


def test_unpadded_dates_are_normalised():
    assert gemini.normalize_expense({"date": "2026-9-1"}, TODAY)["date"] == "2026-09-01"


def test_descriptions_are_tidied_and_capped_at_200_characters():
    def description(value):
        return gemini.normalize_expense({"description": value}, TODAY)["description"]

    assert description("  Uber \n ride  ") == "Uber ride"
    assert description("x" * 250) == "x" * 200
    assert description(42) == ""


# ------------------------------------------------------------------ #
# Extraction                                                           #
# ------------------------------------------------------------------ #

def test_note_is_sent_with_the_date(fake_gemini):
    values = gemini.extract_from_note("Spent 23.50 on an Uber yesterday", TODAY)

    assert values["amount"] == "23.50"
    contents, today = fake_gemini.calls[0]
    assert "Spent 23.50 on an Uber yesterday" in contents[0]
    assert today == TODAY


def test_receipt_is_sent_as_an_inline_image(fake_gemini):
    gemini.extract_from_receipt(b"fake image bytes", "image/png", TODAY)

    part = fake_gemini.calls[0][0][0]
    assert part.inline_data.data == b"fake image bytes"
    assert part.inline_data.mime_type == "image/png"


@pytest.mark.parametrize("reply", [None, "", "not json", "[1, 2]", '"Food"'])
def test_replies_that_are_not_a_json_object_raise(fake_gemini, reply):
    fake_gemini.reply = reply

    with pytest.raises(gemini.AutofillError, match="couldn't read that"):
        gemini.extract_from_note("Lunch", TODAY)


def test_a_reply_with_no_amount_or_description_raises(fake_gemini):
    fake_gemini.reply = json.dumps(
        {"amount": None, "category": "Other", "date": None, "description": None}
    )

    with pytest.raises(gemini.AutofillError, match="couldn't find an expense"):
        gemini.extract_from_note("hello there", TODAY)


# ------------------------------------------------------------------ #
# Gemini request                                                       #
# ------------------------------------------------------------------ #

def test_request_uses_the_key_timeout_schema_and_date(fake_client):
    assert real_generate(["Lunch"], TODAY) == '{"amount": 1}'

    assert fake_client["options"]["api_key"] == "test-key"
    assert fake_client["options"]["http_options"].timeout == gemini.TIMEOUT_MS
    request = fake_client["models"].request
    assert request["model"] == gemini.DEFAULT_MODEL
    assert request["contents"] == ["Lunch"]
    config = request["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["category"]["enum"] == CATEGORIES
    assert "Today is Saturday, 2026-09-12." in config.system_instruction
    assert config.automatic_function_calling.disable is True


def test_model_can_be_overridden(fake_client, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")

    real_generate(["Lunch"], TODAY)
    assert fake_client["models"].request["model"] == "gemini-test-model"


@pytest.mark.parametrize(
    "failure, message",
    [
        (errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), "busy right now"),
        (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT"}}), "couldn't read that"),
        (errors.ServerError(503, {"error": {"status": "UNAVAILABLE"}}), "couldn't read that"),
        (httpx.ReadTimeout("timed out"), "couldn't read that"),
        (httpx.ConnectError("no network"), "couldn't read that"),
    ],
)
def test_api_failures_become_friendly_errors(fake_client, failure, message):
    fake_client["models"].outcome = failure

    with pytest.raises(gemini.AutofillError, match=message):
        real_generate(["Lunch"], TODAY)


@pytest.mark.parametrize("key, enabled", [("", False), ("test-key", True)])
def test_autofill_is_enabled_only_with_a_key(monkeypatch, key, enabled):
    monkeypatch.setenv("GEMINI_API_KEY", key)

    assert gemini.is_enabled() is enabled


# ------------------------------------------------------------------ #
# Access and setup                                                     #
# ------------------------------------------------------------------ #

def test_signed_out_autofill_redirects_to_login(client, fake_gemini):
    response = autofill_note(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert fake_gemini.calls == []


def test_add_expense_page_hides_autofill_without_a_key(client):
    sign_in(client)

    response = client.get("/expenses/add")
    assert b'action="/expenses/autofill"' not in response.data
    assert b'action="/expenses/add"' in response.data


def test_autofill_without_a_key_shows_an_error(client):
    sign_in(client)

    response = autofill_note(client)
    assert response.status_code == 200
    assert b"AI autofill isn&#39;t available right now." in response.data
    assert ai_request_rows() == []


def test_add_expense_page_shows_both_autofill_forms_with_a_key(client, fake_gemini):
    sign_in(client)

    section = expense_section(client.get("/expenses/add"))
    assert section.count(b'action="/expenses/autofill"') == 2
    assert b'enctype="multipart/form-data"' in section
    assert b'type="file" id="receipt" name="receipt"' in section
    assert b'maxlength="300"' in input_tag(section, "note")
    assert section.count(b'name="today"') == 2
    assert b'action="/expenses/add"' in section
    assert b"autofill-notice" not in section
    assert b"autofill-error" not in section


def test_validation_errors_keep_the_autofill_panel(client, fake_gemini):
    sign_in(client)

    response = client.post(
        "/expenses/add", data={"amount": "abc", "category": "Food", "date": "2026-09-05"}
    )
    assert b"expense-error" in response.data
    assert b'action="/expenses/autofill"' in response.data


# ------------------------------------------------------------------ #
# Filling the form                                                     #
# ------------------------------------------------------------------ #

def test_note_fills_the_form_without_saving(client, fake_gemini):
    sign_in(client)
    before = expense_count()

    response = autofill_note(client)

    assert response.status_code == 200
    section = expense_section(response)
    assert b'value="23.50"' in input_tag(section, "amount")
    assert b'<option value="Transport" selected>' in section
    assert b'value="2026-09-11"' in input_tag(section, "date")
    assert b'value="Uber ride"' in input_tag(section, "description")
    assert b'value="Spent 23.50 on an Uber yesterday"' in input_tag(section, "note")
    assert b"Filled in from your description." in section
    assert expense_count() == before


def test_receipt_photo_is_sent_to_gemini(client, fake_gemini):
    sign_in(client)

    response = autofill_receipt(
        client, image=b"\x89PNG fake", filename="receipt.png", mime_type="image/png"
    )

    part = fake_gemini.calls[0][0][0]
    assert part.inline_data.data == b"\x89PNG fake"
    assert part.inline_data.mime_type == "image/png"
    assert b"Filled in from your receipt." in response.data
    assert b'value="23.50"' in input_tag(expense_section(response), "amount")


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_browser_date_is_used_when_close_to_the_server_date(client, fake_gemini, offset):
    sign_in(client)
    browser_today = date.today() + timedelta(days=offset)

    autofill_note(client, today=browser_today.isoformat())
    assert fake_gemini.calls[0][1] == browser_today


@pytest.mark.parametrize(
    "value", ["", "not-a-date", "2000-01-01", (date.today() + timedelta(days=2)).isoformat()]
)
def test_other_browser_dates_fall_back_to_the_server_date(client, fake_gemini, value):
    sign_in(client)

    autofill_note(client, today=value)
    assert fake_gemini.calls[0][1] == date.today()


def test_unusable_model_output_is_blanked_and_escaped(client, fake_gemini):
    fake_gemini.reply = json.dumps(
        {
            "amount": "lots",
            "category": "Groceries",
            "date": "someday",
            "description": "<script>alert(1)</script>",
        }
    )
    sign_in(client)

    section = expense_section(autofill_note(client))
    assert b'value=""' in input_tag(section, "amount")
    assert b" selected>" not in section
    assert f'value="{date.today().isoformat()}"'.encode() in input_tag(section, "date")
    assert b"<script>alert(1)</script>" not in section
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in input_tag(section, "description")


def test_gemini_errors_are_shown_and_the_form_still_works(client, fake_gemini):
    fake_gemini.reply = gemini.AutofillError(BUSY)
    sign_in(client)

    section = expense_section(autofill_note(client))
    assert b"autofill-error" in section
    assert BUSY.encode() in section
    assert b"autofill-notice" not in section
    assert b'action="/expenses/add"' in section
    assert f'value="{date.today().isoformat()}"'.encode() in input_tag(section, "date")
    assert b'value="Spent 23.50 on an Uber yesterday"' in input_tag(section, "note")


# ------------------------------------------------------------------ #
# Validation                                                           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("mime_type", ["application/pdf", "image/gif", "text/plain"])
def test_unsupported_files_are_rejected(client, fake_gemini, mime_type):
    sign_in(client)

    response = autofill_receipt(client, filename="receipt.pdf", mime_type=mime_type)
    assert b"Choose a JPEG, PNG, WebP or HEIC photo." in response.data
    assert fake_gemini.calls == []


def test_empty_photo_is_rejected(client, fake_gemini):
    sign_in(client)

    response = autofill_receipt(client, image=b"")
    assert b"That photo is empty." in response.data
    assert fake_gemini.calls == []


@pytest.mark.parametrize("note", ["", "   "])
def test_blank_submission_is_rejected(client, fake_gemini, note):
    sign_in(client)

    response = autofill_note(client, note=note)
    assert b"Choose a receipt photo or describe the expense." in response.data
    assert fake_gemini.calls == []


def test_note_length_is_capped_at_300_characters(client, fake_gemini):
    sign_in(client)

    response = autofill_note(client, note="x" * 301)
    assert b"Keep the description to 300 characters or fewer." in response.data
    assert fake_gemini.calls == []

    autofill_note(client, note="x" * 300)
    assert len(fake_gemini.calls) == 1


def test_oversized_photo_gets_a_413_with_a_message(client, fake_gemini):
    sign_in(client)

    response = autofill_receipt(client, image=b"x" * (gemini.MAX_RECEIPT_MB * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert b"Receipt photos must be 4 MB or smaller." in response.data
    assert b'action="/expenses/add"' in response.data
    assert fake_gemini.calls == []


# ------------------------------------------------------------------ #
# Daily limit                                                          #
# ------------------------------------------------------------------ #

def test_requests_are_logged_per_user_and_source(client, fake_gemini):
    sign_in(client)

    autofill_note(client)
    autofill_receipt(client)
    assert ai_request_rows() == [(demo_user_id(), "note"), (demo_user_id(), "receipt")]


def test_rejected_submissions_are_not_counted(client, fake_gemini):
    sign_in(client)

    autofill_note(client, note="")
    autofill_receipt(client, mime_type="application/pdf")
    assert ai_request_rows() == []


def test_daily_limit_stops_further_requests(client, fake_gemini, monkeypatch):
    monkeypatch.setattr(gemini, "DAILY_LIMIT", 2)
    sign_in(client)

    fake_gemini.reply = gemini.AutofillError(BUSY)
    autofill_note(client)
    fake_gemini.reply = json.dumps(UBER_REPLY)
    autofill_note(client)

    response = autofill_note(client)
    assert b"You&#39;ve used all 2 AI autofills for today." in response.data
    assert len(fake_gemini.calls) == 2


def test_daily_limit_is_per_user(client, fake_gemini, monkeypatch):
    monkeypatch.setattr(gemini, "DAILY_LIMIT", 1)
    sign_in(client)
    autofill_note(client)
    client.get("/logout")

    sign_in_new_user(client)
    response = autofill_note(client)
    assert b"Filled in from your description." in response.data


def test_yesterdays_requests_do_not_count(client, fake_gemini, monkeypatch):
    monkeypatch.setattr(gemini, "DAILY_LIMIT", 1)
    sign_in(client)
    conn = db.get_db()
    conn.execute(
        "INSERT INTO ai_requests (user_id, source, created_at) "
        "VALUES (?, 'note', datetime('now', '-1 day'))",
        (demo_user_id(),),
    )
    conn.commit()
    conn.close()

    response = autofill_note(client)
    assert b"Filled in from your description." in response.data


# ------------------------------------------------------------------ #
# Markup                                                               #
# ------------------------------------------------------------------ #

def test_no_hex_colours_on_the_autofill_panel(client, fake_gemini):
    sign_in(client)

    for response in (
        client.get("/expenses/add"),
        autofill_note(client),
        autofill_note(client, note=""),
    ):
        section = expense_section(response)
        assert b"autofill-card" in section
        assert b"#" not in section.replace(b"&#", b"")
