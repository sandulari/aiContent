"""Analyze a newly-added user page (own or reference).

Uses the same RapidAPI Instagram scraper as the API's in-process analyzer
(but synchronously, since Celery workers are sync). Writes page_profiles,
seeds theme_pages + viral_reels for the niche, then chains into the
recommendation generator so the user's feed is full within ~10s.
"""
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone

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

NICHE_KEYWORDS = {
    "beauty": ["skincare", "beauty", "makeup", "glow", "cosmetics", "skin", "glam"],
    "fitness": ["gym", "fitness", "workout", "muscle", "protein", "training"],
    "business": ["entrepreneur", "business", "startup", "ceo", "hustle", "wealth"],
    "motivation": ["motivation", "mindset", "grind", "success", "inspiration", "goals"],
    "tech": ["tech", "ai", "artificial intelligence", "coding", "software"],
    "food": ["recipe", "cooking", "food", "chef", "kitchen", "baking"],
    "travel": ["travel", "destination", "adventure", "explore", "wanderlust"],
    "fashion": ["fashion", "style", "outfit", "streetwear", "designer"],
    "comedy": ["funny", "comedy", "meme", "humor", "lol", "viral"],
    "finance": ["finance", "investing", "stock", "crypto", "budget", "savings"],
    "luxury": ["luxury", "rich", "lifestyle", "billionaire", "supercar"],
    "money": ["money", "side hustle", "passive income", "make money"],
}

FALLBACK_PAGES = {
    "beauty": ["hudabeauty", "elfcosmetics", "glowrecipe", "fentybeauty", "tatcha"],
    "fitness": ["gymshark", "blogilates", "crossfit", "kayla_itsines"],
    "business": ["garyvee", "foundr", "entrepreneur", "thefutur"],
    "comedy": ["9gag", "pubity", "bestvines", "memes"],
    "travel": ["earthpix", "beautifuldestinations", "natgeo", "discoverearth"],
    "food": ["buzzfeedtasty", "delish", "foodnetwork", "gordonramsayofficial"],
    "fashion": ["hypebeast", "zara", "hm", "asos"],
    "motivation": ["thegoodquote", "motivationdaily", "garyvee"],
    "tech": ["techcrunch", "wired", "futurism"],
    "finance": ["personalfinanceclub", "wealthsimple"],
    "luxury": ["luxurylifestyle", "billionairesclub"],
    "money": ["sidehustlepros", "passiveincomeideas"],
}


# ── Sync RapidAPI helpers ──────────────────────────────────────────────

def _rapid_get(path: str, params: dict, timeout: int = 15) -> dict | None:
    if not RAPIDAPI_KEY:
        return None
    try:
        with httpx.Client(timeout=timeout, headers=RAPIDAPI_HEADERS) as client:
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


def _get_user_reels(user_pk: str | int) -> list[dict]:
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
        {"username": u.get("username", ""), "pk": u.get("pk", ""), "full_name": u.get("full_name", "")}
        for u in users
        if u.get("username")
    ]


_STOPWORDS_ANALYZE = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "by", "for",
    "with", "from", "as", "this", "that", "these", "those", "it", "its",
    "if", "then", "than", "so", "i", "you", "he", "she", "they", "we",
    "my", "your", "his", "her", "their", "our", "me", "him", "us", "them",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "shall", "may", "might", "just", "via", "amp",
    "get", "got", "out", "up", "down", "about", "when", "what", "how",
    "why", "who", "all", "any", "some", "no", "not", "one", "two", "new",
    "like", "make", "made", "every", "day", "today", "now", "here", "there",
    "watch", "see", "look", "check", "link", "bio", "comment", "follow",
    "tag", "share", "subscribe", "reels", "reel", "insta", "instagram",
    "viral", "foryou", "fyp", "trending",
}


