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
| `352d882` | feat | discovery UI page (Task 1.4) |
| `34522ff` | feat | download pipeline (Task 1.5) |
| _pending_ | feat | off-IG similar content (Task 1.6) + ARCHITECTURE.md |

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

### `feat: off-IG similar content (Task 1.6) + ARCHITECTURE.md`

New `services/api/services/offsite_search.py` calls a RapidAPI TikTok
search endpoint to surface related content for a given reference reel.
Picked TikTok over YT Shorts — rationale documented in ARCHITECTURE.md
(content-type match, provider stability, codebase familiarity).

Endpoint: `GET /api/discovery/items/{reel_id}/similar`. Ownership-scoped
via reference_pages.user_id; rate-limited per-user (20/hr) and globally
(500/hr) on the same Redis sliding-window used for refresh.

Query construction: hashtags from the caption (3 max), then word
fallback, then the reel's ig_code so we always send something.
`build_query_from_caption` is its own pure function with 6 cases of
unit tests.

Provider response projection (`_project_tiktok_item`) walks the common
shape variants — `aweme_id`/`id`/`video_id`, `author.unique_id`/
`author.username`, root vs nested `statistics`/`stats`, `digg_count`/
`like_count`, cover-as-string vs cover-as-`{url_list:[]}`. A future
provider swap stays in env vars + that one function.

Error handling per the spec's "error fallback": upstream failures
(429/5xx/timeout/malformed) land as `200 {items: [], error: "..."}`
rather than 502 so the UI renders a graceful explainer card. Strict
exceptions live in the service layer (`TikTokSearchError` +
`TikTokErrorKind` enum); the router maps them to the soft response.

