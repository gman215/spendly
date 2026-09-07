DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def sign_in(client):
    return client.post("/login", data=DEMO)


# ------------------------------------------------------------------ #
# Access control                                                       #
# ------------------------------------------------------------------ #

def test_profile_redirects_when_signed_out(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_profile_returns_200_when_signed_in(client):
    sign_in(client)

    response = client.get("/profile")
    assert response.status_code == 200


def test_profile_is_no_longer_a_placeholder(client):
    sign_in(client)

    assert b"coming in Step 4" not in client.get("/profile").data


# ------------------------------------------------------------------ #
# User info card                                                       #
# ------------------------------------------------------------------ #

def test_profile_shows_the_signed_in_user(client):
    sign_in(client)

    response = client.get("/profile")
    assert b"Demo User" in response.data
    assert b"demo@spendly.com" in response.data
    assert b"Member since" in response.data


def test_profile_never_leaks_the_password_hash(client):
    sign_in(client)

    response = client.get("/profile")
    assert b"pbkdf2" not in response.data
    assert b"scrypt" not in response.data


# ------------------------------------------------------------------ #
# Page sections                                                        #
# ------------------------------------------------------------------ #

def test_profile_shows_summary_stats(client):
    sign_in(client)

    response = client.get("/profile")
    assert b"462.66" in response.data
    assert b"Total spent" in response.data
    assert b"Top category" in response.data


def test_profile_shows_transaction_table(client):
    sign_in(client)

    response = client.get("/profile")
    assert b"txn-table" in response.data
    assert response.data.count(b"<tr>") == 9  # header row + 8 transactions
    assert b"Electricity bill" in response.data


def test_profile_shows_category_breakdown(client):
    sign_in(client)

    response = client.get("/profile")
    assert response.data.count(b"cat-row") == 7
    assert b"badge-bills" in response.data
    assert b"badge-entertainment" in response.data


def test_profile_uses_no_hardcoded_hex_colours(client):
    sign_in(client)

    body = client.get("/profile").data.split(b"<main", 1)[1]
    assert b"#" not in body.replace(b"&#", b"")


# ------------------------------------------------------------------ #
# Navbar                                                               #
# ------------------------------------------------------------------ #

def test_navbar_greeting_links_to_profile(client):
    sign_in(client)

    assert b'href="/profile"' in client.get("/").data


def test_navbar_has_no_profile_link_when_signed_out(client):
    assert b'href="/profile"' not in client.get("/").data
