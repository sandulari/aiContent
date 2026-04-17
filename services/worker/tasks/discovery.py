"""Discovery tasks: theme page discovery pipeline + AI text generation.

Targets the real schema: theme_pages + viral_reels. No references to
the legacy instagram_pages / videos tables.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from celery_app import app
from lib.db import get_session
from lib.discovery_engine import (
    discover_via_hashtags,
    discover_via_graph_crawl,
    discover_via_same_content,
)
from lib.theme_page_eval import evaluate_candidate, quality_gate_check

logger = logging.getLogger(__name__)

CANDIDATES_PER_RUN = int(os.environ.get("DISCOVERY_CANDIDATES_PER_RUN", "15"))
HASHTAG_COOLDOWN_HOURS = int(os.environ.get("DISCOVERY_HASHTAG_COOLDOWN_HOURS", "48"))
GRAPH_CRAWL_BUDGET = int(os.environ.get("DISCOVERY_GRAPH_CRAWL_BUDGET", "10"))
MIN_HEURISTIC_SCORE = int(os.environ.get("THEME_PAGE_MIN_HEURISTIC_SCORE", "4"))
MIN_VIRAL_RATE = float(os.environ.get("QUALITY_GATE_MIN_VIRAL_RATE", "0.10"))


@app.task(name="tasks.discovery.discover_theme_pages_task", bind=True, max_retries=2)
def discover_theme_pages_task(self, niche_id: str | None = None):
    """Full discovery pipeline for a niche.

    If niche_id is None (Beat invocation), iterate over all active niches.
    """
    if niche_id is None:
        with get_session() as session:
            rows = session.execute(
                text("SELECT id FROM niches WHERE is_active = true"),
            ).fetchall()
        queued = 0
        for row in rows:
            try:
                discover_theme_pages_task.delay(str(row.id))
                queued += 1
            except Exception as exc:
                logger.warning("Failed to queue discovery for niche=%s: %s", row.id, exc)
        return {"multi_niche": True, "niches_queued": queued}

    logger.info("Starting discovery pipeline for niche %s", niche_id)
    run_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    try:
        with get_session() as session:
            niche = session.execute(
                text("SELECT name, slug FROM niches WHERE id = :id"),
                {"id": niche_id},
            ).fetchone()
            if not niche:
                return {"error": "Niche not found"}

            session.execute(
                text(
                    """
                    INSERT INTO discovery_runs (id, niche_id, run_type, started_at)
                    VALUES (:id, :niche_id, 'hashtag', :now)
                    """
                ),
                {"id": run_id, "niche_id": niche_id, "now": datetime.now(timezone.utc)},
            )

            session.execute(
                text(
                    """
                    INSERT INTO jobs (id, celery_task_id, job_type, status,
                        reference_id, reference_type, started_at)
                    VALUES (:id, :task_id, 'discover_pages', 'running',
                        :ref_id, 'niche', :now)
                    """
                ),
                {
                    "id": job_id,
                    "task_id": self.request.id or "",
                    "ref_id": niche_id,
                    "now": datetime.now(timezone.utc),
                },
            )

        niche_name = niche.name

        with get_session() as session:
            existing = session.execute(
                text("SELECT username FROM theme_pages"),
            ).fetchall()
            existing_usernames = {r.username for r in existing}

        # Layer 1: hashtag mining
        candidates: set[str] = set()
        hashtags_used: list[str] = []
        try:
            with get_session() as session:
                cooldown_cutoff = datetime.now(timezone.utc) - timedelta(hours=HASHTAG_COOLDOWN_HOURS)
                rows = session.execute(
                    text(
                        """
                        SELECT id, hashtag FROM niche_hashtags
                        WHERE niche_id = :nid AND is_active = true
                          AND (last_used_at IS NULL OR last_used_at < :cutoff)
                        ORDER BY candidates_produced ASC
                        LIMIT 5
                        """
                    ),
                    {"nid": niche_id, "cutoff": cooldown_cutoff},
                ).fetchall()

            for row in rows:
                try:
                    found = discover_via_hashtags(row.hashtag)
                    candidates.update(found)
                    hashtags_used.append(row.hashtag)
                    with get_session() as session:
                        session.execute(
                            text(
                                """
                                UPDATE niche_hashtags
                                SET last_used_at = :now,
                                    candidates_produced = candidates_produced + :count
                                WHERE id = :id
                                """
                            ),
                            {
                                "now": datetime.now(timezone.utc),
                                "count": len(found),
                                "id": str(row.id),
                            },
                        )
                except Exception as e:
                    logger.warning("Hashtag %s failed: %s", row.hashtag, e)
        except Exception as e:
            logger.warning("Hashtag layer failed: %s", e)

        # Layer 2: graph crawl from confirmed theme pages
        pages_crawled: list[str] = []
        try:
            with get_session() as session:
                confirmed = session.execute(
                    text(
                        """
                        SELECT id, username FROM theme_pages
                        WHERE niche_id = :nid
                          AND evaluation_status = 'confirmed'
                          AND is_active = true
                        ORDER BY RANDOM()
                        LIMIT :budget
                        """
                    ),
                    {"nid": niche_id, "budget": GRAPH_CRAWL_BUDGET},
                ).fetchall()

            for page in confirmed:
                try:
                    found = discover_via_graph_crawl(page.username)
                    candidates.update(found)
                    pages_crawled.append(page.username)
                except Exception as e:
                    logger.warning("Graph crawl for @%s failed: %s", page.username, e)
        except Exception as e:
            logger.warning("Graph crawl layer failed: %s", e)

        # Layer 3: same-content cross-ref (captions from top viral reels in niche)
        try:
            with get_session() as session:
                top_captions = session.execute(
                    text(
                        """
                        SELECT caption FROM viral_reels
                        WHERE niche_id = :nid AND view_count >= 5000000
                        ORDER BY view_count DESC
                        LIMIT 5
                        """
                    ),
                    {"nid": niche_id},
                ).fetchall()

            for row in top_captions:
                try:
                    found = discover_via_same_content(row.caption or "")
                    candidates.update(found)
                except Exception as e:
                    logger.warning("Same-content search failed: %s", e)
        except Exception as e:
            logger.warning("Same-content layer failed: %s", e)

        new_candidates = candidates - existing_usernames
        logger.info(
            "Discovery found %d total candidates, %d new", len(candidates), len(new_candidates)
        )

        confirmed_count = 0
        rejected_count = 0

        for username in list(new_candidates)[:CANDIDATES_PER_RUN]:
            try:
                eval_result = evaluate_candidate(username)
                score = eval_result.get("score", 0)
                qg = {}

                if score >= MIN_HEURISTIC_SCORE:
                    qg = quality_gate_check(username)
                    if qg.get("passes", False):
                        eval_status = "confirmed"
                        is_active = True
                        confirmed_count += 1
                    else:
                        eval_status = "rejected"
                        is_active = False
                        rejected_count += 1
                elif score == MIN_HEURISTIC_SCORE - 1:
                    eval_status = "needs_review"
                    is_active = False
                else:
                    eval_status = "rejected"
                    is_active = False
                    rejected_count += 1

                with get_session() as session:
                    session.execute(
                        text(
                            """
                            INSERT INTO theme_pages (
                                id, username, display_name, profile_url, niche_id,
                                is_active, discovered_via, heuristic_score,
                                evaluation_status, viral_hit_rate
                            )
                            VALUES (
                                :id, :uname, :uname, :url, :nid,
                                :active, :via, :score,
                                :eval_status, :viral_rate
                            )
                            ON CONFLICT (username) DO NOTHING
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "uname": username,
                            "url": f"https://www.instagram.com/{username}/",
                            "nid": niche_id,
                            "active": is_active,
                            "via": "hashtag_mining",
                            "score": score,
                            "eval_status": eval_status,
                            "viral_rate": qg.get("viral_rate"),
                        },
                    )
            except Exception as e:
                logger.warning("Evaluation of @%s failed: %s", username, e)
                rejected_count += 1

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE discovery_runs
                    SET finished_at = :now, candidates_found = :found,
                        candidates_confirmed = :confirmed,
                        candidates_rejected = :rejected,
                        hashtags_used = :hashtags, pages_crawled = :pages
                    WHERE id = :id
                    """
                ),
                {
                    "now": datetime.now(timezone.utc),
                    "found": len(new_candidates),
                    "confirmed": confirmed_count,
                    "rejected": rejected_count,
                    "hashtags": json.dumps(hashtags_used),
                    "pages": json.dumps(pages_crawled),
                    "id": run_id,
                },
            )

            session.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'success', finished_at = :now, attempts = attempts + 1
                    WHERE id = :id
                    """
                ),
                {"now": datetime.now(timezone.utc), "id": job_id},
            )

        return {
            "niche": niche_name,
            "candidates_found": len(new_candidates),
            "confirmed": confirmed_count,
            "rejected": rejected_count,
        }

    except Exception as exc:
        logger.error("Discovery pipeline failed: %s", exc, exc_info=True)
        try:
            with get_session() as session:
                session.execute(
                    text(
                        """
                        UPDATE discovery_runs SET finished_at = :now WHERE id = :id
                        """
                    ),
                    {"now": datetime.now(timezone.utc), "id": run_id},
                )
                session.execute(
                    text(
                        """
                        UPDATE jobs SET status = 'failed', finished_at = :now,
                            logs = jsonb_build_object('error', :err)
                        WHERE id = :id
                        """
                    ),
                    {
                        "now": datetime.now(timezone.utc),
                        "err": str(exc)[:1000],
                        "id": job_id,
                    },
                )
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=300)


