import os
import re
import sqlite3
from datetime import date, datetime

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash

from database.db import (
    CATEGORIES,
    count_ai_requests_today,
    create_expense,
    create_user,
    get_category_totals,
    get_db,
    get_expense_stats,
    get_expenses_by_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
    log_ai_request,
    seed_db,
)
from services import gemini

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = gemini.MAX_RECEIPT_MB * 1024 * 1024


# ------------------------------------------------------------------ #
# Database setup                                                      #
# ------------------------------------------------------------------ #

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Session helpers                                                     #
# ------------------------------------------------------------------ #

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = get_user_by_id(user_id)
    if user is None or user["email"] != session.get("user_email"):
        session.clear()
        return None

    return user


@app.context_processor
def inject_current_user():
    return {"current_user": get_current_user()}


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


def parse_expense_form(form):
    values = {
        field: form.get(field, "").strip()
        for field in ("amount", "category", "date", "description")
    }

    if not values["amount"] or not values["category"] or not values["date"]:
        return values, None, "Amount, category and date are required."

    amount_ok = re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", values["amount"])
    amount = float(values["amount"]) if amount_ok else 0
    if amount <= 0:
        return values, None, "Amount must be a number greater than 0 with at most 2 decimal places."
    if amount > 1000000:
        return values, None, "Amount must be 1,000,000 or less."

    if values["category"] not in CATEGORIES:
        return values, None, "Choose a category from the list."

    try:
        expense_date = datetime.strptime(values["date"], "%Y-%m-%d").date()
    except ValueError:
        return values, None, "Enter a valid date in YYYY-MM-DD format."

    if len(values["description"]) > 200:
        return values, None, "Description must be 200 characters or fewer."

    expense = {
        "amount": round(amount, 2),
        "category": values["category"],
        "date": expense_date.isoformat(),
        "description": values["description"] or None,
    }
    return values, expense, None


def parse_autofill_form(form, files):
    note = form.get("note", "").strip()
    receipt = files.get("receipt")

    if receipt and receipt.filename:
        if receipt.mimetype not in gemini.IMAGE_TYPES:
            return note, None, "Choose a JPEG, PNG, WebP or HEIC photo."
        image = receipt.read()
        if not image:
            return note, None, "That photo is empty. Choose another one."
        return note, (image, receipt.mimetype), None

    if not note:
        return note, None, "Choose a receipt photo or describe the expense."
    if len(note) > gemini.MAX_NOTE_LENGTH:
        return note, None, f"Keep the description to {gemini.MAX_NOTE_LENGTH} characters or fewer."
    return note, None, None


def parse_client_today(value):
    server_today = date.today()
    try:
        client_today = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return server_today

    # The browser sends its local date so "yesterday" means the user's yesterday, even though the
    # server clock is UTC on Vercel. A date more than a day away from the server's is ignored.
    if abs((client_today - server_today).days) > 1:
        return server_today
    return client_today


def render_expense_form(status=200, **context):
    context.setdefault("date", date.today().isoformat())
    page = render_template(
        "add_expense.html",
        categories=CATEGORIES,
        ai_enabled=gemini.is_enabled(),
        **context,
    )
    return page, status


# ------------------------------------------------------------------ #
# Error handlers                                                      #
# ------------------------------------------------------------------ #

@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    if request.path != "/expenses/autofill" or get_current_user() is None:
        return error
    return render_expense_form(
        413, autofill_error=f"Receipt photos must be {gemini.MAX_RECEIPT_MB} MB or smaller."
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
        if get_current_user():
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
    session["user_email"] = user["email"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login", logged_out=1))


@app.route("/profile")
def profile():
    user = get_current_user()
    if user is None:
        return redirect(url_for("login"))

    user_id = user["id"]
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
            "description": row["description"] or "—",
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
        added=request.args.get("added"),
    )


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    user = get_current_user()
    if user is None:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_expense_form()

    values, expense, error = parse_expense_form(request.form)
    if error:
        return render_expense_form(error=error, **values)

    create_expense(user["id"], **expense)
    return redirect(url_for("profile", added=1))


@app.route("/expenses/autofill", methods=["POST"])
def autofill_expense():
    user = get_current_user()
    if user is None:
        return redirect(url_for("login"))

    if not gemini.is_enabled():
        return render_expense_form(
            error="AI autofill isn't available right now. Add the expense by hand."
        )

    note, receipt, error = parse_autofill_form(request.form, request.files)
    if error is None and count_ai_requests_today(user["id"]) >= gemini.DAILY_LIMIT:
        error = (
            f"You've used all {gemini.DAILY_LIMIT} AI autofills for today. "
            "You can still add expenses by hand."
        )
    if error:
        return render_expense_form(autofill_error=error, note=note)

    today = parse_client_today(request.form.get("today", ""))
    source = "receipt" if receipt else "note"
    log_ai_request(user["id"], source)
    try:
        if receipt:
            values = gemini.extract_from_receipt(*receipt, today)
        else:
            values = gemini.extract_from_note(note, today)
    except gemini.AutofillError as exc:
        return render_expense_form(autofill_error=str(exc), note=note)

    return render_expense_form(autofilled=source, note=note, **values)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
