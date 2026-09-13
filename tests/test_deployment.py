import os

import database.db as db

DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def sign_in(client):
    return client.post("/login", data=DEMO)


def demo_user_id():
    return db.get_user_by_email(DEMO["email"])["id"]


def set_session(client, **values):
    with client.session_transaction() as session:
        session.clear()
        session.update(values)


def session_data(client):
    with client.session_transaction() as session:
        return dict(session)


# ------------------------------------------------------------------ #
# Database location                                                    #
# ------------------------------------------------------------------ #

def test_db_path_is_in_tmp_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")

    assert db._default_db_path() == "/tmp/expense_tracker.db"


def test_db_path_is_in_project_root_locally(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)

    path = db._default_db_path()
    assert os.path.basename(path) == "expense_tracker.db"
    assert os.path.isfile(os.path.join(os.path.dirname(path), "app.py"))


# ------------------------------------------------------------------ #
# Session                                                              #
# ------------------------------------------------------------------ #

def test_login_stores_user_id_and_email(client):
    sign_in(client)

    session = session_data(client)
    assert session["user_id"] == demo_user_id()
    assert session["user_email"] == DEMO["email"]


def test_unknown_user_id_redirects_profile_to_login(client):
    set_session(client, user_id=999, user_email=DEMO["email"])

    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert "user_id" not in session_data(client)

    response = client.get("/login")
    assert response.status_code == 200
    assert b'action="/login"' in response.data


def test_login_page_renders_for_stale_session(client):
    set_session(client, user_id=999, user_email=DEMO["email"])

    response = client.get("/login")
    assert response.status_code == 200
    assert b'action="/login"' in response.data
    assert session_data(client) == {}


def test_session_without_email_is_signed_out(client):
    set_session(client, user_id=demo_user_id())

    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert session_data(client) == {}


def test_session_with_mismatched_email_is_signed_out(client):
    set_session(client, user_id=demo_user_id(), user_email="nitish@example.com")

    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert b"Demo User" not in response.data
    assert session_data(client) == {}


def test_stale_session_on_landing_page_shows_signed_out_nav(client):
    set_session(client, user_id=999, user_email=DEMO["email"])

    response = client.get("/")
    assert response.status_code == 200
    assert b"Hi, Demo User" not in response.data
    assert b"Sign out" not in response.data
    assert b"Get started" in response.data
    assert session_data(client) == {}
