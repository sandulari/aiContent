# Architecture — Per-reference-page discovery + downloads

This doc covers the **new** flow introduced on
`feat/student-workflow-and-hardening`. The legacy niche-based recommendation
pipeline (`/discover`, `theme_pages`, `viral_reels`, `user_reel_recommendations`)
is unchanged and lives alongside.

## End-to-end student flow

```
Settings                                        Sources page
─────────                                       ─────────
1. Student connects IG via OAuth                4. /sources renders the cached
   /settings/instagram                             reels, ranked + filtered.
2. Student adds up to 5 reference pages         5. "Refresh" -> BackgroundTask
   (capped via DB trigger).                        repopulates the cache.
3. Student edits the discovery_filter           6. "Open on IG" -> permalink.
   (sort + thresholds). /preview shows         7. "Download" -> MinIO; polled
      live match count.                           until done.
                                                8. "Find similar" -> TikTok
                                                   results in the same grid.
```

## Tables (new)

| Table | Purpose | Key constraints |
|---|---|---|
| `reference_pages` | Inspiration IG accounts per user | `UNIQUE(user_id, ig_handle)`, BEFORE-INSERT trigger caps at 5 rows / user |
| `discovery_filter` | Per-user feed knobs | `UNIQUE(user_id)`, CHECK constraints on every numeric range + the sort_by enum |
| `reference_reels` | Durable RapidAPI response cache | `UNIQUE(reference_page_id, ig_media_id)`, indexes on `(page, posted_at DESC)` / `(view_count DESC)` / `(fetched_at)` |
| `downloads` | Per-user record of a reel pulled into MinIO | `UNIQUE(user_id, reference_reel_id)` — the idempotency key for `POST /items/{id}/download` |

## Endpoints (new)

```
GET    /api/reference-pages           list caller's reference pages
POST   /api/reference-pages           idempotent add
DELETE /api/reference-pages/{id}      remove (owner-scoped)

GET    /api/discovery-filter          row or defaults
PUT    /api/discovery-filter          INSERT ... ON CONFLICT UPDATE upsert
POST   /api/discovery-filter/preview  count matching cached reels

GET    /api/discovery/items                paginated feed
POST   /api/discovery/refresh              kick BackgroundTask
POST   /api/discovery/items/{id}/download  idempotent download trigger
GET    /api/discovery/downloads/{id}       poll status
GET    /api/discovery/items/{id}/similar   off-IG (TikTok) similar content
```

## RapidAPI sources

Three different RapidAPI products are used. All share the same
`RAPIDAPI_KEY` env (RapidAPI accounts are one-key-fits-all) but each can
be overridden via dedicated env vars:

| Purpose | Default host | Env override |
|---|---|---|
| IG profile + reels (used by both the reference cache and the legacy scraper) | `instagram-api-fast-reliable-data-scraper.p.rapidapi.com` | `RAPIDAPI_PROFILE_HOST` |
| Video download (resolves IG/TikTok/YT permalinks to a streamable URL) | `social-download-all-in-one.p.rapidapi.com` | `RAPIDAPI_VIDEO_DL_HOST` + `_PATH` + `_KEY` |
| Off-IG similar (TikTok search by keywords) | `tiktok-scraper7.p.rapidapi.com` | `RAPIDAPI_TIKTOK_HOST` + `_SEARCH_PATH` + `_KEY` |

### Why TikTok and not YouTube Shorts (Task 1.6)

Spec gave us the choice. Picked TikTok because:

1. **Content-type match.** Students use this app to ride trending IG reels;
   TikTok is the same vertical-video format with overlapping creators.
   YT Shorts is a downstream re-upload destination for many of them, so
   "find similar on TikTok" surfaces *originating* content; "find similar
   on YT Shorts" surfaces re-uploads.
2. **Provider stability.** Multiple RapidAPI TikTok search endpoints
   ship the same shape (`aweme_id`/`id`/`video_id` + `author.unique_id`
   + standard stats). YT Data API providers vary more on response keys
   and tend to deprecate routes faster.
3. **Codebase familiarity.** `services/worker/lib/search_tiktok.py`
   already exists for the legacy Playwright scraper. Even though we
   don't reuse it, the project's mental model is TikTok-flavored.

The response projector lives at `services/api/services/offsite_search.py:_project_tiktok_item`.
Walking common shape variants (root vs nested `statistics`/`stats`,
`digg_count` vs `like_count`, etc.) keeps a future provider swap to one
function + env vars rather than a code change at every call site.

## Background work

`POST /discovery/refresh` and `POST /discovery/items/{id}/download` both
use FastAPI's `BackgroundTasks` for their slow path. The HTTP response
returns 202 immediately; the work runs in the same uvicorn worker after
the response is sent. This is deliberate:

- Adding Celery would require duplicating the service module across
  `services/api` and `services/worker` (separate Python packages, no
  shared lib in the project today). FOUND-ISSUES #6 has the migration
  plan when refresh time grows past ~5s or we want a periodic beat.

The pattern:

```python
# Router
background.add_task(refresh_pages_background, pages)
return {"queued": True, ...}

# Inner (testable) function — uses caller's session, doesn't commit
async def do_refresh(pages, db): ...

# Outer wrapper — production-only, opens fresh session, commits
async def refresh_pages_background(pages):
    async with async_session() as db:
        result = await do_refresh(pages, db)
        await db.commit()
```

Tests drive the inner function on the savepoint-mode test session so
writes roll back at teardown.

## Rate limits

Single Redis-backed sliding-window helper at
`services/api/services/rate_limiter.py`. Pipeline-atomic INCR + EXPIRE
nx=True so concurrent INCRs can't both miss the EXPIRE and leave a
counter without a TTL.

| Action | Per-user cap | Global cap |
|---|---|---|
| Discovery refresh | 5 / hour | 200 / hour |
| Find similar | 20 / hour | 500 / hour |

429 responses include `retry_after` (seconds) so the UI can render a
"try again in Xs" message.

## Editor handoff (Task 1.7)

The student's path from a downloaded reel to the editor reuses the
existing `/editor/{export_id}` route. `user_exports` is polymorphic by
source: legacy niche-discovery exports carry `viral_reel_id`, new
discovery-download exports carry `reference_reel_id`. A DB-level CHECK
enforces exactly one is set:

```sql
CHECK ((viral_reel_id IS NOT NULL)::int + (reference_reel_id IS NOT NULL)::int = 1)
```

`POST /api/discovery/downloads/{id}/edit` is the handoff:
- 404 if the download isn't the caller's
- 409 if the download isn't `status="done"` yet
- Idempotent on (user_id, reference_reel_id) — re-POSTing returns the
  existing `UserExport` with 200 instead of creating a duplicate

Template selection: prefer the user's default; fall back to the first
seeded master template; 500 if neither exists.

Worker exporter (`services/worker/tasks/exporter.py`) still loads the
source video via `viral_reel_id -> viral_reels -> video_files`. For a
discovery-download export the source lives in the `downloads.minio_key`
slot — the exporter needs a one-shot branch on which FK is populated.
FOUND-ISSUES #7 has the patch.

## DiscoveryItem shape

One dataclass + TS interface, used everywhere. Carries `id` (the
`reference_reel` UUID, `None` for un-cached projections like TikTok
search results) so the frontend's per-card actions can address the
item by id when applicable.

```
id, source_handle, permalink, media_url, thumbnail, caption,
views, likes, comments, posted_at, duration_seconds, score
```

Same shape regardless of source (IG cached reel, freshly-projected
RapidAPI item, TikTok search result) — `SourcesGrid` + `SourcesCard`
work for all three on the frontend.
