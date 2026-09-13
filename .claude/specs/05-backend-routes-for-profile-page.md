# Spec: Backend Routes For Profile Page

## Overview

Replace the hardcoded `PROFILE_STATS`, `PROFILE_TRANSACTIONS`, and `PROFILE_CATEGORIES` globals in
`app.py` with real queries against the `expenses` table, scoped to the signed-in user. Step 4 built
the profile page's full UI against fake data so the layout could be validated in isolation; the
`/profile` route and `templates/profile.html` already exist and already render a `stats` dict, a
`transactions` list, and a `categories` list in exactly the shape this step needs to keep producing.
This step does not change what the page looks like — it changes where its numbers come from, so
that a real user's actual spending (not the seeded demo data) shows up correctly once expenses can
be created, edited, and deleted in Steps 7–9. The user info card is untouched: it already reads the
real `current_user` from the Step 3 context processor and was never part of the hardcoded data.

## Depends on

- **Step 1 — Database Setup** (complete): `get_db()` and the `expenses` table
  (`user_id`, `amount`, `category`, `date`, `description`) that every new query in this step reads
  from.
- **Step 3 — Login and Logout** (complete): `session["user_id"]` is what scopes every query to the
  signed-in user; there is no cross-user leakage risk to design around because every helper takes
  `user_id` as a required argument.
- **Step 4 — Profile Page Design** (complete): `/profile`'s auth guard, `templates/profile.html`,
  and the `stats` / `transactions` / `categories` context shape all already exist and are reused
  as-is.

## Routes

No new routes. `GET /profile` already exists (Step 4) and keeps its method, path, and
`session.get("user_id")` auth guard exactly as they are — only the body of the view function
changes, from building hardcoded context to querying the database.

## Database changes

No new tables, columns, or constraints — the Step 1 `expenses` table already has everything needed
(`user_id`, `amount`, `category`, `date`, `description`).

Three new query helpers are added to `database/db.py`, in a new `# Expenses` section below the
existing `# Users` section:

- `get_expense_stats(user_id)` — one aggregate query:
  `SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count FROM expenses
  WHERE user_id = ?`. Returns a single `sqlite3.Row`; `COALESCE` guarantees `total_spent` is `0`
  rather than `NULL` for a user with no expenses.
- `get_category_totals(user_id)` — `SELECT category, SUM(amount) AS total FROM expenses WHERE
  user_id = ? GROUP BY category ORDER BY total DESC`. Returns a list of `sqlite3.Row` (empty list
  for a user with no expenses). Ordering by total descending means the first row, when present, is
  the user's top category — no separate query is needed for that.
- `get_expenses_by_user(user_id, limit=None)` — `SELECT * FROM expenses WHERE user_id = ? ORDER BY
  date DESC, id DESC`, with an optional `LIMIT ?` appended when `limit` is given. The `id DESC`
  tiebreaker keeps same-day expenses in insertion order. Returns a list of `sqlite3.Row`.

All three open their connection with `get_db()` and close it before returning, matching the
existing helpers in `# Users`.

`profile()` in `app.py` calls `get_expenses_by_user(user_id, limit=10)` for the "Recent
transactions" table — the table is a recent-activity view, not full history, and the seeded demo
user's 8 rows all fit under that limit so existing behaviour is unchanged. `transaction_count` in
`stats`, however, comes from `get_expense_stats()`, not `len(transactions)`, so it stays correct
once a user has more than 10 expenses.

`profile()` derives everything the template needs from those three query results:

- `stats["total_spent"]` — `total_spent` formatted as `f"{value:.2f}"`. Formatting (not raw float
  interpolation) is required: SQLite `SUM` over `REAL` columns can return values like
  `462.65999999999997`, and `:.2f` is what turns that back into `"462.66"`.
- `stats["transaction_count"]` — used as-is (an int).
- `stats["top_category"]` — `category_rows[0]["category"]` if `category_rows` is non-empty, else
  `"—"` (the same em-dash fallback `month_year` already uses for missing data).
- `transactions[i]["amount"]` — each row's `amount` formatted as `f"{value:.2f}"`; `date`,
  `description`, `category` pass through unchanged.
