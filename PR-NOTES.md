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
| `d445d36` | feat | off-IG similar content (Task 1.6) + ARCHITECTURE.md |
| `67dcfb8` | feat | editor handoff + scheduler tests (Task 1.7) |
| `004f062` | feat | CSRF double-submit cookie (Task 2.1) |
| `3b81e15` | feat | Idempotency-Key middleware (Task 2.2) |
| `ffd0f3a` | feat | XSS sanitization — bleach + DOMPurify (Task 2.3) |
| `ddb33ae` | feat | rotating refresh tokens + reuse detection (Task 2.4) |
| `f0d5cac` | feat | strict CORS allowlist (Task 2.5) |
| _pending_ | feat | CSP + security headers (Task 2.6) |

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

### `feat: CSRF double-submit cookie (Task 2.1)`

Double-submit cookie pattern for cross-site request forgery protection on
authenticated mutating routes.

**Middleware** (`services/api/middleware/csrf.py`):
- New `CSRFMiddleware` registered AFTER `CORSMiddleware` in `main.py`
  (Starlette runs middleware in REVERSE add order, so this runs *before*
  CORS in the request path and *after* it in the response path — the
  cookie ends up on the response after CORS headers have been merged).
- On `POST/PUT/PATCH/DELETE` for an authenticated request: compares
  the `X-CSRF-Token` header against the `csrf_token` cookie via
  `hmac.compare_digest` (timing-safe). Missing/mismatch -> 403 with
  `{"code": "csrf_failure"}`.
- On every response: if the request didn't carry a `csrf_token`
  cookie, sets a fresh one — 256 bits of `secrets.token_urlsafe`,
  `SameSite=Lax`, `Secure` in prod, **not** HttpOnly (JS must read
  it to echo back in the header).
- **Exemptions**:
  - Safe methods (`GET`, `HEAD`, `OPTIONS`)
  - `/api/auth/login`, `/register`, `/refresh`, `/forgot-password`,
    `/reset-password` (no session yet — nothing to forge against)
  - `/api/ig/oauth/*` prefix (Meta-initiated redirect from another
    origin couldn't carry our CSRF cookie; the start endpoint has
    its own signed HMAC nonce)
  - Requests with no `access_token` cookie — skip CSRF so the auth
    dependency returns the real 401 instead of a misleading 403

**Frontend** (`apps/web/lib/api.ts`):
- `req<T>` now reads the `csrf_token` cookie via `document.cookie`
  and injects `X-CSRF-Token` on every mutating request automatically.
- SSR-safe (returns `null` when `document` is undefined).
- First-page-load path: if no cookie yet, the request goes through
  unauthenticated paths or carries no header; the GET that fetches
  the page receives one in `Set-Cookie`, so the *next* mutating
  request has a token to echo.

**Tests** (`services/api/tests/test_csrf.py`, 7 cases):
- spec bullets: missing token rejected (403), wrong token rejected
  (403), valid token accepted (201)
- exemptions: GET is safe (200), unauthenticated POST gets the auth
  layer's 401 not a CSRF 403, `/api/auth/login` exempt (auth
  response not csrf 403)
- cookie issuance: `csrf_token` set on response when request had
  none; cookie has no `HttpOnly` flag (JS must read it)

**Conftest update**: `authed_client` pre-seeds a known `csrf_token`
cookie + matching `X-CSRF-Token` default header so the ~130 existing
mutating tests don't all 403. Tests that exercise the rejection path
use the raw `client` fixture and set the access-token cookie
themselves so they can control the CSRF state explicitly.

### `feat: Idempotency-Key middleware (Task 2.2)`

Standard `Idempotency-Key` header support on mutating routes — clients
that retry an in-flight POST/PUT/PATCH/DELETE with the same key + same
body get the cached response instead of double-applying the side
effect. Same key + different body returns 409.

**Middleware** (`services/api/middleware/idempotency.py`):
- Reads `Idempotency-Key` on POST/PUT/PATCH/DELETE; safe methods and
  unkeyed requests pass through untouched.
- Validates the key against `^[A-Za-z0-9_\-]{8,128}$` — bogus values
  return 400 `invalid_idempotency_key` (so we don't pollute Redis
  with junk and so clients see their bug immediately).
- Drains the request body, hashes it, and re-injects it via
  `request._receive` so the downstream app still sees the body.
- Cache key is `idem:{sha256(access_token)[:16]}:{method}:{path}?{query}:{key}`
  so users are isolated AND a key reused across different routes
  doesn't collide. Anonymous requests share the `anon` slot.
