# Spec: Vercel Deployment Fix

## Overview

Spendly is deployed on Vercel (project `spendly`), and every request, including `/`, returns
`500 FUNCTION_INVOCATION_FAILED`. The app crashes on import, before Flask handles a single request,
so no route works. This is not a roadmap step. It is a fix that makes the existing Steps 1–6 app
start up on Vercel, and it leaves local development (`python app.py`) working exactly as it does
today. It sits between Step 6 and Step 7 and does not take a roadmap number.

### Root cause

From the Vercel runtime logs (deployment `dpl_5dTyg2PiuL3Y2gE4iexzrHcm5PE1`):

```
File "/var/task/app.py", line 29, in <module>
    init_db()
File "/var/task/database/db.py", line 18, in get_db
    conn = sqlite3.connect(DB_PATH)
sqlite3.OperationalError: unable to open database file
```

1. `database/db.py` sets `DB_PATH` to `<project root>/expense_tracker.db`. On Vercel the project
   root is `/var/task`.
2. `expense_tracker.db` is in `.gitignore`, so it is not in the deployment. SQLite has to create
   it.
3. A Vercel Function's filesystem is **read-only except for `/tmp`**, so SQLite cannot create the
   file under `/var/task`, and `sqlite3.connect()` raises.
4. `app.py` calls `init_db()` / `seed_db()` at import time, so the exception kills the whole
   module import. Vercel reports `could not import "app.py"` and returns 500 for every path.

Committing a pre-built `.db` file would **not** fix this. The directory would still be read-only,
so every write (registration, login-time seeding) would fail, and SQLite also needs to write
journal files next to the database.

### Second defect this fix exposes: stale sessions

Once the database lives in `/tmp`, it is empty on every cold start (reseeded with only the demo
user), but the browser's signed session cookie survives. That leads to two failures:

- **Crash / redirect trap (reproduced locally).** If `session["user_id"]` points to a user that
  isn't in the current database, `GET /profile` returns **500**
  (`jinja2.exceptions.UndefinedError: 'None' has no attribute 'name'` from `current_user['name']`
  in `profile.html`). `GET /login` sees a `user_id` in the session and redirects back to
  `/profile`, so the user is stuck until they visit `/logout`.
- **Cross-user exposure.** User IDs are `AUTOINCREMENT` per database. Say user A registers and
  gets `id = 2`, the instance goes cold, and user B then registers on a fresh instance and also
  gets `id = 2`. A's old cookie (`user_id = 2`) would show **B's profile and expenses**. A cookie
  that stores only `user_id` cannot tell these two users apart.

Both have to be fixed in this change, because moving the database to `/tmp` is what makes them
happen on Vercel.

### Known limitation: data does not persist on Vercel

This fix makes the deployed app **run**. It does not make its data **durable**. `/tmp` belongs to
one function instance and is wiped whenever that instance is recycled (idle cold start, redeploy,
scale-out to a second instance). On Vercel:

- The demo account (`demo@spendly.com` / `demo123`) and its 8 expenses always exist, because
  `seed_db()` runs on every cold start.
- Registered accounts, and the expenses added once Steps 7–9 exist, **will disappear** without
  warning, and concurrent instances will not see each other's data.

Durable storage needs a hosted database, e.g. Turso/libSQL (keeps the SQLite dialect) or a Vercel
Marketplace Postgres such as Neon. That breaks the CLAUDE.md constraints "stdlib `sqlite3` … no
external database" and "no new dependencies", so it is **out of scope** and needs its own spec
and decision. It should be settled before real users are pointed at the deployment.

## Depends on

- **Step 1 — Database Setup** (complete): `DB_PATH`, `get_db()`, `init_db()`, `seed_db()` in
  `database/db.py`, and the import-time `init_db()` / `seed_db()` calls in `app.py`.
- **Step 3 — Login and Logout** (complete): `session["user_id"]` set by `POST /login` and cleared by
  `/logout`; the `/login` GET redirect for signed-in users.
- **Steps 4–6 — Profile page** (complete): the `/profile` auth guard, `inject_current_user`, and
  `current_user` usage in `base.html` / `profile.html`.

## Routes

No new routes, and no route changes path, method, or access level. Two behaviours change:

- `GET /login` — redirects to `/profile` only when the session resolves to a **real, matching**
  user (see `get_current_user()` below). A stale session is cleared and the login page renders
  with 200 instead of bouncing to `/profile` — public
- `GET /profile` — a stale session is cleared and gets a `302` to exactly `/login` (the same
  response as signed-out), never a 500 — logged-in
