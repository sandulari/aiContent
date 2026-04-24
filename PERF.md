# Perf triage — April 2026 (static analysis)

## Existing tuning confirmed correct
- `pool_size=20, max_overflow=10, pool_pre_ping=True` (services/api/db/session.py:17-23)
- `worker_prefetch_multiplier=1` (services/worker/celery_app.py:19)
- Existing indexes (init.sql + migrations.py):
  - `users.email` UNIQUE
  - `user_pages(user_id)`, `user_pages(user_id, page_type)`
  - `user_pages UNIQUE(user_id, ig_username)`
  - `page_snapshots(user_page_id, taken_at DESC)`, `page_snapshots(user_page_id, week_key)`
  - `page_profiles(user_page_id)`
  - `user_page_reels(user_page_id, posted_at DESC)`, `UNIQUE(user_page_id, ig_code)`
  - `theme_pages.username` UNIQUE, `theme_pages(niche_id)`, `theme_pages(evaluation_status)`
  - `viral_reels(theme_page_id)`, `viral_reels(niche_id)`, `viral_reels(view_count DESC)`, `viral_reels.ig_video_id` UNIQUE
  - `user_reel_recommendations(user_page_id)`, `user_reel_recommendations(match_score DESC)`, `UNIQUE(user_page_id, viral_reel_id)`
  - `video_sources(viral_reel_id)`, `video_files(viral_reel_id)`
  - `user_templates(user_id)`, `user_exports(user_id)`
  - `jobs(job_type)`, `jobs(status)`
  - `reel_profiles(viral_reel_id)` UNIQUE, `reel_profiles(topic)`
  - `ai_text_generations(viral_reel_id)`, `ai_text_generations(user_page_id)`

---

## Top findings (ranked by impact)

### 1. [middleware/auth.py:141-172] — `get_current_user` opens a second DB session on every authenticated request
**Code**:
```python
async def get_current_user(request: Request, db=None):
    ...
    if db is None:                       # <-- always None in practice
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == UUID(user_id)))
            user = result.scalar_one_or_none()
```
**Why slow**: FastAPI does not inject `db` into `get_current_user` because the parameter has a default of `None` rather than `Depends(get_db)`. Every endpoint that also declares `db: AsyncSession = Depends(get_db)` therefore acquires **two** pool connections per request (one for auth, one for the handler), doubling pool pressure and checkout latency. The second session also fires `BEGIN`/`COMMIT` + `SELECT * FROM users WHERE id = ...` separately from the request's main transaction. With 20+ concurrent dashboard loads this is the fastest way to exhaust the pool.
**Fix**:
- Change the signature to `async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):` and drop the `if db is None` branch. Reuse the request-scoped session for the user lookup. No index change needed.
**Priority**: P0

---

### 2. [routers/reels.py:70-85] — Similar-reels full-text search has no GIN index; seq-scans `viral_reels` on every detail page
**Query**:
```sql
SELECT vr.id, ..., ts_rank(to_tsvector('english', COALESCE(vr.caption, '')),
                            to_tsquery('english', :search)) as relevance
FROM viral_reels vr
LEFT JOIN theme_pages tp ON tp.id = vr.theme_page_id
WHERE vr.id != :reel_id
  AND vr.view_count > 5000
  AND to_tsvector('english', COALESCE(vr.caption, '')) @@ to_tsquery('english', :search)
ORDER BY relevance DESC, vr.view_count DESC
LIMIT 8
```
**Why slow**: `to_tsvector(...)` is computed per-row, there is no functional GIN index on `viral_reels.caption`, so Postgres does a full sequential scan + per-row tsvector computation every time anyone opens a reel. This scales linearly with the `viral_reels` table (tens of thousands of rows even on a small deployment — seeded theme-page scraping produces a lot).
**Fix**: add a functional GIN index:
```sql
CREATE INDEX IF NOT EXISTS idx_viral_reels_caption_fts
ON viral_reels USING GIN (to_tsvector('english', COALESCE(caption, '')));
```
Postgres will then use it directly because the `@@` predicate matches the expression.
**Priority**: P0

---

