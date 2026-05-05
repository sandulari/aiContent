"""Deep discovery pipeline — human-mimicking content discovery.

Full pipeline triggered after onboarding:
  1. Seed expansion — reference pages → suggested accounts + follows
  2. Second-degree scan — discovered pages → THEIR suggested accounts
  3. Scrape reels from all discovered pages
  4. Per-reel Claude profiling — topic/format/hook/visual/audio
  5. Multi-dimensional matching — Claude profile + keywords + niche tags
  6. Virality filter — views + engagement + velocity
  7. Store 500+ ranked recommendations
"""
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib import claude_client

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "instagram-api-fast-reliable-data-scraper.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}"
RAPIDAPI_HEADERS = {
    "x-rapidapi-host": RAPIDAPI_HOST,
    "x-rapidapi-key": RAPIDAPI_KEY,
    "Content-Type": "application/json",
}

# Pipeline config
MAX_SEED_PAGES = 15           # Max pages to discover per reference page
MAX_SECOND_DEGREE = 8         # Max second-degree pages per seed
MAX_REELS_PER_PAGE = 20       # Reels to scrape per discovered page
MAX_TOTAL_PAGES = 60          # Total pages to process across all layers
MIN_VIEWS_THRESHOLD = 5000    # Min views for a reel to be worth profiling
PROFILE_BATCH_SIZE = 8        # Reels per Claude profiling batch
TARGET_RECS = 500             # Target recommendation count
MAX_RECS = 1000               # Absolute max
MAX_PER_SOURCE = 25           # Max reels from one source page
API_DELAY = 1.2               # Seconds between RapidAPI calls


# ── RapidAPI helpers (sync for Celery) ────────────────────────────────

def _rapid_get(path: str, params: dict, timeout: int = 15) -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        with httpx.Client(timeout=timeout, headers=RAPIDAPI_HEADERS) as client:
            r = client.get(f"{RAPIDAPI_BASE}{path}", params=params)
            if r.status_code == 429:
                logger.warning("RapidAPI 429 on %s, backing off", path)
                time.sleep(5)
                r = client.get(f"{RAPIDAPI_BASE}{path}", params=params)
            if r.status_code != 200:
                logger.warning("rapidapi %s -> %d", path, r.status_code)
                return None
            return r.json()
    except Exception as exc:
        logger.warning("rapidapi %s failed: %s", path, exc)
        return None


def _get_profile(username: str) -> dict | None:
    data = _rapid_get("/profile", {"username": username})
    if not data or not data.get("username"):
        return None
    return data


def _get_user_reels(user_pk: str | int, max_pages: int = 1) -> list[dict]:
    data = _rapid_get("/reels", {"user_id": str(user_pk)}, timeout=20)
    if not data:
        return []
    items = data.get("data", {}).get("items", [])
    out: list[dict] = []
    for item in items:
        media = item.get("media", item)
        code = media.get("code", "")
        if not code:
            continue
        thumb = ""
        iv = media.get("image_versions2", {})
        candidates = iv.get("candidates", []) if isinstance(iv, dict) else []
        if candidates:
            thumb = candidates[0].get("url", "")
        cap_obj = media.get("caption", {})
        caption = cap_obj.get("text", "") if isinstance(cap_obj, dict) else ""
        out.append({
            "shortcode": code,
            "url": f"https://www.instagram.com/reel/{code}/",
            "thumbnail_url": thumb,
            "view_count": media.get("play_count", 0) or media.get("view_count", 0) or 0,
            "like_count": media.get("like_count", 0) or 0,
            "comment_count": media.get("comment_count", 0) or 0,
            "duration_seconds": media.get("video_duration", 0) or 0,
            "caption": caption[:500],
            "taken_at": media.get("taken_at", 0),
        })
    return out


def _get_suggested(user_pk: str | int) -> list[dict]:
    data = _rapid_get("/discover_chaining", {"user_id": str(user_pk)})
    if not data:
        return []
    users = data.get("users", []) or data.get("data", [])
    return [
        {"username": u.get("username", ""), "pk": u.get("pk", ""),
         "full_name": u.get("full_name", ""),
         "follower_count": u.get("follower_count", 0)}
        for u in users if u.get("username")
    ]


def _get_following(user_pk: str | int) -> list[dict]:
    """Get accounts this user follows — another discovery signal."""
    data = _rapid_get("/following", {"user_id": str(user_pk), "count": "50"}, timeout=20)
    if not data:
        return []
    users = data.get("users", []) or data.get("data", [])
    return [
        {"username": u.get("username", ""), "pk": u.get("pk", ""),
         "full_name": u.get("full_name", ""),
         "follower_count": u.get("follower_count", 0)}
        for u in users if u.get("username")
    ]


# ── Core pipeline ─────────────────────────────────────────────────────