- `POST /login` — on success, also stores `session["user_email"] = user["email"]` alongside the
  existing `session["user_id"]` — public

Every page that renders `base.html` also treats a stale session as signed out (nav shows the
signed-out links) and clears it, via the context processor.

### What counts as a valid session

`get_current_user()` in `app.py` returns the user row or `None`:

1. No `session["user_id"]` → `None` (session untouched).
2. `get_user_by_id(session["user_id"])` returns no row → `session.clear()`, return `None`.
3. The row's `email` is not equal to `session.get("user_email")` (this includes a missing
   `user_email`, as in cookies issued before this fix) → `session.clear()`, return `None`.
4. Otherwise return the row.

Sessions issued before this change carry no `user_email`, so those users must sign in once more.
That is intended.

## Database changes

No new tables, columns, indexes or constraints, and no change to any query.

`database/db.py` only changes **where** the database file lives. In the `# Setup` section, add a
private helper above `DB_PATH` and build `DB_PATH` from it:

```python
def _default_db_path():
    if os.environ.get("VERCEL"):
        return "/tmp/expense_tracker.db"
    return os.path.join(BASE_DIR, "expense_tracker.db")


DB_PATH = _default_db_path()
```

- `VERCEL=1` is a Vercel system environment variable, available at runtime when "Enable access to
  System Environment Variables" is on in the project's settings.
- Without `VERCEL` (local dev, pytest), the path is exactly what it is today.
- `DB_PATH` stays a module-level name that `get_db()` reads at call time, because `conftest.py`
  monkeypatches `db.DB_PATH`.
- `_default_db_path()` reads the environment when called, not at import time, so tests can check
  both branches with `monkeypatch.setenv` / `delenv` without reloading the module.

## Templates

**Create:** none.

**Modify:** none. `base.html` and `profile.html` keep using `current_user` unchanged. The fix is
that `current_user` is now `None` for stale sessions, and `/profile` redirects before it renders.

## Files to change

- `database/db.py`: `_default_db_path()` and `DB_PATH = _default_db_path()` in `# Setup`, as above.
  Nothing else in the file changes.
- `app.py`
  - `# Session helpers`: add `get_current_user()` (rules under **What counts as a valid session**)
    above `inject_current_user`, and change `inject_current_user` to return
    `{"current_user": get_current_user()}`.
  - `login()` GET: `if get_current_user():` replaces `if session.get("user_id"):`.
  - `login()` POST: after `session["user_id"] = user["id"]`, add
    `session["user_email"] = user["email"]`.
  - `profile()`: `user = get_current_user()`; if `None`, `return redirect(url_for("login"))`;
    otherwise `user_id = user["id"]`. The rest of `profile()` is unchanged.
  - `app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")` stays as is. The real
    key is supplied through Vercel environment variables (see **Definition of done**).
- `CLAUDE.md`
  - `database/db.py` paragraph: the DB file is `<project root>/expense_tracker.db` locally and
    `/tmp/expense_tracker.db` when `VERCEL` is set, chosen by `_default_db_path()`.
  - "Tech constraints", dev-server bullet: note that the app is also deployed to Vercel
    (zero-config Flask, entrypoint `app.py`), where the SQLite database is ephemeral and
    per-instance, and `SECRET_KEY` comes from the Vercel project's environment variables.
  - Roadmap table, `/login` row: it sets `session["user_id"]` **and** `session["user_email"]`, and
    signed-in checks go through `get_current_user()`.

## Files to create

- `tests/test_deployment.py`: tests for this spec (see **Definition of done**). Use the existing
  `client` fixture from `conftest.py`. Never write to the real `/tmp/expense_tracker.db` or the
  real project-root database from a test.

## New dependencies

No new dependencies. `os` is already imported in both files. No `vercel.json` or `pyproject.toml`
is needed: Vercel auto-detects the Flask `app` in `app.py`, and `requirements.txt` is unchanged.

## Rules for implementation

- No SQLAlchemy or ORMs, and no hosted or external database. Keep stdlib `sqlite3` through
  `database/db.py` (durable storage is a separate, out-of-scope decision; see **Overview**).
- Parameterised queries only (no query changes in this fix).
- Passwords hashed with werkzeug (unchanged).
- Use CSS variables and never hardcode hex values (no CSS changes in this fix).
- All templates extend `base.html` (no template changes in this fix).
- **Local behaviour is unchanged when `VERCEL` is not set**: same DB file location, same seed
  data, same pages.
- Do not commit `expense_tracker.db`, do not remove it from `.gitignore`, and do not try to bundle a
  database into the deployment.
