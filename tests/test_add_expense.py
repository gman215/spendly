from datetime import date

import pytest

import database.db as db

DEMO = {"email": "demo@spendly.com", "password": "demo123"}
NITISH = {"name": "Nitish Kumar", "email": "nitish@example.com", "password": "password123"}


def sign_in(client):
    return client.post("/login", data=DEMO)


def sign_in_new_user(client):
    client.post("/register", data=NITISH)
    return client.post(
        "/login", data={"email": NITISH["email"], "password": NITISH["password"]}
    )


def demo_user_id():
    return db.get_user_by_email(DEMO["email"])["id"]


def expense_form(**overrides):
    return {
        "amount": "12.34",
        "category": "Food",
        "date": date.today().isoformat(),
        "description": "Coffee beans",
        **overrides,
    }


def expense_count():
    conn = db.get_db()
    count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    conn.close()
    return count


def latest_expense():
    conn = db.get_db()
    row = conn.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row


def profile_section(response):
    section = response.data.split(b'class="profile-section"', 1)[1]
    return section.split(b"</section>", 1)[0]


def expense_section(response):
    section = response.data.split(b'class="expense-section"', 1)[1]
    return section.split(b"</section>", 1)[0]


def transaction_rows(response):
    body = profile_section(response).split(b"<tbody>", 1)[1]
    return body.split(b"</tbody>", 1)[0].count(b"<tr>")


def stat_value(text):
    return f'<span class="profile-stat-value">{text}</span>'.encode()


# ------------------------------------------------------------------ #
# Access control                                                       #
# ------------------------------------------------------------------ #

def test_get_add_expense_redirects_when_signed_out(client):
    response = client.get("/expenses/add")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_post_add_expense_redirects_when_signed_out_and_inserts_nothing(client):
    before = expense_count()

    response = client.post("/expenses/add", data=expense_form())

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert expense_count() == before


# ------------------------------------------------------------------ #
# Form                                                                 #
# ------------------------------------------------------------------ #

def test_get_add_expense_renders_the_form(client):
    sign_in(client)

    response = client.get("/expenses/add")
    assert response.status_code == 200
    assert b'action="/expenses/add"' in response.data
    for field in (b'name="amount"', b'name="category"', b'name="date"', b'name="description"'):
        assert field in response.data
    assert f'value="{date.today().isoformat()}"'.encode() in response.data
    assert b"Choose a category" in response.data
    assert b"expense-error" not in response.data
    assert b'href="/profile"' in expense_section(response)


def test_categories_are_listed_in_order(client):
    sign_in(client)

    data = client.get("/expenses/add").data
    positions = [
        data.index(f'<option value="{category}"'.encode())
        for category in ("Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other")
    ]
    assert positions == sorted(positions)


# ------------------------------------------------------------------ #
# Adding an expense                                                    #
# ------------------------------------------------------------------ #

def test_valid_expense_redirects_to_profile_with_notice(client):
    sign_in(client)

    response = client.post("/expenses/add", data=expense_form())
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile?added=1"
    assert b"Expense added." in client.get(response.headers["Location"]).data


def test_valid_expense_is_stored_for_the_signed_in_user(client):
    sign_in(client)

    client.post("/expenses/add", data=expense_form())

    row = latest_expense()
    assert row["user_id"] == demo_user_id()
    assert row["amount"] == 12.34
    assert row["category"] == "Food"
    assert row["date"] == date.today().isoformat()
    assert row["description"] == "Coffee beans"


def test_profile_reflects_the_new_expense(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form())

    response = client.get("/profile")
    section = profile_section(response)
    assert b"$475.00" in section
    assert stat_value(9) in section
    assert stat_value("Bills") in section
    assert transaction_rows(response) == 9
    assert b"Coffee beans" in section
    assert b"$12.34" in section
    assert b"$108.76" in section


def test_a_large_expense_can_change_the_top_category(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form(amount="150", category="Shopping"))

    section = profile_section(client.get("/profile"))
    assert stat_value("Shopping") in section
    assert b"$612.66" in section
    assert b"$239.99" in section


def test_refreshing_the_profile_does_not_add_again(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form())

    client.get("/profile?added=1")
    client.get("/profile?added=1")
    assert expense_count() == 9


def test_blank_description_is_stored_as_null_and_shown_as_a_dash(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form(description="   "))

    assert latest_expense()["description"] is None
    assert '<td class="txn-desc">—</td>'.encode() in profile_section(client.get("/profile"))


def test_back_dated_expense_is_listed_last_and_filterable(client):
    sign_in(client)
    client.post(
        "/expenses/add", data=expense_form(date="2000-01-01", description="Ancient receipt")
    )

    section = profile_section(client.get("/profile"))
    assert section.index(b"Ancient receipt") > section.index(b"Groceries at Trader Joe")

    response = client.get("/profile?start_date=2000-01-01&end_date=2000-01-01")
    assert transaction_rows(response) == 1
    assert b"Ancient receipt" in profile_section(response)


def test_unpadded_date_is_normalised(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form(date="2026-9-1"))

    assert latest_expense()["date"] == "2026-09-01"