- On hit: same body hash → cached response with `Idempotent-Replay: true`;
  different body hash → 409 `idempotency_key_conflict`.
- On miss: runs the handler, caches the response for 24h ONLY if the
  status is 2xx AND no `Set-Cookie` header is present. The Set-Cookie
  guard means `/api/auth/login` is not silently cached without its
  `access_token` cookie (which would leave the replayed client logged
  out without realizing it).

**Middleware order** (`main.py`): CORS → Idempotency → CSRF. Starlette
runs middleware in REVERSE add order in the request path, so CSRF
gates incoming requests first — a cached replay can NEVER bypass
CSRF validation. Idempotency captures the response before CSRF sets
its `csrf_token` cookie on the way out, which is correct: the CSRF
middleware always re-issues a fresh cookie on every response anyway.

**Frontend** (`apps/web/lib/api.ts`): every mutating call generates
its own `Idempotency-Key` via `crypto.randomUUID()`. The key lives
in the request-local `headers` object, so the 401-refresh retry
path replays with the *same* key — that's the entire reason the
header exists. SSR-safe with a hex-string fallback.

**Tests** (`services/api/tests/test_idempotency.py`, 8 cases):
- spec bullets: same key + same body → cached replay (DB has 1 row);
  same key + different body → 409
- no key → no caching (each call hits handler, no `Idempotent-Replay`)
- different keys → independent
- per-user scoping: user A's key doesn't shadow user B's request
- safe methods + bad key format + non-2xx not cached

Tests use `fakeredis` injected via `idempotency._test_client` so the
suite never needs a real Redis (same pattern as the rate limiter).

### `feat: XSS sanitization — bleach + DOMPurify (Task 2.3)`

Defense-in-depth against script injection in user-supplied strings.
React's auto-escaping covers JSX text interpolation, but the app also
interpolates `display_name` into HTML email templates (welcome,
password reset) where there is no automatic escape — that's the real
injection sink we close here.

**Backend** (`services/api/services/sanitizer.py`):
- `clean_text(s)` — `bleach.clean(..., tags=[], strip=True)` strips
  every HTML tag and keeps the text content. Used in Pydantic field
  validators so user input is sanitized on the way IN and the stored
  row is plain text.
- `escape_for_html(s)` — wraps `html.escape(s, quote=True)` for
  defense-in-depth inside email templates. Pre-existing rows or
  admin-set fields could carry raw HTML; escaping at the
  interpolation point catches them.
- `schemas/user.py:UserCreate.display_name` runs through `clean_text`
  in a `@field_validator`. A display name that's entirely HTML tags
  (e.g. `<img><br>`) becomes empty after strip and is rejected as a
  validation error rather than stored.
- `services/email_templates.py` interpolates every untrusted value
  through `escape_for_html` (aliased as `e`). The reset_url is built
  server-side from known parts but goes through `e()` too — no
  string ever lands in HTML without escape.
- `requirements.txt` gains `bleach==6.2.0`.

**Frontend** (`apps/web/lib/sanitize.ts`):
- `sanitizeHtml(s)` — wraps `isomorphic-dompurify` with an explicit
  allow-list (`b/i/em/strong/a/p/br/ul/ol/li` + `href/title/rel/target`)
  for any future `dangerouslySetInnerHTML` callsite. Strips
  `<script>`, all `on*` handlers, `javascript:` URIs, and data: attrs.
- `stripHtml(s)` — text-only fallback for non-React sinks
  (clipboard, alert, log messages).
- `package.json` adds `isomorphic-dompurify` so the helper works in
  both SSR and CSR.
- Today there are zero `dangerouslySetInnerHTML` usages, so this is
  a library addition with no behaviour change at any current
  callsite. The XSS hardening that happens today is on the backend.

**Tests** (~14 cases):
- `services/api/tests/test_sanitizer.py` — `clean_text` strips tags
  (parametrised across 6 inputs); `UserCreate` strips `<script>`
  from `display_name`; all-HTML display name -> ValidationError;
  welcome + reset email templates HTML-escape both `display_name`
  and `reset_url` (incl. `&` inside the URL).
- `apps/web/__tests__/sanitize.test.ts` — `sanitizeHtml` strips
  script tags / event handlers / `javascript:` URIs; preserves
  allow-listed inline tags; returns "" for nullish. `stripHtml`
  returns plain text only.

### `feat: rotating refresh tokens + reuse detection (Task 2.4)`

