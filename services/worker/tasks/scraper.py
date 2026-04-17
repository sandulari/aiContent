"""Scraper tasks — scrape theme pages for viral reels."""
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from celery_app import app
from lib.db import get_session
from lib.instagram import scrape_profile

logger = logging.getLogger(__name__)


@app.task(name="tasks.scraper.scrape_all_active_pages", bind=True, max_retries=2)
def scrape_all_active_pages(self):
    """Periodic: dispatch scrape tasks for theme pages due for scraping."""
    try:
        with get_session() as session:
            rows = session.execute(text("""
                SELECT id, username, scrape_interval_minutes
                FROM theme_pages
                WHERE is_active = true AND evaluation_status = 'confirmed'
                  AND (last_scraped_at IS NULL
                       OR last_scraped_at < NOW() - (scrape_interval_minutes || ' minutes')::INTERVAL)
                ORDER BY last_scraped_at ASC NULLS FIRST
                LIMIT 50
            """)).fetchall()
        dispatched = 0
        for row in rows:
            scrape_page.apply_async(args=[str(row.id)], queue="queue.scrape")
            dispatched += 1
        logger.info("Dispatched %d scrape tasks", dispatched)
        return {"dispatched": dispatched}
    except Exception as exc:
        logger.error("scrape_all_active_pages failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(name="tasks.scraper.scrape_page", bind=True, max_retries=3)
def scrape_page(self, page_id: str):
    """Scrape one theme page for viral reels."""
    try:
        with get_session() as session:
            page = session.execute(
                text("SELECT username, min_views_threshold, niche_id FROM theme_pages WHERE id = :id"),
                {"id": page_id},
            ).fetchone()
            if not page:
                return {"error": "Page not found"}

            username = page.username
            threshold = page.min_views_threshold
            niche_id = str(page.niche_id) if page.niche_id else None

            job_id = str(uuid.uuid4())
            session.execute(text("""
                INSERT INTO jobs (id, celery_task_id, job_type, status, started_at, reference_id, reference_type)
                VALUES (:id, :task_id, 'scrape', 'running', :now, :ref_id, 'theme_page')
            """), {"id": job_id, "task_id": self.request.id or "", "now": datetime.now(timezone.utc), "ref_id": page_id})

        videos = scrape_profile(username, max_posts=50)
        logger.info("Scraped %d videos from @%s", len(videos), username)

        new_count = 0
        with get_session() as session:
            existing = session.execute(
                text("SELECT ig_video_id FROM viral_reels WHERE theme_page_id = :pid"),
                {"pid": page_id},
            ).fetchall()
            existing_ids = {r.ig_video_id for r in existing}

            for v in videos:
                if v.video_id in existing_ids:
                    continue
                vid_id = str(uuid.uuid4())
                session.execute(text("""
                    INSERT INTO viral_reels (id, theme_page_id, ig_video_id, ig_url,
                        thumbnail_url, view_count, like_count, comment_count, duration_seconds,
                        caption, posted_at, scraped_at, niche_id, status)
                    VALUES (:id, :page_id, :ig_vid, :url, :thumb, :views, :likes, :comments,
                        :duration, :caption, :posted, :scraped, :niche_id, :status)
                """), {
                    "id": vid_id, "page_id": page_id, "ig_vid": v.video_id,
                    "url": v.url, "thumb": v.thumbnail_url,
                    "views": v.view_count, "likes": v.like_count,
                    "comments": v.comment_count, "duration": v.duration_seconds,
                    "caption": v.caption, "posted": v.posted_at,
                    "scraped": datetime.now(timezone.utc),
                    "niche_id": niche_id,
                    "status": "discovered" if v.view_count < threshold else "discovered",
                })
                new_count += 1

            session.execute(
                text("UPDATE theme_pages SET last_scraped_at = :now WHERE id = :id"),
                {"now": datetime.now(timezone.utc), "id": page_id},
            )
            session.execute(text("""
                UPDATE jobs SET status = 'success', finished_at = :now, attempts = attempts + 1 WHERE id = :id
            """), {"now": datetime.now(timezone.utc), "id": job_id})

        return {"username": username, "found": len(videos), "new": new_count}

    except Exception as exc:
        logger.error("scrape_page failed for %s: %s", page_id, exc)
        raise self.retry(exc=exc, countdown=120)