def _discover_pages_from_references(
    reference_usernames: list[str],
    existing_usernames: set[str],
) -> list[dict]:
    """Layer 1: Seed expansion from reference pages.

    For each reference page: get suggested accounts + following list.
    Returns list of candidate page dicts.
    """
    discovered: dict[str, dict] = {}  # username -> page info

    for ref_username in reference_usernames:
        profile = _get_profile(ref_username)
        if not profile:
            continue
        ref_pk = profile.get("pk") or profile.get("pk_id")
        if not ref_pk:
            continue

        # Suggested accounts (Instagram's own "Similar accounts")
        suggested = _get_suggested(ref_pk)
        time.sleep(API_DELAY)

        for s in suggested[:MAX_SEED_PAGES]:
            uname = s["username"]
            if uname in existing_usernames or uname in discovered:
                continue
            if uname in reference_usernames:
                continue
            discovered[uname] = {
                "username": uname,
                "pk": s.get("pk", ""),
                "full_name": s.get("full_name", ""),
                "follower_count": s.get("follower_count", 0),
                "discovered_via": f"suggested_from_{ref_username}",
                "degree": 1,
            }

        # Following list — another strong signal
        following = _get_following(ref_pk)
        time.sleep(API_DELAY)

        for f in following[:MAX_SEED_PAGES]:
            uname = f["username"]
            if uname in existing_usernames or uname in discovered:
                continue
            if uname in reference_usernames:
                continue
            # Only keep pages with decent following (likely content pages)
            if (f.get("follower_count") or 0) < 5000:
                continue
            discovered[uname] = {
                "username": uname,
                "pk": f.get("pk", ""),
                "full_name": f.get("full_name", ""),
                "follower_count": f.get("follower_count", 0),
                "discovered_via": f"following_of_{ref_username}",
                "degree": 1,
            }

        if len(discovered) >= MAX_TOTAL_PAGES:
            break

    logger.info("Layer 1 seed expansion: %d pages from %d references",
                len(discovered), len(reference_usernames))
    return list(discovered.values())


def _second_degree_scan(
    first_degree: list[dict],
    existing_usernames: set[str],
    reference_usernames: list[str],
) -> list[dict]:
    """Layer 2: Second-degree expansion.

    For top first-degree pages, get THEIR suggested accounts.
    """
    first_degree_usernames = {p["username"] for p in first_degree}
    second_degree: dict[str, dict] = {}

    # Sort by follower count to prioritize bigger accounts
    sorted_pages = sorted(first_degree, key=lambda x: x.get("follower_count", 0), reverse=True)

    for page in sorted_pages[:12]:  # Top 12 first-degree pages
        pk = page.get("pk")
        if not pk:
            profile = _get_profile(page["username"])
            if not profile:
                continue
            pk = profile.get("pk") or profile.get("pk_id")
            if not pk:
                continue

        suggested = _get_suggested(pk)
        time.sleep(API_DELAY)

        for s in suggested[:MAX_SECOND_DEGREE]:
            uname = s["username"]
            if (uname in existing_usernames or uname in first_degree_usernames
                    or uname in second_degree or uname in reference_usernames):
                continue
            if (s.get("follower_count") or 0) < 10000:
                continue
            second_degree[uname] = {
                "username": uname,
                "pk": s.get("pk", ""),
                "full_name": s.get("full_name", ""),
                "follower_count": s.get("follower_count", 0),
                "discovered_via": f"2nd_degree_from_{page['username']}",
                "degree": 2,
            }

        total = len(first_degree) + len(second_degree)
        if total >= MAX_TOTAL_PAGES:
            break

    logger.info("Layer 2 second-degree scan: %d pages from %d sources",
                len(second_degree), min(12, len(sorted_pages)))
    return list(second_degree.values())


def _scrape_and_store_reels(
    pages: list[dict],
    niche_id: str | None,
) -> list[dict]:
    """Scrape reels from discovered pages and store in viral_reels.

    Returns list of reel dicts with id, caption, view_count etc for profiling.
    """
    all_reels: list[dict] = []

    for page in pages:
        username = page["username"]
        pk = page.get("pk")

        if not pk:
            profile = _get_profile(username)
            if not profile:
                continue
            pk = profile.get("pk") or profile.get("pk_id")
            page["follower_count"] = profile.get("follower_count", 0)
            if not pk:
                continue

        # Ensure theme_page exists
        with get_session() as session:
            tp_row = session.execute(
                text("SELECT id FROM theme_pages WHERE username = :u"),
                {"u": username},
            ).fetchone()

            if tp_row:
                tp_id = str(tp_row.id)
            else:
                tp_id = str(uuid.uuid4())
                session.execute(
                    text("""
                        INSERT INTO theme_pages
                            (id, username, display_name, profile_url,
                             niche_id, follower_count, is_active,
                             evaluation_status, discovered_via)
                        VALUES (:id, :u, :name, :url, :nid, :fc, true,
                                'confirmed', :via)
                        ON CONFLICT (username) DO UPDATE SET
                            follower_count = EXCLUDED.follower_count,
                            is_active = true
                    """),
                    {
                        "id": tp_id,
                        "u": username,
                        "name": page.get("full_name", username),
                        "url": f"https://www.instagram.com/{username}/",
                        "nid": niche_id,
                        "fc": page.get("follower_count", 0),
                        "via": page.get("discovered_via", "deep_discovery"),
                    },
                )
                # Re-fetch in case ON CONFLICT updated existing
                tp_row2 = session.execute(
                    text("SELECT id FROM theme_pages WHERE username = :u"),
                    {"u": username},
                ).fetchone()
                if tp_row2:
                    tp_id = str(tp_row2.id)

        # Scrape reels
        reels = _get_user_reels(pk, max_pages=1)
        time.sleep(API_DELAY)

        page_reel_count = 0
        with get_session() as session:
            for reel in reels[:MAX_REELS_PER_PAGE]:
                code = reel["shortcode"]
                views = reel["view_count"]
                if views < MIN_VIEWS_THRESHOLD:
                    continue

                # Check if already exists
                exists = session.execute(
                    text("SELECT id FROM viral_reels WHERE ig_video_id = :v"),
                    {"v": code},
                ).fetchone()

                if exists:
                    reel_id = str(exists.id)
                    # Update view count if higher
                    session.execute(
                        text("""
                            UPDATE viral_reels
                            SET view_count = GREATEST(view_count, :views),
                                like_count = GREATEST(like_count, :likes),
                                thumbnail_url = COALESCE(NULLIF(:thumb, ''), thumbnail_url)
                            WHERE id = :id
                        """),
                        {"views": views, "likes": reel["like_count"],
                         "thumb": reel["thumbnail_url"], "id": reel_id},
                    )
                else:
                    reel_id = str(uuid.uuid4())
                    posted = (
                        datetime.utcfromtimestamp(reel["taken_at"])
                        if reel["taken_at"]
                        else datetime.utcnow()
                    )
                    session.execute(
                        text("""
                            INSERT INTO viral_reels (
                                id, theme_page_id, ig_video_id, ig_url,
                                thumbnail_url, view_count, like_count,
                                comment_count, duration_seconds, caption,
                                posted_at, niche_id, status
                            )
                            VALUES (:id, :pid, :vid, :url, :thumb,
                                :views, :likes, :comments, :dur, :cap,
                                :posted, :nid, 'discovered')
                            ON CONFLICT (ig_video_id) DO NOTHING
                        """),
                        {
                            "id": reel_id, "pid": tp_id, "vid": code,
                            "url": reel["url"], "thumb": reel["thumbnail_url"],
                            "views": views, "likes": reel["like_count"],
                            "comments": reel["comment_count"],
                            "dur": reel["duration_seconds"],
                            "cap": reel["caption"], "posted": posted,
                            "nid": niche_id,
                        },
                    )

                all_reels.append({
                    "id": reel_id,
                    "caption": reel["caption"],
                    "view_count": views,
                    "like_count": reel["like_count"],
                    "comment_count": reel["comment_count"],
                    "duration_seconds": reel["duration_seconds"],
                    "source_username": username,
                    "theme_page_id": tp_id,
                    "posted_at": reel.get("taken_at"),
                })
                page_reel_count += 1

        logger.info("  @%s: %d qualifying reels", username, page_reel_count)

    logger.info("Total reels scraped: %d from %d pages", len(all_reels), len(pages))
    return all_reels


