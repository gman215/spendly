# Spec: Add Expense

## Overview

Turn the `/expenses/add` placeholder into a form that lets a signed-in user record an expense. Until
now every expense on `/profile` has come from `seed_db()`: Steps 5 and 6 read the `expenses` table,
but nothing in the app can write to it, so a newly registered user's profile is permanently
`$0.00`. This step adds `GET /expenses/add`, which shows a form for amount, category, date (defaulting
to today) and an optional description, and `POST /expenses/add`, which validates the input, inserts
a row for the signed-in user through a new `create_expense()` helper, and redirects to
`/profile?added=1`. The profile page shows an "Expense added." notice there. Its stats, transactions
table, category breakdown and date filter pick up the new row with no query changes, because they
already read from the table. The profile page also gains an "Add expense" button, the only way to
reach the form. This is the first step where users write their own expense data, and Step 8 (edit)
will reuse its validation. On the Vercel deployment, expenses land in the ephemeral `/tmp` database
and disappear on cold starts. That is the known limitation in `.claude/specs/fix-vercel-deployment.md`
and is out of scope here.

## Depends on

- **Step 1 — Database Setup** (complete): the `expenses` table (`user_id`, `amount` REAL, `category`,
  `date` TEXT, `description` nullable) and the `CATEGORIES` list in `database/db.py`.
- **Step 3 — Login and Logout** and the **Vercel deployment fix** (complete): `get_current_user()` in
  `app.py` is the auth guard, and the user it returns is the only source of `user_id`.
- **Steps 4–6 — Profile page** (complete): `templates/profile.html`, the `profile()` context shape,
  `get_expenses_by_user()` ordering (`date DESC, id DESC`), and the Step 6 date filter, whose plain
  text comparison requires dates stored as zero-padded `YYYY-MM-DD`.

## Routes

- `GET /expenses/add` — render the empty form with the date pre-filled to today — logged-in
- `POST /expenses/add` — validate; on success insert the expense and `302` to `/profile?added=1`; on
  failure re-render the form with HTTP 200, one error message, and the submitted values — logged-in
- `GET /profile` — unchanged path, method and guard; also reads the `added` query parameter to show
  the success notice — logged-in

The route decorator becomes `@app.route("/expenses/add", methods=["GET", "POST"])`, and the view
keeps its name, `add_expense`. It moves out of the `# Placeholder routes` section into `# Routes`,
directly below `profile()`, the same way `logout()` moved in Step 3. The Step 8 and Step 9
placeholders stay where they are.

A signed-out visitor, or one with a stale session, gets a `302` to exactly `/login` on both `GET` and
`POST`, and a `POST` inserts nothing.

### Validation (applied in this order)

Validation lives in a new helper in the `# Request helpers` section of `app.py`, next to
`parse_date_range()`: `parse_expense_form(form)` returns `(values, expense, error)`.

- `values` is always a dict of the four submitted fields, each `.strip()`ped: `amount`, `category`,
  `date`, `description`. It is what the form is re-filled with.
- `expense` is `None` on error. On success it is a dict with `amount` (a `float` rounded to 2
  places), `category`, `date` (`.isoformat()` string) and `description` (the stripped string, or
  `None` when blank), ready to pass as `create_expense(user["id"], **expense)`.
- `error` is `None` or the first message below.

1. Read the four fields from `request.form` and strip each. Missing fields count as `""`.
2. `amount`, `category` or `date` empty → `"Amount, category and date are required."`
3. `amount` must fully match `[0-9]+(\.[0-9]{1,2})?` (`re.fullmatch`, ASCII digits only) and be
   greater than 0 → `"Amount must be a number greater than 0 with at most 2 decimal places."` This
   rejects `0`, `0.00`, `-5`, `abc`, `12.345`, `1e3`, `nan`, `inf`, `$5` and `1,000`.
4. `float(amount)` greater than `1000000` → `"Amount must be 1,000,000 or less."` (`1000000` itself is
   allowed.) The cap also stops a 400-digit string from becoming `inf`.