### 3. [routers/recommendations.py:65-87] — Recommendation feed has no composite index covering its WHERE + ORDER BY
**Query**: `GET /api/my-pages/{page_id}/recommendations`
```python
select(UserReelRecommendation, ViralReel, ThemePage.username)
 .join(ViralReel, ViralReel.id == UserReelRecommendation.viral_reel_id)
 .outerjoin(ThemePage, ThemePage.id == ViralReel.theme_page_id)
 .where(
     UserReelRecommendation.user_page_id == page_id,
     UserReelRecommendation.is_dismissed.is_(False),
     ViralReel.view_count >= min_views,
 )
 .order_by(UserReelRecommendation.match_score.desc(), ViralReel.view_count.desc())
 .offset(offset).limit(limit)
```
**Why slow**: The two existing indexes are `(user_page_id)` alone and `(match_score DESC)` alone — neither covers `(user_page_id, is_dismissed, match_score DESC)`. Postgres has to pick one, filter the rest row-by-row, then re-sort. With `add_page` inserting **500 recommendations per page** (my_pages.py:437, 460), each student accumulates thousands of recs quickly; the planner falls back to a bitmap scan + sort on every feed load, and this endpoint is hit constantly.
**Fix**: composite index that lines up with the hot filter + sort:
```sql
CREATE INDEX IF NOT EXISTS idx_recs_page_active_score
ON user_reel_recommendations(user_page_id, is_dismissed, match_score DESC);
```
No query change required — the planner picks it up automatically.
**Priority**: P0

---

### 4. [routers/recommendations.py:131-153] — Dashboard summary fires two COUNT(*) queries every load
**Code**:
```python
total = (await db.execute(
    select(func.count()).select_from(UserReelRecommendation)
    .where(UserReelRecommendation.user_page_id == page_id,
           UserReelRecommendation.is_dismissed.is_(False)))).scalar() or 0

viral = (await db.execute(
    select(func.count()).select_from(UserReelRecommendation)
    .join(ViralReel, ViralReel.id == UserReelRecommendation.viral_reel_id)
    .where(UserReelRecommendation.user_page_id == page_id,
           UserReelRecommendation.is_dismissed.is_(False),
           ViralReel.view_count >= VIRAL_VIEW_FLOOR))).scalar() or 0
```
**Why slow**: Two separate round-trips; the second joins `viral_reels` just to filter by `view_count`. Called every time the dashboard mounts or the "still building your feed" banner re-checks. The feed has hundreds-to-thousands of rows per page; counting them all twice per mount compounds with finding #1 (extra session).
**Fix**: collapse into one query using `FILTER`:
```python
stmt = (
    select(
        func.count().label("total"),
        func.count().filter(ViralReel.view_count >= VIRAL_VIEW_FLOOR).label("viral"),
    )
    .select_from(UserReelRecommendation)
    .join(ViralReel, ViralReel.id == UserReelRecommendation.viral_reel_id)
    .where(UserReelRecommendation.user_page_id == page_id,
           UserReelRecommendation.is_dismissed.is_(False))
)
row = (await db.execute(stmt)).one()
```
Also benefits from the index proposed in finding #3.
**Priority**: P1

---

### 5. [routers/my_pages.py:840-878] — Dashboard pulls two full `UserPageReel` sets and aggregates in Python
**Code**: two back-to-back `select(UserPageReel).where(... posted_at BETWEEN ...)` executions (current period + comparison period), then `sum(r.view_count for r in ...)` etc. in Python.
**Why slow**: Python-side aggregation loads every row over the wire even though the response only needs scalar totals + a top reel. For the 7-day default window this is fine, but users pick 30/90-day ranges from the UI — that's hundreds of rows transferred per dashboard load. Also, **the two queries differ only by date range** and can be merged into one with conditional aggregation.
**Fix**: push the sums to the DB. One round-trip per dashboard:
```python
reel_stats = await db.execute(
    select(
        func.sum(case((UserPageReel.posted_at.between(start_dt, end_dt), UserPageReel.view_count), else_=0)).label("views"),
        func.sum(case((UserPageReel.posted_at.between(start_dt, end_dt), UserPageReel.like_count), else_=0)).label("likes"),
        func.sum(case((UserPageReel.posted_at.between(start_dt, end_dt), UserPageReel.comment_count), else_=0)).label("comments"),
        func.count().filter(UserPageReel.posted_at.between(start_dt, end_dt)).label("posts"),
        func.sum(case((UserPageReel.posted_at.between(comp_start_dt, comp_end_dt), UserPageReel.view_count), else_=0)).label("comp_views"),
        # ... etc
    ).where(
        UserPageReel.user_page_id == page_id,
        UserPageReel.posted_at >= comp_start_dt,
        UserPageReel.posted_at <= end_dt,
    )
)
```
Keep a separate small `SELECT ... ORDER BY view_count DESC LIMIT N` for the top reel + chart rows. The existing index `idx_user_page_reels_page_posted(user_page_id, posted_at DESC)` already supports this.
**Priority**: P1