@app.task(name="tasks.discovery.generate_ai_text_task", bind=True, max_retries=2)
def generate_ai_text_task(self, viral_reel_id: str, user_page_id: str):
    """Generate AI headline/subtitle suggestions for a viral reel."""
    logger.info("Generating AI text for viral_reel=%s user_page=%s", viral_reel_id, user_page_id)
    try:
        from lib.ai_client import generate_text_sync

        with get_session() as session:
            reel = session.execute(
                text(
                    """
                    SELECT v.caption, v.view_count, tp.username,
                           n.name as niche_name
                    FROM viral_reels v
                    JOIN theme_pages tp ON tp.id = v.theme_page_id
                    LEFT JOIN niches n ON n.id = v.niche_id
                    WHERE v.id = :vid
                    """
                ),
                {"vid": viral_reel_id},
            ).fetchone()

            if not reel:
                return {"error": "Reel not found"}

        result = generate_text_sync(
            niche=reel.niche_name or "General",
            caption=reel.caption or "",
            page_name=reel.username or "",
            view_count=reel.view_count or 0,
        )

        with get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO ai_text_generations (
                        id, viral_reel_id, user_page_id,
                        headlines, subtitles, caption_suggestion,
                        model_used, generated_at
                    )
                    VALUES (:id, :vid, :upid,
                        CAST(:headlines AS JSONB), CAST(:subtitles AS JSONB),
                        :cap_sug, :model, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "vid": viral_reel_id,
                    "upid": user_page_id,
                    "headlines": json.dumps(result.get("headlines", [])),
                    "subtitles": json.dumps(result.get("subtitles", [])),
                    "cap_sug": result.get("caption_suggestion"),
                    "model": result.get("model_used", "unknown"),
                    "now": datetime.now(timezone.utc),
                },
            )

        return result

    except Exception as exc:
        logger.error("AI text generation failed: %s", exc)
        raise self.retry(exc=exc, countdown=30)
