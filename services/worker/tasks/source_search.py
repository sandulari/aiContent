"""
Source search task: find the EXACT same video on YouTube/TikTok.

Instagram reels are often reposted from YouTube/TikTok. We find the original
by searching with multiple query strategies and scoring candidates by
duration match (strongest signal) + text similarity.
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

# ---------------------------------------------------------------------------
# Noise / stop-word sets
# ---------------------------------------------------------------------------

_NOISE_TOKENS = {
    "9gag", "fyp", "foryou", "foryoupage", "viral", "viralvideo",
    "reels", "reel", "instagram", "ig", "explore", "trending",
    "follow", "like", "share", "comment", "subscribe",
    "tiktok", "instareels", "instagood", "explorepage", "repost",
    "motivationquotes", "motivational", "viralreels", "dailymotivation",
    "inspirationalquotes", "fyppage", "fypp", "viralpost", "instadaily",
    "instavideo", "reelsinstagram", "reelsvideo", "trendingreels",
    "explorepage", "likeforlikes", "followforfollowback", "likes",
    "followme", "followback", "likesforlike", "commentbelow",
    "doubleclick", "tagafriend", "sharethis", "savepost",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "by", "for",
    "with", "from", "as", "this", "that", "these", "those", "it", "its",
    "if", "then", "than", "so", "i", "you", "he", "she", "they", "we",
    "my", "your", "his", "her", "their", "our", "me", "him", "us", "them",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "shall", "may", "might", "just", "via", "amp",
    "not", "no", "yes", "all", "any", "some", "every", "each", "more",
    "most", "other", "about", "into", "over", "after", "before", "when",
    "where", "how", "what", "who", "which", "why", "because", "also",
    "very", "much", "many", "such", "only", "even", "still", "already",
    "here", "there", "now", "get", "got", "make", "made", "take", "took",
    "come", "came", "going", "goes", "know", "knew", "think", "thought",
    "want", "need", "look", "see", "saw", "way", "well", "back",
    "never", "always", "really", "right", "one", "two", "new", "old",
    "first", "last", "long", "great", "little", "own", "good", "big",
    "high", "small", "large", "next", "early", "young", "same", "able",
    "best", "must", "let", "keep", "too", "don", "doesn", "didn",
    "won", "isn", "aren", "wasn", "weren", "hasn", "haven", "hadn",
    "couldn", "wouldn", "shouldn", "ain",
}

# Confidence threshold — stop searching once we find a candidate this good
_HIGH_CONFIDENCE_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------


def _build_search_queries(caption: str, duration: float, page_username: str) -> list[str]:
    """Build multiple search queries from most specific to least.

    Returns up to ~6 distinct queries ordered by expected precision.
    """
    queries: list[str] = []

    if not caption:
        return [page_username] if page_username else []

    # Clean caption: strip hashtags, mentions, emojis, special chars
    clean = re.sub(r"#\w+", "", caption)
    clean = re.sub(r"@\w+", "", clean)
    clean = re.sub(r"[^\w\s'\".,!?-]", "", clean)  # Remove emojis / specials
    clean = re.sub(r"\s+", " ", clean).strip()

    # Split into sentences
    sentences = re.split(r"[.!?\n]+", clean)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

    # Strategy 1: Most unique/longest sentence as exact-phrase search.
    # Exact phrases are the single best way to find a specific video.
    if sentences:
        best = max(sentences, key=len)
        if len(best) > 20:
            queries.append(f'"{best[:80]}"')

    # Strategy 2: First meaningful sentence (unquoted, broader match)
    if sentences:
        first = sentences[0][:60]
        queries.append(first)

    # Strategy 3: Named entities + first sentence fragment.
    # Capitalized multi-word tokens are likely person/brand names.
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", caption)
    names = [n for n in names if len(n) > 3 and n.lower() not in _STOPWORDS]
    if names and sentences:
        queries.append(f"{names[0]} {sentences[0][:40]}")

    # Build a shared pool of distinctive content words
    words: list[str] = []
    for w in clean.split():
        wl = w.lower().strip(".,!?'\"")
        if len(wl) > 4 and wl not in _STOPWORDS and wl not in _NOISE_TOKENS:
            words.append(wl)

    # Strategy 4: Top distinctive nouns
    if words:
        queries.append(" ".join(words[:6]))

    # Strategy 5: Short version for YouTube Shorts
    if words:
        queries.append(f"{' '.join(words[:4])} #shorts")

    # Strategy 6: Page username + key words (the IG poster may be the uploader)
    if page_username and words:
        queries.append(f"{page_username} {' '.join(words[:3])}")

    # Dedupe while preserving order
    seen: set[str] = set()
    final: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            final.append(q)

    return final or ([page_username] if page_username else [])


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _duration_match_score(ig_duration: float, yt_duration: float) -> float:
    """Score 0-1 based on how close the durations are.

    Duration is the strongest signal we have: if two videos are within
    +/-2 seconds they are almost certainly the same content.
    """
    if not ig_duration or not yt_duration:
        return 0.3  # Unknown — neutral bias

    diff = abs(ig_duration - yt_duration)
    if diff <= 2:
        return 1.0   # Almost certainly the same video
    elif diff <= 5:
        return 0.8   # Very likely
    elif diff <= 10:
        return 0.5   # Possible (slightly different cut)
    elif diff <= 30:
        return 0.2   # Unlikely but worth checking
    else:
        return 0.0   # Different video


def _text_similarity(text1: str, text2: str) -> float:
    """Word-overlap ratio between two texts.

    Uses set intersection over the smaller set so that a short YouTube title
    matching several words of a long Instagram caption still scores high.
    """
    if not text1 or not text2:
        return 0.0

    def _meaningful_words(t: str) -> set[str]:
        return {
            w.lower()
            for w in re.findall(r"\w+", t)
            if len(w) > 3 and w.lower() not in _STOPWORDS and w.lower() not in _NOISE_TOKENS
        }

    words1 = _meaningful_words(text1)
    words2 = _meaningful_words(text2)
    if not words1 or not words2:
        return 0.0

    overlap = len(words1 & words2)
    return overlap / min(len(words1), len(words2))


def _calculate_match_confidence(
    ig_caption: str,
    ig_duration: float,
    yt_title: str,
    yt_duration: float,
) -> float:
    """Combined confidence that the YouTube result is the same video.

    Weights: duration 60%, text 40%.
    Duration is the killer signal — two videos with the exact same length
    from a keyword search are almost certainly the same content.
    """
    duration_score = _duration_match_score(ig_duration, yt_duration)
    text_score = _text_similarity(ig_caption, yt_title)

    confidence = duration_score * 0.6 + text_score * 0.4
    return round(confidence, 2)


# ---------------------------------------------------------------------------
# yt-dlp search
# ---------------------------------------------------------------------------


def _search_youtube_via_http(query: str, max_results: int = 8) -> list[dict]:
    """Search YouTube via HTTP scraping — works even when yt-dlp is bot-blocked."""
    import urllib.parse
    import httpx

    results: list[dict] = []
    try:
        encoded = urllib.parse.quote_plus(query)
        resp = httpx.get(
            f"https://www.youtube.com/results?search_query={encoded}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("YouTube HTTP search failed: %d", resp.status_code)
            return []

        # Extract video IDs and titles from the page
        video_ids = list(dict.fromkeys(re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', resp.text)))[:max_results]

        # Extract titles — they appear in the JSON data embedded in the page
        titles = {}
        for match in re.finditer(r'"videoId":"([^"]+)".*?"text":"([^"]{5,100})"', resp.text):
            vid_id, title = match.group(1), match.group(2)
            if vid_id not in titles:
                titles[vid_id] = title

        # Get duration for each video using yt-dlp (just metadata, no download)
        for vid_id in video_ids:
            url = f"https://www.youtube.com/watch?v={vid_id}"
            title = titles.get(vid_id, "")
            duration = 0

            # Try to get duration via yt-dlp metadata
            try:
                cmd = ["yt-dlp", "--dump-json", "--no-download", "--socket-timeout", "10", url]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if proc.returncode == 0 and proc.stdout.strip():
                    info = json.loads(proc.stdout.strip().split("\n")[0])
                    duration = info.get("duration") or 0
                    if not title:
                        title = info.get("title", "")
            except Exception:
                pass

            results.append({
                "source_type": "youtube",
                "source_url": url,
                "source_title": title,
                "source_thumbnail_url": f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                "resolution": None,
                "fps": None,
                "duration": duration,
            })

    except Exception as e:
        logger.error("YouTube HTTP search error: %s", e)

    return results


def _search_youtube_via_ytdlp(query: str, max_results: int = 8) -> list[dict]:
    """Search YouTube using yt-dlp's built-in search.

    Uses --dump-json WITHOUT --flat-playlist so we get full metadata
    including accurate duration for each result.
    Falls back to HTTP scraping if yt-dlp is bot-blocked.
    """
    results: list[dict] = []
    try:
        cmd = [
            "yt-dlp",
            f"ytsearch{max_results}:{query}",
            "--dump-json",
            "--no-download",
            "--socket-timeout", "15",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

        if proc.returncode != 0:
            logger.warning("yt-dlp YouTube search blocked, falling back to HTTP: %s", proc.stderr[:200])
            return _search_youtube_via_http(query, max_results)

        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                vid_id = info.get("id", "")
                title = info.get("title", "")
                duration = info.get("duration") or 0
                url = (
                    info.get("webpage_url")
                    or info.get("url")
                    or f"https://www.youtube.com/watch?v={vid_id}"
                )

                if not vid_id:
                    continue

                results.append({
                    "source_type": "youtube",
                    "source_url": url,
                    "source_title": title,
                    "source_thumbnail_url": info.get("thumbnail"),
                    "resolution": info.get("resolution"),
                    "fps": info.get("fps"),
                    "duration": duration,
                })
            except json.JSONDecodeError:
                continue

    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp YouTube search timed out for query '%s'", query)
    except Exception as e:
        logger.error("yt-dlp YouTube search error for query '%s': %s", query, e)

    return results


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(name="tasks.source_search.search_source", bind=True, max_retries=2)
def search_source(self, reel_id: str):
    """Search for the exact same video on YouTube/TikTok.

    Flow:
      1. Load reel data (caption, duration, page username)
      2. Build multiple targeted search queries
      3. For each query, search YouTube (8 results per query)
      4. Score ALL results by duration match + text similarity
      5. Stop early if any result scores above the high-confidence threshold
      6. Insert top 6 results as video_sources, sorted by confidence
      7. Update reel status
    """
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

            caption = row.caption or ""
            duration = row.duration_seconds or 0
            ig_url = row.ig_url
            ig_vid_id = row.ig_video_id
            username = row.username or ""

            # Create job record
            job_id = str(uuid.uuid4())
            session.execute(text("""
                INSERT INTO jobs (id, celery_task_id, job_type, status, started_at, reference_id, reference_type)
                VALUES (:id, :task_id, 'search_source', 'running', :now, :ref_id, 'viral_reel')
            """), {
                "id": job_id, "task_id": self.request.id or "",
                "now": datetime.now(timezone.utc), "ref_id": reel_id,
            })

        # ----- Build queries and search -----
        query_candidates = _build_search_queries(caption, duration, username)
        logger.info(
            "Source search for reel %s — %d query candidates: %s",
            reel_id, len(query_candidates), query_candidates,
        )

        all_candidates: list[dict] = []
        seen_urls: set[str] = set()
        queries_tried = 0
        winning_query: str | None = None
        early_stop = False

        for query in query_candidates:
            queries_tried += 1
            results = _search_youtube_via_ytdlp(query, max_results=8)

            if not results:
                logger.info("  query '%s' returned 0 results — next", query)
                continue

            # Score each result
            batch_best_confidence = 0.0
            for r in results:
                if r["source_url"] in seen_urls:
                    continue
                seen_urls.add(r["source_url"])

                confidence = _calculate_match_confidence(
                    caption, duration,
                    r.get("source_title", ""), r.get("duration", 0),
                )
                r["match_confidence"] = confidence
                all_candidates.append(r)

                if confidence > batch_best_confidence:
                    batch_best_confidence = confidence

            logger.info(
                "  query '%s' → %d new results, best confidence=%.2f",
                query, len(results), batch_best_confidence,
            )

            # Early stop: we found a very high-confidence match
            if batch_best_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
                winning_query = query
                early_stop = True
                logger.info(
                    "  HIGH-CONFIDENCE match found (%.2f) — stopping search",
                    batch_best_confidence,
                )
                break

        if not early_stop and all_candidates:
            winning_query = query_candidates[0]

        # Sort by confidence descending, keep top 6
        all_candidates.sort(key=lambda c: c["match_confidence"], reverse=True)
        top_candidates = all_candidates[:6]

        logger.info(
            "Source search for reel %s complete: %d total candidates, "
            "keeping top %d, queries_tried=%d, winning_query='%s'",
            reel_id, len(all_candidates), len(top_candidates),
            queries_tried, winning_query,
        )
        if top_candidates:
            logger.info(
                "  Best match: confidence=%.2f title='%s' duration=%s url=%s",
                top_candidates[0]["match_confidence"],
                top_candidates[0].get("source_title", "")[:80],
                top_candidates[0].get("duration"),
                top_candidates[0].get("source_url"),
            )

        # ----- Store results -----
        with get_session() as session:
            stored_count = 0
            for result in top_candidates:
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
                    "conf": result["match_confidence"],
                    "now": datetime.now(timezone.utc),
                })
                stored_count += 1

            # Update reel status
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
            "queries_tried": queries_tried,
            "early_stop": early_stop,
            "best_confidence": top_candidates[0]["match_confidence"] if top_candidates else 0,
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
