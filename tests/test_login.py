import database.db as db

DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def demo_user_id():
    return db.get_user_by_email(DEMO["email"])["id"]


def session_user_id(client):
    with client.session_transaction() as session:
        return session.get("user_id")


def sign_in(client):
    return client.post("/login", data=DEMO)


# ------------------------------------------------------------------ #
# GET                                                                  #
# ------------------------------------------------------------------ #

def test_get_login_renders_form(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'action="/login"' in response.data
    assert b"auth-success" not in response.data
    assert b"auth-error" not in response.data


def test_get_login_redirects_when_signed_in(client):
    sign_in(client)

    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


# ------------------------------------------------------------------ #
# Successful sign-in                                                   #
# ------------------------------------------------------------------ #

def test_valid_login_redirects_to_landing(client):
    response = sign_in(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_valid_login_stores_user_id_in_session(client):
    sign_in(client)

    assert session_user_id(client) == demo_user_id()


def test_email_is_trimmed_and_lowercased(client):
    response = client.post(
        "/login", data={**DEMO, "email": "  DEMO@Spendly.com  "}
    )

    assert response.status_code == 302
    assert session_user_id(client) == demo_user_id()


def test_registered_user_can_sign_in(client):
    client.post(
        "/register",
        data={
            "name": "Nitish Kumar",
            "email": "nitish@example.com",
            "password": "supersecret",
        },
    )

    response = client.post(
        "/login", data={"email": "nitish@example.com", "password": "supersecret"}
    )

    assert response.status_code == 302
    assert session_user_id(client) == db.get_user_by_email("nitish@example.com")["id"]


# ------------------------------------------------------------------ #
# Validation                                                           #
# ------------------------------------------------------------------ #

def test_wrong_password_is_rejected(client):
    response = client.post("/login", data={**DEMO, "password": "wrongpassword"})

    assert response.status_code == 200
    assert b"Incorrect email or password." in response.data
    assert session_user_id(client) is None


def test_unknown_email_gives_the_same_message(client):
    response = client.post("/login", data={**DEMO, "email": "nobody@example.com"})

    assert response.status_code == 200
    assert b"Incorrect email or password." in response.data
    assert session_user_id(client) is None


def test_blank_email_is_rejected(client):
    response = client.post("/login", data={**DEMO, "email": "   "})

    assert response.status_code == 200
    assert b"Email and password are required." in response.data
    assert session_user_id(client) is None


def test_blank_password_is_rejected(client):
    response = client.post("/login", data={**DEMO, "password": ""})

    assert response.status_code == 200
    assert b"Email and password are required." in response.data
    assert session_user_id(client) is None


def test_error_keeps_email_but_not_password(client):
    response = client.post("/login", data={**DEMO, "password": "wrongpassword"})

    assert b'value="demo@spendly.com"' in response.data
    assert b"wrongpassword" not in response.data


# ------------------------------------------------------------------ #
# Logout                                                               #
# ------------------------------------------------------------------ #

def test_logout_clears_session_and_redirects(client):
    sign_in(client)

    response = client.get("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?logged_out=1")
    assert session_user_id(client) is None


def test_logout_when_signed_out_is_harmless(client):
    response = client.get("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?logged_out=1")


def test_login_shows_notice_after_logout(client):
    response = client.get("/login?logged_out=1")

    assert response.status_code == 200
    assert b"auth-success" in response.data
    assert "You've been signed out.".encode() in response.data


# ------------------------------------------------------------------ #
# Navbar                                                               #
# ------------------------------------------------------------------ #

def test_navbar_shows_user_when_signed_in(client):
    sign_in(client)

    response = client.get("/")
    assert b"Hi, Demo User" in response.data
    assert b"Sign out" in response.data
    assert b"Get started" not in response.data


def test_navbar_shows_sign_in_when_signed_out(client):
    response = client.get("/")

    assert b"Sign in" in response.data
    assert b"Get started" in response.data
    assert b"Sign out" not in response.data


def test_navbar_persists_across_pages(client):
    sign_in(client)

    for path in ("/", "/terms", "/privacy"):
        assert b"Hi, Demo User" in client.get(path).data
