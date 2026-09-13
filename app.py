import os
import sqlite3
from datetime import date, datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_db,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# ------------------------------------------------------------------ #
# Database setup                                                      #
# ------------------------------------------------------------------ #

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Session helpers                                                     #
# ------------------------------------------------------------------ #

@app.context_processor
def inject_current_user():
    user_id = session.get("user_id")
    return {"current_user": get_user_by_id(user_id) if user_id else None}


# ------------------------------------------------------------------ #
# Template filters                                                    #
# ------------------------------------------------------------------ #

@app.template_filter("month_year")
def month_year(value):
    if not value:
        return "—"
    return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%B %Y")


# ------------------------------------------------------------------ #
# Demo profile data (Step 4 — replaced by real queries in Step 5)     #
# ------------------------------------------------------------------ #

PROFILE_STATS = {
    "total_spent": "462.66",
    "transaction_count": 8,
    "top_category": "Bills",
}

# Same rows as seed_db(), newest first. Days are all <= 28 so replace() is safe
# in February, and the dates follow date.today() instead of drifting into the past.
PROFILE_TRANSACTIONS = [
    {
        "date": date.today().replace(day=day).strftime("%Y-%m-%d"),
        "description": description,
        "category": category,
        "amount": amount,
    }
    for day, category, description, amount in [
        (22, "Other", "Charity donation", "20.00"),
        (18, "Food", "Dinner with friends", "42.10"),
        (14, "Shopping", "New running shoes", "89.99"),
        (10, "Entertainment", "Movie tickets", "28.00"),
        (7, "Health", "Pharmacy - prescription refill", "32.75"),
        (5, "Bills", "Electricity bill", "120.50"),
        (3, "Transport", "Monthly metro pass", "75.00"),
        (1, "Food", "Groceries at Trader Joe's", "54.32"),
    ]
]

PROFILE_CATEGORIES = [
    {"name": "Bills", "amount": "120.50", "percent": "26.0", "width": 100},
    {"name": "Food", "amount": "96.42", "percent": "20.8", "width": 80},
    {"name": "Shopping", "amount": "89.99", "percent": "19.4", "width": 75},
    {"name": "Transport", "amount": "75.00", "percent": "16.2", "width": 62},
    {"name": "Health", "amount": "32.75", "percent": "7.1", "width": 27},
    {"name": "Entertainment", "amount": "28.00", "percent": "6.1", "width": 23},
    {"name": "Other", "amount": "20.00", "percent": "4.3", "width": 17},
]


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = None
    if not name or not email or not password:
        error = "All fields are required."
    elif "@" not in email or not all(email.split("@", 1)):
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif get_user_by_email(email):
        error = "An account with that email already exists."

    if error is None:
        try:
            create_user(name, email, password)
        except sqlite3.IntegrityError:
            error = "An account with that email already exists."

    if error:
        return render_template("register.html", error=error, name=name, email=email)

    return redirect(url_for("login", registered=1))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("profile"))
        return render_template(
            "login.html",
            registered=request.args.get("registered"),
            logged_out=request.args.get("logged_out"),
        )

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = None
    if not email or not password:
        error = "Email and password are required."
    else:
        user = get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Incorrect email or password."

    if error:
        return render_template("login.html", error=error, email=email)

    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login", logged_out=1))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template(
        "profile.html",
        stats=PROFILE_STATS,
        transactions=PROFILE_TRANSACTIONS,
        categories=PROFILE_CATEGORIES,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
