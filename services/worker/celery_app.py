"""Celery application configuration for the Viral Reel Engine (VRE)."""

import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("vre", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_routes={
        "tasks.scraper.*": {"queue": "queue.scrape"},
        "tasks.discovery.*": {"queue": "queue.discover"},
        "tasks.deep_discovery.*": {"queue": "queue.discover"},
        "tasks.downloader.*": {"queue": "queue.download"},
        "tasks.source_search.*": {"queue": "queue.search"},
        "tasks.enhancer.*": {"queue": "queue.enhance"},
        "tasks.exporter.*": {"queue": "queue.export"},
        "tasks.analyze_page.*": {"queue": "queue.analyze"},
        "tasks.recommendation.*": {"queue": "queue.analyze"},
        "tasks.page_stats_snapshot.*": {"queue": "queue.analyze"},
        "tasks.seed_default_template.*": {"queue": "queue.analyze"},
        "tasks.publish_scheduled_reel.*": {"queue": "queue.publish"},
    },
    beat_schedule={
        # Keep the viral_reels pool fresh on every confirmed theme page.
        "scrape-active-pages": {
            "task": "tasks.scraper.scrape_all_active_pages",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "queue.scrape"},
        },
        # Grow the theme_pages pool for every niche every 6h.
        "discover-theme-pages": {
            "task": "tasks.discovery.discover_theme_pages_task",
            "schedule": crontab(minute=0, hour="*/6"),
            "options": {"queue": "queue.discover"},
        },
        # Refresh recommendations for every user page every hour so
        # students always see something new without clicking anything.
        "refresh-recommendations": {
            "task": "tasks.recommendation.refresh_all_pages",
            "schedule": crontab(minute=10, hour="*"),
            "options": {"queue": "queue.analyze"},
        },
        # Snapshot every user's own IG page daily for the weekly dashboard.
        "snapshot-own-pages": {
            "task": "tasks.page_stats_snapshot.snapshot_all_own_pages",
            "schedule": crontab(minute=0, hour=6),
            "options": {"queue": "queue.analyze"},
        },
        # Dispatch scheduled Instagram Reels whose time has come. Runs
        # every minute so the wall-clock drift between scheduled_at and
        # actual publish never exceeds ~60s.
        "tick-scheduled-reels": {
            "task": "tasks.publish_scheduled_reel.tick_scheduled_reels",
            "schedule": crontab(minute="*"),
            "options": {"queue": "queue.publish"},
        },
        # Reconcile reels stuck in 'processing' (worker crash, lost poll,
        # etc.) against Meta's container state so rows don't dangle.
        "cleanup-stuck-publishes": {
            "task": "tasks.publish_scheduled_reel.cleanup_stuck_processing",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "queue.publish"},
        },
    },
)

# Explicit imports of all task modules so @app.task registrations run.
import tasks.scraper  # noqa: F401, E402
import tasks.discovery  # noqa: F401, E402
import tasks.downloader  # noqa: F401, E402
import tasks.source_search  # noqa: F401, E402
import tasks.enhancer  # noqa: F401, E402
import tasks.exporter  # noqa: F401, E402
import tasks.analyze_page  # noqa: F401, E402
import tasks.recommendation  # noqa: F401, E402
import tasks.page_stats_snapshot  # noqa: F401, E402
import tasks.deep_discovery  # noqa: F401, E402
import tasks.seed_default_template  # noqa: F401, E402
import tasks.publish_scheduled_reel  # noqa: F401, E402