- Do not hardcode or commit a secret key. Do not change the `SECRET_KEY` fallback in code.
- Keep the session key name `user_id` (`tests/test_login.py` reads it). `user_email` is added
  alongside it, not in place of it.
- `get_current_user()` never opens a connection itself; it calls `get_user_by_id()`.
- The import-time `init_db()` / `seed_db()` calls in `app.py` stay where they are. With a writable
  path they succeed, and on Vercel they are what recreate the demo account on each cold start.
- Do not wrap `init_db()` in `try/except` to hide the error. If the database can't be opened, the
  deployment should keep failing loudly.
- Do not touch `/`, `/register`, `/logout`, `/terms`, `/privacy`, any template, `style.css`,
  `main.js`, or the Step 7–9 placeholder routes. Do not move `static/` in this fix (see the static
  assets check below).
- All 47 existing tests must keep passing **unmodified**.

## Definition of done

### Automated (`pytest`, locally)

- [ ] `pytest` passes: the 47 existing tests unmodified, plus `tests/test_deployment.py`.
- [ ] `_default_db_path()` returns `"/tmp/expense_tracker.db"` when `VERCEL=1` is set.
- [ ] `_default_db_path()` returns `<project root>/expense_tracker.db` (the directory that contains
      `app.py`) when `VERCEL` is unset.
- [ ] After `POST /login` as the demo user, the session holds `user_id` equal to the demo user's id
      and `user_email` equal to `demo@spendly.com`.
- [ ] Session with `user_id = 999` (no such user): `GET /profile` returns `302` to `/login` and the
      session afterwards has no `user_id`. `GET /login` then returns `200` with the login form (no
      redirect loop).
- [ ] Session with only `user_id` = the demo user's id and **no** `user_email` (a pre-fix cookie):
      `GET /profile` returns `302` to `/login`, and the session is cleared.
- [ ] Session with `user_id` = the demo user's id but `user_email = "nitish@example.com"`:
      `GET /profile` returns `302` to `/login` and never shows "Demo User" or the demo expenses.
- [ ] With a stale session (`user_id = 999`), `GET /` returns `200`, does not contain `Hi, `, and
      clears the session.

### Manual, locally

- [ ] `python app.py` still creates and uses `expense_tracker.db` in the project root, and signing
      in as `demo@spendly.com` / `demo123` shows `$462.66` and `8` transactions on `/profile`.
- [ ] Simulated Vercel import: in a scratch shell,
      `VERCEL=1 venv/bin/python -c "import database.db as d; print(d.DB_PATH)"` prints
      `/tmp/expense_tracker.db`.

### Vercel project settings (dashboard, before redeploying)

- [ ] Settings → Environment Variables → **Enable access to System Environment Variables** is
      checked, so `VERCEL=1` exists at runtime.
- [ ] A `SECRET_KEY` environment variable is set for **Production** and **Preview** to a long random
      value (e.g. the output of `venv/bin/python -c "import secrets; print(secrets.token_hex(32))"`).
      It is never committed. Without it, the public fallback key lets anyone forge a session cookie.
- [ ] The branch is merged to `main` (or deployed as a preview), and a new deployment is created
      after the variable is added. Env var changes only apply to new deployments.

### On the deployed site

- [ ] `https://spendly-nine-bay.vercel.app/` returns `200` and renders the landing page.
- [ ] The deployment's runtime logs contain no `unable to open database file` and no
      `could not import "app.py"`.
- [ ] `/favicon.ico` returns `404`, not `500` (no favicon exists; the crash was the only reason it
      500'd).
- [ ] **Static assets check:** `/static/css/style.css` returns `200` with a CSS content type and the
      pages are styled. Vercel's Flask docs recommend `public/**` over Flask's `static_folder`. If
      this check fails, record it; moving assets to `public/` is a follow-up change, not part of
      this fix.
- [ ] Signing in as `demo@spendly.com` / `demo123` lands on `/profile` with `$462.66`, `8`
      transactions, and a working date filter.
- [ ] Registering "Nitish Kumar" / `nitish@example.com`, then signing in, shows that user's empty
      profile (`$0.00`) during the same visit.
- [ ] After a **redeploy**, which forces fresh instances with empty `/tmp`, the browser still holding
      the Nitish cookie loads `/profile` as a redirect to `/login` (no 500), and the demo account
      still signs in. Nitish's account is gone, which is expected (see **Known limitation**).
- [ ] `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy` and the Step 7–9 placeholder
      routes behave as they do locally.