def _tokenise_signature(text_blob: str) -> list[str]:
    import re as _re
    if not text_blob:
        return []
    cleaned = _re.sub(r"@\w+", " ", text_blob)
    cleaned = _re.sub(r"#(\w+)", r"\1", cleaned)
    cleaned = _re.sub(r"[^\w\s]", " ", cleaned.lower())
    out = []
    for w in cleaned.split():
        wl = w.strip("_0123456789")
        if len(wl) < 4:  # 4+ char threshold filters out tiny noise
            continue
        if wl in _STOPWORDS_ANALYZE:
            continue
        out.append(wl)
    return out


def _detect_niche(username: str, bio: str, captions: str) -> str:
    """Niche detection with prefix-anchored matching.

    Weights username + bio 5× over captions so the user's account identity
    dominates over whatever random reels they happened to post recently.

    Uses a prefix-anchored regex (`\\bkeyword`) instead of full word boundaries
    so "entrepreneur" matches "entrepreneurship", "entrepreneurial",
    "entrepreneurs" — all legitimate inflections. This is what broke the
    @entrepreneurialogyy case: the bio said "Decoding the science of
    entrepreneurship" and a full-word regex missed every inflection.
    """
    import re as _re

    username_l = (username or "").lower()
    bio_l = (bio or "").lower()
    captions_l = (captions or "").lower()

    # Split the username on separators so "entrepreneurial_ceo" yields
    # ["entrepreneurial", "ceo"] for matching.
    username_parts = " ".join(_re.split(r"[._\-]+", username_l))

    scores: dict[str, float] = {}
    for slug, keywords in NICHE_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            # Prefix-anchored: `\bentrepreneur` matches both "entrepreneur"
            # and "entrepreneurship" but not "technopreneur" (no boundary
            # at start). Multi-word keywords fall back to `in` substring.
            if " " in kw:
                if kw in bio_l:
                    score += 5
                if kw in captions_l:
                    score += 1
                continue
            pattern = r"\b" + _re.escape(kw)
            # username + bio: high weight — account identity
            score += 5 * len(_re.findall(pattern, username_parts))
            score += 5 * len(_re.findall(pattern, bio_l))
            # Raw-username substring for concatenated handles like
            # "entrepreneuriallogyy".
            if kw in username_l:
                score += 3
            # Captions: low weight (content drifts)
            score += len(_re.findall(pattern, captions_l))
        if score > 0:
            scores[slug] = score

    if not scores:
        return "comedy"
    return max(scores.items(), key=lambda x: x[1])[0]


def _build_signature_from_page(username: str, bio: str, captions_blob: str, niche_slug: str) -> list[str]:
    """Return up to ~25 unique keywords that describe this page,
    ordered by frequency in the user's own content."""
    from collections import Counter
    import re as _re

    counter: Counter = Counter()

    if username:
        parts = _re.split(r"[._\-]+", username.lower())
        for p in parts:
            for tok in _tokenise_signature(p):
                counter[tok] += 4
        # Substring pull for concatenated handles.
        full = username.lower()
        for anchor_list in NICHE_KEYWORDS.values():
            for a in anchor_list:
                if len(a) >= 5 and a in full:
                    counter[a] += 3

    for tok in _tokenise_signature(bio):
        counter[tok] += 2

    for tok in _tokenise_signature(captions_blob):
        counter[tok] += 1

    # Seed with the detected niche's anchors so the signature isn't empty
    # for pages with sparse captions.
    for anchor in NICHE_KEYWORDS.get(niche_slug, []):
        if " " not in anchor:
            counter[anchor] += 2

    return [w for w, _ in counter.most_common(25)]


def _mark_job(job_id: str, status: str, error: str | None = None):
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


# ── The task itself ────────────────────────────────────────────────────

