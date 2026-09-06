from werkzeug.security import check_password_hash

import database.db as db

VALID = {"name": "Nitish Kumar", "email": "nitish@example.com", "password": "supersecret"}


def count_users(email):
    conn = db.get_db()
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE email = ?", (email,)
    ).fetchone()["n"]
    conn.close()
    return total


# ------------------------------------------------------------------ #
# GET                                                                  #
# ------------------------------------------------------------------ #

def test_get_register_renders_form(client):
    response = client.get("/register")
    assert response.status_code == 200
    assert b'action="/register"' in response.data


# ------------------------------------------------------------------ #
# Successful registration                                              #
# ------------------------------------------------------------------ #

def test_valid_registration_redirects_to_login(client):
    response = client.post("/register", data=VALID)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?registered=1")


def test_valid_registration_creates_one_hashed_user(client):
    client.post("/register", data=VALID)

    user = db.get_user_by_email("nitish@example.com")
    assert user is not None
    assert user["name"] == "Nitish Kumar"
    assert count_users("nitish@example.com") == 1
    assert user["password_hash"] != VALID["password"]
    assert VALID["password"] not in user["password_hash"]
    assert check_password_hash(user["password_hash"], VALID["password"])


def test_email_is_trimmed_and_lowercased(client):
    client.post("/register", data={**VALID, "email": "  Nitish@Example.COM  "})

    assert db.get_user_by_email("nitish@example.com") is not None


def test_registering_twice_keeps_one_row(client):
    client.post("/register", data=VALID)
    response = client.post("/register", data=VALID)

    assert response.status_code == 200
    assert "An account with that email already exists.".encode() in response.data
    assert count_users("nitish@example.com") == 1


# ------------------------------------------------------------------ #
# Validation                                                           #
# ------------------------------------------------------------------ #

def test_blank_field_is_rejected(client):
    response = client.post("/register", data={**VALID, "name": "   "})

    assert response.status_code == 200
    assert b"All fields are required." in response.data
    assert db.get_user_by_email("nitish@example.com") is None


def test_invalid_email_is_rejected(client):
    response = client.post("/register", data={**VALID, "email": "notanemail"})

    assert response.status_code == 200
    assert b"Enter a valid email address." in response.data
    assert db.get_user_by_email("notanemail") is None


def test_short_password_is_rejected(client):
    response = client.post("/register", data={**VALID, "password": "sevench"})

    assert response.status_code == 200
    assert b"Password must be at least 8 characters." in response.data
    assert db.get_user_by_email("nitish@example.com") is None


def test_seeded_email_is_rejected(client):
    response = client.post("/register", data={**VALID, "email": "demo@spendly.com"})

    assert response.status_code == 200
    assert "An account with that email already exists.".encode() in response.data
    assert count_users("demo@spendly.com") == 1


def test_error_keeps_name_and_email_but_not_password(client):
    response = client.post("/register", data={**VALID, "password": "short"})

    assert b'value="Nitish Kumar"' in response.data
    assert b'value="nitish@example.com"' in response.data
    assert b"short" not in response.data


# ------------------------------------------------------------------ #
# Login page notice                                                    #
# ------------------------------------------------------------------ #

def test_login_shows_notice_after_registering(client):
    response = client.get("/login?registered=1")

    assert response.status_code == 200
    assert b"auth-success" in response.data


def test_login_has_no_notice_by_default(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert b"auth-success" not in response.data
