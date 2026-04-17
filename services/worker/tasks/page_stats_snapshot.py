"""Weekly stats snapshot for user's own Instagram pages.

Powers the weekly dashboard: top reel this week, comments / followers
gained WoW, engagement delta.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib.instagram import scrape_profile
from lib.theme_page_eval import _fetch_profile_metadata

logger = logging.getLogger(__name__)


def _week_key(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _snapshot_one_page(user_page_id: str, ig_username: str) -> dict | None:
    meta = _fetch_profile_metadata(ig_username)
    followers = meta.get("followers")
    following = None  # _fetch_profile_metadata doesn't expose this
    posts = meta.get("posts")

    reels = []
    try:
        reels = scrape_profile(ig_username, max_posts=30)
    except Exception as exc:
        logger.warning("scrape_profile failed for @%s: %s", ig_username, exc)

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def _in_week(reel) -> bool:
        if not reel.posted_at:
            return True
        try:
            parsed = datetime.fromisoformat(reel.posted_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed >= cutoff
        except Exception:
            return False

    week_reels = [r for r in reels if _in_week(r)]

    total_views = sum(r.view_count for r in week_reels)
    total_likes = sum(r.like_count for r in week_reels)
    total_comments = sum(r.comment_count for r in week_reels)

    top_reel = None
    if reels:
        top = max(reels, key=lambda r: (r.view_count, r.like_count))
        top_reel = {
            "ig_video_id": top.video_id,
            "ig_url": top.url,
            "view_count": top.view_count,
            "like_count": top.like_count,
            "caption": (top.caption or "")[:500],
        }

    now = datetime.now(timezone.utc)
    snapshot_id = str(uuid.uuid4())

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO page_snapshots (
                    id, user_page_id, taken_at, week_key,
                    follower_count, following_count, total_posts,
                    total_views_week, total_likes_week, total_comments_week,
                    top_reel_ig_id, top_reel_url, top_reel_views,
                    top_reel_likes, top_reel_caption, raw_payload
                )
                VALUES (:id, :pid, :now, :week,
                    :followers, :following, :posts,
                    :views, :likes, :comments,
                    :top_id, :top_url, :top_views,
                    :top_likes, :top_caption, CAST(:raw AS JSONB))
                """
            ),
            {
                "id": snapshot_id,
                "pid": user_page_id,
                "now": now,
                "week": _week_key(now),
                "followers": followers,
                "following": following,
                "posts": posts,
                "views": total_views,
                "likes": total_likes,
                "comments": total_comments,
                "top_id": top_reel["ig_video_id"] if top_reel else None,
                "top_url": top_reel["ig_url"] if top_reel else None,
                "top_views": top_reel["view_count"] if top_reel else None,
                "top_likes": top_reel["like_count"] if top_reel else None,
                "top_caption": top_reel["caption"] if top_reel else None,
                "raw": json.dumps({"week_reels": len(week_reels), "total_reels": len(reels)}),
            },
        )

        session.execute(
            text(
                """
                UPDATE user_pages
                SET follower_count = COALESCE(:followers, follower_count),
                    total_posts = COALESCE(:posts, total_posts),
                    last_scraped_at = :now
                WHERE id = :id
                """
            ),
            {
                "followers": followers,
                "posts": posts,
                "now": now,
                "id": user_page_id,
            },
        )

    return {
        "snapshot_id": snapshot_id,
        "followers": followers,
        "reels_in_week": len(week_reels),
        "top_reel_views": top_reel["view_count"] if top_reel else None,
    }


@app.task(name="tasks.page_stats_snapshot.snapshot_page", bind=True, max_retries=2)
def snapshot_page(self, user_page_id: str):
    logger.info("Snapshot for user_page=%s", user_page_id)
    job_id = str(uuid.uuid4())

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :task_id, 'snapshot_page', 'running',
                    :ref_id, 'user_page', :now)
                """
            ),
            {
                "id": job_id,
                "task_id": self.request.id or "",
                "ref_id": user_page_id,
                "now": datetime.now(timezone.utc),
            },
        )

        row = session.execute(
            text("SELECT ig_username, page_type FROM user_pages WHERE id = :id"),
            {"id": user_page_id},
        ).fetchone()

    def _finish_job(status: str, error: str | None = None):
        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = :status, finished_at = :now,
                        attempts = attempts + 1,
                        logs = CASE WHEN :error IS NULL THEN logs
                                    ELSE jsonb_build_object('error', :error) END
                    WHERE id = :id
                    """
                ),
                {
                    "status": status,
                    "now": datetime.now(timezone.utc),
                    "error": error,
                    "id": job_id,
                },
            )

    if not row:
        _finish_job("failed", "user_page not found")
        return {"error": "user_page not found"}
    if row.page_type != "own":
        _finish_job("success", None)
        return {"skipped": "not an own page"}

    try:
        result = _snapshot_one_page(user_page_id, row.ig_username) or {}
        _finish_job("success")
        return result
    except Exception as exc:
        logger.error("Snapshot failed: %s", exc, exc_info=True)
        _finish_job("failed", str(exc)[:1000])
        raise self.retry(exc=exc, countdown=300)


@app.task(name="tasks.page_stats_snapshot.snapshot_all_own_pages", bind=True)
def snapshot_all_own_pages(self):
    """Beat-triggered: snapshot every user's own page daily."""
    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT id FROM user_pages
                WHERE page_type = 'own' AND is_active = true
                """
            ),
        ).fetchall()

    queued = 0
    for row in rows:
        try:
            snapshot_page.delay(str(row.id))
            queued += 1
        except Exception as exc:
            logger.warning("Failed to queue snapshot %s: %s", row.id, exc)

    return {"queued": queued}