Replaces the single-hash `users.refresh_token` column with a dedicated
`refresh_tokens` table keyed by `(family_id, token_hash)`. Each
`/api/auth/login` (or register) starts a new family; every
`/api/auth/refresh` marks the presented row revoked and inserts a
successor in the SAME family. A replay of an already-revoked token
is detected as reuse — the entire family is deleted and the client
is forced to re-login. Closes FOUND-ISSUES #3 (15-min access TTL)
and #4 (reuse detection).

**Access token TTL**: default lowered from 60 → **15 minutes** per
the spec.

**New table** (`refresh_tokens`):
```
id, user_id (FK -> users ON DELETE CASCADE),
family_id (uuid, not FK — group label),
token_hash (sha256, UNIQUE), issued_at, expires_at, revoked_at
```

Indexes on `user_id` and `family_id`. Migration appended to
`db/migrations.py`. The legacy `users.refresh_token{,_expires}` columns
are now dead code — left in the model with a DEPRECATED comment for
a future drop-column migration; no code path reads or writes them.

**Service module** (`services/api/services/refresh_tokens.py`):
- `issue_new_family(db, user_id)` — login / register entry point
- `rotate_refresh_token(db, raw)` — returns a `RotationOutcome` with
  a `result` enum the router branches on: `ROTATED` / `REUSE` /
  `EXPIRED` / `UNKNOWN`
- `revoke_token(db, raw)` — logout

On REUSE: `DELETE FROM refresh_tokens WHERE family_id = ?` purges
both the active successor AND the revoked predecessors. The legitimate
user AND the attacker both have to log in fresh — the chain can't
continue. On EXPIRED: row is marked revoked (not deleted) so a
later replay still trips REUSE rather than silently being UNKNOWN.

**Router** (`routers/auth.py`):
- `_issue_login_session` replaces the old `_issue_tokens`; starts a
  fresh family.
