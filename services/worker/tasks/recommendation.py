"""Recommendation engine — content-aware scoring across reference pages.

Discovers viral reels by combining signals from the student's own page and
ALL their reference pages. Instead of fragile keyword matching, we build a
rich keyword set from profile metadata *and* reference pages' actual reel
captions, then score every candidate reel on four axes:

  1. Caption relevance  (0–0.40) — word overlap with reference keywords
  2. View performance   (0–0.30) — log-scaled view count
  3. Engagement ratio   (0–0.15) — (likes+comments)/views
  4. Freshness          (0–0.15) — linear decay over 90 days

After scoring, results are diversified so no single theme page dominates
the feed (max 30 reels per source page).
"""
import json
import logging
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib.db import get_session

logger = logging.getLogger(__name__)

# ── Volume targets ───────────────────────────────────────────
BASE_RECS = 500
PER_REF_RECS = 200
MAX_RECS = 1000

# Progressive view-count floors — we try from the highest first and relax
# until we have enough candidates.
VIEW_FLOORS = [100_000, 50_000, 10_000, 5_000, 1_000, 0]

# Max reels from any single theme page in the final recommendation set.
MAX_PER_PAGE = 30

# ── Stop words ───────────────────────────────────────────────
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "not", "with", "this", "that", "it", "be", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "can", "i", "you", "we", "they", "he", "she", "my", "your", "our", "their",
    "me", "us", "him", "her", "them", "who", "what", "when", "where", "how", "why",
    "all", "each", "every", "both", "few", "more", "most", "other", "some", "such",
    "no", "nor", "only", "own", "same", "so", "than", "too", "very", "just", "if",
    "about", "up", "out", "from", "by", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "these", "those", "am", "been", "being",
    "get", "got", "getting", "go", "going", "come", "make", "like", "know", "take",
    "see", "look", "want", "give", "use", "find", "tell", "ask", "work", "seem",
    "feel", "try", "leave", "call", "need", "become", "keep", "let", "begin", "show",
    "hear", "play", "run", "move", "live", "believe", "bring", "happen", "write",
    "provide", "sit", "stand", "lose", "pay", "meet", "include", "continue", "set",
    "learn", "change", "lead", "understand", "watch", "follow", "stop", "create",
    "speak", "read", "allow", "add", "spend", "grow", "open", "walk", "win", "offer",
    "think", "say", "help", "turn", "start", "might", "also", "now", "then", "here",
    "there", "well", "way", "even", "new", "still", "because", "much", "really",
    "one", "two", "three", "first", "last", "long", "great", "little", "right",
    "old", "big", "high", "different", "small", "large", "next", "early", "young",
    "important", "public", "bad", "same", "able", "sure", "real", "point", "thing",
    "its", "dont", "im", "youre", "hes", "shes", "were", "theyre", "ive", "youve",
    "weve", "theyve", "link", "bio", "dm", "follow", "comment", "share", "repost",
    "tag", "save", "click",
    # Instagram/social noise
    "reel", "reels", "insta", "instagram", "viral", "foryou", "fyp", "trending",
    "subscribe", "via", "amp",
}


# ── Helpers ──────────────────────────────────────────────────

def _clean_word(w: str) -> str:
    """Strip a token down to alphanumeric characters."""
    return "".join(c for c in w if c.isalnum())


def _tokenise(text_blob: str) -> list[str]:
    """Return lowercased content tokens. Hashtags -> inner word, @mentions dropped."""
    if not text_blob:
        return []
    cleaned = re.sub(r"@\w+", " ", text_blob)
    cleaned = re.sub(r"#(\w+)", r"\1", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.lower())
    tokens = []
    for w in cleaned.split():
        wl = w.strip("_0123456789")
        if len(wl) < 3 or wl in STOP_WORDS or wl.isdigit():
            continue
        tokens.append(wl)
    return tokens


