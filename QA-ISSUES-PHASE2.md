# QA Issues — Phase 2: Code & Structural Review

## Instagram Connection & Auth

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 1 | Token storage security | FIXED | JWT passed as ?token= query param for downloads (leaks in logs/history). Tradeoff accepted for browser download support. | `apps/web/lib/api.ts:235` |
| 2 | Token expiry handling | PASS | Shell.tsx calls api.auth.me() on mount, clears token + redirects on 401 | `apps/web/components/layout/shell.tsx:34-44` |
| 3 | RapidAPI rate limit handling | FIXED | No 429 retry existed. Added _request_with_retry() with exponential backoff (3 attempts) | `services/api/services/instagram_api.py` |
| 4 | RapidAPI downtime handling | PASS | Returns None/empty on failure, task retries (max_retries=2) | `services/worker/tasks/analyze_page.py:67-79` |
| 5 | Multiple page handling | PASS | Checks duplicate (user_id, ig_username), returns 409 | `services/api/routers/my_pages.py:135-141` |
| 6 | Disconnect flow cleanup | PARTIAL | DB cascades work. MinIO files not cleaned (orphan accumulation). Acceptable for now. | `services/api/routers/my_pages.py:240` |
| 7 | Session persistence | PASS | Shell reads from localStorage on every route | `apps/web/components/layout/shell.tsx:25` |

## Content Discovery Engine

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 8 | N+1 queries | FIXED | Per-page PageProfile query replaced with single batch query using profile_map dict | `services/api/routers/my_pages.py:96-121` |
| 9 | Pagination | PASS | offset/limit supported, max 300, empty list for 0 results | `services/api/routers/recommendations.py:48-49` |
| 10 | Content deduplication | PASS | UNIQUE constraint exists on (user_page_id, viral_reel_id) in init.sql | `infra/postgres/init.sql:150` |
| 11 | Deleted content handling | ACCEPTED | No stale content detection. Thumbnails proxy with placeholder fallback. | N/A |
| 12 | Thumbnail loading | PASS | Proxied through API, 1x1 transparent PNG placeholder on CDN failure | `services/api/routers/files.py:188-228` |

## Content Download Pipeline

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 13 | Download failure handling | PASS | max_retries=3, countdown=180s, job status set to failed | `services/worker/tasks/downloader.py:22,186` |
| 14 | yt-dlp error handling | PASS | CalledProcessError caught, simpler format fallback, TimeoutExpired caught | `services/worker/lib/ytdlp.py:62-80` |
| 15 | Large file handling | FIXED | Added --max-filesize 500M to yt-dlp command | `services/worker/lib/ytdlp.py:55` |
| 16 | Concurrent downloads | PASS | Isolated file paths per video_id, Celery handles parallel safely | `services/worker/tasks/downloader.py:23` |
| 17 | File format validation | FIXED | Added ffprobe validation after download to confirm valid video stream | `services/worker/lib/ytdlp.py:120-128` |

## Content Editor

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 18 | Autosave | FIXED | Added 3-second debounced autosave via useEffect on dirty state | `apps/web/app/editor/[exportId]/page.tsx:333` |
| 19 | State persistence | PASS | All state saved server-side, restored on page load | `apps/web/app/editor/[exportId]/page.tsx:112-170` |
| 20 | Export file quality | PASS | CRF 18, libx264, 1080x1920, AAC 192k, faststart | `services/worker/lib/video_proc.py:252-254` |
| 21 | Editor performance guards | FIXED | Warning shown for videos >200MB with size estimate | `apps/web/app/editor/[exportId]/page.tsx:160` |

## Dashboard & Analytics

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 22 | Instant data after connection | PASS | Immediate analyze_page_task trigger, "Still gathering stats" empty state | `services/api/routers/my_pages.py:172-197` |
| 23 | Zero-data state | PASS | has_data:false with helpful empty state | `apps/web/app/dashboard/page.tsx:141-147` |
| 24 | Data accuracy | PASS | Correct delta computation with None safety | `services/api/routers/my_pages.py:325-328` |
| 25 | Number formatting | PASS | formatViews() for large numbers, toLocaleString() for raw | `apps/web/lib/utils.ts:7-16` |
| 26 | Timezone handling | PASS | Relative time display works regardless of timezone | `apps/web/lib/utils.ts:31-48` |

## Error Handling

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 27 | API error messages | PASS | All HTTPException details are human-readable | All routers |
| 28 | Silent failures | FIXED | 23 empty catch blocks replaced with error state + banner across 7 pages | 7 page files |
| 29 | Frontend error display | FIXED | All API calls now have catch blocks with setError | 7 page files |

## Security

| # | Check | Status | Detail | File |
|---|-------|--------|--------|------|
| 30 | Auth on every endpoint | FIXED | Added get_current_user to 5 file endpoints. Thumbnail stays open (IG proxy only). | `services/api/routers/files.py` |
| 31 | Cross-user data isolation | PASS | All queries filter by current_user.id | All routers |
| 32 | Hardcoded secrets | FIXED | JWT default changed to dev-only warning | `services/api/middleware/auth.py:17` |
| 33 | Input sanitization | FIXED | _strip_html() on headline/subtitle/caption. Username regex validation. | `services/api/routers/exports.py`, `my_pages.py` |
| 34 | File upload validation | PASS | Extension allowlist, size limits (5MB logo, 25MB audio) | `services/api/routers/templates.py`, `files.py` |
| 35 | CORS config | FIXED | Removed wildcard, defaults to localhost only | `services/api/main.py:25-27` |