- `/refresh` branches on the outcome, emits typed error codes
  (`refresh_token_reuse` | `refresh_token_expired` | `invalid_refresh_token`)
  inside the HTTPException detail so the frontend can render a
  specific message ("your session may have been compromised — log in
  again").
- `/logout` revokes the current token but leaves the family in place
  so a later replay still trips REUSE.

**Tests** (`services/api/tests/test_refresh_tokens.py`, 13 cases):
- access-token TTL default = 15
- service layer state machine: rotate happy path, reuse → family
  purge, unknown → UNKNOWN, expired → row marked revoked, logout
  revoke
- HTTP end-to-end: login inserts row; /refresh rotates (old revoked,
  new active, same family); replay of revoked cookie returns 401
  `refresh_token_reuse` AND family is gone; unknown cookie returns
  `invalid_refresh_token`; no cookie → 401; logout revokes current
  row without touching the family

Per-IP auth rate limiter is cleared in an autouse fixture so the test
suite can't accidentally trip the 5-register / 8-login caps.

### `feat: strict CORS allowlist (Task 2.5)`

Replace the previous `allow_methods=["*"] / allow_headers=["*"]` setup
with a strict allowlist driven by `ALLOWED_ORIGINS` env. The actual
exploit it closed is FOUND-ISSUES #5: with `allow_credentials=True`,
browsers ignore a wildcard origin and FastAPI's `CORSMiddleware`
falls back to echoing the request origin — functionally an open
allowlist that any site can read responses from. We now reject `*` +
credentials at startup so the misconfiguration can't ship.

**New module** (`services/api/middleware/cors_config.py`):
- `parse_allowed_origins(raw, *, allow_credentials)` — splits the env
  string, strips whitespace, drops empties. Raises `InsecureCORSConfig`
  if `*` appears with credentials enabled.
- `cors_kwargs(env=…)` — assembles the kwargs for
  `app.add_middleware(CORSMiddleware, **kw)`. Reads `ALLOWED_ORIGINS`
  first, falls back to legacy `CORS_ORIGINS` (in-place deploys keep
  working), then the localhost dev defaults.
- Methods enumerated: `GET, POST, PUT, PATCH, DELETE, OPTIONS`.
  Request headers enumerated: `Content-Type, Authorization,
  X-CSRF-Token` (Task 2.1), `Idempotency-Key` (Task 2.2).
- `expose_headers`: `Idempotent-Replay` (so JS can tell a cached
  replay from a fresh execution) + `Retry-After` (so the 429 retry
  UI works).
- `max_age=600` to cache preflight OPTIONS for 10 min.

**Infra**:
- `docker-compose.yml` — dev default switched from `CORS_ORIGINS=*`
  (which would now fail at startup) to the localhost list, and the
  env var is renamed to `ALLOWED_ORIGINS`.
- `infra/.env.production.template` — `CORS_ORIGINS` → `ALLOWED_ORIGINS`
  with a note about the no-`*`-with-credentials rule.

**Tests** (`services/api/tests/test_cors_config.py`, 13 cases):
- Unit: parse comma-list / strip whitespace / fall back to defaults
  / `*` + credentials → `InsecureCORSConfig` / `*` without
  credentials → allowed.
- `cors_kwargs`: prefers `ALLOWED_ORIGINS`, falls back to
  `CORS_ORIGINS`, methods + headers enumerated (no `*`), exposes
  `Idempotent-Replay` + `Retry-After`.
- HTTP end-to-end: GET with allowed `Origin` echoes
  `Access-Control-Allow-Origin`; disallowed origin has no ACAO
  header; preflight OPTIONS for a POST with `X-CSRF-Token` +
  `Idempotency-Key` is permitted.

Closes FOUND-ISSUES #5.

### `feat: CSP + security headers (Task 2.6)`

Final Phase 2 task — OWASP-recommended response headers on every
response from BOTH the API and the Next.js frontend.

**API** (`services/api/middleware/security_headers.py`):
- New `SecurityHeadersMiddleware` added LAST so it's the OUTERMOST
  wrapper. Every response — including the CSRF 403, the auth 401,
  validation 422s, and the idempotency 409 — gets headers stamped
  on the way out.
- `Content-Security-Policy: default-src 'none'; frame-ancestors
  'none'; base-uri 'none'` — the strictest CSP possible for an
  API. The API serves JSON; nothing it returns should ever execute
  scripts or be embedded.
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  — only emitted when the request was actually HTTPS (proxy header
  `X-Forwarded-Proto: https` honoured). Browsers ignore HSTS on
  plain HTTP anyway, but emitting it from a misconfigured proxy
  could pin clients to the wrong scheme — better to be explicit.
- `X-Content-Type-Options: nosniff` — kills MIME sniffing.
- `X-Frame-Options: DENY` — older sibling of CSP frame-ancestors.
- `Referrer-Policy: strict-origin-when-cross-origin` — browser
  default since 2020, set explicitly so it can't drift.
- `Permissions-Policy: camera=(), microphone=(), geolocation=(),
  payment=(), usb=(), magnetometer=(), gyroscope=()` — disable
  every browser capability the app doesn't use.

**Frontend** (`apps/web/next.config.js`):
- Adds `Content-Security-Policy` + `Strict-Transport-Security` to
  the existing security-header set.
- CSP is necessarily looser than the API's — Next inlines its
  runtime bootstrap so `script-src` includes `'unsafe-inline'` and
  `'unsafe-eval'` (the latter for dev HMR). Every other directive
  is minimum-needed: `default-src 'self'`, `img-src 'self' data:
  blob: https:` (IG thumbnails / CDN avatars), `connect-src 'self'
  ${NEXT_PUBLIC_API_URL}`, `frame-ancestors 'none'`,
  `base-uri 'self'`, `form-action 'self'`, `object-src 'none'`.
- FOUND-ISSUES #9 documents the script-src tightening plan
  (per-request nonce via Next middleware) — bounded refactor
  deferred until we audit any inline 3rd-party scripts.

**Tests** (`services/api/tests/test_security_headers.py`, 5 cases):
- Health endpoint has every expected header (CSP, nosniff, frame
  options, referrer, permissions with camera/mic/geo disabled).
- Plain HTTP request has NO HSTS (avoiding pin-to-wrong-scheme).
- HTTPS request (`X-Forwarded-Proto: https`) gets HSTS with
  `max-age` + `includeSubDomains`.
- CSRF 403 carries security headers (proves the middleware wraps
  early-return responses).
- Unauthenticated 401 carries security headers (auth dep also
  short-circuits).

## Phase 2 complete

All six security tasks shipped on this branch:

- 2.1 CSRF double-submit cookie — `004f062`
- 2.2 Idempotency-Key middleware — `3b81e15`
- 2.3 XSS sanitization (bleach + DOMPurify) — `ffd0f3a`
- 2.4 Rotating refresh tokens + reuse detection — `ddb33ae`
- 2.5 Strict CORS allowlist — `f0d5cac`
- 2.6 CSP + security headers — _this commit_

Plus Phase 1 (per-reference-page discovery + downloads + editor
handoff). FOUND-ISSUES has the parked items (#1 worker-enhancer
queue.publish, #2 dual reference-pages UI, #6 BackgroundTasks ->
Celery, #7 worker exporter reference_reel_id, #8 frontend 401-retry
discrimination, #9 frontend CSP nonces).
- Worker exporter dispatch for reference_reel_id (FOUND-ISSUES #7)
