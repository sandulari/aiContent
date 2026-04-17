"""
Source search task: find the same or similar video on YouTube/other platforms.
Uses yt-dlp's built-in search (no API keys required) as the primary method.
"""

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from celery_app import app
from lib.db import get_session

logger = logging.getLogger(__name__)

TMP_DIR = os.getenv("HARVESTER_TMP_DIR", "/tmp/harvester")


# Hashtags and words that are pure noise — they steer the YouTube search
# away from the actual content. "9gag" matches the wrong account, "fyp"
# is generic spam, etc.
_NOISE_TOKENS = {
    "9gag", "fyp", "foryou", "foryoupage", "viral", "viralvideo",
    "reels", "reel", "instagram", "ig", "explore", "trending",
    "follow", "like", "share", "comment", "subscribe",
    "tiktok", "instareels", "instagood",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "by", "for",
    "with", "from", "as", "this", "that", "these", "those", "it", "its",
    "if", "then", "than", "so", "i", "you", "he", "she", "they", "we",
    "my", "your", "his", "her", "their", "our", "me", "him", "us", "them",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "shall", "may", "might", "just", "via", "amp",
}


def _extract_keywords(caption: str, page_username: str = "") -> list[str]:
    """Return a *prioritised* list of search query candidates.

    The renderer used to use a single mangled query string, which broke on
    captions like "drill drop and roll 🐱 @baaaaauri - #calico #9gag #straycat"
    (gets searched literally → 0 YouTube hits). The new flow tries several
    strategies in order until one returns results:

      1. Best content words + best hashtag (e.g. "calico straycat")
      2. Top hashtags joined (e.g. "calico straycat")
      3. Page username + a content noun
      4. Page username alone
      5. Cleaned full caption (last-ditch)
    """
    queries: list[str] = []

    if not caption:
        if page_username:
            queries.append(page_username)
        queries.append("viral video")
        return queries

    # Pull hashtags and @mentions out so we can use them separately.
    hashtags = [
        h.lower()
        for h in re.findall(r"#(\w+)", caption)
        if h.lower() not in _NOISE_TOKENS
    ]
    mentions = [m.lower() for m in re.findall(r"@(\w+)", caption)]

    # Strip emojis, punctuation, mentions, and hashtags from the body text.
    body = re.sub(r"#\w+", " ", caption)
    body = re.sub(r"@\w+", " ", body)
    body = re.sub(r"[^\w\s'-]", " ", body)
    body = re.sub(r"\s+", " ", body).strip()

    # Score body words: keep short content nouns, drop stopwords + noise.
    words = []
    for w in body.split():
        wl = w.lower().strip("'-")
        if not wl or len(wl) < 3:
            continue
        if wl in _STOPWORDS or wl in _NOISE_TOKENS:
            continue
        if wl.isdigit():
            continue
        words.append(wl)

    top_words = words[:6]
    top_tags = hashtags[:3]

    # Strategy 1: combine the best 1-2 hashtags with the best body words.
    if top_tags and top_words:
        q1 = " ".join(top_tags[:2] + top_words[:3])
        queries.append(q1)

    # Strategy 2: just the meaningful hashtags, joined.
    if top_tags:
        queries.append(" ".join(top_tags))

    # Strategy 3: page username + a couple of content words.
    if page_username and top_words:
        queries.append(f"{page_username} {' '.join(top_words[:2])}")

    # Strategy 4: just the body words (no tags).
    if top_words:
        queries.append(" ".join(top_words[:4]))

    # Strategy 5: page username alone (last resort).
    if page_username:
        queries.append(page_username)

    # Strategy 6: cleaned-up full caption, capped.
    cleaned_full = (body or caption)[:80].rsplit(" ", 1)[0] if body else caption[:80]
    if cleaned_full and cleaned_full not in queries:
        queries.append(cleaned_full)

    # Dedupe while preserving order, drop empties.
    seen: set[str] = set()
    final: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            final.append(q)

    return final or ["viral video"]


