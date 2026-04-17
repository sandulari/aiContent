# QA Fixes Log — Shadow Pages Brutal Audit

## CRITICAL Fixes

### C1. Unauthenticated file endpoints
- **Issue:** GET /api/files/{id}/download, /video/{id}/stream, /video/{id}/info, /logo/{id}, /export-logo/{id} served content without any authentication
- **Root cause:** Auth dependency was missing from these route handlers
- **Fix:** Added `current_user: User = Depends(get_current_user)` to all 5 endpoints
- **Files:** `services/api/routers/files.py`

### C2. Hardcoded JWT secret
- **Issue:** `JWT_SECRET` had a guessable default value committed to source
- **Root cause:** `os.getenv("JWT_SECRET", "change-me-in-production-vre-secret-key-2024")`
- **Fix:** Changed to warn on startup if not set, uses explicit dev-only fallback
- **Files:** `services/api/middleware/auth.py`

### C3. CORS wildcard with credentials
- **Issue:** Default CORS origins included `*` alongside `allow_credentials=True`
- **Root cause:** Permissive default in main.py
- **Fix:** Removed wildcard, defaults to localhost:3000,localhost:8080
- **Files:** `services/api/main.py`

### C4. No rate limiting on AI endpoints
- **Issue:** Unlimited requests to /api/ai/chat could drain Claude API budget
- **Root cause:** No rate limiting existed anywhere in the API
- **Fix:** Added per-user in-memory rate limiter (10 req/60s) to all 3 AI endpoints
- **Files:** `services/api/routers/ai.py`

### C5. Export download auth (prior session)
- **Issue:** GET /api/exports/{id}/download had no auth guard
- **Fix:** Added JWT verification via query param or Authorization header
- **Files:** `services/api/routers/exports.py`

## HIGH Fixes

### H1. 30+ silent catch blocks in frontend
- **Issue:** Empty `catch {}` blocks swallowed errors across 7 pages, giving users zero feedback
- **Fix:** Added error state + error banner + console.error to all 23 catch blocks
- **Files:** `apps/web/app/dashboard/page.tsx`, `discover/page.tsx`, `editor/[exportId]/page.tsx`, `settings/page.tsx`, `templates/page.tsx`, `exports/page.tsx`, `library/page.tsx`

### H2. Render accepts jobs with no video file
- **Issue:** POST /api/exports/{id}/render accepted jobs even when no video existed
- **Fix:** Added prerequisite check for VideoFile before dispatching Celery task
- **Files:** `services/api/routers/exports.py`

### H3. No download size limit
- **Issue:** yt-dlp had no max-filesize, could download multi-GB files
- **Fix:** Added `--max-filesize 500M` flag
- **Files:** `services/worker/lib/ytdlp.py`

### H4. No RapidAPI 429 retry
- **Issue:** Instagram API calls had no retry on rate limit (429)
- **Fix:** Added `_request_with_retry()` with exponential backoff (3 attempts) to all 3 RapidAPI methods
- **Files:** `services/api/services/instagram_api.py`

### H5. Audio fade dropped at render (prior session)
- **Fix:** Added afade=t=in/out FFmpeg filters
- **Files:** `services/worker/lib/video_proc.py`

### H6. Long-word wrapping overflow (prior session)
- **Fix:** Added character-level word breaking in _wrap_text_to_width
- **Files:** `services/worker/lib/video_proc.py`

### H7. Bridge-down double messaging (prior session)
- **Fix:** Detect bridge-down strings, rollback optimistic message, show error banner
- **Files:** `apps/web/components/editor/AITextPanel.tsx`

### H8. Canvas video drag no clamps
- **Issue:** Video could be dragged entirely off-canvas or scaled infinitely
- **Fix:** Added clampW/clampH/clampX/clampY functions matching exporter bounds
- **Files:** `apps/web/components/editor/Canvas.tsx`

### H9. Nginx stripping /api/ prefix
- **Issue:** proxy_pass trailing slash stripped the /api/ prefix FastAPI needs
- **Fix:** Removed trailing slash from proxy_pass
- **Files:** `infra/nginx/nginx.conf`

## MEDIUM Fixes

### M1. Font picker / worker font mismatch
- **Issue:** 13 fonts in picker but only Inter installed in worker; others fell back to DejaVu
- **Fix:** Trimmed picker to 5 fonts (Inter, Roboto, Open Sans, Lato, DejaVu Sans), installed matching apt packages in worker
- **Files:** `apps/web/components/editor/PropertiesPanel.tsx`, `services/worker/lib/video_proc.py`, `services/worker/Dockerfile`

