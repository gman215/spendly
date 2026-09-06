# Spec: Login and Logout

## Overview

Give Spendly a working session. Registration (Step 2) creates accounts, but `templates/login.html`
POSTs to `/login` and `app.py` only defines a `GET` handler, so signing in returns a 405 and
`/logout` is still a placeholder string. This step adds `POST /login`: look the user up by email,
verify the submitted password against `password_hash` with `werkzeug.security.check_password_hash`,
and on success store the user's id in Flask's signed-cookie `session` and redirect to the landing
page. `/logout` becomes a real route that clears the session and returns the visitor to
`/login?logged_out=1`. The navbar in `base.html` starts reflecting who is signed in. This is the
step that makes "the current user" a concept the app can use — every later step (profile in Step 4,
and all the expense routes, which are scoped by `user_id`) depends on it.

## Depends on

- **Step 1 — Database Setup** (complete): `get_db()`, `init_db()`, `seed_db()`, and the `users`
  table with `id`, `email` UNIQUE and `password_hash`.
- **Step 2 — Registration** (complete): `create_user()` writes werkzeug password hashes and
  `get_user_by_email()` already provides the lookup this step verifies against; the seeded
  `demo@spendly.com` / `demo123` account gives us a known-good login.

Nothing else. This step does **not** implement `/profile` (Step 4) or any route protection for the
expense routes (Steps 7–9).

## Routes

- `GET /login` — render the sign-in form; show the `registered` notice (from Step 2) and the new
  `logged_out` notice; redirect to `/` if the visitor already has a session — public
  *(already exists; the route decorator changes to accept POST as well)*
- `POST /login` — validate the submitted email / password, verify the hash, set
  `session["user_id"]`, redirect to `/`; re-render `login.html` with `error` on failure — public
- `GET /logout` — clear the session and redirect to `/login?logged_out=1`; harmless when nobody is
  signed in — public *(currently the Step 3 placeholder string)*

No other routes change. The Step 4 and Step 7–9 placeholder routes stay exactly as they are.

## Database changes

**No schema changes.** The `users` table created by `init_db()` already has every column this
feature needs — `id` for the session value and `password_hash` for verification.

One new query helper is added to `database/db.py`, in the existing `# Users` section next to
`get_user_by_email()` (no new tables, columns or constraints):

- `get_user_by_id(user_id)` — `SELECT * FROM users WHERE id = ?`; returns the `sqlite3.Row` or
  `None`. Used to resolve `session["user_id"]` into a user for the navbar, and to detect a stale
  session cookie pointing at a deleted user.

It opens its connection with `get_db()` and closes it before returning, exactly like
`get_user_by_email()`.

## Templates

**Create:** none.

**Modify:**

- `templates/login.html`
  - Add `{% if logged_out %}<div class="auth-success">You've been signed out.</div>{% endif %}`
    directly above the existing `{% if registered %}` block inside `.auth-card`, reusing the
    `.auth-success` style added in Step 2.
  - Re-populate the email field after a failed sign-in (`value="{{ email or '' }}"`). The password
    field is never re-populated.
  - Keep the existing `{% if error %}` block, the same classes, the hardcoded `action="/login"`,
    and the "nitish@example.com" placeholder.
- `templates/base.html`
  - Wrap the two links in `.nav-links` in `{% if current_user %}` / `{% else %}`:
    - signed in → `<span class="nav-user">Hi, {{ current_user['name'] }}</span>` and
      `<a href="{{ url_for('logout') }}" class="nav-cta">Sign out</a>`
    - signed out → the existing "Sign in" and "Get started" links, unchanged
  - `Sign out` takes the `.nav-cta` slot so it survives the mobile rule that hides
    non-`.nav-cta` nav links.
  - Nothing else in `base.html` changes — same nav/footer structure, same blocks.

## Files to change

- `app.py`
  - `import os`; `from flask import Flask, redirect, render_template, request, session, url_for`;
    `from werkzeug.security import check_password_hash`.
  - `from database.db import create_user, get_db, get_user_by_email, get_user_by_id, init_db, seed_db`.
  - Set `app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")` immediately after
    the app is created — without it `session` raises at runtime.
  - New `# Session helpers` section banner (between the database-setup and `# Routes` banners)
    holding a single `@app.context_processor` that resolves `session.get("user_id")` through
    `get_user_by_id()` and injects `current_user` (`None` when signed out) into every template, so
    `base.html` needs nothing passed to it per-route.
  - `@app.route("/login", methods=["GET", "POST"])` — GET renders the form, POST authenticates.
  - `logout()` moves out of the `# Placeholder routes` section into `# Routes`, above the
    remaining placeholders.