def build_reference_keywords(own_profile: dict, ref_profiles: list[dict],
                             ref_reel_captions: list[str]) -> set[str]:
    """Build a set of meaningful keywords from all reference data.

    Sources:
      - Student's own page niche + topics
      - ALL reference pages' niche + topics
      - Top captions from reference pages' reels (common words, stop-words removed)
    """
    words: set[str] = set()

    # From profiles (own + all references)
    for profile in [own_profile] + ref_profiles:
        if not profile:
            continue
        topics = profile.get("top_topics") or []
        if isinstance(topics, list):
            for topic in topics:
                if isinstance(topic, str):
                    words.update(t for t in _tokenise(topic) if len(t) > 3)
        niche = profile.get("niche_primary")
        if niche and isinstance(niche, str):
            words.update(t for t in _tokenise(niche) if len(t) > 3)
        # Also extract from username
        username = profile.get("username", "")
        if username:
            parts = re.split(r"[._\-]+", username.lower())
            for p in parts:
                for token in _tokenise(p):
                    if len(token) >= 4:
                        words.add(token)

    # From reference pages' top reel captions
    for caption in ref_reel_captions:
        if not caption:
            continue
        for w in caption.lower().split():
            clean = _clean_word(w)
            if len(clean) > 3 and clean not in STOP_WORDS:
                words.add(clean)

    return words


def score_reel(caption: str | None, view_count: int, like_count: int,
               comment_count: int, posted_at: datetime | None,
               reference_keywords: set[str]) -> float:
    """Score a candidate reel on four axes. Returns 0.0–1.0."""
    score = 0.0

    # 1. Caption relevance (0–0.4)
    reel_words = set(_tokenise(caption)) if caption else set()
    overlap = len(reel_words & reference_keywords)
    relevance = min(overlap / max(len(reference_keywords), 1), 1.0)
    score += relevance * 0.4

    # 2. View performance (0–0.3) — log-scaled, 10M views = 1.0
    if view_count and view_count > 0:
        view_score = min(math.log10(view_count) / 7, 1.0)
        score += view_score * 0.3

    # 3. Engagement ratio (0–0.15) — 10% engagement = max
    if view_count and view_count > 0:
        engagement = ((like_count or 0) + (comment_count or 0)) / view_count
        score += min(engagement * 10, 1.0) * 0.15

    # 4. Freshness (0–0.15) — linear decay over 90 days
    if posted_at:
        try:
            if posted_at.tzinfo is None:
                days_old = (datetime.utcnow() - posted_at).days
            else:
                days_old = (datetime.now(timezone.utc) - posted_at).days
        except Exception:
            days_old = 90
        freshness = max(0, 1.0 - days_old / 90)
        score += freshness * 0.15

    return round(score, 4)


def build_match_reason(caption: str | None, reference_keywords: set[str],
                       score: float, view_count: int) -> str:
    """Generate a human-readable match reason."""
    views_str = f"{view_count:,}" if view_count else "0"

    if not caption:
        return f"Viral content \u2014 {views_str} views"

    reel_words = set(_tokenise(caption))
    matching = reel_words & reference_keywords
    top_matches = sorted(matching, key=len, reverse=True)[:3]

    if top_matches:
        return f"Matches your content: {', '.join(top_matches)} \u2014 {views_str} views"
    elif score > 0.6:
        return f"High-performing similar content \u2014 {views_str} views"
    else:
        return f"Trending in your niche \u2014 {views_str} views"


def _load_page_profile(session, page_id: str) -> dict:
    """Fetch the newest page_profiles row for a user_page_id as a dict."""
    row = session.execute(
        text(
            """
            SELECT up.ig_username, up.page_type,
                   pp.niche_primary, pp.top_topics, pp.content_style,
                   pp.raw_analysis
            FROM user_pages up
            LEFT JOIN LATERAL (
                SELECT niche_primary, top_topics, content_style, raw_analysis
                FROM page_profiles
                WHERE user_page_id = up.id
                ORDER BY analyzed_at DESC LIMIT 1
            ) pp ON true
            WHERE up.id = :pid
            """
        ),
        {"pid": page_id},
    ).fetchone()
    if not row:
        return {}

    topics = row.top_topics
    if isinstance(topics, str):
        try:
            topics = json.loads(topics)
        except Exception:
            topics = []
    elif not isinstance(topics, list):
        topics = []

    raw = row.raw_analysis
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if not isinstance(raw, dict):
        raw = None

    return {
        "id": page_id,
        "username": row.ig_username or "",
        "page_type": row.page_type,
        "niche_primary": row.niche_primary,
        "top_topics": topics,
        "content_style": row.content_style,
        "raw_analysis": raw,
    }