def test_whitespace_is_stripped(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form(amount="  12.50  ", description="  Lunch  "))

    row = latest_expense()
    assert row["amount"] == 12.5
    assert row["description"] == "Lunch"


def test_maximum_amount_is_accepted(client):
    sign_in(client)

    response = client.post("/expenses/add", data=expense_form(amount="1000000"))
    assert response.status_code == 302
    assert latest_expense()["amount"] == 1000000


def test_200_character_description_is_accepted(client):
    sign_in(client)

    response = client.post("/expenses/add", data=expense_form(description="x" * 200))
    assert response.status_code == 302
    assert latest_expense()["description"] == "x" * 200


# ------------------------------------------------------------------ #
# Validation                                                           #
# ------------------------------------------------------------------ #

def assert_rejected(client, form, message):
    before = expense_count()
    response = client.post("/expenses/add", data=form)

    assert response.status_code == 200
    assert b"expense-error" in response.data
    assert message.encode() in response.data
    assert expense_count() == before
    return response


@pytest.mark.parametrize("field", ["amount", "category", "date"])
def test_required_fields(client, field):
    sign_in(client)

    assert_rejected(
        client, expense_form(**{field: "   "}), "Amount, category and date are required."
    )


@pytest.mark.parametrize(
    "amount", ["0", "0.00", "-5", "abc", "12.345", "1e3", "nan", "inf", "$5", "1,000"]
)
def test_invalid_amounts_are_rejected(client, amount):
    sign_in(client)

    assert_rejected(
        client,
        expense_form(amount=amount),
        "Amount must be a number greater than 0 with at most 2 decimal places.",
    )


def test_amount_over_the_maximum_is_rejected(client):
    sign_in(client)

    assert_rejected(
        client, expense_form(amount="1000000.01"), "Amount must be 1,000,000 or less."
    )


@pytest.mark.parametrize("category", ["Groceries", "food"])
def test_unknown_categories_are_rejected(client, category):
    sign_in(client)

    assert_rejected(
        client, expense_form(category=category), "Choose a category from the list."
    )


@pytest.mark.parametrize("bad_date", ["2026-02-30", "not-a-date"])
def test_invalid_dates_are_rejected(client, bad_date):
    sign_in(client)

    assert_rejected(
        client, expense_form(date=bad_date), "Enter a valid date in YYYY-MM-DD format."
    )


def test_long_description_is_rejected(client):
    sign_in(client)

    assert_rejected(
        client,
        expense_form(description="x" * 201),
        "Description must be 200 characters or fewer.",
    )


def test_error_keeps_the_submitted_values(client):
    sign_in(client)

    response = assert_rejected(
        client,
        expense_form(amount="abc", date="2026-09-05", description="Taxi home"),
        "Amount must be a number greater than 0 with at most 2 decimal places.",
    )
    assert b'value="abc"' in response.data
    assert b'value="2026-09-05"' in response.data
    assert b'value="Taxi home"' in response.data
    assert b'<option value="Food" selected>' in response.data


# ------------------------------------------------------------------ #
# Safety and scoping                                                   #
# ------------------------------------------------------------------ #

def test_sql_like_description_is_stored_literally(client):
    sign_in(client)
    description = "'); DROP TABLE expenses; --"

    client.post("/expenses/add", data=expense_form(description=description))

    assert latest_expense()["description"] == description
    assert expense_count() == 9


def test_script_description_is_escaped(client):
    sign_in(client)
    client.post("/expenses/add", data=expense_form(description="<script>alert(1)</script>"))

    response = client.get("/profile")
    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.data


def test_user_id_field_is_ignored(client):
    client.post("/register", data=NITISH)
    nitish_id = db.get_user_by_email(NITISH["email"])["id"]
    sign_in(client)

    client.post("/expenses/add", data=expense_form(user_id=nitish_id))

    assert latest_expense()["user_id"] == demo_user_id()


def test_new_user_can_add_an_expense(client):
    sign_in_new_user(client)
    client.post(
        "/expenses/add",
        data=expense_form(amount="20.00", category="Transport", description="Bus fare"),
    )

    section = profile_section(client.get("/profile"))
    assert b"$20.00" in section
    assert stat_value(1) in section
    assert stat_value("Transport") in section

    client.get("/logout")
    sign_in(client)
    assert b"$462.66" in profile_section(client.get("/profile"))


# ------------------------------------------------------------------ #
# Markup                                                               #
# ------------------------------------------------------------------ #

def test_profile_has_an_add_expense_button_and_no_notice(client):
    sign_in(client)

    section = profile_section(client.get("/profile"))
    assert b'href="/expenses/add"' in section
    assert b"Expense added." not in section


def test_no_hex_colours_on_the_add_expense_page(client):
    sign_in(client)

    section = expense_section(client.get("/expenses/add"))
    assert b"#" not in section.replace(b"&#", b"")


def test_no_hex_colours_on_the_profile_with_the_notice(client):
    sign_in(client)

    section = profile_section(client.get("/profile?added=1"))
    assert b"Expense added." in section
    assert b"#" not in section.replace(b"&#", b"")


def test_edit_and_delete_are_still_placeholders(client):
    assert b"coming in Step 8" in client.get("/expenses/1/edit").data
    assert b"coming in Step 9" in client.get("/expenses/1/delete").data
