# Spec: AI Expense Autofill

## Overview

Add Google Gemini to the add-expense page. A signed-in user can fill in the form from a receipt
photo or from a plain-English note such as "spent 23.50 on an Uber yesterday". This is an
off-roadmap feature built after Step 7, and it builds on Step 7's form and validation instead of
adding a second way to write expenses. Gemini returns JSON that follows a schema, the server cleans
each field, and the result pre-fills the existing form. The user reviews it and saves through
`POST /expenses/add` as usual, so nothing the model says reaches the database until the user and
`parse_expense_form()` have both seen it. Steps 8–9 (edit and delete) are not touched.

## Depends on

- **Step 7 — Add Expense** (complete): `templates/add_expense.html`, `parse_expense_form()`,
  `create_expense()` and the `CATEGORIES` list.
- **Step 3 — Login and Logout** and the **Vercel deployment fix** (complete): `get_current_user()` is
  the only source of `user_id`. The Vercel database lives in `/tmp` and is temporary.

## Routes

- `POST /expenses/autofill` — logged-in. It takes either a `receipt` file (multipart) or a `note`
  text field, plus an optional `today` field holding the browser's local date. It re-renders
  `add_expense.html`, pre-filled on success or with `autofill_error` set otherwise, and it never
  inserts an expense. A signed-out visitor gets a `302` to `/login`.
- `GET /expenses/add` and `POST /expenses/add` — behaviour unchanged. Both now render through
  `render_expense_form()`, which adds `categories`, `ai_enabled` and a default `date` of today, so the
  autofill panel also shows after a validation error.

Checks, in order:

