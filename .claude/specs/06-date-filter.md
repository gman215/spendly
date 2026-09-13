# Spec: Date Filter

## Overview

Let a signed-in user narrow `/profile` to a date range. Step 5 wired the profile page to real
queries, but every number on it is all-time: "Total spent", the transaction count, the top
category, the recent-transactions table and the category breakdown always cover every expense the
user has ever logged. This step adds a small "From / To" form above the summary stats that submits
`GET /profile?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`; the route validates the two dates and
passes them to the three existing Step 5 query helpers, which gain optional, inclusive date bounds.
Either bound may be left blank for an open-ended range, and with no bounds the page shows the same
all-time data as Step 5. The range applies to everything below the form: the three stats, the
transactions table and "Spending by category". The transactions table also stops being capped at
the 10 most recent rows. It lists **every** expense in the chosen range, or every expense the user
has with no filter, so the table always agrees with the "Transactions" count and the category
breakdown. This exists now, before expenses can be added, edited and deleted in Steps 7–9,
because it only touches read queries that already exist. Once users start writing their own
expenses, "what did I spend this month / between these dates" is the first question the profile
page needs to answer. The user info card is not affected by the filter.

## Depends on

- **Step 1 — Database Setup** (complete): the `expenses.date` column is `TEXT` in zero-padded
  `YYYY-MM-DD` form, which is what makes plain `>=` / `<=` string comparison a correct date
  comparison.
- **Step 3 — Login and Logout** (complete): `session["user_id"]` scopes every query; the filter only
  ever narrows a user's own rows.
- **Step 4 — Profile Page Design** (complete): `templates/profile.html`, its CSS section, and the
  `/profile` auth guard.
- **Step 5 — Backend Routes for Profile Page** (complete): `get_expense_stats()`,
  `get_category_totals()`, `get_expenses_by_user()` and the `stats` / `transactions` / `categories`
  context that `profile()` builds from them. This step extends those helpers rather than adding new
  queries.

## Routes

No new routes. `GET /profile` keeps its path, method and auth guard (signed-out visitors still get a
`302` to exactly `/login`, with the query string dropped). It now also reads two optional query
parameters. Access level is unchanged: logged-in only.

- `GET /profile` — no parameters, or both blank → all-time data, as in Step 5 but with every expense
  listed — logged-in
- `GET /profile?start_date=YYYY-MM-DD` → expenses on or after that date — logged-in
- `GET /profile?end_date=YYYY-MM-DD` → expenses on or before that date — logged-in
- `GET /profile?start_date=…&end_date=…` → expenses between the two dates, **both inclusive** —
  logged-in

The form uses `method="get"`, so a filtered view is a shareable, refreshable URL and nothing is
written to the session or the database.

### Validation (applied in this order)

Validation runs in a helper in `app.py`, `parse_date_range(args)`, which returns
`(start_date, end_date, error)`:

1. Read `start_date` and `end_date` from `request.args` and `.strip()` each. An empty value means "no
   bound" and is not an error.
2. Parse each non-empty value with `datetime.strptime(value, "%Y-%m-%d").date()`. If either fails
   (bad format, or an impossible date like `2026-02-30`) → `"Enter a valid date in YYYY-MM-DD
   format."`
3. If both are present and `start > end` → `"Start date must be on or before the end date."`
4. On success, return each bound **re-formatted with `.isoformat()`**, not the raw string.
   `strptime` accepts unpadded input like `2026-09-1`, and passing that raw string to SQLite would
   break the text comparison against the stored `2026-09-01`.

On an error, `profile()` still returns **HTTP 200**. It renders the error message, shows
**unfiltered** (all-time) data, and re-fills the inputs with the stripped values the user submitted
(Jinja autoescaping covers anything odd). An invalid date is never passed to a query helper.

## Database changes

No new tables, columns, indexes or constraints. The Step 1 `expenses` table already has the `date`
column this needs.

