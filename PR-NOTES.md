# PR — Student workflow + security hardening

Branch: `feat/student-workflow-and-hardening` off `main` @ `7c6b23c`.

## Commits so far

| Commit | Type | Subject |
|---|---|---|
| `1d5a8de` | chore | bootstrap test infrastructure (pytest + vitest) |
| `8d7cd43` | feat | reference pages model + UI (Task 1.1) |
| `5f66f96` | feat | discovery filter config (Task 1.2) |
| `6b4bd36` | feat | reference_reels cache + discovery service module (Task 1.3a) |
| `8d817ab` | feat | discovery endpoints + rate limiter + filter preview wiring (Task 1.3b) |
| _pending_ | feat | discovery UI page (Task 1.4) |

## What's in this PR (so far)

### `chore: bootstrap test infrastructure`

No prior test setup existed in the repo. Added the minimum needed to satisfy
the "tests at breakpoints" rule going forward:

**Backend** — `pytest` + `pytest-asyncio` with shared fixtures in
`services/api/tests/conftest.py`:
- transactional `db_session` (rolls back per test, uses SAVEPOINTs so router
  rollback in `IntegrityError` handlers doesn't nuke the outer test trans)
- `client` — FastAPI HTTPX async client with `get_db` overridden
- `authed_client` — `client` plus a real `access_token` cookie for a freshly
  inserted `User`
- `other_authed_user` — second persisted user for cross-tenant tests

A no-DB smoke test (`tests/test_auth_helpers.py`) exercises password +
JWT roundtrips so we can confirm the framework loads even without Postgres.

**Frontend** — `vitest` 2 + `@testing-library/react` + `jsdom`. Vitest config
mirrors the tsconfig `@/*` path alias so production imports resolve in
tests. `apps/web/__tests__/smoke.test.tsx` renders `Button` and checks
loading-state disable behavior.

**Makefile** — added `test`, `test-api`, `test-web`, `test-db-up`,
`test-db-down`. `test-db-up` spins up a throwaway `postgres:16-alpine` on
`localhost:5433` with the credentials the conftest expects.

### `feat: reference pages model + UI (Task 1.1)`

New `reference_pages` table separate from the legacy
`user_pages.page_type='reference'` so the existing niche-based recommendation
pipeline keeps working untouched. Per-user cap of 5 enforced two ways:

1. **DB trigger** `trg_reference_pages_max` (BEFORE INSERT) raises with
   `ERRCODE = 'check_violation'` and message "max 5 reference pages per
   user" — race-safe backstop against concurrent inserts both passing the
   service check.
2. **Service-layer** count guard in the router returns a friendly 409
   `{"code": "max_reference_pages", "detail": "..."}` before the trigger
   even fires (saves a round-trip and gives a user-readable message).

Duplicate prevention via `UNIQUE(user_id, ig_handle)`. `POST` is
idempotent: re-adding the same handle returns 200 with the existing row
(not 201). Pydantic validator normalizes handles to lowercase and
strips `@`, scheme, and trailing query/path so `@NATGEO`,
`https://www.instagram.com/natgeo/?hl=en`, and `natgeo` all map to one row.

**Backend tests** (`tests/test_reference_pages.py`, 16 cases):
- list empty / list reflects add
- add creates row + idempotent re-add returns same id
- normalization collapses 3 input forms to one row
- invalid handles rejected at the Pydantic layer (5 parametrized cases)
- cap-at-5 enforced via service layer (friendly 409)
- cap-at-5 enforced via DB trigger (direct INSERT bypasses service guard)
- delete removes own row / 404 on nonexistent
- cross-tenant: user A can't list, see, or delete user B's pages
- two users can independently track the same handle
- unauthenticated list/add/delete all return 401

**Frontend tests** (`apps/web/__tests__/referencePagesPanel.test.tsx`):
- empty state, add, idempotent re-add (no duplicate in DOM)
- cap state disables input + button with "Limit reached"
- server error surfaces inline via `role="alert"`
- remove preserves siblings

## How to run the tests

```bash
# Backend (needs Docker for the test postgres)
make test-db-up
cd services/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q

# Frontend
cd apps/web && npm install && npm test
```

**Test verification status**: tests written and syntax-checked, but I have
NOT yet run them locally end-to-end. The Mac in front of me has Python
3.14.4 (brew packaging bug — broken `libexpat` ABI prevents pip
bootstrap) and Docker isn't running. The pytest config is straightforward;
expect them to pass first try. If something flakes when you run, paste the
output and I'll fix.

### `feat: discovery filter config (Task 1.2)`

New `discovery_filters` table with `UNIQUE(user_id)` — one filter row per
user, lazily created on first PUT. Sensible defaults baked into the model
constants and the Pydantic schema so the UI can render "save the defaults
to lock in" copy.

Authoritative validation lives in DB CHECK constraints (`min_views >= 0`,
`min_engagement_rate BETWEEN 0 AND 1`, `max_age_days BETWEEN 1 AND 365`,
`sort_by IN (...)`). Pydantic mirrors them with `Field(ge=, le=)` so users
see a clean 422 instead of a 500 from a CHECK violation. `model_config =
ConfigDict(extra="forbid")` rejects unknown payload keys.

`/api/discovery-filter`:
- `GET` — returns the row if present, defaults + `is_default=true` otherwise
- `PUT` — Postgres `INSERT ... ON CONFLICT (user_id) DO UPDATE` upsert; bumps
  `updated_at` via `func.now()` since Postgres doesn't auto-update timestamps
- `POST /preview` — accepts a hypothetical filter, returns the count of
  reels that would match. Until Task 1.3's `reference_reels` cache lands,
  always returns `{count: 0, has_cache: false}` (one-line swap when 1.3
  ships); the `has_cache=false` flag drives the "no data yet" UI explainer
  so users don't see a misleading zero

Frontend `DiscoveryFilterPanel` (rendered in `/settings`):
- Loads current filter on mount, populates 6 fields
- Debounced `/preview` call (400 ms) on every field edit — counter renders
  "X reels match" when `has_cache=true`, explainer copy otherwise
- Save button stays disabled when draft matches saved (field-by-field
  comparison so a cleared + retyped value doesn't read as dirty)
- Server validation errors surface inline via `role="alert"`

Tests:
- Backend `tests/test_discovery_filters.py` — 14 cases: defaults when
  no row, PUT creates + GET reflects, PUT-twice is upsert (no duplicate
  row in DB), 10-case parametrized validation (negatives, out-of-range
  engagement, sort_by enum, extra key forbidden), empty-body PUT saves
  defaults, /preview returns 0 + has_cache=false, /preview validates
  payload, cross-user isolation (A's PUT invisible to B's GET), 401 on
  unauthenticated GET/PUT/preview
- Frontend `__tests__/discoveryFilterPanel.test.tsx` — 5 cases: load +
  populate fields, empty-cache explainer, live count when has_cache=true,
  Save disabled when not dirty + enabled after change + sends payload,
  /preview re-fires after a field edit

### `feat: reference_reels cache + discovery service module (Task 1.3a)`

Foundation commit — no new endpoints or worker tasks, site keeps running.

- New `reference_reels` table caches RapidAPI reel projections per
  reference page. `UNIQUE(reference_page_id, ig_media_id)` makes future
  refresh an idempotent upsert. Indexes cover the three hot reads:
  `(page, posted_at DESC)`, `(view_count DESC)`, `(fetched_at)`.
- `services/api/services/reference_discovery.py`: pure logic + RapidAPI
  client wrapper. `DiscoveryItem` shape matches Phase 1.3 spec exactly.
  `RapidAPIError` carries a `RapidAPIErrorKind` enum so callers branch on
  `.kind` instead of grepping strings. Kept separate from the legacy
  `services/instagram_api.py` (which swallows errors to keep the niche
  scraper running) so the new flow can surface failures.
- 27 test cases: 16 pure-logic (engagement math, score per sort key, filter
  thresholds including in-seconds max_age, rank determinism + tiebreaker,
  mapper for dict / ORM-like / missing optionals) + 11 HTTP via
  `httpx.MockTransport` (status mapping for 404/429/5xx/418, timeout,
  malformed body, missing user_id, paging stop conditions, missing key).

### `feat: discovery endpoints + rate limiter + filter preview wiring (Task 1.3b)`

Wires the foundation into the API surface:

- **`GET /api/discovery/items`** — paginated, applies the caller's saved
  filter (or defaults), ranks via `rank_items`, returns `has_cache: false`
  on an empty cache so the UI shows the "Run discovery to populate" copy
  instead of a misleading zero.
- **`POST /api/discovery/refresh`** — kicks a RapidAPI fetch off via
  `FastAPI BackgroundTasks` (same uvicorn worker, no Celery for now —
  see FOUND-ISSUES #7 for the Celery follow-up). Per-user cap of 5
  refreshes / hour and global cap of 200 / hour share a Redis sliding-
  window via `services/rate_limiter.py`. Returns 429 with
  `{code: "rate_limit", retry_after}` when the cap is hit.
- **`POST /api/discovery-filter/preview`** updated to count the matching
  rows in `reference_reels` for the caller. `has_cache` is now meaningful.
- **Background refresh split** into `do_refresh(pages, db)` (pure, uses
  caller's session, no commit) + `refresh_pages_background(pages)` (opens
  fresh session, commits). Tests drive the inner directly on the savepoint-
  mode test session so writes roll back at teardown.

Frontend API client (`apps/web/lib/api.ts`) gains `api.discovery.items()` +
`api.discovery.refresh()` plus the matching types. No UI yet — the
discovery grid is Task 1.4.

Tests:
- `tests/test_rate_limiter.py` — 6 cases with `fakeredis`: first call
  returns 1 + sets TTL, increments to cap, raises above cap, TTL not
  reset on subsequent increments (sustained load doesn't extend the
  window), keys are independent, retry_after reflects current TTL.
- `tests/test_discovery_items_router.py` — 12 cases: items empty
  cache, only-this-users-reels, applies-saved-filter, ranks-by-sort_by,
  pagination, refresh-no-pages, refresh-queues, refresh-per-user-429,
  do_refresh inserts / is upsert / continues on one-handle failure,
  filter preview counts cached items + empty cache stays has_cache=false.

`requirements-test.txt` now also pins `fakeredis==2.30.0`.

## Still pending (in this branch)
- 1.5 Download pipeline (existing code present — needs idempotency wiring)
- 1.6 Off-IG similar content
- 1.7 Editor handoff + scheduler (largely already built)
- Phase 2 hardening (CSRF, idempotency, XSS, refresh-token reuse-detection,
  CORS allowlist, CSP)