- `categories[i]["amount"]` — each category row's `total` formatted as `f"{value:.2f}"`.
- `categories[i]["percent"]` — `f"{total / total_spent * 100:.1f}"` (share of the user's overall
  spend), or `"0.0"` when `total_spent` is `0`.
- `categories[i]["width"]` — `round(total / max_total * 100)` where `max_total` is the first (and
  largest) row from `get_category_totals()` — this reproduces the existing progress-bar scaling
  (e.g. the demo data's Bills row is `width: 100`, the rest scaled relative to it), or `0` when
  there are no categories.

## Templates

**Create:** none.

**Modify:** none. `templates/profile.html` already loops over `transactions` and `categories` and
reads `stats.total_spent` / `stats.transaction_count` / `stats.top_category` — since this step keeps
that exact context shape, an empty list from a new user with no expenses renders as an empty table
body / empty category list with no error, and needs no template change to do so.

## Files to change

- `app.py`
  - Delete the `PROFILE_STATS`, `PROFILE_TRANSACTIONS`, and `PROFILE_CATEGORIES` globals and their
    `# Demo profile data (Step 4 — replaced by real queries in Step 5)` banner.
  - `from database.db import (..., get_expense_stats, get_category_totals,
    get_expenses_by_user)`.
  - Rewrite `profile()` to query via the three new helpers and build `stats` / `transactions` /
    `categories` as described above, then `render_template` with the same three names it already
    passes today. The auth guard (`if not session.get("user_id"): return redirect(url_for("login"))`)
    is unchanged.
- `database/db.py` — add the `# Expenses` section and its three helpers, below `# Users`.
- `tests/test_profile.py` — add coverage for a user with zero expenses (see Definition of done);
  existing tests are not expected to need changes, since they assert against the same seeded demo
  data the new queries read from.

## Files to create

None.

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs — stdlib `sqlite3` only, through `database/db.py`.
- Parameterised queries only. Never build SQL with f-strings, `%`, or concatenation.
- Passwords hashed with werkzeug (unchanged — this step touches no auth code).
- All SQL and connection handling stays in `database/db.py`; `profile()` calls the three new
  helpers rather than opening a connection or writing SQL of its own.
- Every new helper takes `user_id` as a required parameter and filters on it — no query in this
  step may return another user's expenses.
- Use CSS variables — never hardcode hex values (not expected to come up, since no CSS changes).
- All templates extend `base.html` (not expected to come up, since no templates change).
- Keep `profile()` thin: call the helpers, format/derive the three context values, render — no
  business logic beyond the formatting rules listed above.
- Format every monetary value with `:.2f` before it reaches a template; never interpolate a raw
  `REAL` column value.
- Do not touch `/register`, `/login`, `/logout`, the landing/terms/privacy routes or templates, or
  the Step 7–9 placeholder routes.

## Definition of done

Verified by running `python app.py` and using the app at `http://localhost:5001`:

- [ ] `pytest` passes, including the existing `tests/test_profile.py` suite unmodified — the demo
      user's real totals (`$462.66`, 8 transactions, 7 `cat-row`s, `badge-bills` top category)
      match what the hardcoded data produced before this step.
- [ ] Registering a brand-new account and visiting `/profile` while signed in as that user returns
      HTTP 200 with no server error, shows `$0.00` total spent, `0` transactions, and `—` as the
      top category, with no rows in the transaction table or category list.
- [ ] `sqlite3 expense_tracker.db "SELECT SUM(amount) FROM expenses WHERE user_id = 1;"` matches the
      "Total spent" value shown on `/profile` for the demo user.
- [ ] The "Recent transactions" table is ordered newest-first by date, matching
      `SELECT date FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC`.
- [ ] The "Spending by category" list is ordered highest-total-first, and each row's `%` reflects
      that category's share of the user's total spend (not the seeded-data hardcoded percentages).
- [ ] No hardcoded `PROFILE_STATS` / `PROFILE_TRANSACTIONS` / `PROFILE_CATEGORIES` remain in
      `app.py`.
- [ ] `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy`, and the Step 7–9 placeholder
      routes behave exactly as they did before this step.
