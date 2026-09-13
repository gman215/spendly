from datetime import date

import database.db as db

DEMO = {"email": "demo@spendly.com", "password": "demo123"}


def sign_in(client):
    return client.post("/login", data=DEMO)


def profile_section(response):
    """Just the profile page's own markup — not base.html's nav and footer."""
    section = response.data.split(b'class="profile-section"', 1)[1]
    return section.split(b"</section>", 1)[0]


def transaction_rows(response):
    body = profile_section(response).split(b"<tbody>", 1)[1]
    return body.split(b"</tbody>", 1)[0].count(b"<tr>")


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


def test_member_since_is_a_month_and_year_not_an_iso_date(client):
    sign_in(client)

    response = client.get("/profile")
    assert date.today().strftime("Member since %B %Y").encode() in response.data
    assert date.today().strftime("%Y-%m-%d").encode() not in profile_section(
        response
    ).split(b"<tbody>", 1)[0]


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
    assert transaction_rows(response) == 8
    assert b"Electricity bill" in response.data


def test_transaction_dates_track_the_current_month(client):
    sign_in(client)

    response = client.get("/profile")
    this_month = date.today().strftime("%Y-%m-").encode()
    assert profile_section(response).count(this_month) == 8


def test_profile_shows_category_breakdown(client):
    sign_in(client)

    response = client.get("/profile")
    assert response.data.count(b"cat-row") == 7
    assert b"badge-bills" in response.data
    assert b"badge-entertainment" in response.data


def test_profile_uses_no_hardcoded_hex_colours(client):
    sign_in(client)

    section = profile_section(client.get("/profile"))
    assert b"#" not in section.replace(b"&#", b"")


# ------------------------------------------------------------------ #
# Real data                                                            #
# ------------------------------------------------------------------ #

def sign_in_new_user(client):
    client.post(
        "/register",
        data={
            "name": "Nitish Kumar",
            "email": "nitish@example.com",
            "password": "password123",
        },
    )
    return client.post(
        "/login", data={"email": "nitish@example.com", "password": "password123"}
    )


def add_demo_expense(amount, description, expense_date="2000-01-01", category="Other"):
    user_id = db.get_user_by_email(DEMO["email"])["id"]
    conn = db.get_db()
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, expense_date, description),
    )
    conn.commit()
    conn.close()


def test_new_user_sees_an_empty_profile(client):
    sign_in_new_user(client)

    response = client.get("/profile")
    section = profile_section(response)
    assert response.status_code == 200
    assert b"$0.00" in section
    assert '<span class="profile-stat-value">—</span>'.encode() in section
    assert transaction_rows(response) == 0
    assert section.count(b"cat-row") == 0


def test_profile_only_shows_the_signed_in_users_expenses(client):
    sign_in_new_user(client)

    section = profile_section(client.get("/profile"))
    assert b"Electricity bill" not in section
    assert b"462.66" not in section


def test_transactions_are_newest_first(client):
    sign_in(client)

    section = profile_section(client.get("/profile"))
    assert section.index(b"Charity donation") < section.index(b"Groceries at Trader Joe")


def test_recent_transactions_are_capped_but_the_count_is_not(client):
    for n in range(12):
        add_demo_expense(1.00, f"Old expense {n}")
    sign_in(client)

    response = client.get("/profile")
    assert transaction_rows(response) == 10
    assert b'<span class="profile-stat-value">20</span>' in profile_section(response)


def test_total_reflects_expenses_in_the_database(client):
    add_demo_expense(37.34, "Late bill")
    sign_in(client)

    assert b"$500.00" in profile_section(client.get("/profile"))


# ------------------------------------------------------------------ #
# Navbar                                                               #
# ------------------------------------------------------------------ #

def test_navbar_greeting_links_to_profile(client):
    sign_in(client)

    assert b'href="/profile"' in client.get("/").data


def test_navbar_has_no_profile_link_when_signed_out(client):
    assert b'href="/profile"' not in client.get("/").data