- `database/db.py` — add `get_user_by_id()` in the existing `# Users` section.
- `templates/login.html` — signed-out notice and sticky email (see above).
- `templates/base.html` — session-aware nav links (see above).
- `static/css/style.css` — add a single `.nav-user` rule in the existing navbar section, next to
  `.nav-links a`, using existing custom properties (`--ink-muted`) and the existing nav font sizing.
  No other CSS changes; `.auth-success` and `.auth-error` are reused as-is.

## Files to create

- `tests/test_login.py` — pytest coverage for this step, mirroring the structure and the section
  banners of `tests/test_register.py` and using the existing `client` fixture from `conftest.py`
  (which points `db.DB_PATH` at a temp database and seeds the demo user).

## New dependencies

No new dependencies. `session` ships with Flask 3.1.3, `check_password_hash` with Werkzeug 3.1.6,
and `os` is stdlib.

## Validation rules

Applied in the `POST /login` handler, in this order; the first failure re-renders the form with a
single `error` string and an HTTP 200:

1. Strip whitespace from `email` and lowercase it. Do not strip the password.
2. Both fields required → `"Email and password are required."`
3. Look the user up with `get_user_by_email()`; if there is no row, **or**
   `check_password_hash(user["password_hash"], password)` is false →
   `"Incorrect email or password."`

Use that one message for both the unknown-email and wrong-password cases — never reveal whether an
account exists. On success: `session.clear()` (drop any stale session before writing the new one),
then `session["user_id"] = user["id"]`, then redirect to `url_for("landing")`.

## Rules for implementation

- No SQLAlchemy or ORMs — stdlib `sqlite3` only, through `database/db.py`.
- Parameterised queries only. Never build SQL with f-strings, `%`, or concatenation.
- Passwords hashed with werkzeug: verify with `check_password_hash`, never by comparing strings,
  never by re-hashing and comparing. No plaintext password is stored, logged, or passed back to a
  template.
- All SQL and connection handling stays in `database/db.py`; the login view calls
  `get_user_by_email()` rather than opening a connection of its own.
- Keep the view functions thin: parse `request.form` → validate → call a `db.py` helper → render or
  redirect. `logout()` is two lines.
- Session state is only ever `session["user_id"]` — an integer id, resolved through
  `get_user_by_id()`. Never store the name, email, or password hash in the cookie.
- Use CSS variables — never hardcode a hex value. `.nav-user` reuses `--ink-muted`.
- New CSS goes in `static/css/style.css` in the existing navbar section — no inline styles, no new
  stylesheet.
- All templates extend `base.html`; no new template is created.
- Keep the form's hardcoded `action="/login"` path — do not "fix" it to `url_for`.
- Redirect after a successful POST (POST/Redirect/GET) so a refresh doesn't resubmit credentials.
- No `flash()`, no `@login_required` decorator, no "remember me", no password reset, no
  `/profile` implementation, and no protection added to the Step 7–9 expense routes — those are
  later steps. Notices use the `?registered=1` / `?logged_out=1` query-parameter pattern
  established in Step 2.
- Do not touch the registration flow, the landing/terms/privacy templates, `tests/test_register.py`,
  or any unrelated CSS.

## Definition of done

Verified by running `python app.py` and using the app at `http://localhost:5001`:

- [ ] `GET /login` still renders the form as before, with no error or notice box visible.
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/`, and the navbar shows
      "Hi, Demo User" plus a "Sign out" button instead of "Sign in" / "Get started".
- [ ] The signed-in navbar persists across `/`, `/terms` and `/privacy` — the session survives
      navigation and a browser refresh.
- [ ] `  DEMO@Spendly.com  ` (padded and mixed case) signs in successfully.
- [ ] Signing in with the right email and a wrong password re-renders `/login` with "Incorrect
      email or password." and no session is created.
- [ ] Signing in with an email that has no account shows that same message — the wording does not
      reveal whether the account exists.
- [ ] Submitting with either field blank re-renders with "Email and password are required."
- [ ] After a failed sign-in the email field is still filled in and the password field is empty.
- [ ] Registering a brand-new account at `/register` and then signing in with those credentials
      works end to end.
- [ ] Clicking "Sign out" redirects to `/login?logged_out=1`, the page shows "You've been signed
      out.", and the navbar is back to "Sign in" / "Get started".
- [ ] Visiting `/logout` while already signed out redirects to the same place without erroring.
- [ ] Visiting `/login` while signed in redirects to `/`.
- [ ] `/logout` no longer returns the "coming in Step 3" placeholder string.
- [ ] `/`, `/register`, `/terms`, `/privacy` and every remaining placeholder route behave exactly
      as they did before this step.
- [ ] `pytest` passes: the Step 2 registration tests still pass and `tests/test_login.py` covers
      successful sign-in, both failure messages, session clearing on logout, and the signed-in
      navbar.
