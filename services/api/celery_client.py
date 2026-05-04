"""Celery client — dispatches tasks to workers."""
import os
from uuid import UUID
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("vre", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True)


def trigger_analyze_page(page_id: UUID) -> str:
    r = celery_app.send_task("tasks.analyze_page.analyze_page_task", args=[str(page_id)], queue="queue.analyze")
    return r.id

def trigger_page_stats_snapshot(page_id: UUID) -> str:
    r = celery_app.send_task(
        "tasks.page_stats_snapshot.snapshot_page",
        args=[str(page_id)],
        queue="queue.analyze",
    )
    return r.id

def trigger_discover_pages(niche_id: UUID) -> str:
    r = celery_app.send_task("tasks.discovery.discover_theme_pages_task", args=[str(niche_id)], queue="queue.discover")
    return r.id

def trigger_scrape_page(page_id: UUID) -> str:
    r = celery_app.send_task("tasks.scraper.scrape_page", args=[str(page_id)], queue="queue.scrape")
    return r.id

def trigger_source_search(reel_id: UUID) -> str:
    r = celery_app.send_task("tasks.source_search.search_source", args=[str(reel_id)], queue="queue.search")
    return r.id

def trigger_download(reel_id: UUID, source_id: UUID = None) -> str:
    args = [str(reel_id)]
    if source_id:
        args.append(str(source_id))
    r = celery_app.send_task("tasks.downloader.download_video", args=args, queue="queue.download")
    return r.id

def trigger_export_render(export_id: UUID) -> str:
    r = celery_app.send_task("tasks.exporter.export_video_task", args=[str(export_id)], queue="queue.export")
    return r.id

def trigger_generate_recommendations(page_id: UUID) -> str:
    r = celery_app.send_task("tasks.recommendation.generate_recommendations_task", args=[str(page_id)], queue="queue.analyze")
    return r.id

def trigger_deep_discovery(page_id: UUID) -> str:
    r = celery_app.send_task("tasks.deep_discovery.deep_discovery_task", args=[str(page_id)], queue="queue.discover")
    return r.id

def trigger_seed_default_template(user_id: UUID) -> str:
    r = celery_app.send_task("tasks.seed_default_template.seed_for_user", args=[str(user_id)], queue="queue.analyze")
    return r.id

def trigger_auto_discover(ig_username: str, niche_slug: str) -> str:
    r = celery_app.send_task(
        "tasks.auto_discover.auto_discover_for_user_page",
        args=[ig_username, niche_slug],
        queue="queue.discover",
    )
    return r.id