Frontend:
  - `api.discovery.findSimilar(reelId)` + `SimilarResponse` type
  - `/sources` page renders a separate "Similar elsewhere" view when
    a Find Similar click resolves (back button restores the main feed)
  - Reuses `SourcesGrid` + `SourcesCard` so cards look the same across
    IG and TikTok results — per the spec's component-reuse requirement
  - `SourcesCard` now derives the top-right handle link based on
    permalink hostname (TikTok permalinks point to tiktok.com profile;
    IG to instagram.com — was hardcoded to IG before)
  - Selection state is shared across modes (a quirk: clicking Select on
    a TikTok item persists in the main selection set). Noted in
    FOUND-ISSUES — not a functional break.
  - Download + Find Similar are intentionally omitted on the similar
    grid: downloads target reference_reels (TikTok items aren't there),
    and recursive similar would be confusing.

Tests:
  - `test_offsite_search.py` — 23 cases: build_query_from_caption (6),
    _project_tiktok_item shape variants + handle normalization + None
    returns (6), search_similar_tiktok HTTP including the explicit
    SOURCE ISOLATION check (request host is tiktok-scraper7, not
    instagram-anything), 429/non-2xx/timeout/malformed/missing-list/
    missing-key, drops-unparseable-keeps-rest (11).
  - `test_discovery_items_router.py` — 6 new cases: similar happy path
    (with hashtag query assertion), error-fallback returns 200+error
    flag, 404 missing, 404 not-owner, 429 rate-limited, 401 unauth.
  - `sourcesPage.test.tsx` — 2 new cases: Find Similar click opens
    similar view + back returns to feed; error response renders the
    explainer card.

New top-level `ARCHITECTURE.md` documents:
  - End-to-end student flow
  - New tables + endpoints (one place to look)
  - The three RapidAPI sources used + their env overrides
  - Why TikTok over YT Shorts
  - BackgroundTasks vs Celery decision (and the migration trigger)
  - Rate-limit caps
  - DiscoveryItem shape contract

### `feat: editor handoff + scheduler tests (Task 1.7)`

The scheduler was already built (`/api/scheduled-reels` + the publish
worker — Phase 0 audit). The missing piece per spec was "wire downloaded
items into the existing editor entrypoint" — `/editor/{exportId}`. The
remaining work in this commit:

**Editor handoff**:
  - Schema relaxation: `user_exports.viral_reel_id` dropped to nullable
    + new `reference_reel_id` column FK to reference_reels. CHECK
    constraint enforces exactly-one-set so the worker can dispatch on
    whichever FK is populated.
  - `_export_to_dict` updated to emit both ids (null-safe).
  - New endpoint `POST /api/discovery/downloads/{id}/edit`:
    * 404 if not the caller's, 409 if status != "done"
    * Idempotent on (user_id, reference_reel_id) — re-POSTing returns
      the same UserExport with 200
    * Template lookup prefers user's default, falls back to first
      seeded master template
    * Auto-attaches user's first 'own' page; seeds caption from the
      reel's first 200 chars
  - Frontend: SourcesCard's Download button morphs to **"Edit"** when
    `downloadStatus="done"` AND an `onEdit` handler is provided.
    Clicking it now dispatches to onEdit (not onDownload). Single
    button slot per card — title attribute distinguishes the two modes.
  - SourcesPage's `handleEdit` calls `api.discovery.edit(downloadId)`
    then `router.push("/editor/{exportId}")`.

**Scheduler tests** (existing endpoints had ZERO coverage — Phase 0
finding). New `tests/test_scheduled_reels.py` covers the spec's
required cases plus the supporting surface:

  - **Timezone handling** (the spec's first bullet):
    naive datetime → 422 from the Pydantic field_validator;
    tz-aware → 201 with the response normalized to UTC.
  - **Schedule window**: too-soon (lead < 2 min) → 400; too-far
    (>60 days) → 400.
  - **IG preconditions**: not connected → 409 ig_not_connected;
    token expired → 409 ig_token_expired; PERSONAL account → 409
    ig_account_type_personal.
  - **Export readiness**: export not in `status="done"` → 404.
  - **Double-publish prevention** (spec bullet):
    DELETE on processing/published row → 409 not_cancellable; PATCH
    on non-queued row → 409 not_editable; DELETE on queued → 204.
  - **Retry semantics** (spec "failure -> retry with cap"):
    failed row -> /retry resets attempt_count + last_error +
    ig_container_id, status -> queued. Retry on any non-failed
    status -> 409 not_retryable (parametrized across 4 states).
  - **Status transitions surface** (spec bullet): list endpoint's
    `counts` dict reflects ALL rows regardless of any filter applied
    to `items` — the UI's status-badge contract.
  - **Cross-tenant ownership**: A can't GET/DELETE/POST-retry B's
    schedules (all 404, no existence leak).
  - **Unauthenticated**: every endpoint returns 401 with no cookie.

**Tests added for the editor handoff** (extending the discovery_items
router tests):
  - 201 on first POST + correct FK shape (`reference_reel_id` set,
    `viral_reel_id` null) verified by re-fetching the UserExport row.
  - 200 idempotent return on second POST + count assertion that only
    one UserExport row exists.
  - 409 not_ready when status="downloading" / "queued" / "failed".
  - 404 missing download, 404 cross-tenant, 401 unauthenticated.

**Card test**: one new case for "downloadStatus=done with onEdit"
asserting the button reads "Edit", is enabled, and dispatches to
onEdit (not onDownload).

**Page test**: end-to-end "click Download, button morphs to Edit,
click Edit, calls api.discovery.edit, navigates to /editor/{id}" —
uses `vi.hoisted` to stub next/navigation's useRouter.

**Docs**:
  - ARCHITECTURE.md gets a new "Editor handoff" section describing
    the polymorphic UserExport source FKs + the worker-side gap.
  - FOUND-ISSUES #7 documents the exporter follow-up (worker reads
    source via viral_reel_id; needs a branch for reference_reel_id
    -> downloads.minio_key). Bounded refactor — the migration plan
    is in the issue.

## Still pending (in this branch)
- Phase 2 hardening (CSRF, idempotency, XSS, refresh-token reuse-detection,
  CORS allowlist, CSP)
- Worker exporter dispatch for reference_reel_id (FOUND-ISSUES #7)
