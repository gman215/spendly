import os
import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

# ------------------------------------------------------------------ #
# Setup                                                                #
# ------------------------------------------------------------------ #

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------------ #
# Schema                                                               #
# ------------------------------------------------------------------ #

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
# Seed data                                                            #
# ------------------------------------------------------------------ #

def seed_db():
    conn = get_db()
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if existing:
        conn.close()
        return

    password_hash = generate_password_hash("demo123")
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", password_hash),
    )
    user_id = cursor.lastrowid

    today = date.today()
    sample_expenses = [
        (1, "Food", "Groceries at Trader Joe's", 54.32),
        (3, "Transport", "Monthly metro pass", 75.00),
        (5, "Bills", "Electricity bill", 120.50),
        (7, "Health", "Pharmacy - prescription refill", 32.75),
        (10, "Entertainment", "Movie tickets", 28.00),
        (14, "Shopping", "New running shoes", 89.99),
        (18, "Food", "Dinner with friends", 42.10),
        (22, "Other", "Charity donation", 20.00),
    ]

    for day, category, description, amount in sample_expenses:
        expense_date = today.replace(day=day).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )

    conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
# Users                                                                #
# ------------------------------------------------------------------ #

def get_user_by_email(email):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return user


def create_user(name, email, password):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return user


# ------------------------------------------------------------------ #
# Expenses                                                             #
# ------------------------------------------------------------------ #

def get_expense_stats(user_id):
    conn = get_db()
    stats = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
        "FROM expenses WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return stats


def get_category_totals(user_id):
    conn = get_db()
    totals = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        "WHERE user_id = ? GROUP BY category ORDER BY total DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return totals


def get_expenses_by_user(user_id, limit=None):
    query = "SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC"
    params = [user_id]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    conn = get_db()
    expenses = conn.execute(query, params).fetchall()
    conn.close()
    return expenses