The three Step 5 helpers in the `# Expenses` section of `database/db.py` gain two optional keyword
arguments, `start_date=None` and `end_date=None`, both ISO `YYYY-MM-DD` strings. Existing calls keep
working unchanged:

- `get_expense_stats(user_id, start_date=None, end_date=None)`
- `get_category_totals(user_id, start_date=None, end_date=None)`
- `get_expenses_by_user(user_id, limit=None, start_date=None, end_date=None)`: `limit` stays the
  second parameter.

One private helper is added at the top of the `# Expenses` section so the three queries don't repeat
the same branching:

- `_date_range_clause(start_date, end_date)` returns `(sql, params)`. `sql` is built only from the
  fixed fragments `" AND date >= ?"` and `" AND date <= ?"`, one for each bound that is not `None`,
  and `params` is the matching list of values. Both bounds `None` → `("", [])`.

Each helper puts the clause right after `WHERE user_id = ?` and before any `GROUP BY` /
`ORDER BY` / `LIMIT`, with `params` spliced in right after `user_id`. For example:

```sql
SELECT category, SUM(amount) AS total FROM expenses
WHERE user_id = ? AND date >= ? AND date <= ?
GROUP BY category ORDER BY total DESC
```

Ordering, `COALESCE`, and the `id DESC` tiebreaker are unchanged from Step 5.

`profile()` stops passing `limit=10` to `get_expenses_by_user()`, so the table gets every matching
row. The helper keeps its optional `limit` parameter (default `None` = no limit) so its signature
doesn't churn; nothing in this step passes it.

## Templates

**Create:** none.

**Modify:** `templates/profile.html` only.

- **Filter form**: a new `<form class="filter-bar" method="get" action="/profile">` placed between
  `.profile-header` and `.profile-stats`, containing:
  - two `.filter-field` wrappers, each holding a `<label class="filter-label">` ("From" / "To") and
    an `<input type="date" class="form-input">` with `id`/`name` of `start_date` / `end_date` and
    `value="{{ start_date or '' }}"` / `value="{{ end_date or '' }}"`
  - a `.filter-actions` wrapper with `<button type="submit" class="btn-primary">Apply</button>` and,
    only when `start_date or end_date` is non-empty, `<a href="/profile" class="btn-ghost">Clear</a>`
- **Error**: `{% if error %}<div class="filter-error">{{ error }}</div>{% endif %}` directly after the
  form, before `.profile-stats`.
- **Stat notes**: "Total spent" note becomes
  `{{ "in selected range" if filter_active else "all time" }}`, and the "Transactions" note becomes
  `{{ "in selected range" if filter_active else "logged so far" }}`. The "Top category" note
  ("highest spend") and all `profile-stat-value` spans are unchanged.
- **Empty state**: when `filter_active and not transactions`, render
  `<p class="filter-empty">No expenses in this date range.</p>` after `.txn-table-wrap` in the
  transactions panel, and again after `.cat-list` in the category panel. It must be outside the
  `<table>` and never a `<tr>` (the existing `transaction_rows()` test helper counts `<tr>` in
  `<tbody>`).
- **Panel title**: `Recent transactions` becomes `Transactions`, since the table is no longer a
  recent-only view.
- Nothing else in the template changes: same user info card, same table markup, same `cat-row`
  markup.

`profile()` passes these context names in addition to `stats` / `transactions` / `categories`:
`start_date`, `end_date` (the values to re-fill the inputs with), `filter_active` (`True` only when
there is no error and at least one bound is set), and `error` (`None` or the message).

## Files to change

- `app.py`
  - New `# Request helpers` section banner between `# Template filters` and `# Routes`, holding
    `parse_date_range(args)` as described under **Validation**. It uses the existing
    `from datetime import datetime` import.
  - `profile()` calls `parse_date_range(request.args)`. On error it queries with no bounds; on
    success it passes `start_date=` / `end_date=` to all three helpers
    (`get_expenses_by_user(user_id, start_date=…, end_date=…)`, with **no** `limit`). The stats / transactions /
    categories formatting from Step 5 is otherwise unchanged. It renders with the four extra context
    names above.
