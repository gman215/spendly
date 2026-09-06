# Spec: Registration

## Overview

Make the registration form actually create accounts. Today `templates/register.html` POSTs to
`/register`, but `app.py` only defines a `GET` handler, so submitting the form returns a 405 and
the `{% if error %}` block in the template is never populated. This step adds `POST` handling to
the `/register` route: validate the submitted name / email / password, hash the password with
werkzeug, insert a row into the `users` table via a new `database/db.py` helper, and redirect the
new user to the sign-in page. It is the first feature that writes user data, and it turns the
Step 1 `users` schema into something the rest of the roadmap (login, sessions, profile, expenses)
can build on. Sessions are deliberately **not** part of this step — a successful registration
sends the user to `/login` rather than logging them in.

## Depends on

- **Step 1 — Database Setup** (complete): `get_db()`, `init_db()` and `seed_db()` exist in
  `database/db.py`, and the `users` table (`id`, `name`, `email` UNIQUE, `password_hash`,
  `created_at`) is created on app startup.

Nothing else. This step does not depend on login/logout (Step 3) and must not implement it.

## Routes

- `GET /register` — render the empty registration form — public *(already exists; the route
  decorator changes to accept POST as well)*
- `POST /register` — validate the submitted form, create the user, redirect to
  `/login?registered=1` on success; re-render `register.html` with `error` on failure — public
- `GET /login` — unchanged behaviour, but now reads the `registered` query parameter so the login
  page can show a "account created" confirmation — public

No other routes change. The Step 3–9 placeholder routes stay exactly as they are.

## Database changes

**No schema changes.** The `users` table created by `init_db()` in `database/db.py` already has
every column this feature needs, including the `UNIQUE` constraint on `email` that backs the
duplicate-account check.

Two new query helpers are added to `database/db.py` (no new tables, columns or constraints):

- `get_user_by_email(email)` — `SELECT` a single user row by email; returns the `sqlite3.Row` or
  `None`.
- `create_user(name, email, password)` — hash `password` with `generate_password_hash`, `INSERT`
  into `users`, commit, and return the new `lastrowid`.

Both open their connection with `get_db()` and close it before returning.

## Templates

**Create:** none.

**Modify:**

- `templates/register.html`
  - Re-populate `name` and `email` with the submitted values when the form is re-rendered after an
    error (`value="{{ name or '' }}"`, `value="{{ email or '' }}"`), so the user doesn't retype
    everything. The password field is never re-populated.
  - Keep the existing `{% if error %}<div class="auth-error">` block as-is — it is the error
    surface this step finally populates.
  - No other markup changes: same classes, same hardcoded `action="/register"`, same
    "Nitish Kumar" / "nitish@example.com" placeholders.
- `templates/login.html`
  - Add a single `{% if registered %}<div class="auth-success">Account created — sign in
    below.</div>{% endif %}` block directly above the existing `{% if error %}` block inside
    `.auth-card`. This is the only change to this file.

## Files to change

- `app.py`
  - `from flask import Flask, render_template, request, redirect, url_for`
  - `from database.db import get_db, init_db, seed_db, get_user_by_email, create_user`
  - `@app.route("/register", methods=["GET", "POST"])` — GET renders the form; POST validates,
    creates the user, and redirects.
  - `login()` passes `registered=request.args.get("registered")` into `render_template`.
  - Both view functions stay in the existing `# Routes` section, above the
    `# Placeholder routes` banner.
- `database/db.py`
  - Add a `# Users` section banner and the `get_user_by_email()` / `create_user()` helpers below
    the existing seed-data section.
- `templates/register.html` — sticky form values (see above).
- `templates/login.html` — success notice (see above).
- `static/css/style.css` — add `.auth-success` in the existing auth section, immediately after
  `.auth-error`, built from existing custom properties (`--accent-light`, `--accent`,
  `--radius-sm`) and mirroring `.auth-error`'s box metrics.

## Files to create

None.

## New dependencies

No new dependencies. `werkzeug.security.generate_password_hash` is already imported by
`database/db.py`, and `request` / `redirect` / `url_for` ship with Flask 3.1.3.

## Validation rules

Applied in the `POST /register` handler, in this order; the first failure re-renders the form with
a single `error` string and an HTTP 200:

1. Strip whitespace from `name` and `email`; lowercase `email`. Do not strip the password.
2. All three fields required → `"All fields are required."`
3. Email must contain an `@` with text either side → `"Enter a valid email address."`
4. Password must be at least 8 characters → `"Password must be at least 8 characters."`
5. Email must not already exist (`get_user_by_email`) → `"An account with that email already
   exists."`

Wrap the `create_user()` call in a `try` / `except sqlite3.IntegrityError` that falls back to the
same duplicate-email message, so a race between the check and the insert surfaces as a form error
rather than a 500.

## Rules for implementation

- No SQLAlchemy or ORMs — stdlib `sqlite3` only, through `database/db.py`.
- Parameterised queries only. Never build SQL with f-strings, `%`, or concatenation.
- Passwords hashed with `werkzeug.security.generate_password_hash`; the plaintext password is
  never stored, logged, or passed back to a template.
- All SQL and connection handling lives in `database/db.py`. The route must not `import sqlite3`
  for a connection of its own — it may import `sqlite3` only to catch `IntegrityError`.
- Keep the view function thin: parse `request.form` → validate → call a `db.py` helper → render or
  redirect.
- Use CSS variables — never hardcode a hex value. `.auth-success` reuses `--accent-light`,
  `--accent`, `--radius-sm` and the existing spacing scale.
- New CSS goes in `static/css/style.css` in the existing auth section — no inline styles, no new
  stylesheet.
- All templates extend `base.html`; no new template is created and `base.html` is not touched.
- Keep the forms' hardcoded `action="/register"` / `action="/login"` paths — do not "fix" them to
  `url_for`.
- No sessions, no `secret_key`, no `flash()`, no login — that is Step 3. Success is communicated
  with the `?registered=1` query parameter.
- Do not touch the Step 3–9 placeholder routes, the landing/terms/privacy templates, or any
  unrelated CSS.
- Redirect after a successful POST (POST/Redirect/GET) so a browser refresh doesn't resubmit.

## Definition of done

Verified by running `python app.py` and using the app at `http://localhost:5001`:

- [ ] `GET /register` still renders the form exactly as before, with no error box visible.
- [ ] Submitting the form with a new name / email / password ≥ 8 chars redirects to
      `/login?registered=1`, and the login page shows the "Account created" success notice.
- [ ] The new row exists in the `users` table with the correct name and lowercased email:
      `sqlite3 expense_tracker.db "SELECT id, name, email FROM users;"`
- [ ] `password_hash` for the new row starts with `scrypt:` (or `pbkdf2:`) — the plaintext
      password appears nowhere in the database.
- [ ] Submitting with any field blank re-renders `/register` with "All fields are required."
- [ ] Submitting `notanemail` as the email re-renders with "Enter a valid email address."
- [ ] Submitting a 7-character password re-renders with "Password must be at least 8 characters."
- [ ] Registering with `demo@spendly.com` (the seeded user) re-renders with "An account with that
      email already exists." and no second row is inserted.
- [ ] After any validation error, the name and email fields are still filled in and the password
      field is empty.
- [ ] Registering the same new email twice leaves exactly one row for it.
- [ ] Refreshing the login page after a successful registration does not create a duplicate user.
- [ ] `/login`, `/`, `/terms`, `/privacy` and every placeholder route behave exactly as they did
      before this step.