def _profile_reels_with_claude(reels: list[dict]) -> int:
    """Run Claude profiling on reels and store in reel_profiles table.

    Returns count of reels profiled.
    """
    if not claude_client.is_enabled():
        logger.info("Claude not enabled, skipping reel profiling")
        return 0

    # Filter out already-profiled reels
    reel_ids = [r["id"] for r in reels]
    already_profiled: set[str] = set()
    with get_session() as session:
        if reel_ids:
            # Check in batches to avoid query size limits
            for i in range(0, len(reel_ids), 100):
                batch_ids = reel_ids[i:i + 100]
                # Hand psycopg2 uuid.UUID objects (not strings) so the list
                # round-trips as uuid[]. SQLAlchemy's text() compiler also
                # mishandles the `::uuid[]` cast (it sees `:uuid` as a
                # second bind param), so we skip the SQL cast entirely.
                from uuid import UUID
                uuid_batch = [UUID(s) if isinstance(s, str) else s for s in batch_ids]
                rows = session.execute(
                    text("""
                        SELECT viral_reel_id::text FROM reel_profiles
                        WHERE viral_reel_id = ANY(:ids)
                    """),
                    {"ids": uuid_batch},
                ).fetchall()
                already_profiled.update(str(r.viral_reel_id) for r in rows)

    to_profile = [r for r in reels if r["id"] not in already_profiled]
    logger.info("Profiling %d reels (%d already done)", len(to_profile), len(already_profiled))

    if not to_profile:
        return 0

    # Batch profile via Claude
    profiles = claude_client.profile_reels_batch(to_profile, batch_size=PROFILE_BATCH_SIZE)
    logger.info("Claude returned profiles for %d/%d reels", len(profiles), len(to_profile))

    # Store profiles
    stored = 0
    with get_session() as session:
        for reel in to_profile:
            profile = profiles.get(reel["id"])
            if not profile:
                continue
            try:
                session.execute(
                    text("""
                        INSERT INTO reel_profiles (
                            id, viral_reel_id, topic, format,
                            hook_pattern, visual_style, audio_type,
                            content_summary, niche_tags, confidence,
                            analyzed_at
                        )
                        VALUES (:id, :rid, :topic, :format,
                            :hook, :visual, :audio,
                            :summary, :tags, :conf, :now)
                        ON CONFLICT (viral_reel_id) DO UPDATE SET
                            topic = EXCLUDED.topic,
                            format = EXCLUDED.format,
                            hook_pattern = EXCLUDED.hook_pattern,
                            visual_style = EXCLUDED.visual_style,
                            audio_type = EXCLUDED.audio_type,
                            content_summary = EXCLUDED.content_summary,
                            niche_tags = EXCLUDED.niche_tags,
                            analyzed_at = EXCLUDED.analyzed_at
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "rid": reel["id"],
                        "topic": (profile.get("topic") or "general")[:200],
                        "format": (profile.get("format") or "entertainment")[:50],
                        "hook": (profile.get("hook_pattern") or "")[:50],
                        "visual": (profile.get("visual_style") or "")[:50],
                        "audio": (profile.get("audio_type") or "")[:50],
                        "summary": (profile.get("content_summary") or "")[:300],
                        "tags": profile.get("niche_tags", []),
                        "conf": 0.8,
                        "now": datetime.now(timezone.utc),
                    },
                )
                stored += 1
            except Exception as e:
                logger.warning("Failed to store profile for reel %s: %s", reel["id"], e)

    logger.info("Stored %d reel profiles", stored)
    return stored


# ---------------------------------------------------------------------------
# Downloadability gate
# ---------------------------------------------------------------------------

# Reels probed earlier than this many days ago are trusted; older results
# get re-probed because YouTube takedowns / regional unavailability shift
# over time.
_DOWNLOADABILITY_RECHECK_DAYS = 7

# Cap how many top candidates we probe per discovery run. Beauty/IG-
# native niches have a low cross-platform match rate (~13% on test
# data), so we need to probe widely to surface enough downloadable
# reels for the UI. 250 covers most users' final_recs after page
# diversification; cron jobs that build 500-row recs lists are still
# bounded.
_DOWNLOADABILITY_PROBE_TOP_N = 250

# Parallelism for the YouTube probe. Each probe does one HTTP request,
# so 12 concurrent stays well under YouTube's per-IP rate limit and
# finishes 250 reels in ~40s with two-query lookups.
_DOWNLOADABILITY_PROBE_WORKERS = 12


def _filter_to_downloadable(
    recs: list[tuple[float, Any]],
    session,
) -> list[tuple[float, Any]]:
    """Drop recommendations whose source video can't be found anywhere.

    The biggest UX bug in the previous version: recommendations surfaced
    reels that, when clicked, had no downloadable source on YouTube /
    TikTok. Repurpose.io's killer feature is precisely this gate — if we
    can't pull it, never show it. Now caches the result on viral_reels so
    a second discovery run for the same content costs zero HTTP calls.
    """
    if not recs:
        return recs

    # Step 1: load cached probe state for every candidate.
    reel_ids = [str(r[1].id) for r in recs]
    state_rows = session.execute(
        text(
            """
            SELECT id::text AS id, is_downloadable, source_check_at
            FROM viral_reels
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": [uuid.UUID(rid) for rid in reel_ids]},
    ).fetchall()
    state: dict[str, tuple[bool | None, datetime | None]] = {
        r.id: (r.is_downloadable, r.source_check_at) for r in state_rows
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=_DOWNLOADABILITY_RECHECK_DAYS)

    # Step 2: split into "use cached state" vs "needs re-probe". Only the
    # top N by score get probed if uncached; the long tail is ignored
    # because it almost certainly won't appear in the user's view anyway.
    top_recs = recs[:_DOWNLOADABILITY_PROBE_TOP_N]
    to_probe: list[Any] = []
    for _, reel in top_recs:
        rid = str(reel.id)
        is_dl, checked_at = state.get(rid, (None, None))
        if is_dl is True and checked_at and checked_at >= cutoff:
            continue  # Cached as downloadable, fresh enough.
        if is_dl is False and checked_at and checked_at >= cutoff:
            continue  # Cached as undownloadable, fresh enough — skip probe.
        to_probe.append(reel)

    # Step 3: probe in parallel. Late import — the worker that runs
    # deep_discovery may not load source_search at module import time.
    from tasks.source_search import quick_downloadability_probe

    probe_results: dict[str, bool] = {}
    if to_probe:
        with ThreadPoolExecutor(max_workers=_DOWNLOADABILITY_PROBE_WORKERS) as pool:
            futures = {
                pool.submit(
                    quick_downloadability_probe,
                    getattr(reel, "caption", "") or "",
                    float(getattr(reel, "duration_seconds", 0) or 0),
                    getattr(reel, "source_username", "") or "",
                ): str(reel.id)
                for reel in to_probe
            }
            # 120s ceiling for the whole batch — 100 reels × 2s / 8 workers
            # = ~25s typical, with wide margin for slow YouTube responses.
            for fut in as_completed(futures, timeout=120):
                rid = futures[fut]
                try:
                    probe_results[rid] = bool(fut.result())
                except Exception as exc:
                    logger.warning("Downloadability probe failed for %s: %s", rid, exc)
                    probe_results[rid] = False

        # Persist probe results so the next discovery run reuses them.
        now = datetime.now(timezone.utc)
        for rid, is_dl in probe_results.items():
            session.execute(
                text(
                    """
                    UPDATE viral_reels
                    SET is_downloadable = :dl, source_check_at = :now
                    WHERE id = :id
                    """
                ),
                {"dl": is_dl, "now": now, "id": uuid.UUID(rid)},
            )

    # Step 4: assemble the allowed set — anything probed True OR cached
    # True from earlier runs.
    allowed: set[str] = set()
    for _, reel in recs:
        rid = str(reel.id)
        if rid in probe_results:
            if probe_results[rid]:
                allowed.add(rid)
        else:
            cached_dl, _ = state.get(rid, (None, None))
            if cached_dl:
                allowed.add(rid)

    filtered = [(s, r) for (s, r) in recs if str(r.id) in allowed]
    logger.info(
        "Downloadability gate: %d candidates → %d kept (probed=%d, cached=%d)",
        len(recs),
        len(filtered),
        len(to_probe),
        len(recs) - len(to_probe),
    )
    return filtered


def _claude_review_pass(
    final_recs: list[tuple[float, Any]],
    user_niche_tags: list[str],
    reference_profiles: list[dict],
) -> tuple[list[tuple[float, Any]], dict[str, dict]]:
    """Run Claude Haiku as a "thoughtful brand strategist" over top candidates.

    The 5-axis score gets us 80% of the way there; this pass catches the
    edge cases the math misses (a quote-on-music video that has the right
    keywords but obviously wrong format; a reel from an adjacent niche
    that scores high but feels off-brand).

    Drops anything with score < 6/10. Returns the filtered list AND a
    map from reel_id → {claude_score, claude_reason} so the caller can
    persist Claude's reasoning into match_reason / match_score.

    On total Claude API outage, returns final_recs unchanged + empty map
    — caller falls back to score-only ranking.
    """
    if not final_recs:
        return final_recs, {}

    # Late import — keeps deep_discovery importable even if claude_client
    # has a transient issue.
    from lib.claude_client import review_reel_match, is_enabled as claude_is_enabled

    if not claude_is_enabled():
        logger.info("Claude reviewer pass skipped (CLAUDE_API_KEY not configured)")
        return final_recs, {}

    # Cap the reviewer to the top 50 — anything below that won't appear
    # in the user's first scroll anyway, and Claude calls cost money.
    top = final_recs[:50]
    rest = final_recs[50:]

    # Build the brand profile once.
    primary_niche = ""
    if reference_profiles:
        primary_niche = reference_profiles[0].get("niche_primary", "") or ""
    if not primary_niche and user_niche_tags:
        primary_niche = user_niche_tags[0]

    ref_descriptors: list[str] = []
    for prof in reference_profiles[:5]:
        np_ = prof.get("niche_primary", "") or "?"
        topics = prof.get("top_topics") or []
        topic_str = ", ".join(topics[:3]) if isinstance(topics, list) else ""
        ref_descriptors.append(f"{np_} ({topic_str})" if topic_str else np_)

    brand_profile = {
        "niche": primary_niche or "general creator",
        "niche_tags": list(user_niche_tags)[:8],
        "reference_pages": ref_descriptors,
    }

    # Fan out — Haiku is fast, but 50 sequential calls would still be ~75s.
    # 8 in parallel keeps wall-time under ~12s.
    review_map: dict[str, dict] = {}

    def _review_one(score_reel: tuple[float, Any]) -> tuple[str, dict | None]:
        _, reel = score_reel
        reel_payload = {
            "caption": getattr(reel, "caption", "") or "",
            "view_count": int(getattr(reel, "view_count", 0) or 0),
            "source_username": getattr(reel, "source_username", "") or "",
            "duration_seconds": int(getattr(reel, "duration_seconds", 0) or 0),
            "topic": getattr(reel, "topic", None),
        }
        try:
            return str(reel.id), review_reel_match(brand_profile, reel_payload)
        except Exception as exc:
            logger.warning("Claude reviewer failed for reel %s: %s", reel.id, exc)
            return str(reel.id), None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_review_one, sr) for sr in top]
        for fut in as_completed(futures, timeout=180):
            try:
                rid, review = fut.result()
            except Exception:
                continue
            if review is not None:
                review_map[rid] = review

    # If Claude reviewed nothing (total outage), fall back to score-only.
    if not review_map:
        logger.warning(
            "Claude reviewer pass returned zero results for %d candidates — "
            "falling back to score-only ranking",
            len(top),
        )
        return final_recs, {}

    # Filter top-50 by Claude's score; keep the long tail (rest) untouched
    # since it wasn't reviewed and we don't want to silently drop reels
    # just because they were below the reviewer cap.
    SCORE_FLOOR = 6
    filtered_top: list[tuple[float, Any]] = []
    dropped_low = 0
    for score, reel in top:
        rid = str(reel.id)
        review = review_map.get(rid)
        if review is None:
            # Reviewer call failed for this one — keep it (don't penalize
            # for our infra hiccup) but don't override its reason.
            filtered_top.append((score, reel))
            continue
        if review["score"] < SCORE_FLOOR:
            dropped_low += 1
            continue
        filtered_top.append((score, reel))

    logger.info(
        "Claude reviewer pass: %d top candidates → %d kept (%d below floor=%d, %d errored)",
        len(top),
        len(filtered_top),
        dropped_low,
        SCORE_FLOOR,
        len(top) - len(review_map),
    )

    return filtered_top + rest, review_map