- `database/db.py`: add `_date_range_clause()` and the optional bounds on the three `# Expenses`
  helpers.
- `templates/profile.html`: filter form, error, stat notes, empty state, panel title (see
  **Templates**).
- `static/css/style.css`: in the existing "Profile page" section, add a `/* Date filter */`
  sub-section after `/* User info card */` with `.filter-bar`, `.filter-field`, `.filter-label`,
  `.filter-actions`, `.filter-error` and `.filter-empty`. Add a stacking rule for `.filter-bar` inside
  the existing `@media (max-width: 600px)` block. Reuse `.form-input`, `.btn-primary` and `.btn-ghost`
  as-is.
- `tests/test_profile.py`: append a `# Date filter` section. Exactly one existing test changes:
  `test_recent_transactions_are_capped_but_the_count_is_not` encodes the 10-row cap this step
  removes. Replace it with `test_all_transactions_are_listed`, which adds the same 12 expenses and
  asserts 20 table rows and a `20` count. Every other existing test must keep passing
  **unmodified**.
- `CLAUDE.md`: add the date filter and the full transaction list to the `/profile` row of the
  "Implemented" table (Step 6), replacing "recent transactions". Replace
  the "Step 6 isn't named anywhere in the code" paragraph now that Step 6 is defined. Mention the new
  optional `start_date` / `end_date` bounds in the `database/db.py` paragraph.

## Files to create

None.

## New dependencies

No new dependencies. `datetime` is stdlib, and `<input type="date">` needs no JS or library.

## Rules for implementation

- No SQLAlchemy or ORMs. Use stdlib `sqlite3` only, through `database/db.py`.
- Parameterised queries only. Date values always go through `?` placeholders. The only SQL text that
  varies is the choice between the two fixed fragments in `_date_range_clause()`, never user input,
  f-strings, `%` or concatenation of values.
- Passwords hashed with werkzeug (unchanged, since this step touches no auth code).
- Use CSS variables and never hardcode hex values. `.filter-error` uses `--danger-light` /
  `--danger`, not a copy of `.auth-error`'s hardcoded border colour.
- All templates extend `base.html` (no new template is created).
- All SQL stays in `database/db.py`; `profile()` and `parse_date_range()` never open a connection.
- Every query stays scoped by `user_id`. A date bound can only narrow a user's own rows.
- Validate before querying, and always pass normalised `.isoformat()` strings to the helpers.
- **Apart from the removed row cap and the renamed panel title, unfiltered `/profile` must render
  exactly as in Step 5.** In particular, with no filter the
  profile section must contain no date strings: no default `value`, no `min` / `max` attributes, no
  preset links. `test_transaction_dates_track_the_current_month` counts `YYYY-MM-` occurrences and
  `test_member_since_is_a_month_and_year_not_an_iso_date` forbids today's date above the table.
- No `#` anywhere in the profile section markup (no `href="#"`, no fragments), because
  `test_profile_uses_no_hardcoded_hex_colours` checks for it. The Clear link is `href="/profile"`.
- No new class name may contain the substring `cat-row` (existing tests count it).
- Keep the form's hardcoded `action="/profile"`. Don't switch to `url_for`, matching the other forms.
- Keep bounds inclusive on both ends.
- No row cap. The table lists every expense that matches the range (all of them with no filter),
  newest first. No pagination, no "show more" button, and no fixed-height scroll box around the
  table. The "Transactions" stat still comes from `get_expense_stats()`.