### M2. Exporter missing export_minio_key in SELECT
- **Issue:** Atomic re-render referenced export_minio_key but didn't select it
- **Fix:** Added to SELECT clause
- **Files:** `services/worker/tasks/exporter.py`

### M3. Split-brain color scheme
- **Issue:** Sidebar used green accent, rest of app used blue; onboarding had wrong logo
- **Fix:** Unified nav active state to blue, fixed onboarding logo to "SP" brand, aligned Card colors
- **Files:** `apps/web/components/layout/sidebar.tsx`, `apps/web/app/onboarding/page.tsx`, `apps/web/components/ui/card.tsx`

### M4. 12 unused Google Fonts loaded
- **Issue:** Layout loaded 12 font families (200KB+) but only Inter was used
- **Fix:** Trimmed to 4 fonts matching worker (Inter, Roboto, Open Sans, Lato)
- **Files:** `apps/web/app/layout.tsx`

### M5. "Scrape" in user-facing copy
- **Issue:** Technical jargon "scrape" visible to customers
- **Fix:** Changed to "find" / "analyze"
- **Files:** `apps/web/app/discover/page.tsx`, `apps/web/app/settings/page.tsx`

### M6. Product title still "Viral Reel Engine"
- **Fix:** Changed to "Shadow Pages" with appropriate description
- **Files:** `apps/web/app/layout.tsx`

### M7. N+1 query in list_my_pages
- **Issue:** Separate PageProfile query per page in loop
- **Root cause:** Classic N+1 pattern — one query loads pages, then N more fetch profiles
- **Fix:** Single batch query with subquery for max(analyzed_at), results stored in profile_map dict
- **Files:** `services/api/routers/my_pages.py`

### M8. IG username accepts arbitrary characters
- **Issue:** `nike' OR '1'='1` accepted as valid username
- **Root cause:** Only stripped @, no format validation
- **Fix:** Added `re.match(r'^[a-zA-Z0-9_.]{1,30}$')` check, returns 400 on mismatch
- **Files:** `services/api/routers/my_pages.py`

### M9. XSS payloads stored unsanitized
- **Issue:** `<script>alert(1)</script>` stored verbatim in headline_text, subtitle_text
- **Root cause:** No server-side sanitization on text fields
- **Fix:** Added `_strip_html()` regex helper, applied in both POST create and PUT update
- **Files:** `services/api/routers/exports.py`

### M10. No DELETE route for exports
- **Issue:** Users could not delete unwanted exports
- **Root cause:** Route simply didn't exist
- **Fix:** Added DELETE /{export_id} with ownership check, best-effort MinIO cleanup of rendered file
- **Files:** `services/api/routers/exports.py`

### M11. No autosave in editor
- **Issue:** Save was manual only — unsaved work lost on browser close
- **Root cause:** No auto-trigger for handleSave
- **Fix:** Added useEffect with 3-second debounce on dirty state + all editor state variables
- **Files:** `apps/web/app/editor/[exportId]/page.tsx`

### M12. No ffprobe validation after download
- **Issue:** Downloaded file could be corrupted or non-video, uploaded to MinIO regardless
- **Root cause:** Only checked file existence, not validity
- **Fix:** Added ffprobe check for video stream after download, raises RuntimeError if not valid
- **Files:** `services/worker/lib/ytdlp.py`

### M13. console.error leaks raw error objects
- **Issue:** 26 catch blocks logged full error objects to browser console (tokens, URLs, stack traces)
- **Root cause:** Recent error-handling fix used `console.error("msg", e)` instead of sanitized form
- **Fix:** Changed all 26 to `console.error("msg:", e?.message || "unknown error")`
- **Files:** 7 page files in `apps/web/app/`

### M14. No delete button in UI
- **Issue:** Backend DELETE export route existed but frontend had no way to call it
- **Root cause:** `api.exports.delete()` method missing, no delete button in UI
- **Fix:** Added delete() to api.ts, added Delete button with confirm dialog to exports + library pages
- **Files:** `apps/web/lib/api.ts`, `apps/web/app/exports/page.tsx`, `apps/web/app/library/page.tsx`

## LOW Fixes

### L1. No video size guard in editor
- **Issue:** Large videos could cause browser memory pressure with no warning
- **Fix:** Added warning banner when video > 200MB with size estimate
- **Files:** `apps/web/app/editor/[exportId]/page.tsx`

### L2. Debug comment in API docstring
- **Issue:** "drop it to zero for debugging" visible in API docstring
- **Fix:** Removed debug reference
- **Files:** `services/api/routers/recommendations.py`