def _load_reference_reel_captions(session, ref_page_ids: list[str],
                                  limit_per_page: int = 50) -> list[str]:
    """Load captions from reference pages' reels (user_page_reels table).

    Falls back to viral_reels if the reference page shares a username with
    a theme page that has scraped reels.
    """
    captions: list[str] = []

    if not ref_page_ids:
        return captions

    # Try user_page_reels first (direct reel cache for user pages)
    for page_id in ref_page_ids:
        rows = session.execute(
            text(
                """
                SELECT caption FROM user_page_reels
                WHERE user_page_id = :pid AND caption IS NOT NULL AND caption != ''
                ORDER BY view_count DESC NULLS LAST
                LIMIT :lim
                """
            ),
            {"pid": page_id, "lim": limit_per_page},
        ).fetchall()
        for r in rows:
            captions.append(r.caption)

    # If we got very few captions, also try matching reference usernames
    # against theme_pages -> viral_reels for additional signal.
    if len(captions) < 20:
        for page_id in ref_page_ids:
            rows = session.execute(
                text(
                    """
                    SELECT vr.caption
                    FROM viral_reels vr
                    JOIN theme_pages tp ON tp.id = vr.theme_page_id
                    JOIN user_pages up ON LOWER(up.ig_username) = LOWER(tp.ig_username)
                    WHERE up.id = :pid
                      AND vr.caption IS NOT NULL AND vr.caption != ''
                    ORDER BY vr.view_count DESC
                    LIMIT :lim
                    """
                ),
                {"pid": page_id, "lim": limit_per_page},
            ).fetchall()
            for r in rows:
                captions.append(r.caption)

    return captions