1. Signed out → `302` to `/login`.
2. `GEMINI_API_KEY` blank or missing → `error` (the main form's error box):
   "AI autofill isn't available right now. Add the expense by hand."
3. `parse_autofill_form(form, files)` returns `(note, receipt, error)`:
   - A `receipt` with a filename takes priority. Its mimetype must be in `IMAGE_TYPES` (JPEG, PNG,
     WebP, HEIC, HEIF), otherwise "Choose a JPEG, PNG, WebP or HEIC photo.". An empty file gives
     "That photo is empty. Choose another one."
   - Otherwise the stripped `note` must be non-blank ("Choose a receipt photo or describe the
     expense.") and at most 300 characters ("Keep the description to 300 characters or fewer.").
4. `count_ai_requests_today(user_id) >= DAILY_LIMIT` (30) →
   "You've used all 30 AI autofills for today. You can still add expenses by hand."
5. `log_ai_request(user_id, "receipt" | "note")`, then call Gemini. Failed calls count toward the
   limit, but submissions rejected in steps 2–4 don't.
6. `AutofillError` → its message is shown as `autofill_error`.

A request body over `MAX_CONTENT_LENGTH` (4 MB) on this path, from a signed-in user, gets HTTP 413
with the `autofill_error` "Receipt photos must be 4 MB or smaller.".

`parse_client_today(value)` uses the browser's date when it is within one day of the server's
`date.today()`, and the server date otherwise. Vercel's clock is UTC, so without it "yesterday" would
be wrong for users behind UTC in the evening.

## Gemini integration

`services/gemini.py` is the only module that talks to Gemini.

- SDK `google-genai`. The model is `GEMINI_MODEL` if set, otherwise `gemini-3.5-flash-lite`. The
  timeout is `HttpOptions(timeout=20_000)` (milliseconds). The SDK's default of no retries is kept,
  and automatic function calling is disabled because no tools are passed.
- `response_mime_type="application/json"` with `response_json_schema`: `amount` number|null,
  `category` enum of `CATEGORIES`, `date` string|null, `description` string|null, all required.
- The system instruction includes today's date, explains how to resolve relative and year-less
  dates, and says the receipt or note is data, not instructions.
- Errors are turned into `AutofillError` messages that are safe to show:
  - `APIError` with code 429 → "Gemini is busy right now. Try again in a minute."
  - any other `APIError`, `httpx.HTTPError` (timeouts, connection failures), or a reply that isn't a
    JSON object → "Gemini couldn't read that right now. Try again or fill in the form yourself."
  - no usable amount and no usable description → "Gemini couldn't find an expense in that. Try a
    clearer photo or fill in the form yourself."
- `normalize_expense(data, today)` cleans each field independently:
  - `amount`: a real int or float (not bool), finite, rounded to 2 places, `0 < x <= 1,000,000`,
    formatted as `"12.50"`. Otherwise `""`.
  - `category`: exactly one of `CATEGORIES`, otherwise `""` so the user has to pick one.
  - `date`: a valid `YYYY-MM-DD` string, normalised with `strptime`. Otherwise today's date.
  - `description`: whitespace collapsed and cut to 200 characters. Otherwise `""`.

## Database changes

New table, created in `init_db()`:

```sql
CREATE TABLE IF NOT EXISTS ai_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,            -- 'receipt' or 'note'
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
)
```

New helpers in an `# AI usage` section of `database/db.py`:

- `count_ai_requests_today(user_id)` counts rows with `created_at >= date('now')`, which is the
  current UTC day.
- `log_ai_request(user_id, source)`

## Templates

**Modify:** `templates/add_expense.html`. Between `.expense-header` and `.expense-card`, add
`{% if ai_enabled %}<div class="autofill-card">` containing:

- `h2.autofill-title` "Autofill with Gemini" and `p.autofill-subtitle`
- `.autofill-error` when `autofill_error` is set, otherwise `.autofill-notice` when `autofilled` is
  set ("Filled in from your receipt." or "Filled in from your description.", then "Check each field,
  then add the expense.")
- the receipt form: `method="POST" action="/expenses/autofill" enctype="multipart/form-data"
  data-autofill`, a hidden `today`, `input type="file" id="receipt" name="receipt"
  accept="image/*" required`, and a Scan button with `data-busy-text`
- `p.autofill-divider` "or"
- the note form: `data-autofill`, a hidden `today`, `input id="note" name="note" maxlength="300"
  value="{{ note or '' }}" required`, and a Fill button with `data-busy-text`

## Files to change

- `app.py`: `load_dotenv()`, `MAX_CONTENT_LENGTH`, `parse_autofill_form()`, `parse_client_today()`,
  `render_expense_form()`, a new `# Error handlers` section with the 413 handler, and the
  `autofill_expense()` route below `add_expense()`.
- `database/db.py`: the `ai_requests` table and the two helpers.
- `templates/add_expense.html`: the autofill panel.
- `static/css/style.css`: a `/* Autofill */` sub-section at the end of "Expense form", using CSS
  variables only.
- `static/js/main.js`: sets `today` and the busy button state on submit, shrinks receipts over 1 MB
  (or in unsupported formats) to a JPEG of at most 2000px before upload, and resets busy buttons on
  `pageshow`.
- `conftest.py`: an autouse fixture that blanks `GEMINI_API_KEY` and replaces `gemini._generate`
  with a stub that fails the test.
- `requirements.txt`, `CLAUDE.md`.

## Files to create

- `services/__init__.py`, `services/gemini.py`
- `tests/test_autofill.py`
- `.env.example` (committed) and a local `.env` (gitignored)
- `README.md`

## New dependencies

- `google-genai==2.23.0`: the official Google Gen AI SDK.
- `python-dotenv==1.2.3`: loads `GEMINI_API_KEY` from the gitignored `.env` when running locally.

## Rules for implementation

- No SQLAlchemy or ORMs. Use parameterised queries only, and keep all SQL in `database/db.py`.
- Passwords stay hashed with werkzeug (this feature touches no auth code).
- Use CSS variables and never hardcode hex values. All templates extend `base.html`.
- Model output only pre-fills the form. It is never passed to `create_expense()`.
- `user_id` comes only from `get_current_user()`.
- The API key stays on the server and is never rendered or sent to the browser.
- Tests never make network calls.
- With no key set, the app behaves exactly as it did after Step 7.
- Do not implement Steps 8–9. All existing tests keep passing unmodified.

## Definition of done

- [ ] `pytest` passes: the 98 existing tests unmodified, plus `tests/test_autofill.py`.
- [ ] With `GEMINI_API_KEY` blank, `/expenses/add` has no autofill panel and everything else works
      as before.
- [ ] With a real key, the note "Spent 23.50 on an Uber yesterday" fills in `23.50`, Transport,
      yesterday's date and an Uber description, and shows the notice. No expense is saved until
      Add expense is clicked.
- [ ] A real receipt photo fills in its total, date, merchant and a sensible category.
- [ ] A phone photo over 4 MB still scans, because the browser shrinks it first.
- [ ] Choosing a PDF shows "Choose a JPEG, PNG, WebP or HEIC photo.".
- [ ] A body over 4 MB (for example a curl upload) gets a 413 with "Receipt photos must be 4 MB or
      smaller.".
- [ ] After 30 autofills in one UTC day, the next one shows the daily-limit message.
- [ ] An invalid key shows "Gemini couldn't read that right now…" and the manual form still works.
- [ ] While a request runs, the button shows "Scanning…" or "Reading…" and is disabled.
- [ ] No `#` or hex colours appear in the expense section, and the page is usable at 390px wide.
