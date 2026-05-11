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

`services/api/middleware/auth.py:21`:
```python
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
```

Phase 2.4 spec wants 15. Will be lowered in Task 2.4 alongside the
rotating-refresh-token + reuse-detection work.

## 4. Refresh-token reuse detection missing

`services/api/middleware/auth.py` + `routers/auth.py` use a single
SHA-256 hash on `users.refresh_token`. Rotation works (overwrite on each
`/refresh`), but a replayed old refresh token cannot be detected as a
reuse — it just fails because the hash already changed. Spec (Task 2.4)
wants the entire token family revoked on a reuse attempt.

Fix sketch: separate `refresh_tokens` table keyed by `(family_id,
token_hash)`. On `/refresh`, validate the presented hash exists with
`revoked_at IS NULL`; mark it revoked and insert a successor in the same
family. On a presented hash that is `revoked_at IS NOT NULL`, delete
every row in that family and force re-login.

## 5. `CORSMiddleware` wildcard origin + `allow_credentials=True` is unsafe

`services/api/main.py:25-29`:
```python
allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(","),
allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
```

Per the CORS spec, browsers refuse to send credentials with `*` origin.
FastAPI's `CORSMiddleware` works around it by echoing the request origin,
which is functionally an open allowlist. Phase 2.5 will replace with a
strict `ALLOWED_ORIGINS` env-driven list.

## 6. `apps/web/lib/api.ts` token refresh treats _every_ 401 as a refresh trigger

The retry-on-401 logic doesn't distinguish between "your access token
expired" and "you tried to access something you don't own". A 401 from
an ownership check will fire a pointless `/api/auth/refresh` call,
masking the actual error from logs. Fine for now, worth tightening when
Phase 2.4 lands.
