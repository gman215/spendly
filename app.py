import os
import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_category_totals,
    get_db,
    get_expense_stats,
    get_expenses_by_user,
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
# Request helpers                                                     #
# ------------------------------------------------------------------ #

def parse_date_range(args):
    start_date = args.get("start_date", "").strip()
    end_date = args.get("end_date", "").strip()

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    except ValueError:
        return start_date, end_date, "Enter a valid date in YYYY-MM-DD format."

    if start and end and start > end:
        return start_date, end_date, "Start date must be on or before the end date."

    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
        None,
    )


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
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    start_date, end_date, error = parse_date_range(request.args)
    filter_active = not error and bool(start_date or end_date)
    bounds = {} if error else {"start_date": start_date, "end_date": end_date}

    expense_stats = get_expense_stats(user_id, **bounds)
    category_rows = get_category_totals(user_id, **bounds)
    expense_rows = get_expenses_by_user(user_id, **bounds)

    total_spent = expense_stats["total_spent"]
    max_total = category_rows[0]["total"] if category_rows else 0

    stats = {
        "total_spent": f"{total_spent:.2f}",
        "transaction_count": expense_stats["transaction_count"],
        "top_category": category_rows[0]["category"] if category_rows else "—",
    }
    transactions = [
        {
            "date": row["date"],
            "description": row["description"],
            "category": row["category"],
            "amount": f"{row['amount']:.2f}",
        }
        for row in expense_rows
    ]
    categories = [
        {
            "name": row["category"],
            "amount": f"{row['total']:.2f}",
            "percent": f"{row['total'] / total_spent * 100:.1f}" if total_spent else "0.0",
            "width": round(row["total"] / max_total * 100) if max_total else 0,
        }
        for row in category_rows
    ]

    return render_template(
        "profile.html",
        stats=stats,
        transactions=transactions,
        categories=categories,
        start_date=start_date,
        end_date=end_date,
        filter_active=filter_active,
        error=error,
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
