"""Auto-discover theme pages for a newly-added user page.

Background replacement for the in-request `_auto_discover_for_niche`
helper in services/api/routers/my_pages.py. Used to fire ~45 sequential
queries inside POST /api/my-pages, blocking the response 5–30s. Now
triggered as a Celery task so the API returns 201 immediately and the
worker fills `theme_pages` + `viral_reels` in the background.

Logic mirrors the original loop:
  1. Profile-lookup the just-added page to get its IG `pk`.
  2. Pull suggested accounts (Instagram's "Similar accounts" graph).
  3. For each suggested account, upsert a `theme_pages` row tagged with
     the detected niche, then scrape one page of their reels into
     `viral_reels` (ON CONFLICT DO UPDATE on counts).

Reuses the RapidAPI helpers in tasks.deep_discovery to avoid duplicating
client config; this task only adds the niche-resolution + persistence.
"""
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from tasks.deep_discovery import _get_profile, _get_user_reels, _get_suggested

logger = logging.getLogger(__name__)

MAX_SUGGESTED = 15
API_DELAY = 0.5  # matches the original loop's pacing


def _resolve_niche_id(session, niche_slug: str) -> str | None:
    """Find the niche by slug or fuzzy name; create it if missing."""
    slug = niche_slug.lower()
    row = session.execute(
        text(
            "SELECT id FROM niches WHERE slug = :slug OR LOWER(name) LIKE :like LIMIT 1"
        ),
        {"slug": slug, "like": f"%{slug}%"},
    ).fetchone()
    if row:
        return str(row.id)

    new_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO niches (id, name, slug, is_active) "
            "VALUES (:id, :name, :slug, true) ON CONFLICT (slug) DO NOTHING"
        ),
        {"id": new_id, "name": niche_slug.title(), "slug": slug},
    )
    row = session.execute(
        text("SELECT id FROM niches WHERE slug = :slug"),
        {"slug": slug},
    ).fetchone()
    return str(row.id) if row else new_id


@app.task(name="tasks.auto_discover.auto_discover_for_user_page", bind=True, max_retries=1)
def auto_discover_for_user_page(self, ig_username: str, niche_slug: str) -> dict:
    """Discover similar accounts + scrape their reels for a user's niche."""
    profile = _get_profile(ig_username)
    if not profile:
        return {"reels_scraped": 0, "reason": "profile_not_found"}

    user_pk = profile.get("pk") or profile.get("pk_id")
    if not user_pk:
        return {"reels_scraped": 0, "reason": "no_pk"}

    suggested = _get_suggested(user_pk)
    if not suggested:
        return {"reels_scraped": 0, "reason": "no_suggested"}

    with get_session() as session:
        niche_id = _resolve_niche_id(session, niche_slug)

    if not niche_id:
        return {"reels_scraped": 0, "reason": "no_niche_id"}

    total_reels = 0
    pages_processed = 0
    now = datetime.now(timezone.utc)

    for acct in suggested[:MAX_SUGGESTED]:
        username = acct.get("username") or ""
        pk = acct.get("pk") or ""
        if not username or not pk:
            continue

        with get_session() as session:
            existing = session.execute(
                text("SELECT id FROM theme_pages WHERE username = :u"),
                {"u": username},
            ).fetchone()
            if existing:
                continue

            tp_id = str(uuid.uuid4())
            session.execute(
                text(
                    """
                    INSERT INTO theme_pages (id, username, niche_id, is_active,
                        evaluation_status, discovered_via, created_at)
                    VALUES (:id, :username, :niche_id, true, 'confirmed',
                        'auto_discover', :now)
                    ON CONFLICT (username) DO NOTHING
                    """
                ),
                {"id": tp_id, "username": username, "niche_id": niche_id, "now": now},
            )
            tp_row = session.execute(
                text("SELECT id FROM theme_pages WHERE username = :u"),
                {"u": username},
            ).fetchone()
            real_tp_id = str(tp_row.id) if tp_row else tp_id

        try:
            reels = _get_user_reels(pk, max_pages=1)
        except Exception as exc:
            logger.warning("Reel scrape failed for @%s: %s", username, str(exc)[:120])
            time.sleep(API_DELAY)
            continue

        if not reels:
            time.sleep(API_DELAY)
            continue

        rows = []
        for reel in reels:
            code = reel.get("shortcode") or reel.get("code") or ""
            if not code:
                continue
            taken_at = reel.get("taken_at")
            posted_at = (
                datetime.fromtimestamp(taken_at, tz=timezone.utc) if taken_at else None
            )
            caption_raw = reel.get("caption") or ""
            if isinstance(caption_raw, dict):
                caption_raw = caption_raw.get("text") or ""
            caption = str(caption_raw)[:500]
            thumb = reel.get("thumbnail_url") or ""
            rows.append({
                "id": str(uuid.uuid4()),
                "tp_id": real_tp_id,
                "code": code,
                "url": f"https://www.instagram.com/reel/{code}/",
                "thumb": thumb[:500],
                "views": int(reel.get("view_count") or reel.get("play_count") or 0),
                "likes": int(reel.get("like_count") or 0),
                "comments": int(reel.get("comment_count") or 0),
                "caption": caption,
                "posted_at": posted_at,
                "now": now,
                "niche_id": niche_id,
            })

        if rows:
            # Single executemany — psycopg2 batches the parameter sets
            # under one round-trip, much cheaper than N round-trips for
            # ~12 reels per page across 15 pages.
            with get_session() as session:
                session.execute(
                    text(
                        """
                        INSERT INTO viral_reels (id, theme_page_id, ig_video_id,
                            ig_url, thumbnail_url, view_count, like_count,
                            comment_count, caption, posted_at, scraped_at,
                            niche_id, status, created_at)
                        VALUES (:id, :tp_id, :code, :url, :thumb, :views,
                            :likes, :comments, :caption, :posted_at, :now,
                            :niche_id, 'discovered', :now)
                        ON CONFLICT (ig_video_id) DO UPDATE SET
                            view_count = EXCLUDED.view_count,
                            like_count = EXCLUDED.like_count
                        """
                    ),
                    rows,
                )
            total_reels += len(rows)
            pages_processed += 1

        time.sleep(API_DELAY)

    logger.info(
        "auto_discover @%s niche=%s pages=%d reels=%d",
        ig_username, niche_slug, pages_processed, total_reels,
    )
    return {
        "reels_scraped": total_reels,
        "pages_processed": pages_processed,
        "niche_slug": niche_slug,
    }
