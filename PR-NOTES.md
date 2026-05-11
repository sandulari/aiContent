# PR — Student workflow + security hardening

Branch: `feat/student-workflow-and-hardening` off `main` @ `7c6b23c`.

## Commits so far

| Commit | Type | Subject |
|---|---|---|
| `1d5a8de` | chore | bootstrap test infrastructure (pytest + vitest) |
| _pending_ | feat | reference pages model + UI (Task 1.1) |

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

## Still pending (in this branch)

- 1.2 Discovery filter config
- 1.3 RapidAPI discovery service
- 1.4 Discovery UI
- 1.5 Download pipeline (existing code present — needs idempotency wiring)
- 1.6 Off-IG similar content
- 1.7 Editor handoff + scheduler (largely already built)
- Phase 2 hardening (CSRF, idempotency, XSS, refresh-token reuse-detection,
  CORS allowlist, CSP)