5. `category` not exactly one of `CATEGORIES` (case-sensitive) → `"Choose a category from the list."`
6. `date` not parseable with `datetime.strptime(date, "%Y-%m-%d")` →
   `"Enter a valid date in YYYY-MM-DD format."` (the same message as Step 6). On success, store
   `.date().isoformat()`, never the raw string: `strptime` accepts `2026-9-1`, and the Step 6 filter
   would miss that row.
7. `description` longer than 200 characters (after stripping) →
   `"Description must be 200 characters or fewer."`

Future dates are allowed, and there is no minimum date. The server clock is UTC on Vercel, so a
"no future dates" rule would reject today's date for users ahead of UTC.

On an error, `add_expense()` renders `add_expense.html` with HTTP 200, `error`, `categories`, and
`**values`. Nothing is written.

## Database changes

No new tables, columns, indexes or constraints. The Step 1 `expenses` table already has every
column.

One write helper is added at the end of the `# Expenses` section in `database/db.py`:

- `create_expense(user_id, amount, category, date, description=None)`:
  `INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)`, then
  commit, close, and return `lastrowid`. It opens its connection with `get_db()` like every other
  helper. `created_at` is left to the column default.

It is named `create_expense`, not `add_expense`, so it doesn't collide with the view function it is
imported next to (and it matches `create_user()`).

## Templates

**Create:** `templates/add_expense.html`, which `{% extends "base.html" %}` with
`{% block title %}Add expense — Spendly{% endblock %}`:

- `<section class="expense-section">` › `<div class="expense-container">`
  - `.expense-header` with `<h1 class="expense-title">Add an expense</h1>` and
    `<p class="expense-subtitle">Log what you spent and when</p>`
  - `.expense-card` containing:
    - `{% if error %}<div class="expense-error">{{ error }}</div>{% endif %}`
    - `<form method="POST" action="/expenses/add">` with four `.form-group`s, each a `<label for>`
      plus a control with class `form-input`:
      - **Amount**: `<input type="number" id="amount" name="amount" step="0.01" min="0.01"
        max="1000000" inputmode="decimal" placeholder="0.00" value="{{ amount or '' }}" required
        autofocus>`
      - **Category**: `<select id="category" name="category" required>` whose first option is
        `<option value="">Choose a category</option>`, followed by one `<option>` per entry in
        `categories`, in `CATEGORIES` order, with `selected` when it equals `category`
      - **Date**: `<input type="date" id="date" name="date" value="{{ date or '' }}" required>`
      - **Description (optional)**: `<input type="text" id="description" name="description"
        maxlength="200" placeholder="Groceries at Trader Joe's" value="{{ description or '' }}">`
    - `<button type="submit" class="btn-submit">Add expense</button>`
  - `<p class="expense-cancel"><a href="/profile">Cancel</a></p>` below the card

On `GET`, `add_expense()` passes `categories=CATEGORIES` and `date=date.today().isoformat()`, and
nothing else.

**Modify:** `templates/profile.html` only.

- **Notice**: `{% if added %}<div class="profile-notice">Expense added.</div>{% endif %}` directly
  after `.profile-header` and before the `.filter-bar` form.
- **Add button**: replace the Transactions panel's `<h2 class="profile-panel-title">Transactions</h2>`
  with `<div class="profile-panel-head">`, which holds that same `<h2>` followed by
  `<a href="/expenses/add" class="btn-primary">Add expense</a>`. The "Spending by category" panel
  title is unchanged.
- Nothing else in the template changes.

## Files to change

- `app.py`
  - Imports: `import re`; `from datetime import date, datetime`; add `CATEGORIES` and
    `create_expense` to the `from database.db import (...)` list.
  - `# Request helpers`: add `parse_expense_form(form)` below `parse_date_range()`, as described
    under **Validation**. Don't name a local variable `date` (it would shadow the import).
  - `add_expense()`: guard with `user = get_current_user()` / `redirect(url_for("login"))`; `GET`
    renders the empty form; `POST` calls `parse_expense_form(request.form)`, re-renders on error, or
    calls `create_expense(user["id"], **expense)` and returns
    `redirect(url_for("profile", added=1))`. Move it into `# Routes` below `profile()`.
  - `profile()`: pass `added=request.args.get("added")` to `render_template`, and build each
    transaction's `"description"` as `row["description"] or "—"` (Jinja would otherwise print `None`
    for a blank description). Nothing else in `profile()` changes.