def _build_enhanced_recommendations(
    user_page_id: str,
    user_niche_tags: list[str],
    reference_profiles: list[dict],
    target_recs: int = TARGET_RECS,
) -> dict:
    """Score and insert recommendations using both keyword matching and Claude profiles.

    Enhanced scoring axes:
      1. Caption relevance (0-0.30) — keyword overlap
      2. Topic match (0-0.20) — Claude profile topic vs user niche tags
      3. View performance (0-0.20) — log-scaled views
      4. Engagement (0-0.15) — likes+comments/views
      5. Freshness (0-0.15) — linear decay over 90 days
    """
    import math
    import re

    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
        "for", "of", "and", "or", "but", "not", "with", "this", "that", "it",
        "be", "have", "has", "do", "will", "can", "i", "you", "we", "they",
        "my", "your", "our", "follow", "like", "share", "comment", "dm",
        "link", "bio", "repost", "tag", "save", "click", "read", "caption",
        "reel", "reels", "instagram", "viral", "trending", "fyp",
    }

    def tokenise(t: str) -> set[str]:
        if not t:
            return set()
        cleaned = re.sub(r"@\w+", " ", t)
        cleaned = re.sub(r"#(\w+)", r"\1", cleaned)
        cleaned = re.sub(r"[^\w\s]", " ", cleaned.lower())
        return {w for w in cleaned.split() if len(w) > 3 and w not in STOP_WORDS}

    # Build keyword signature from niche tags + reference profiles
    keywords: set[str] = set()
    for tag in user_niche_tags:
        keywords.update(tokenise(tag))
    for prof in reference_profiles:
        topics = prof.get("top_topics") or []
        if isinstance(topics, list):
            for t in topics:
                if isinstance(t, str):
                    keywords.update(tokenise(t))
        niche = prof.get("niche_primary", "")
        if niche:
            keywords.update(tokenise(niche))
        sig = prof.get("keyword_signature") or []
        if isinstance(sig, list):
            for s in sig:
                if isinstance(s, str) and len(s) > 3:
                    keywords.add(s.lower())

    # Normalize niche tags for topic matching
    niche_tag_tokens = set()
    for tag in user_niche_tags:
        niche_tag_tokens.update(tokenise(tag))

    with get_session() as session:
        # Clear old recommendations
        session.execute(
            text("DELETE FROM user_reel_recommendations WHERE user_page_id = :pid"),
            {"pid": user_page_id},
        )

        # Load candidate reels with their profiles
        rows = session.execute(
            text("""
                SELECT vr.id, vr.caption, vr.view_count, vr.like_count,
                       vr.comment_count, vr.posted_at, vr.theme_page_id,
                       vr.duration_seconds,
                       rp.topic, rp.format, rp.hook_pattern, rp.niche_tags as profile_tags,
                       tp.username as source_username
                FROM viral_reels vr
                LEFT JOIN reel_profiles rp ON rp.viral_reel_id = vr.id
                LEFT JOIN theme_pages tp ON tp.id = vr.theme_page_id
                WHERE vr.view_count >= 5000
                ORDER BY vr.view_count DESC
                LIMIT 5000
            """),
        ).fetchall()

        if not rows:
            return {"inserted": 0, "pool_size": 0}

        # Score each reel
        # WEIGHTING NOTE: rebalanced post-launch — the previous formula gave
        # 0.20 to view_performance which let "dog video with 50M views" beat
        # "niche-fit reel with 200k views." Niche fit (caption + topic) now
        # dominates; views still help break ties between equally-on-brand
        # candidates. Total still sums to 1.00.
        scored: list[tuple[float, Any]] = []
        for r in rows:
            score = 0.0

            # 1. Caption relevance (0-0.35) — was 0.30
            reel_words = tokenise(r.caption) if r.caption else set()
            overlap = len(reel_words & keywords)
            relevance = min(overlap / max(len(keywords), 1), 1.0)
            score += relevance * 0.35

            # 2. Topic match (0-0.25) — was 0.20. Claude-profiled tags
            # are the strongest niche-fit signal we have.
            if r.profile_tags and niche_tag_tokens:
                profile_tag_tokens = set()
                for pt in (r.profile_tags if isinstance(r.profile_tags, list) else []):
                    if isinstance(pt, str):
                        profile_tag_tokens.update(tokenise(pt))
                if r.topic:
                    profile_tag_tokens.update(tokenise(r.topic))
                topic_overlap = len(profile_tag_tokens & niche_tag_tokens)
                topic_score = min(topic_overlap / max(len(niche_tag_tokens), 1), 1.0)
                score += topic_score * 0.25
            elif r.caption and niche_tag_tokens:
                # Fallback when no Claude profile yet: caption-vs-niche.
                caption_tokens = tokenise(r.caption)
                fallback_overlap = len(caption_tokens & niche_tag_tokens)
                score += min(fallback_overlap / max(len(niche_tag_tokens), 1), 1.0) * 0.12

            # 3. View performance (0-0.10) — was 0.20. Tie-breaker only.
            if r.view_count and r.view_count > 0:
                view_score = min(math.log10(r.view_count) / 7, 1.0)
                score += view_score * 0.10

            # 4. Engagement (0-0.15) — unchanged.
            if r.view_count and r.view_count > 0:
                engagement = ((r.like_count or 0) + (r.comment_count or 0)) / r.view_count
                score += min(engagement * 10, 1.0) * 0.15

            # 5. Freshness (0-0.15) — unchanged.
            if r.posted_at:
                try:
                    if r.posted_at.tzinfo is None:
                        days_old = (datetime.utcnow() - r.posted_at).days
                    else:
                        days_old = (datetime.now(timezone.utc) - r.posted_at).days
                except Exception:
                    days_old = 90
                freshness = max(0, 1.0 - days_old / 90)
                score += freshness * 0.15

            scored.append((round(score, 4), r))

        # Sort by score, tie-break by views
        scored.sort(key=lambda x: (-x[0], -(x[1].view_count or 0)))

        # Diversify — max per source page
        final_recs: list[tuple[float, Any]] = []
        page_counts: dict[str, int] = defaultdict(int)

        for s, reel in scored:
            page_id = str(reel.theme_page_id) if reel.theme_page_id else "unknown"
            if page_counts[page_id] >= MAX_PER_SOURCE:
                continue
            final_recs.append((s, reel))
            page_counts[page_id] += 1
            if len(final_recs) >= target_recs:
                break

        # ── Step 5b: Downloadability gate ───────────────────────────
        # Drop any reel we can't pull from YouTube/etc. — saves the user
        # from clicking dead recommendations. Caches probe results on
        # viral_reels so re-running discovery is cheap.
        final_recs = _filter_to_downloadable(final_recs, session)

        # ── Step 5c: Claude reviewer pass ───────────────────────────
        # The math gets us 80% of the way; Claude catches the edge cases
        # (wrong format despite right keywords, off-brand despite right
        # niche). Runs Haiku — ~$0.05 per discovery, ~10s wall time.
        final_recs, review_map = _claude_review_pass(
            final_recs, user_niche_tags, reference_profiles,
        )

        # Insert recommendations
        inserted = 0
        for final_score, reel in final_recs:
            reel_words = tokenise(reel.caption) if reel.caption else set()
            matched_kw = sorted(reel_words & keywords)[:10]

            # Prefer Claude's reason — it's a strategist's read on the fit
            # ("Tutorial format matches your educational tone") vs. our
            # heuristic ("Matches: skincare, glow, makeup — 200k views").
            review = review_map.get(str(reel.id))
            views_str = f"{reel.view_count:,}" if reel.view_count else "0"
            if review and review.get("reason"):
                reason = review["reason"]
            elif matched_kw:
                reason = f"Matches: {', '.join(matched_kw[:3])} — {views_str} views"
            elif reel.topic:
                reason = f"{reel.topic.title()} content — {views_str} views"
            elif final_score > 0.6:
                reason = f"High-performing similar content — {views_str} views"
            else:
                reason = f"Trending in your niche — {views_str} views"

            factors = {
                "matched_keywords": matched_kw,
                "view_count": reel.view_count,
                "like_count": reel.like_count,
                "topic": reel.topic or None,
                "format": getattr(reel, 'format', None),
                "hook_pattern": reel.hook_pattern if hasattr(reel, 'hook_pattern') else None,
                "source_username": reel.source_username if hasattr(reel, 'source_username') else None,
                "engagement_ratio": round(
                    ((reel.like_count or 0) + (reel.comment_count or 0))
                    / max(reel.view_count or 1, 1), 4
                ),
                "reference_pages": len(reference_profiles),
                "source_pages": len(page_counts),
            }

            session.execute(
                text("""
                    INSERT INTO user_reel_recommendations (
                        id, user_page_id, viral_reel_id,
                        match_score, match_reason, match_factors
                    )
                    VALUES (:id, :pid, :rid, :score, :reason, CAST(:factors AS JSONB))
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": str(uuid.uuid4()),
                    "pid": user_page_id,
                    "rid": str(reel.id),
                    "score": max(0.01, float(final_score)),
                    "reason": reason[:500],
                    "factors": json.dumps(factors),
                },
            )
            inserted += 1

    return {
        "inserted": inserted,
        "pool_size": len(rows),
        "scored_above_threshold": sum(1 for s, _ in scored if s > 0.3),
        "source_pages": len(page_counts),
        "keywords": len(keywords),
        "niche_tags": len(user_niche_tags),
    }


# ── The Celery task ───────────────────────────────────────────────────

@app.task(
    name="tasks.deep_discovery.deep_discovery_task",
    bind=True,
    max_retries=1,
    time_limit=900,   # 15 min hard limit
    soft_time_limit=840,
)
def deep_discovery_task(self, user_page_id: str):
    """Full deep discovery pipeline triggered after onboarding.

    1. Load user's own page + reference pages + niche tags
    2. Seed expansion from reference pages (suggested + following)
    3. Second-degree scan from top discovered pages
    4. Scrape reels from all discovered pages
    5. Claude-profile each reel for topic/format/hook
    6. Build enhanced recommendations with 5-axis scoring
    7. Store 500+ ranked recommendations
    """
    logger.info("=== DEEP DISCOVERY starting for user_page=%s ===", user_page_id)
    job_id = str(uuid.uuid4())

    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :task_id, 'deep_discovery', 'running',
                    :ref_id, 'user_page', :now)
            """),
            {
                "id": job_id,
                "task_id": self.request.id or "",
                "ref_id": user_page_id,
                "now": datetime.now(timezone.utc),
            },
        )

    try:
        # ── Step 0: Load user context ─────────────────────────────
        with get_session() as session:
            page_row = session.execute(
                text("""
                    SELECT up.id, up.ig_username, up.user_id, up.niche_tags
                    FROM user_pages up
                    WHERE up.id = :pid AND up.page_type = 'own'
                """),
                {"pid": user_page_id},
            ).fetchone()

            if not page_row:
                logger.warning("Own page %s not found", user_page_id)
                return {"error": "Page not found"}

            user_id = str(page_row.user_id)
            own_username = page_row.ig_username
            user_niche_tags = page_row.niche_tags or []

            # Load reference pages
            ref_rows = session.execute(
                text("""
                    SELECT up.id, up.ig_username
                    FROM user_pages up
                    WHERE up.user_id = :uid AND up.page_type = 'reference' AND up.is_active = true
                """),
                {"uid": user_id},
            ).fetchall()

            reference_usernames = [r.ig_username for r in ref_rows]
            ref_page_ids = [str(r.id) for r in ref_rows]

            # Load reference profiles for scoring
            reference_profiles = []
            for rpid in ref_page_ids:
                prof = session.execute(
                    text("""
                        SELECT niche_primary, top_topics, raw_analysis
                        FROM page_profiles
                        WHERE user_page_id = :pid
                        ORDER BY analyzed_at DESC LIMIT 1
                    """),
                    {"pid": rpid},
                ).fetchone()
                if prof:
                    topics = prof.top_topics
                    if isinstance(topics, str):
                        try:
                            topics = json.loads(topics)
                        except Exception:
                            topics = []
                    raw = prof.raw_analysis
                    if isinstance(raw, str):
                        try:
                            raw = json.loads(raw)
                        except Exception:
                            raw = {}
                    reference_profiles.append({
                        "niche_primary": prof.niche_primary,
                        "top_topics": topics if isinstance(topics, list) else [],
                        "keyword_signature": (raw or {}).get("keyword_signature", []) if isinstance(raw, dict) else [],
                    })

            # Get niche_id
            niche_result = session.execute(
                text("""
                    SELECT n.id FROM niches n
                    JOIN page_profiles pp ON pp.niche_primary = n.slug
                        OR LOWER(pp.niche_primary) = LOWER(n.name)
                    WHERE pp.user_page_id = :pid
                    ORDER BY pp.analyzed_at DESC LIMIT 1
                """),
                {"pid": user_page_id},
            ).fetchone()
            niche_id = str(niche_result.id) if niche_result else None

            # Existing theme page usernames
            existing_rows = session.execute(
                text("SELECT username FROM theme_pages"),
            ).fetchall()
            existing_usernames = {r.username for r in existing_rows}

        logger.info(
            "Context: @%s, %d ref pages, %d niche tags, niche_id=%s",
            own_username, len(reference_usernames), len(user_niche_tags), niche_id,
        )

        if not reference_usernames:
            logger.warning("No reference pages found for user_page=%s", user_page_id)
            # Fall back to existing recommendation engine
            from tasks.recommendation import generate_recommendations_task
            generate_recommendations_task.delay(user_page_id)
            with get_session() as session:
                session.execute(
                    text("UPDATE jobs SET status = 'success', finished_at = :now WHERE id = :id"),
                    {"now": datetime.now(timezone.utc), "id": job_id},
                )
            return {"fallback": True, "reason": "no_reference_pages"}

        # ── Step 1: Seed expansion ────────────────────────────────
        first_degree = _discover_pages_from_references(
            reference_usernames, existing_usernames,
        )

        # ── Step 2: Second-degree scan ────────────────────────────
        second_degree = _second_degree_scan(
            first_degree, existing_usernames, reference_usernames,
        )

        all_discovered = first_degree + second_degree
        logger.info("Total discovered pages: %d (1st: %d, 2nd: %d)",
                    len(all_discovered), len(first_degree), len(second_degree))

        # ── Step 3: Scrape reels ──────────────────────────────────
        all_reels = _scrape_and_store_reels(all_discovered, niche_id)

        # Also include existing reels from the DB that match niche
        with get_session() as session:
            existing_reels = session.execute(
                text("""
                    SELECT vr.id::text, vr.caption, vr.view_count, vr.like_count,
                           vr.comment_count, vr.duration_seconds,
                           tp.username as source_username,
                           vr.theme_page_id::text
                    FROM viral_reels vr
                    LEFT JOIN theme_pages tp ON tp.id = vr.theme_page_id
                    WHERE vr.view_count >= :min_views
                    ORDER BY vr.view_count DESC
                    LIMIT 3000
                """),
                {"min_views": MIN_VIEWS_THRESHOLD},
            ).fetchall()

        existing_ids = {r["id"] for r in all_reels}
        for er in existing_reels:
            if str(er.id) not in existing_ids:
                all_reels.append({
                    "id": str(er.id),
                    "caption": er.caption or "",
                    "view_count": er.view_count or 0,
                    "like_count": er.like_count or 0,
                    "comment_count": er.comment_count or 0,
                    "duration_seconds": er.duration_seconds or 0,
                    "source_username": er.source_username or "",
                    "theme_page_id": er.theme_page_id or "",
                })

        logger.info("Total reel pool for profiling: %d", len(all_reels))

        # ── Step 4: Claude profiling ──────────────────────────────
        # Profile top reels by view count (most valuable to profile first)
        reels_to_profile = sorted(
            all_reels, key=lambda x: x.get("view_count", 0), reverse=True
        )[:200]  # Profile top 200 reels

        profiled_count = _profile_reels_with_claude(reels_to_profile)

        # ── Step 5+6: Enhanced scoring + recommendations ──────────
        rec_result = _build_enhanced_recommendations(
            user_page_id=user_page_id,
            user_niche_tags=user_niche_tags,
            reference_profiles=reference_profiles,
            target_recs=min(MAX_RECS, TARGET_RECS + len(reference_usernames) * 100),
        )

        # Mark job as success
        with get_session() as session:
            session.execute(
                text("""
                    UPDATE jobs SET status = 'success', finished_at = :now,
                        logs = CAST(:logs AS JSONB)
                    WHERE id = :id
                """),
                {
                    "now": datetime.now(timezone.utc),
                    "id": job_id,
                    "logs": json.dumps({
                        "pages_discovered": len(all_discovered),
                        "reels_scraped": len(all_reels),
                        "reels_profiled": profiled_count,
                        "recommendations": rec_result.get("inserted", 0),
                    }),
                },
            )

        result = {
            "user_page_id": user_page_id,
            "pages_discovered": len(all_discovered),
            "first_degree": len(first_degree),
            "second_degree": len(second_degree),
            "reels_scraped": len(all_reels),
            "reels_profiled": profiled_count,
            **rec_result,
        }

        logger.info("=== DEEP DISCOVERY complete: %s ===", result)
        return result

    except Exception as exc:
        logger.error("Deep discovery failed: %s", exc, exc_info=True)
        try:
            with get_session() as session:
                session.execute(
                    text("""
                        UPDATE jobs SET status = 'failed', finished_at = :now,
                            logs = jsonb_build_object('error', :err)
                        WHERE id = :id
                    """),
                    {"now": datetime.now(timezone.utc), "err": str(exc)[:1000], "id": job_id},
                )
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=120)