---

### 6. [routers/my_pages.py:1046-1071] — `refresh-stats` does N+1 upsert with SELECT-then-INSERT/UPDATE per reel
**Code**:
```python
for reel in reels:
    existing = await db.execute(
        select(UserPageReel).where(
            UserPageReel.user_page_id == page_id,
            UserPageReel.ig_code == code))
    existing_reel = existing.scalar_one_or_none()
    if existing_reel: ... else: db.add(UserPageReel(...))
```
**Why slow**: Up to 60 reels per refresh (`max_pages=5`) → 60 sequential `SELECT` round-trips plus 60 inserts/updates, all serialized by `await`. Each round-trip at ~1 ms is fine alone but compounds; this is the classic "Why is the refresh spinner laggy?" pattern.
**Fix**: use Postgres `INSERT ... ON CONFLICT (user_page_id, ig_code) DO UPDATE SET ...`. The `UNIQUE(user_page_id, ig_code)` constraint already exists in migrations.py:100, so the upsert is a one-liner. Example:
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
stmt = pg_insert(UserPageReel).values([...all reels...])
stmt = stmt.on_conflict_do_update(
    index_elements=["user_page_id", "ig_code"],
    set_={
        "view_count": stmt.excluded.view_count,
        "like_count": stmt.excluded.like_count,
        "comment_count": stmt.excluded.comment_count,
        "posted_at": stmt.excluded.posted_at,
        "scraped_at": stmt.excluded.scraped_at,
    },
)
await db.execute(stmt)
```
One query instead of 60+.
**Priority**: P1

---

### 7. [routers/my_pages.py:248-311] — `_auto_discover_for_niche` fires ~45 sequential queries per page add
**Code**: inside `for acct in suggested[:15]:` — one `SELECT theme_pages`, one `INSERT`, one `SELECT theme_pages` again (to resolve `ON CONFLICT`), then per-reel `INSERT viral_reels` with another explicit `await`. Total ≈ 3 + (12 × 15) ≈ 183 round-trips in the `POST /api/my-pages` critical path.
**Why slow**: The entire cascade runs **in-request** before returning 201 to the client. `add_page` also runs `analyze_page` via Celery, a 500-row recommendations INSERT (my_pages.py:419-464), an immediate profile + reel scrape (my_pages.py:491-531), and a sibling re-analysis fan-out. Combined, the endpoint can block 5–30 s before the UI sees the new page.
**Fix**: move `_auto_discover_for_niche` into a Celery task (same `trigger_*` pattern already used for `trigger_analyze_page`). Return 201 immediately and let the worker populate Discover in the background. Also consolidate the `INSERT theme_pages + SELECT theme_pages` into one statement using `INSERT ... RETURNING id`.
**Priority**: P1

---

### 8. [routers/templates.py:120-123] — `create_template` loads a full row just to test existence
**Code**:
```python
count = (await db.execute(
    select(UserTemplate).where(UserTemplate.user_id == current_user.id)
)).scalars().first()
is_first = count is None
```
**Why slow**: `select(UserTemplate)` without a column list loads every column of the first row (including large JSONB `logo_position`, `headline_defaults`, `subtitle_defaults`, `text_layers`). Hot path on every template creation.
**Fix**: use a scalar existence check — no index change needed:
```python
is_first = (await db.execute(
    select(func.count()).select_from(UserTemplate)
    .where(UserTemplate.user_id == current_user.id).limit(1)
)).scalar() == 0
```
Or `select(exists().where(...))`.
**Priority**: P2

---

### 9. [routers/jobs.py:33-53] — Jobs list materializes every user's export + page IDs in Python
**Code**:
```python
own_export_ids = {str(row[0]) for row in (await db.execute(
    select(UserExport.id).where(UserExport.user_id == current_user.id))).all()}