- No JavaScript (no `main.js` changes, no auto-submit), no preset ranges ("This month", "Last 30
  days"), no category or amount filtering, and no storing the filter in the session.
  Those are out of scope.
- Do not touch `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy`, `base.html`, other
  templates, or the Step 7–9 placeholder routes.

## Definition of done

Verified by running `python app.py` and using the app at `http://localhost:5001` signed in as
`demo@spendly.com` / `demo123`. The figures below assume only the 8 seeded demo expenses (as in the
pytest `client` fixture). `YYYY-MM` is the month those expenses were seeded in, which on a fresh
database is the current month.

- [ ] `pytest` passes. `test_login.py`, `test_register.py` and every `tests/test_profile.py` test
      except the replaced cap test are unmodified.
- [ ] `/profile` with no query string shows `$462.66`, `8` transactions, Bills as top category,
      8 table rows under a "Transactions" heading, 7 category rows, and notes "all time" /
      "logged so far". Both date inputs are empty and there is no Clear link.
- [ ] Picking From `YYYY-MM-01` and To `YYYY-MM-07` and clicking Apply goes to
      `/profile?start_date=YYYY-MM-01&end_date=YYYY-MM-07` and shows `$282.57`, `4` transactions,
      Bills as top category, 4 table rows, and 4 category rows (Bills 42.6%, Transport 26.5%, Food
      19.2%, Health 11.6%). Both stat notes read "in selected range", the inputs keep the chosen
      dates, and a Clear link is shown.
- [ ] Bounds are inclusive: `?start_date=YYYY-MM-10&end_date=YYYY-MM-10` shows `$28.00`, `1`
      transaction ("Movie tickets"), Entertainment as top category.
- [ ] Start only: `?start_date=YYYY-MM-14` shows `$152.09`, `3` transactions, Shopping as top category.
- [ ] End only: `?end_date=YYYY-MM-05` shows `$249.82`, `3` transactions, Bills as top category.
- [ ] A range with no expenses (`?start_date=YYYY-MM-02&end_date=YYYY-MM-02`) returns 200 with
      `$0.00`, `0` transactions, `—` as top category, no table rows, no category rows, and
      "No expenses in this date range." shown.
- [ ] `?start_date=YYYY-MM-07&end_date=YYYY-MM-01` returns 200 with "Start date must be on or before
      the end date." It shows the unfiltered `$462.66` / `8` data with "all time" notes, and the
      inputs keep the submitted values.
- [ ] `?start_date=not-a-date`, `?start_date=2026-02-30` and `?start_date=' OR 1=1 --` each return
      200 (no server error) with "Enter a valid date in YYYY-MM-DD format." and unfiltered data.
- [ ] Unpadded input is normalised: `?start_date=YYYY-MM-1&end_date=YYYY-MM-7` shows the same
      `$282.57` / `4` result as the padded range, and the inputs show `YYYY-MM-01` / `YYYY-MM-07`.
- [ ] Blank parameters (`?start_date=&end_date=`) behave exactly like no query string, with no error
      message.
- [ ] Clicking Clear returns to `/profile` with all-time data and empty inputs.
- [ ] Signed out, `/profile?start_date=YYYY-MM-01` redirects (302) to `/login`.
- [ ] A different user (register "Nitish Kumar" / `nitish@example.com`) filtering the same range sees
      `$0.00` and none of the demo user's expenses.
- [ ] All expenses are listed, not just the most recent. With 12 extra demo expenses added (20
      total), `/profile` shows all 20 table rows and a `20` count. If 12 of those 20 fall inside a
      chosen range, that range shows exactly those 12 rows and a `12` count.
- [ ] The category breakdown follows the range too: category rows, amounts and percentages only
      include expenses inside the chosen dates (see the `YYYY-MM-01`–`YYYY-MM-07` figures above).
- [ ] For the dev database, `sqlite3 expense_tracker.db "SELECT printf('%.2f', SUM(amount)), COUNT(*)
      FROM expenses WHERE user_id = 1 AND date BETWEEN 'YYYY-MM-01' AND 'YYYY-MM-07';"` matches the
      "Total spent" and "Transactions" values shown for that range.
- [ ] No hex colour values and no `#` appear in the profile section, with or without a filter.
- [ ] At ≤ 600px width the filter form stacks vertically and stays usable.
- [ ] `/`, `/register`, `/login`, `/logout`, `/terms`, `/privacy` and the Step 7–9 placeholder routes
      behave exactly as before.