def _search_youtube_via_ytdlp(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube using yt-dlp's built-in search. No API key needed."""
    results = []
    try:
        cmd = [
            "yt-dlp",
            f"ytsearch{max_results}:{query}",
            "--dump-json",
            "--no-download",
            "--flat-playlist",
            "--socket-timeout", "15",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if proc.returncode != 0:
            logger.warning("yt-dlp YouTube search failed: %s", proc.stderr[:200])
            return []

        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                vid_id = info.get("id", "")
                title = info.get("title", "")
                duration = info.get("duration") or 0
                url = info.get("url") or info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"

                if not vid_id:
                    continue

                results.append({
                    "source_type": "youtube",
                    "source_url": url,
                    "source_title": title,
                    "source_thumbnail_url": info.get("thumbnail"),
                    "resolution": None,
                    "fps": None,
                    "duration": duration,
                })
            except json.JSONDecodeError:
                continue

    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp YouTube search timed out")
    except Exception as e:
        logger.error("yt-dlp YouTube search error: %s", e)

    return results


def _search_youtube_shorts_via_ytdlp(query: str, max_results: int = 3) -> list[dict]:
    """Search YouTube Shorts specifically."""
    return _search_youtube_via_ytdlp(f"{query} #shorts", max_results)


def _calculate_match_confidence(
    original_caption: str,
    original_duration: float,
    candidate_title: str,
    candidate_duration: float,
) -> float:
    """Calculate how likely this is the same or very similar video."""
    score = 0.0

    # Title/caption word overlap
    if original_caption and candidate_title:
        orig_words = set(re.findall(r"\w+", original_caption.lower()))
        cand_words = set(re.findall(r"\w+", candidate_title.lower()))
        if orig_words and cand_words:
            overlap = len(orig_words & cand_words) / max(len(orig_words), 1)
            score += overlap * 0.5  # Up to 0.5 from text match

    # Duration similarity
    if original_duration and candidate_duration and original_duration > 0:
        dur_diff = abs(original_duration - candidate_duration)
        if dur_diff <= 3:
            score += 0.3  # Very close duration
        elif dur_diff <= 10:
            score += 0.2
        elif dur_diff <= 30:
            score += 0.1

    # Base score for being found via keyword search
    score += 0.2

    return min(score, 1.0)


@app.task(name="tasks.source_search.search_source", bind=True, max_retries=2)
def search_source(self, reel_id: str):
    """Search for alternative sources of a viral reel on YouTube and other platforms."""
    logger.info("Starting source search for reel %s", reel_id)

    try:
        with get_session() as session:
            row = session.execute(text("""
                SELECT v.caption, v.duration_seconds, v.ig_url, v.ig_video_id,
                       p.username
                FROM viral_reels v
                JOIN theme_pages p ON p.id = v.theme_page_id
                WHERE v.id = :vid
            """), {"vid": reel_id}).fetchone()

            if not row:
                logger.error("Reel %s not found", reel_id)
                return {"error": "Reel not found"}

            caption, duration, ig_url, ig_vid_id, username = (
                row.caption, row.duration_seconds, row.ig_url,
                row.ig_video_id, row.username,
            )

            job_id = str(uuid.uuid4())
            session.execute(text("""
                INSERT INTO jobs (id, celery_task_id, job_type, status, started_at, reference_id, reference_type)
                VALUES (:id, :task_id, 'search_source', 'running', :now, :ref_id, 'viral_reel')
            """), {
                "id": job_id, "task_id": self.request.id or "",
                "now": datetime.now(timezone.utc), "ref_id": reel_id,
            })

        # Build a *prioritised list* of search query candidates, then walk
        # them until one returns hits. The old single-string approach gave
        # up after the literal caption produced 0 results.
        query_candidates = _extract_keywords(caption, username)
        logger.info("Source search candidates for %s: %s", reel_id, query_candidates)

        all_results: list[dict] = []
        seen_urls: set[str] = set()
        winning_query: str | None = None

        for query in query_candidates:
            yt_results = _search_youtube_via_ytdlp(query, max_results=5)
            yt_shorts = _search_youtube_shorts_via_ytdlp(query, max_results=3)
            batch = yt_results + yt_shorts
            for r in batch:
                if r["source_url"] not in seen_urls:
                    all_results.append(r)
                    seen_urls.add(r["source_url"])
            if all_results:
                winning_query = query
                logger.info(
                    "  query '%s' produced %d results — stopping cascade",
                    query, len(all_results),
                )
                break
            logger.info("  query '%s' returned 0 — trying next strategy", query)

        logger.info("Found %d total results for reel %s (winning query=%s)", len(all_results), reel_id, winning_query)

        # Calculate match confidence and store results
        with get_session() as session:
            stored_count = 0
            for result in all_results:
                confidence = _calculate_match_confidence(
                    caption or "",
                    duration or 0,
                    result.get("source_title", ""),
                    result.get("duration", 0),
                )

                session.execute(text("""
                    INSERT INTO video_sources (id, viral_reel_id, source_type, source_url,
                        source_title, source_thumbnail_url, resolution,
                        match_confidence, is_selected, found_at)
                    VALUES (:id, :vid, :type, :url, :title, :thumb, :res,
                        :conf, false, :now)
                """), {
                    "id": str(uuid.uuid4()),
                    "vid": reel_id,
                    "type": result["source_type"],
                    "url": result["source_url"],
                    "title": result.get("source_title"),
                    "thumb": result.get("source_thumbnail_url"),
                    "res": result.get("resolution"),
                    "conf": round(confidence, 3),
                    "now": datetime.now(timezone.utc),
                })
                stored_count += 1

            # Update video status
            new_status = "source_found" if stored_count > 0 else "failed"
            error_msg = None if stored_count > 0 else "No alternative sources found on YouTube"

            session.execute(text("""
                UPDATE viral_reels SET status = :status, error_message = :err WHERE id = :vid
            """), {"status": new_status, "err": error_msg, "vid": reel_id})

            # Update job
            session.execute(text("""
                UPDATE jobs SET status = 'success', finished_at = :now, attempts = attempts + 1
                WHERE id = :id
            """), {"now": datetime.now(timezone.utc), "id": job_id})

        return {
            "reel_id": reel_id,
            "sources_found": stored_count,
            "winning_query": winning_query,
            "queries_tried": len(query_candidates),
        }

    except Exception as exc:
        logger.error("Source search failed for %s: %s", reel_id, exc, exc_info=True)
        try:
            with get_session() as session:
                session.execute(text("""
                    UPDATE viral_reels SET status = 'failed', error_message = :err WHERE id = :vid
                """), {"err": str(exc)[:500], "vid": reel_id})
                session.execute(text("""
                    UPDATE jobs SET status = 'failed', finished_at = :now, attempts = attempts + 1
                    WHERE reference_id = :rid AND reference_type = 'viral_reel'
                      AND job_type = 'search_source' AND status = 'running'
                """), {"now": datetime.now(timezone.utc), "rid": reel_id})
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)