own_page_ids = {str(row[0]) for row in (await db.execute(
    select(UserPage.id).where(UserPage.user_id == current_user.id))).all()}
allowed_ids = own_export_ids | own_page_ids
stmt = select(Job).where(Job.reference_id.in_(list(allowed_ids))).order_by(...)
```
**Why slow**: Round-trips 2 lists of UUIDs to Python just to stuff them back into an `IN (...)` clause. For heavy users (100+ exports, 20+ pages) this can send a 3 KB `IN (...)` literal on every poll — and the polling UI hits this endpoint every ~3 s. Also no index on `jobs.reference_id`, so the final query falls back to seq-scan on a large table.
**Fix**:
1. Replace the Python set build with two `EXISTS` subselects:
   ```sql
   WHERE (Job.reference_type = 'user_export' AND Job.reference_id IN (SELECT id FROM user_exports WHERE user_id = :uid))
      OR (Job.reference_type IN ('user_page','viral_reel') AND Job.reference_id IN (SELECT id FROM user_pages WHERE user_id = :uid))
   ```
2. Add an index:
   ```sql
   CREATE INDEX IF NOT EXISTS idx_jobs_ref ON jobs(reference_id);
   CREATE INDEX IF NOT EXISTS idx_jobs_created_desc ON jobs(created_at DESC);
   ```
**Priority**: P2

---

## Proposed new indexes (ready to append to migrations.py)

```sql
-- Finding #2: functional GIN for similar-reel full-text search
CREATE INDEX IF NOT EXISTS idx_viral_reels_caption_fts
    ON viral_reels USING GIN (to_tsvector('english', COALESCE(caption, '')));

-- Finding #3: composite covering the recommendation feed hot path
CREATE INDEX IF NOT EXISTS idx_recs_page_active_score
    ON user_reel_recommendations(user_page_id, is_dismissed, match_score DESC);

-- Finding #9: jobs polling endpoint
CREATE INDEX IF NOT EXISTS idx_jobs_ref ON jobs(reference_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_desc ON jobs(created_at DESC);
```

## Proposed N+1 / query-shape fixes

- `middleware/auth.py:141` — change `db=None` to `db: AsyncSession = Depends(get_db)`, delete the `if db is None` branch. Single highest-impact fix.
- `routers/my_pages.py:1046` — replace per-reel SELECT+INSERT/UPDATE loop with `INSERT ... ON CONFLICT DO UPDATE` batch on `(user_page_id, ig_code)`.
- `routers/my_pages.py:840-878` — collapse current-period + comparison-period reel fetches into one query with `SUM(CASE WHEN ... END)` aggregation.
- `routers/recommendations.py:131-153` — collapse `total` and `viral` counts into a single query using `COUNT(*) FILTER (WHERE ...)`.
- `routers/templates.py:120-123` — replace full-row `SELECT` with `SELECT COUNT(*)` / `SELECT EXISTS(...)`.
- `routers/jobs.py:33-53` — replace Python-side ID materialization with an EXISTS/IN subquery sent once to Postgres.
- `routers/my_pages.py:193-319` — move `_auto_discover_for_niche` into a Celery task so `POST /my-pages` returns fast.

## Checked-and-fine list (what looked suspicious but isn't)

- `routers/my_pages.py:144-167` `list_my_pages` profile batch-load — already the correct one-query-per-relation pattern; keyed off `PageProfile(user_page_id, max(analyzed_at))` subquery. No N+1.
- `routers/reels.py:41-46` `get_reel` — already uses `selectinload(ViralReel.sources)` + `selectinload(ViralReel.files)`. Correct.
- `routers/exports.py:128-130` `list_exports` — index `user_exports(user_id)` covers it; response size bounded by number of exports per user.
- `routers/exports.py:161-171` default-own-page lookup — `user_pages(user_id, page_type)` composite index applies.
- `routers/my_pages.py:687-693` `weekly-dashboard` — `LIMIT 8` on `idx_page_snapshots_page_time` is an index scan, two rows of work. Fine.
- `routers/my_pages.py:898-917` follower delta lookups — covered by `idx_page_snapshots_page_time(user_page_id, taken_at DESC)`; `LIMIT 1`. Fine.
- `routers/reels.py:99-118` fallback same-niche query — covered by `idx_viral_reels_niche`, `idx_viral_reels_views`. Fine.
