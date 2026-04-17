# QA Audit Map — Shadow Pages Architecture

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS |
| Backend API | FastAPI (async), SQLAlchemy 2.0, Pydantic, Python 3.12 |
| Workers | Celery 5 with Redis broker, Python 3.12 |
| Database | PostgreSQL 16 |
| Object Storage | MinIO (S3-compatible) |
| Proxy | Nginx |
| AI | Claude via bridge daemon (host:7777) + Anthropic API fallback |
| Instagram | RapidAPI scraper (not official OAuth) |
| Video Processing | FFmpeg, yt-dlp, Pillow, Real-ESRGAN |
| Container Orchestration | Docker Compose (11 services) |

## Frontend Pages

| Route | Screen | Purpose |
|-------|--------|---------|
| `/` | Root | Auth check, redirect to /dashboard or /auth/login |
| `/auth/login` | Login | Email/password form |
| `/auth/register` | Register | Account creation form |
| `/onboarding` | Onboarding | Connect IG page, animated progress |
| `/dashboard` | Dashboard | Weekly stats, follower delta, top reel, recent exports |
| `/discover` | Discover Feed | Recommendation grid, sort/filter, dismiss/use actions |
| `/reels/[id]` | Reel Detail | Caption, stats, find sources, download, open editor |
| `/editor/[exportId]` | Video Editor | Canvas, layers, properties, timeline, audio, AI chat |
| `/library` | Library | Export card grid with edit/download/delete |
| `/exports` | Exports Table | Export table with status, dates, edit/download/delete |
| `/templates` | Template Builder | Canvas-based template editor with logo/headline/subtitle |
| `/settings` | Settings | Add/remove own and reference IG pages |

## Frontend Components

| Directory | Components |
|-----------|-----------|
| `layout/` | Shell (auth wrapper), Sidebar (6 nav items + logout) |
| `ui/` | Button, Card, Input, Modal, Select, Badge, Table |
| `shared/` | EmptyState, Loading, StatusBadge |
| `editor/` | Canvas, LayersPanel, PropertiesPanel, Timeline, AudioControls, AITextPanel, ExportDialog |

## API Endpoints (10 routers, 40+ endpoints)

### Auth (`/api/auth`)
- POST /register, POST /login, GET /me

### My Pages (`/api/my-pages`)
- GET / (list), POST / (add), DELETE /{id} (remove)
- GET /{id}/profile, GET /{id}/stats, GET /{id}/weekly-dashboard
- POST /{id}/refresh-stats

### Recommendations (`/api/my-pages`)
- GET /{page_id}/recommendations, GET /{page_id}/recommendations/summary
- POST /recommendations/{id}/dismiss, POST /recommendations/{id}/use

### Reels (`/api/reels`)
- GET /{id}, POST /{id}/find-sources, POST /{id}/download

### Templates (`/api/templates`)
- GET /, GET /{id}, POST /, PUT /{id}, DELETE /{id}
- POST /{id}/set-default, POST /{id}/upload-logo

### Exports (`/api/exports`)
- GET /, POST /, PUT /{id}, DELETE /{id}
- POST /{id}/apply-template/{tid}, POST /{id}/upload-logo
- DELETE /{id}/logo-override, POST /{id}/render
- GET /{id}/status, GET /{id}/download

### AI (`/api/ai`)
- POST /generate-text, POST /chat, POST /regenerate

### Files (`/api/files`)
- GET /{id}/download, GET /video/{id}/stream, GET /video/{id}/info
- GET /logo/{tid}, GET /export-logo/{eid}, GET /thumbnail/{rid}
- POST /upload-audio

### Jobs (`/api/jobs`)
- GET / (list user's jobs)

### Niches (`/api/niches`)
- GET / (list active niches)

## Database (18 tables)

| Table | Purpose |
|-------|---------|
| users | Account credentials + profile |
| user_pages | Connected IG pages (own + reference) |
| page_profiles | AI-analyzed niche, topics, style per page |
| page_snapshots | Weekly growth stats per own page |
| niches | 15 content categories |
| niche_hashtags | Mining sources per niche |
| theme_pages | Discovered external IG accounts |
| viral_reels | Scraped reels from theme pages |
| video_sources | Alternative platform matches (YouTube, TikTok) |
| video_files | Downloaded/enhanced/exported video files in MinIO |
| user_reel_recommendations | AI-matched reels per user page |
| user_templates | Video export templates per user |
| user_exports | User's edited video export jobs |
| ai_text_generations | Log of AI-generated headlines/subtitles |
| discovery_runs | Discovery pipeline execution log |
| jobs | Celery task tracking |

## Worker Tasks & Queues

| Queue | Worker | Tasks |
|-------|--------|-------|
| queue.scrape | worker-scraper (c=4) | scrape_all_active_pages (15min), scrape_page |
| queue.discover | worker-scraper (c=4) | discover_theme_pages_task (6h) |
| queue.analyze | worker-scraper (c=4) | analyze_page_task, generate_recommendations_task, refresh_all_pages (1h), snapshot_all_own_pages (daily 6am) |
| queue.download | worker-downloader (c=4) | download_video_task |
| queue.search | worker-downloader (c=4) | search_source |
| queue.enhance | worker-enhancer (c=2) | enhance_video_task |
| queue.export | worker-enhancer (c=2) | export_video_task |

## Data Flows

### User Onboarding
User registers -> adds IG username -> API triggers analyze_page_task -> RapidAPI profile fetch -> Claude niche detection -> seed theme_pages + viral_reels -> generate_recommendations_task -> 100+ reel feed ready

### Content Discovery (periodic)
Beat scheduler (6h) -> discover_theme_pages_task -> hashtag mining + graph crawl + same-content search -> evaluate candidates (7 heuristics) -> quality gate check -> insert theme_pages

### Recommendation Feed (periodic)
Beat scheduler (1h) -> refresh_all_pages -> load page profiles + reference pages -> keyword scoring + Claude re-ranking -> insert up to 500 recommendations sorted by score

### Download Pipeline
User selects reel -> find-sources (yt-dlp YouTube search) -> user picks source -> download_video_task (yt-dlp) -> ffprobe validation -> upload to MinIO -> video_files record

### Video Export
User edits in editor (autosaves) -> clicks Export -> export_video_task -> download video + logo + audio from MinIO -> Pillow text rendering -> FFmpeg composition (1080x1920) -> atomic upload with per-render UUID -> old file cleanup -> status = done

### Dashboard Stats (periodic)
Beat scheduler (daily 6am) -> snapshot_all_own_pages -> scrape own page reels -> compute WoW deltas -> insert page_snapshots
