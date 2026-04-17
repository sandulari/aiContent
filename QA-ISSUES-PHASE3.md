# QA Issues — Phase 3: Destruction Testing

## First-Time User Flow

| # | Test | Result | HTTP | Note |
|---|------|--------|------|------|
| 1 | Register new user | PASS | 201 | Token returned immediately |
| 2 | Add Instagram page | PASS | 201 | Profile auto-analyzed within seconds |
| 3 | Recommendations appear | PASS | 200 | 100 recs in ~15 seconds |
| 4 | Weekly dashboard | PASS | 200 | has_data:false for new page (correct) |
| 5 | Page profile | PASS | 200 | Niche detected, topics populated |

## Security Tests

| # | Test | Result | HTTP | Note |
|---|------|--------|------|------|
| 6 | No auth on /api/exports | PASS | 403 | Correctly rejected |
| 7 | Cross-user data isolation | PASS | 404 | No info leak |
| 8 | Video stream no auth | FIXED | 403 | Was open, now requires auth |
| 9 | Thumbnail no auth | ACCEPTED | 200 | IG CDN proxy, not user content |
| 10 | SQL injection | PASS | 400 | Parameterized queries + username format validation |
| 11 | XSS in export | FIXED | 200 | Tags now stripped server-side |
| 12 | Path traversal | PASS | 404 | Correctly rejected |

## Edge Cases

| # | Test | Result | HTTP | Note |
|---|------|--------|------|------|
| 13 | Re-render export | PASS | 202 | Atomic re-render with UUID key, old file cleaned up |
| 14 | Delete page with recs | PASS | 204 | CASCADE delete works |
| 15 | Duplicate username | PASS | 409 | "Page already connected" |
| 16 | Download with no sources | PASS | 404 | Correct error |
| 17 | Render with no video | FIXED | 409 | Now validates prerequisite before dispatching |
| 18 | Rate limit (AI chat) | FIXED | 429 | 10 req/min per user enforced |

## API Contract

| # | Test | Result | HTTP | Note |
|---|------|--------|------|------|
| 19 | JSON error responses | PASS | - | All errors return proper JSON |
| 20 | 404 for fake UUIDs | PASS | 404 | Correct across all endpoints |
| 21 | HTTP status codes | PASS | - | 201 create, 204 delete, 202 async |

## Data Integrity

| # | Test | Result | Note |
|---|------|--------|------|
| 22 | Orphaned recommendations | PASS | 0 orphaned, FK CASCADE working |
| 23 | Orphaned video files | PASS | 0 orphaned |
| 24 | NULL required columns | PASS | 0 violations |