- `database/db.py`: add `create_expense()` at the end of `# Expenses`.
- `templates/profile.html`: notice and Add button (see **Templates**).
- `static/css/style.css`
  - In the "Profile page" section: a `/* Notices */` sub-section just before `/* Date filter */` with
    `.profile-notice` (`--accent-light` background, `--accent` text and 1px border, `--radius-sm`,
    same box metrics as `.filter-error`). In `/* Panels */`, add `.profile-panel-head` (flex,
    `justify-content: space-between`, `align-items: center`, `flex-wrap: wrap`, `gap: 1rem`,
    `margin-bottom: 1.25rem`) and `.profile-panel-head .profile-panel-title { margin-bottom: 0; }`.
  - A new top-level `Expense form` banner section between "Profile page" and "Legal pages", with
    `.expense-section`, `.expense-container` (`max-width: var(--auth-width)`), `.expense-header`,
    `.expense-title`, `.expense-subtitle`, `.expense-card`, `.expense-error` (`--danger-light` /
    `--danger`, with a `var(--danger)` border rather than `.auth-error`'s hardcoded hex),
    `.expense-cancel` and `.expense-cancel a` (with a hover state). Mirror the auth page metrics.
    Reuse `.form-group`, `.form-input` and `.btn-submit` as-is.
- `CLAUDE.md`
  - Move `/expenses/add` from the Stub table to the Implemented table:
    `| /expenses/add | GET, POST | Step 7 — signed-in only; parse_expense_form() validates, create_expense() inserts, redirects to /profile?added=1 |`.
  - `/profile` row: mention the `?added=1` notice and the "Add expense" button.
  - `database/db.py` paragraph: list `create_expense()`, and change "the expense routes above still
    need their own write helpers (insert/update/delete)" so it says only Steps 8–9 still need
    update/delete helpers.

## Files to create

- `templates/add_expense.html` (see **Templates**).
- `tests/test_add_expense.py`: pytest coverage for this spec using the existing `client` fixture,
  with the section banners and `sign_in` helper style of `tests/test_profile.py`.

## New dependencies

No new dependencies. `re` and `datetime` are stdlib, and `<input type="number">`,
`<input type="date">` and `<select>` need no JS or library.

## Rules for implementation

- No SQLAlchemy or ORMs. Use stdlib `sqlite3` only, through `database/db.py`.
- Parameterised queries only. All five inserted values go through `?` placeholders, with no
  f-strings, `%` or concatenation.
- Passwords hashed with werkzeug (unchanged, since this step touches no auth code).
- Use CSS variables and never hardcode hex values, in both the new "Expense form" section and the new
  profile rules.
- All templates extend `base.html`, including `add_expense.html`.
- All SQL stays in `database/db.py`; `add_expense()` and `parse_expense_form()` never open a
  connection.
- `user_id` comes only from `get_current_user()`. Any `user_id` (or other extra) field in the
  submitted form is ignored.
- Server-side validation is the authority. The HTML `required`, `min`, `max`, `step` and `maxlength`
  attributes are only a convenience, and tests POST directly.
- Store `amount` as a REAL rounded to 2 places, `date` as zero-padded `YYYY-MM-DD`, and a blank
  description as `NULL` (never `""`).
- POST/Redirect/GET: success always redirects, so refreshing `/profile?added=1` never adds a second
  expense.
- The success notice uses the `?added=1` query-parameter pattern from Steps 2–3. No `flash()`.
- Keep hardcoded paths, matching the other forms: `action="/expenses/add"`, `href="/expenses/add"`,
  `href="/profile"`.
- Existing profile tests constrain the profile section markup:
  - no `#` anywhere (no `href="#"`)
  - no date strings above `<tbody>`, so the Add link carries no `?date=` and the notice text contains
    no date
  - no new class name containing `cat-row`
- No JavaScript (`main.js` is unchanged), no navbar link (`base.html` is unchanged), no custom
  categories, receipts, recurring expenses, currencies or CSRF tokens (no existing form has one), and
  no empty-state message for users without expenses. These are out of scope.
- Do not implement edit or delete (Steps 8–9), and leave their placeholder routes as they are.
- Do not touch `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy`, their templates, or
  `base.html`.
- All 55 existing tests must keep passing **unmodified**.

## Definition of done

Verified by running `python app.py` and using the app at `http://localhost:5001` signed in as
`demo@spendly.com` / `demo123`. Unless an item says otherwise, the figures assume only the 8 seeded
demo expenses (`$462.66` total, as in the pytest `client` fixture). `TODAY` is today's date as
`YYYY-MM-DD`.

- [ ] `pytest` passes: the 55 existing tests unmodified, plus `tests/test_add_expense.py`.
- [ ] `/profile` shows an "Add expense" button in the Transactions panel header linking to
      `/expenses/add`, and no "Expense added." notice.
- [ ] Signed out, `GET /expenses/add` redirects (302) to `/login`. A signed-out `POST /expenses/add`
      with valid data also redirects to `/login` and inserts no row.
- [ ] Signed in, `GET /expenses/add` returns 200 with an empty amount, a category select holding
      "Choose a category" plus the 7 categories in order (Food, Transport, Bills, Health,
      Entertainment, Shopping, Other), the date pre-filled with `TODAY`, an empty description, no
      error box, and a Cancel link to `/profile`.
- [ ] Submitting `12.34` / Food / `TODAY` / `Coffee beans` redirects to `/profile?added=1`, which
      shows "Expense added.", `$475.00` total, `9` transactions, Bills still as top category, a
      "Coffee beans" row with a Food badge and `$12.34`, and a Food category row of `$108.76`.
- [ ] `sqlite3 expense_tracker.db "SELECT amount, category, date, description FROM expenses ORDER BY id DESC LIMIT 1;"`
      returns `12.34|Food|TODAY|Coffee beans`.
- [ ] Refreshing `/profile?added=1` does not add another expense (still `9` transactions).
- [ ] Submitting `150` / Shopping makes Shopping the top category (`$239.99`), with `$612.66` total.
- [ ] Submitting with a blank description saves the row with `description` `NULL`, and its table row
      shows `—` in the Description column.
- [ ] A back-dated expense (`2000-01-01`) appears as the last table row, and
      `/profile?start_date=2000-01-01&end_date=2000-01-01` shows only that expense.
- [ ] A POST with date `2026-9-1` is stored as `2026-09-01`.
- [ ] Surrounding whitespace is stripped: amount `  12.50  ` and description `  Lunch  ` are stored as
      `12.5` and `Lunch`.
- [ ] Each of these returns 200 with the quoted message and inserts no row:
  - [ ] a blank amount, category or date → "Amount, category and date are required."
  - [ ] amount `0`, `-5`, `abc`, `12.345`, `1e3`, `nan` or `$5` → "Amount must be a number greater
        than 0 with at most 2 decimal places."
  - [ ] amount `1000000.01` → "Amount must be 1,000,000 or less." (`1000000` is accepted)
  - [ ] category `Groceries` or `food` → "Choose a category from the list."
  - [ ] date `2026-02-30` or `not-a-date` → "Enter a valid date in YYYY-MM-DD format."
  - [ ] a 201-character description → "Description must be 200 characters or fewer." (exactly 200 is
        accepted)
- [ ] After a validation error, the amount, date and description inputs keep the submitted values,
      and a valid submitted category stays selected.
- [ ] A description of `'); DROP TABLE expenses; --` is stored and shown literally, and
      `<script>alert(1)</script>` is shown escaped, not executed.
- [ ] Scoping: signed in as the demo user, a POST with an extra `user_id` field set to another user's
      id stores the row under the demo user.
- [ ] A new user (register "Nitish Kumar" / `nitish@example.com`) who adds `20.00` / Transport sees
      `$20.00`, `1` transaction and Transport as top category. The demo user's totals are unchanged.
- [ ] No hex colour values and no `#` appear in the add-expense section, or in the profile section
      with or without `?added=1`.
- [ ] At ≤ 600px width the form is usable, and the Transactions panel header wraps without overflow.
- [ ] `/expenses/1/edit` and `/expenses/1/delete` still return their Step 8 and Step 9 placeholder
      strings, and `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy` behave as before.