def _generate_for_page(user_page_id: str) -> dict:
    with get_session() as session:
        # ── 1. Load own page profile ────────────────────────────
        own_profile = _load_page_profile(session, user_page_id)
        if not own_profile:
            logger.info("user_page=%s not found", user_page_id)
            return {"inserted": 0, "pool_size": 0, "signature_size": 0}

        # Find the user_id so we can locate sibling reference pages.
        user_row = session.execute(
            text("SELECT user_id FROM user_pages WHERE id = :pid"),
            {"pid": user_page_id},
        ).fetchone()
        user_id = str(user_row.user_id) if user_row else None

        # ── 2. Load ALL reference pages ─────────────────────────
        reference_profiles: list[dict] = []
        ref_page_ids: list[str] = []
        if user_id:
            ref_rows = session.execute(
                text(
                    """
                    SELECT id FROM user_pages
                    WHERE user_id = :uid AND page_type = 'reference' AND is_active = true
                    """
                ),
                {"uid": user_id},
            ).fetchall()
            for r in ref_rows:
                pid = str(r.id)
                ref_page_ids.append(pid)
                prof = _load_page_profile(session, pid)
                if prof:
                    reference_profiles.append(prof)

        # ── 3. Load reference pages' reel captions ──────────────
        ref_captions = _load_reference_reel_captions(session, ref_page_ids)

        # ── 4. Build combined keyword signature ─────────────────
        reference_keywords = build_reference_keywords(
            own_profile, reference_profiles, ref_captions,
        )

        logger.info(
            "Keyword signature for @%s + %d ref pages: %d keywords (sample: %s)",
            own_profile.get("username", "?"), len(reference_profiles),
            len(reference_keywords), sorted(reference_keywords)[:20],
        )

        # Scale target rec count by number of reference pages.
        target_recs = min(
            MAX_RECS,
            BASE_RECS + len(reference_profiles) * PER_REF_RECS,
        )

        # ── 5. Clear old recommendations ────────────────────────
        session.execute(
            text("DELETE FROM user_reel_recommendations WHERE user_page_id = :pid"),
            {"pid": user_page_id},
        )

        # ── 6. Pull candidate pool from viral_reels ─────────────
        # Over-fetch across progressive view floors so the scorer has
        # enough variety to find genuine matches.
        candidates: list = []
        seen_ids: set[str] = set()
        for floor in VIEW_FLOORS:
            rows = session.execute(
                text(
                    """
                    SELECT id, caption, view_count, like_count, comment_count,
                           duration_seconds, ig_url, theme_page_id, posted_at
                    FROM viral_reels
                    WHERE view_count >= :floor
                      AND thumbnail_url IS NOT NULL AND thumbnail_url != ''
                    ORDER BY view_count DESC
                    LIMIT :lim
                    """
                ),
                {"floor": floor, "lim": 2000},
            ).fetchall()
            for r in rows:
                rid = str(r.id)
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                candidates.append(r)
            # Stop once we have a healthy pool
            if len(candidates) >= 3000:
                break

        if not candidates:
            logger.warning("No candidates in viral_reels pool")
            return {"inserted": 0, "pool_size": 0, "signature_size": len(reference_keywords)}

        # ── 7. Score every candidate ────────────────────────────
        scored: list[tuple[float, object]] = []
        for c in candidates:
            s = score_reel(
                caption=c.caption,
                view_count=c.view_count or 0,
                like_count=c.like_count or 0,
                comment_count=c.comment_count or 0,
                posted_at=c.posted_at,
                reference_keywords=reference_keywords,
            )
            scored.append((s, c))

        # Sort by score descending, tie-break by views.
        scored.sort(key=lambda x: (-x[0], -(x[1].view_count or 0)))

        # ── 8. Diversify sources ────────────────────────────────
        # Enforce max reels per theme page so one account doesn't dominate.
        final_recs: list[tuple[float, object]] = []
        page_counts: dict[str, int] = defaultdict(int)

        for s, reel in scored:
            page_id = str(reel.theme_page_id) if reel.theme_page_id else "unknown"
            if page_counts[page_id] >= MAX_PER_PAGE:
                continue
            final_recs.append((s, reel))
            page_counts[page_id] += 1
            if len(final_recs) >= target_recs:
                break

        # ── 9. Insert recommendations ───────────────────────────
        inserted = 0
        for final_score, reel in final_recs:
            reason = build_match_reason(
                caption=reel.caption,
                reference_keywords=reference_keywords,
                score=final_score,
                view_count=reel.view_count or 0,
            )

            # Compute matched keywords for the factors blob
            reel_tokens = set(_tokenise(reel.caption)) if reel.caption else set()
            matched_kw = sorted(reel_tokens & reference_keywords)

            factors = {
                "matched_keywords": matched_kw[:10],
                "view_count": reel.view_count,
                "like_count": reel.like_count,
                "comment_count": reel.comment_count,
                "engagement_ratio": round(
                    ((reel.like_count or 0) + (reel.comment_count or 0))
                    / max(reel.view_count or 1, 1), 4
                ),
                "signature_size": len(reference_keywords),
                "target_recs": target_recs,
                "reference_pages": len(reference_profiles),
                "source_pages": len(page_counts),
            }
            session.execute(
                text(
                    """
                    INSERT INTO user_reel_recommendations (
                        id, user_page_id, viral_reel_id,
                        match_score, match_reason, match_factors
                    )
                    VALUES (:id, :pid, :rid, :score, :reason, CAST(:factors AS JSONB))
                    ON CONFLICT DO NOTHING
                    """
                ),
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

        kw_matched = sum(1 for s, _ in scored if s > 0.1)
        logger.info(
            "Inserted %d/%d recs for %s (%d scored above 0.1, %d ref pages, %d source pages)",
            inserted, target_recs, user_page_id,
            kw_matched, len(reference_profiles), len(page_counts),
        )

    return {
        "inserted": inserted,
        "target_recs": target_recs,
        "pool_size": len(candidates),
        "signature_size": len(reference_keywords),
        "scored_above_threshold": kw_matched,
        "reference_pages": len(reference_profiles),
        "source_pages": len(page_counts),
    }


@app.task(name="tasks.recommendation.generate_recommendations_task", bind=True, max_retries=2)
def generate_recommendations_task(self, user_page_id: str):
    logger.info("Generating recommendations for user_page=%s", user_page_id)
    job_id = str(uuid.uuid4())
    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO jobs (id, celery_task_id, job_type, status,
                    reference_id, reference_type, started_at)
                VALUES (:id, :task_id, 'generate_recommendations', 'running',
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

    try:
        result = _generate_for_page(user_page_id)
    except Exception as exc:
        logger.error("Recommendation generation failed: %s", exc, exc_info=True)
        with get_session() as session:
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
        raise self.retry(exc=exc, countdown=120)

    with get_session() as session:
        session.execute(
            text(
                """
                UPDATE jobs SET status = 'success', finished_at = :now
                WHERE id = :id
                """
            ),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )

    logger.info("Recs for %s: %s", user_page_id, result)
    return result


@app.task(name="tasks.recommendation.refresh_all_pages", bind=True)
def refresh_all_pages(self):
    """Beat-triggered: regenerate recs for every active user page.

    Keeps feeds fresh as the viral_reels pool grows.
    """
    with get_session() as session:
        rows = session.execute(
            text("SELECT id FROM user_pages WHERE is_active = true"),
        ).fetchall()

    total = 0
    for row in rows:
        try:
            generate_recommendations_task.delay(str(row.id))
            total += 1
        except Exception as exc:
            logger.warning("Failed to queue recs for %s: %s", row.id, exc)

    return {"queued": total}