@app.task(name="tasks.analyze_page.analyze_page_task", bind=True, max_retries=2)
def analyze_page_task(self, user_page_id: str):
    """Analyze a user_pages row using the RapidAPI Instagram scraper.

    Steps:
      1. Fetch profile metadata from RapidAPI.
      2. Detect niche from username + bio + recent captions.
      3. UPDATE user_pages with display name + follower count.
      4. INSERT page_profiles row.
      5. Seed theme_pages + viral_reels for the detected niche
         (suggested accounts + hardcoded fallbacks per niche).
      6. Chain into recommendation generator so the user's feed fills.
    """
    logger.info("Analyzing user_page=%s", user_page_id)
    job_id = str(uuid.uuid4())

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :task_id, 'analyze_page', 'running',
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
        page_row = session.execute(
            text("SELECT id, ig_username, page_type FROM user_pages WHERE id = :id"),
            {"id": user_page_id},
        ).fetchone()

    if not page_row:
        _mark_job(job_id, "failed", "user_page not found")
        return {"error": "user_page not found"}

    ig_username = page_row.ig_username

    try:
        # ── Step 1: fetch profile via RapidAPI ──────────────────────
        profile = _get_profile(ig_username) or {}
        bio = profile.get("biography", "") or ""
        followers = profile.get("follower_count")
        following = profile.get("following_count")
        media_count = profile.get("media_count")
        full_name = profile.get("full_name", ig_username)
        pic_url = (profile.get("hd_profile_pic_url_info", {}) or {}).get("url") or profile.get("profile_pic_url", "")
        user_pk = profile.get("pk") or profile.get("pk_id")

        # ── Step 2: scrape recent reels + niche detection ──────────
        captions_blob = ""
        user_reels: list = []
        if user_pk:
            try:
                user_reels = _get_user_reels(user_pk)
                captions_blob = " ".join(r.get("caption", "") for r in user_reels[:10])
            except Exception:
                pass

        # Try Claude for a rich semantic profile; fall back to the
        # regex-based keyword detection when it fails or is disabled.
        claude_analysis = None
        try:
            claude_analysis = claude_client.analyze_page(
                username=ig_username,
                display_name=full_name,
                bio=bio,
                recent_reels=user_reels[:15],
            )
        except Exception as exc:
            logger.warning("Claude analysis errored for @%s: %s", ig_username, exc)

        if claude_analysis and claude_analysis.get("niche_primary"):
            niche_slug = claude_analysis["niche_primary"].lower().split()[0]
            if niche_slug not in NICHE_KEYWORDS:
                # Claude picked a niche we don't have a matching row for
                # in the `niches` table — fall back to regex detection.
                niche_slug = _detect_niche(ig_username, bio, captions_blob)
        else:
            niche_slug = _detect_niche(ig_username, bio, captions_blob)

        # ── Step 3: update user_pages ───────────────────────────────
        with get_session() as session:
            niche_row = session.execute(
                text("SELECT id FROM niches WHERE slug = :s"),
                {"s": niche_slug},
            ).fetchone()
            niche_id = str(niche_row.id) if niche_row else None

            session.execute(
                text(
                    """
                    UPDATE user_pages
                    SET ig_display_name = :name,
                        ig_profile_pic_url = :pic,
                        follower_count = :f,
                        following_count = :fw,
                        total_posts = :p,
                        last_analyzed_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "name": full_name,
                    "pic": pic_url,
                    "f": followers,
                    "fw": following,
                    "p": media_count,
                    "now": datetime.now(timezone.utc),
                    "id": user_page_id,
                },
            )

            # ── Step 4: page_profiles ───────────────────────────────
            # Prefer Claude's semantic signature when available. Fall
            # back to the regex/frequency-based extractor otherwise.
            if claude_analysis:
                signature = list(
                    dict.fromkeys(
                        [
                            w.lower()
                            for w in (claude_analysis.get("keyword_signature") or [])
                            if isinstance(w, str)
                        ]
                    )
                )[:30]
                # Also include the topics so they influence ranking.
                for t in claude_analysis.get("topics", []) or []:
                    if isinstance(t, str):
                        for w in t.lower().split():
                            if len(w) >= 4 and w not in signature:
                                signature.append(w)
                analysis_model = "claude-" + (claude_client.CLAUDE_MODEL or "unknown")
                content_style = {
                    "source": "claude",
                    "bio": bio[:200],
                    **(claude_analysis.get("content_style") or {}),
                    "target_audience": claude_analysis.get("target_audience", ""),
                    "topics": claude_analysis.get("topics", []),
                }
            else:
                signature = _build_signature_from_page(
                    ig_username, bio, captions_blob, niche_slug
                )
                analysis_model = "rapidapi-worker-v2"
                content_style = {"source": "rapidapi", "bio": bio[:200]}

            logger.info(
                "Signature for @%s (%s / %s): %s",
                ig_username, niche_slug, analysis_model, signature[:15],
            )

            session.execute(
                text(
                    """
                    INSERT INTO page_profiles (
                        id, user_page_id, niche_primary, top_topics,
                        top_formats, content_style, posting_frequency,
                        analysis_model, raw_analysis, analyzed_at
                    )
                    VALUES (:id, :pid, :niche,
                        CAST(:topics AS JSONB), CAST(:formats AS JSONB),
                        CAST(:style AS JSONB), :freq,
                        :model, CAST(:raw AS JSONB), :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "pid": user_page_id,
                    "niche": niche_slug,
                    "topics": json.dumps(signature),
                    "formats": json.dumps(["reels"]),
                    "style": json.dumps(content_style),
                    "freq": 1.0,
                    "model": analysis_model[:100],
                    "raw": json.dumps(claude_analysis) if claude_analysis else None,
                    "now": datetime.now(timezone.utc),
                },
            )

        # ── Step 5: seed theme_pages + viral_reels ──────────────────
        theme_usernames: list[str] = []
        if user_pk:
            try:
                suggested = _get_suggested(user_pk)
                theme_usernames.extend([s["username"] for s in suggested[:8]])
            except Exception:
                pass

        with get_session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT username FROM theme_pages
                    WHERE niche_id = :nid AND is_active = true
                    LIMIT 5
                    """
                ),
                {"nid": niche_id},
            ).fetchall()
        for ep in existing:
            if ep.username not in theme_usernames:
                theme_usernames.append(ep.username)

        for fb in FALLBACK_PAGES.get(niche_slug, FALLBACK_PAGES["comedy"]):
            if fb not in theme_usernames:
                theme_usernames.append(fb)

        total_reels = 0
        for tp_username in theme_usernames[:10]:
            try:
                tp_profile = _get_profile(tp_username)
                if not tp_profile:
                    continue
                tp_pk = tp_profile.get("pk") or tp_profile.get("pk_id")
                if not tp_pk:
                    continue

                with get_session() as session:
                    tp_exists = session.execute(
                        text("SELECT id FROM theme_pages WHERE username = :u"),
                        {"u": tp_username},
                    ).fetchone()
                    if not tp_exists:
                        tp_id = str(uuid.uuid4())
                        session.execute(
                            text(
                                """
                                INSERT INTO theme_pages
                                    (id, username, display_name, profile_url,
                                     niche_id, follower_count, is_active, evaluation_status)
                                VALUES (:id, :u, :name, :url, :nid, :fc, true, 'confirmed')
                                ON CONFLICT (username) DO NOTHING
                                """
                            ),
                            {
                                "id": tp_id,
                                "u": tp_username,
                                "name": tp_profile.get("full_name", tp_username),
                                "url": f"https://www.instagram.com/{tp_username}/",
                                "nid": niche_id,
                                "fc": tp_profile.get("follower_count"),
                            },
                        )
                        page_id = tp_id
                    else:
                        page_id = str(tp_exists.id)

                reels = _get_user_reels(tp_pk)
                with get_session() as session:
                    for reel in reels:
                        if reel["view_count"] < 10000 and reel["like_count"] < 1000:
                            continue
                        exists = session.execute(
                            text("SELECT 1 FROM viral_reels WHERE ig_video_id = :v"),
                            {"v": reel["shortcode"]},
                        ).fetchone()
                        if exists:
                            if reel["thumbnail_url"]:
                                session.execute(
                                    text(
                                        "UPDATE viral_reels SET thumbnail_url = :t WHERE ig_video_id = :v"
                                    ),
                                    {"t": reel["thumbnail_url"], "v": reel["shortcode"]},
                                )
                            continue
                        posted = (
                            datetime.utcfromtimestamp(reel["taken_at"])
                            if reel["taken_at"]
                            else datetime.utcnow()
                        )
                        session.execute(
                            text(
                                """
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
                                """
                            ),
                            {
                                "id": str(uuid.uuid4()),
                                "pid": page_id,
                                "vid": reel["shortcode"],
                                "url": reel["url"],
                                "thumb": reel["thumbnail_url"],
                                "views": reel["view_count"],
                                "likes": reel["like_count"],
                                "comments": reel["comment_count"],
                                "dur": reel["duration_seconds"],
                                "cap": reel["caption"],
                                "posted": posted,
                                "nid": niche_id,
                            },
                        )
                        total_reels += 1
                logger.info("  @%s: scraped %d reels", tp_username, len(reels))
                # RapidAPI rate-limits aggressively (~1 req/sec). 1.5s buffer
                # between theme pages keeps us under the threshold so we
                # don't get a wall of 429s mid-fanout.
                time.sleep(1.5)
            except Exception as exc:
                logger.warning("theme page @%s failed: %s", tp_username, exc)

        _mark_job(job_id, "success")

        # ── Step 6: chain recommendations + re-analyze siblings ─────
        # Adding or removing any page invalidates every other page on
        # the same account: the combined signature (own + all refs) is
        # now different, and any sibling page that was analyzed by an
        # older version of this task is missing the Claude-powered
        # profile. So we fan out in two waves:
        #   wave 1: recompute recs for the page we just analyzed
        #   wave 2: re-analyze EVERY sibling page (own + reference) so
        #           they pick up the latest Claude client + signature
        #           shape. Each re-analysis chains into its own recs.
        try:
            from tasks.recommendation import generate_recommendations_task

            generate_recommendations_task.delay(user_page_id)

            # Only re-analyze siblings whose last_analyzed_at is older
            # than 60 seconds. This breaks the mutual-fanout loop:
            # sibling A → re-analyzes sibling B → B would try to
            # re-analyze A, but A was just touched so it's skipped.
            with get_session() as session:
                sibling_rows = session.execute(
                    text(
                        """
                        SELECT sib.id, sib.page_type, sib.last_analyzed_at
                        FROM user_pages sib
                        JOIN user_pages me ON me.user_id = sib.user_id
                        WHERE me.id = :pid
                          AND sib.id <> :pid
                          AND sib.is_active = true
                          AND (
                              sib.last_analyzed_at IS NULL
                              OR sib.last_analyzed_at < NOW() - INTERVAL '60 seconds'
                          )
                        """
                    ),
                    {"pid": user_page_id},
                ).fetchall()

            for s in sibling_rows:
                sib_id = str(s.id)
                try:
                    # Re-analyze the sibling from scratch so its Claude
                    # profile is rebuilt with the latest client version.
                    # The sibling's own analyze_page_task will chain
                    # recs for itself — no need to double-queue.
                    analyze_page_task.apply_async(args=[sib_id], countdown=2)
                except Exception as exc2:
                    logger.warning(
                        "Failed to queue re-analysis for sibling %s: %s", sib_id, exc2
                    )
        except Exception as exc:
            logger.warning("Failed to chain fan-out for %s: %s", user_page_id, exc)

        return {
            "user_page_id": user_page_id,
            "niche": niche_slug,
            "followers": followers,
            "theme_pages_seeded": len(theme_usernames[:10]),
            "viral_reels_inserted": total_reels,
        }

    except Exception as exc:
        logger.error("analyze_page_task failed for %s: %s", user_page_id, exc, exc_info=True)
        _mark_job(job_id, "failed", str(exc)[:1000])
        raise self.retry(exc=exc, countdown=60)
