import os

import pytest

import database.db as db
from services import gemini


def refuse_real_gemini_call(contents, today):
    raise AssertionError("Tests must not call the real Gemini API. Use the fake_gemini fixture.")


# Runs for every test: AI autofill starts switched off (even if .env has a key) and any code path
# that would reach the network fails loudly instead.
@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(gemini, "_generate", refuse_real_gemini_call)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", os.path.join(tmp_path, "test.db"))
    db.init_db()
    db.seed_db()

    from app import app as flask_app

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as test_client:
        yield test_client
