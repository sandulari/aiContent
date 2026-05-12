# Found issues — parked, not fixed

Things noticed while doing other work. Per the no-scope-creep rule, these
are logged here instead of fixed inline. Each entry has enough detail that
a one-paragraph PR description could be written from it directly.

## 1. `worker-enhancer` Celery queue mismatch — `queue.publish` not consumed in prod compose

**Severity**: high — scheduled IG reels will silently never publish on the
DigitalOcean droplet that uses `infra/docker-compose.prod.yml`.

- `services/worker/celery_app.py:33` routes `tasks.publish_scheduled_reel.*`
  to `queue.publish`.
- `services/worker/celery_app.py:66–77` schedules `tick-scheduled-reels`
  (every minute) and `cleanup-stuck-publishes` (every 15 minutes) on
  `queue.publish`.
- `infra/docker-compose.prod.yml` `worker-enhancer.command` ends with
  `-Q queue.enhance,queue.export` — **`queue.publish` is missing**.
- `render.yaml` is correct (`-Q queue.enhance,queue.export,queue.publish`).

**Fix**: add `,queue.publish` to the `worker-enhancer` command in
`infra/docker-compose.prod.yml`. On the deployed droplet, also restart
`worker-enhancer` so the new queue subscription takes effect.

## 2. Two "reference pages" surfaces in /settings will confuse users

After Task 1.1, the Settings page renders both:
- the legacy section that lists `user_pages` rows with `page_type='reference'`
  (label: "Reference pages") — feeds the niche-based recommendation pipeline
- the new section that lists `reference_pages` rows (label: "Reference pages
  for discovery") — feeds the per-page discovery pipeline added in 1.3

This is on purpose for Task 1.1 ("build alongside, new tables") so the
legacy flow stays untouched. But long-term we should pick one. Candidates:

- **Migrate forward**: write a one-shot migration that copies every
  `user_pages` row with `page_type='reference'` into `reference_pages`
  and stop using `page_type='reference'` for new writes. Drop the legacy
  section from /settings.
- **Migrate backward**: kill `reference_pages`, fold the per-page
  discovery into the existing `user_pages` row with a new column. More
  churn, no clear win.
- **Keep both**: ship a labelling pass so users understand the difference,
  document in /onboarding.

Defer to after Phase 1 is complete and we have user data to inform the call.

## 3. Access token default of 60 minutes vs Phase 2.4 spec of 15

**RESOLVED in Task 2.4** (commit `ddb33ae`) — default lowered to 15.

## 4. Refresh-token reuse detection missing

**RESOLVED in Task 2.4** (commit `ddb33ae`) — new ``refresh_tokens``
table keyed by ``(family_id, token_hash)``. ``/refresh`` rotates within
the family; a replayed revoked token triggers a family-wide purge.

## 5. `CORSMiddleware` wildcard origin + `allow_credentials=True` is unsafe

**RESOLVED in Task 2.5** — strict ``ALLOWED_ORIGINS`` allowlist with
``*`` rejected at startup; methods + request headers + exposed response
headers all enumerated explicitly in
``services/api/middleware/cors_config.py``.

## 6. Discovery refresh runs in-process via BackgroundTasks instead of Celery

`POST /api/discovery/refresh` queues work through FastAPI's
`BackgroundTasks` (Task 1.3b). The refresh runs in the same uvicorn worker
that handled the request, blocking that worker for the duration of the
RapidAPI fetch (~5-30 s for a user with several reference pages).

This is a deliberate trade-off for Task 1.3 — pulling in Celery added
significant complexity (worker-side duplication of the service module
since `services/api` and `services/worker` are separate Python packages
with no shared lib, plus prod-compose / render.yaml queue wiring). The
in-process path is correct for early scale.

**When to migrate**: when one of
- a refresh routinely takes >5 s (uvicorn worker starvation visible in
  p50 latency), or
- we want a periodic Celery beat that refreshes every user's cache on
  a schedule (then `BackgroundTasks` is the wrong tool by definition).

The refactor is bounded: `services/worker/lib/reference_discovery_sync.py`
mirrors `fetch_handle_reels` with sync httpx + sync SQLAlchemy session.
`services/worker/tasks/reference_discovery.py` wraps it in `@app.task`.
`celery_app.py` adds `tasks.reference_discovery.*` -> `queue.discovery_v2`
(NOT `queue.discover` — that's the legacy niche pipeline). Then prod
compose's `worker-enhancer` needs `queue.discovery_v2` appended to its
`-Q` flag (issue #1 above is the same shape — easy to miss).

## 7. Worker exporter doesn't dispatch on `user_exports.reference_reel_id`

Task 1.7 makes `user_exports.viral_reel_id` nullable and adds a
`reference_reel_id` column so a download-sourced UserExport can drive
the existing `/editor/{id}` route. The CHECK constraint ensures exactly
one source FK is populated.

The router-level changes are done. The worker exporter
(`services/worker/tasks/exporter.py`) still reads the source video by
following `user_exports.viral_reel_id -> viral_reels -> video_files`.
For a discovery-download UserExport that join is empty, so a Render
click on a download-sourced export will fail to produce an MP4 until
the exporter learns to branch:

```
if user_exports.reference_reel_id IS NOT NULL:
    source_minio_key = (
        SELECT minio_key FROM downloads
        WHERE reference_reel_id = user_exports.reference_reel_id
          AND user_id = user_exports.user_id
          AND status = 'done'
    )
else:
    source_minio_key = (... existing viral_reels -> video_files lookup ...)
```

The download row already lives at `discovery/{user_id}/{download_id}.mp4`
in the `videos` MinIO bucket, so the fetch is a single SELECT. Editing
the source video in the editor UI (preview, trim, overlay) is unaffected
— it only breaks at render-export time.

## 8. `apps/web/lib/api.ts` token refresh treats _every_ 401 as a refresh trigger

The retry-on-401 logic doesn't distinguish between "your access token
expired" and "you tried to access something you don't own". A 401 from
an ownership check will fire a pointless `/api/auth/refresh` call,
masking the actual error from logs. Fine for now, worth tightening when
Phase 2.4 lands.

## 9. Frontend CSP still allows `'unsafe-inline'` + `'unsafe-eval'` in `script-src`

`apps/web/next.config.js` ships a strict CSP for everything except
`script-src`, which has to allow `'unsafe-inline'` because Next.js
inlines its runtime bootstrap, and `'unsafe-eval'` because dev-mode
HMR uses eval. This widens the XSS-payoff surface — a successful
injection via any other vector could execute inline.

The clean fix is a per-request nonce: Next.js 14 supports it via
middleware that mints a nonce, stamps `<script nonce=...>` on every
Next-emitted script tag, and adds `script-src 'self' 'nonce-...'` to
the CSP header for that request. Implementation:

- `apps/web/middleware.ts` returning a `NextResponse` with `Content-
  Security-Policy` per request.
- `apps/web/app/layout.tsx` reading the nonce from request headers
  (Next gives you a server-side helper) and passing to `<Script>`.

Defer until we have a stable inline-script audit — moving to nonces
breaks any third-party script that doesn't carry the nonce, so we'd
need to confirm we don't load Stripe / GA / etc. inline first.
