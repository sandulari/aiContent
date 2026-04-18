"""Recommendation generator — semantic match between user's page and viral reels.

The old version trusted `viral_reels.niche_id`, which is contaminated: that
column stores whatever niche the *first user who scraped the theme page*
detected, not the reel's actual content. As a result, searching "give me
all reels where niche_id = tech" returned a dumping ground of unrelated
videos that someone at some point labeled 'tech'.

The new ranker ignores niche_id and scores each candidate reel by actual
caption-level word overlap with a keyword *signature* built from the
user's own page (ig_username + bio + the captions of their last ~20
reels). A reel that mentions "entrepreneur", "hustle", and "startup" in
its caption gets a high score for @entrepreneuriallogyy. A random cat
video gets 0 overlap and never shows up.

Target: at least 100 reels with 500K+ views, ranked by relevance then
view count.
"""
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from lib import claude_client
from lib.db import get_session

logger = logging.getLogger(__name__)

# Recommendation volume scales with reference-page count:
#   0 ref pages → 100 recs (just own page)
#   1 ref page → 200 recs
#   2 ref pages → 300 recs
#   cap → 500 recs
BASE_RECS = 500
PER_REF_RECS = 200
MAX_RECS = 1000

VIEW_FLOORS = [500_000, 250_000, 100_000, 50_000, 0]
# Number of top candidates we feed to Claude for re-ranking. More =
# better recommendations but more tokens per page.
CLAUDE_RERANK_TOP = 120

# Generic words that don't carry meaning. If every reel caption contains
# "the", "and", "i", "you" we can't use them to discriminate.
_STOPWORDS = {
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

# High-signal niche anchors. These don't drive detection directly —
# they're used as a seed for the user's signature if their captions
# happen to be too sparse or too noisy to yield good keywords on their own.
_NICHE_ANCHORS = {
    "business": ["entrepreneur", "business", "startup", "founder", "ceo",
                 "hustle", "wealth", "millionaire", "boss", "success",
                 "mindset", "grind", "empire", "brand", "scale"],
    "fitness": ["gym", "fitness", "workout", "muscle", "protein", "training",
                "bodybuilding", "shred", "lift", "cardio", "calisthenics"],
    "beauty": ["skincare", "beauty", "makeup", "glow", "cosmetics", "serum",
               "moisturizer", "lipstick", "foundation", "hair"],
    "money": ["money", "side hustle", "passive income", "invest", "stock",
              "crypto", "finance", "wealth", "portfolio", "dividend"],
    "fashion": ["fashion", "style", "outfit", "streetwear", "designer",
                "clothing", "ootd", "lookbook"],
    "food": ["recipe", "cooking", "food", "chef", "kitchen", "baking",
             "meal", "dish"],
    "travel": ["travel", "destination", "adventure", "explore", "wanderlust"],
    "comedy": ["funny", "comedy", "meme", "humor", "joke", "prank"],
    "motivation": ["motivation", "mindset", "grind", "inspiration", "goals",
                   "discipline", "habits", "growth"],
    "tech": ["tech", "software", "coding", "developer", "startup", "ai",
             "machine learning", "robotics"],
    "luxury": ["luxury", "rich", "mansion", "supercar", "yacht", "private jet"],
}


def _tokenise(text_blob: str) -> list[str]:
    """Return lowercased content tokens. Hashtags → their inner word, @mentions dropped."""
    if not text_blob:
        return []
    # Strip @mentions entirely — they're just account tags
    cleaned = re.sub(r"@\w+", " ", text_blob)
    # Turn hashtags into plain words
    cleaned = re.sub(r"#(\w+)", r"\1", cleaned)
    # Drop everything non-alphanumeric
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.lower())
    tokens = []
    for w in cleaned.split():
        wl = w.strip("_0123456789")
        if len(wl) < 3:
            continue
        if wl in _STOPWORDS:
            continue
        if wl.isdigit():
            continue
        tokens.append(wl)
    return tokens


def _build_signature(ig_username: str, niche: str | None, existing_topics: list) -> set[str]:
    """Assemble the set of keywords that describe this user's page.

    Prefers the user's own content (username + topics derived from their
    real captions) over hardcoded niche anchors, but falls back to anchors
    if nothing else is available.
    """
    keywords: set[str] = set()

    # 1. Username tokens (split on common separators).
    if ig_username:
        parts = re.split(r"[._\-]+", ig_username.lower())
        for p in parts:
            for token in _tokenise(p):
                if len(token) >= 4:
                    keywords.add(token)
        # Also try whole-username substring tokens for concatenated usernames
        # like "entrepreneuriallogyy" → pulls out "entrepreneur".
        full = ig_username.lower()
        for anchor_list in _NICHE_ANCHORS.values():
            for anchor in anchor_list:
                if " " in anchor:
                    continue
                if len(anchor) >= 5 and anchor in full:
                    keywords.add(anchor)

    # 2. Previously computed topics from page_profiles (which now stores
    # the keyword signature in JSONB).
    if isinstance(existing_topics, list):
        for t in existing_topics:
            if isinstance(t, str):
                for token in _tokenise(t):
                    keywords.add(token)

    # 3. Niche anchors — add the detected niche's seed words as a floor.
    if niche and niche in _NICHE_ANCHORS:
        for anchor in _NICHE_ANCHORS[niche]:
            if " " not in anchor:
                keywords.add(anchor)

    return keywords


def _score_reel(caption: str | None, view_count: int, signature: set[str]) -> tuple[float, list[str]]:
    """Return (score 0-1, list of matched keywords)."""
    if not caption:
        caption = ""
    tokens = set(_tokenise(caption))
    matches = sorted(signature & tokens)
    match_count = len(matches)

    # Text-overlap component: 0 matches → 0, 3+ matches → 0.85
    if match_count == 0:
        text_score = 0.0
    elif match_count == 1:
        text_score = 0.35
    elif match_count == 2:
        text_score = 0.6
    else:
        text_score = 0.85

    # View-count component: log-scaled, max ~0.15 at 10M+ views
    view_score = 0.0
    if view_count and view_count > 0:
        view_score = min(0.15, (math.log10(max(view_count, 10)) - 5) * 0.05)
        view_score = max(0.0, view_score)

    total = text_score + view_score

    # Floor anything with at least one keyword match at 0.4 so it's
    # clearly above unrelated content.
    if match_count >= 1:
        total = max(total, 0.4)

    return min(1.0, round(total, 3)), matches


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


def _profile_to_claude_dict(profile: dict) -> dict:
    """Convert a loaded page profile into the shape claude_client expects."""
    raw = profile.get("raw_analysis") or {}
    return {
        "username": profile.get("username", ""),
        "niche_primary": profile.get("niche_primary") or raw.get("niche_primary"),
        "topics": raw.get("topics") or [],
        "keyword_signature": profile.get("top_topics") or [],
        "target_audience": (raw.get("target_audience") if isinstance(raw, dict) else "") or "",
    }


def _generate_for_page(user_page_id: str) -> dict:
    with get_session() as session:
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

        # Load every reference page's profile so we can combine their
        # signatures. The target profile is (this page) + (all the user's
        # reference pages).
        reference_profiles: list[dict] = []
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
                prof = _load_page_profile(session, str(r.id))
                if prof and prof.get("top_topics"):
                    reference_profiles.append(prof)

        # Combine signatures: own page + all reference pages, deduped,
        # preserving order (own keywords first, then references).
        combined_signature: set[str] = set()
        ordered_sig: list[str] = []
        for keyword in own_profile.get("top_topics") or []:
            if isinstance(keyword, str):
                k = keyword.lower()
                if k not in combined_signature:
                    combined_signature.add(k)
                    ordered_sig.append(k)
        for rp in reference_profiles:
            for keyword in rp.get("top_topics") or []:
                if isinstance(keyword, str):
                    k = keyword.lower()
                    if k not in combined_signature:
                        combined_signature.add(k)
                        ordered_sig.append(k)

        ig_username = own_profile.get("username", "")
        niche_slug = own_profile.get("niche_primary")

        # Floor the combined signature with _build_signature so we still
        # get something useful if the page profiles are sparse.
        if len(combined_signature) < 5:
            combined_signature |= _build_signature(ig_username, niche_slug, ordered_sig)

        signature = combined_signature
        logger.info(
            "Combined signature for @%s (%s) + %d ref pages: %d keywords: %s",
            ig_username, niche_slug, len(reference_profiles),
            len(signature), sorted(signature)[:25],
        )

        # Scale target rec count by number of reference pages.
        target_recs = min(
            MAX_RECS,
            BASE_RECS + len(reference_profiles) * PER_REF_RECS,
        )

        # Clear old recommendations so we always show the freshest ranking.
        session.execute(
            text("DELETE FROM user_reel_recommendations WHERE user_page_id = :pid"),
            {"pid": user_page_id},
        )

        # Pull a large candidate pool across view floors, then rank in Python.
        # We over-fetch so the ranker has enough variety to find genuine matches.
        candidates: list = []
        seen_ids: set[str] = set()
        for floor in VIEW_FLOORS:
            rows = session.execute(
                text(
                    """
                    SELECT id, caption, view_count, like_count,
                           duration_seconds, ig_url
                    FROM viral_reels
                    WHERE view_count >= :floor
                      AND thumbnail_url IS NOT NULL AND thumbnail_url != ''
                    ORDER BY view_count DESC
                    LIMIT :lim
                    """
                ),
                {"floor": floor, "lim": 500},
            ).fetchall()
            for r in rows:
                rid = str(r.id)
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                candidates.append(r)
            # Stop once we've got enough variety
            if len(candidates) >= 500:
                break

        if not candidates:
            logger.warning("No candidates in viral_reels pool")
            return {"inserted": 0, "pool_size": 0, "signature_size": len(signature)}

        # Keyword-overlap score for every candidate.
        scored: list[tuple[float, list[str], object]] = []
        for c in candidates:
            score, matches = _score_reel(c.caption, c.view_count or 0, signature)
            scored.append((score, matches, c))

        # Primary sort: keyword-matched reels first, then by score/views.
        scored.sort(key=lambda x: (-(1 if x[1] else 0), -x[0], -(x[2].view_count or 0)))

        # Claude re-ranking on the top N keyword candidates. This is
        # what actually makes the engine smart — Claude reads each
        # candidate caption and decides whether it fits the target
        # creator's niche and style. Graceful fallback if disabled.
        claude_scores: dict[str, dict] = {}
        rerank_used = False
        if claude_client.is_enabled() and len(scored) >= 10:
            # Build a target profile merging own + references via Claude
            # when we have >1 page, else project the single profile.
            claude_inputs = [_profile_to_claude_dict(own_profile)] + [
                _profile_to_claude_dict(rp) for rp in reference_profiles
            ]
            target_profile = None
            try:
                target_profile = claude_client.synthesize_multi_page(claude_inputs)
            except Exception as exc:
                logger.warning("Claude synthesis failed: %s", exc)
            if not target_profile:
                # Fall back to the own-page profile shape directly.
                target_profile = claude_inputs[0]

            rerank_input = [
                {"id": str(c.id), "caption": (c.caption or "")[:180]}
                for _, _, c in scored[:CLAUDE_RERANK_TOP]
            ]
            try:
                claude_scores = claude_client.rank_reels(
                    target_profile=target_profile,
                    candidates=rerank_input,
                    batch_size=40,
                )
                rerank_used = bool(claude_scores)
                if rerank_used:
                    logger.info(
                        "Claude re-ranked %d/%d candidates",
                        len(claude_scores), len(rerank_input),
                    )
            except Exception as exc:
                logger.warning("Claude rank_reels failed: %s", exc)

        # Apply Claude scores where we have them: Claude score replaces
        # the keyword score for ranking but the keyword matches are
        # still surfaced in the reason so the user sees both signals.
        rescored: list[tuple[float, list[str], object, str | None]] = []
        for score, matches, reel in scored:
            rid = str(reel.id)
            claude_hit = claude_scores.get(rid)
            if claude_hit:
                final_score = (claude_hit["score"] * 0.75) + (score * 0.25)
                rescored.append((final_score, matches, reel, claude_hit.get("reason")))
            else:
                rescored.append((score, matches, reel, None))

        rescored.sort(
            key=lambda x: (
                -(1 if x[3] else 0),  # Claude-rated first
                -(1 if x[1] else 0),  # then keyword-matched
                -x[0],                # then by score
                -(x[2].view_count or 0),
            )
        )

        top = rescored[:target_recs]

        inserted = 0
        for final_score, matches, reel, claude_reason in top:
            if claude_reason:
                label = claude_reason[:180]
            elif matches:
                label = (
                    f"Matches your page: {', '.join(matches[:3])}"
                    if len(matches) > 1
                    else f"Matches your page: {matches[0]}"
                )
            else:
                label = "Trending right now"

            factors = {
                "matched_keywords": matches[:10],
                "view_count": reel.view_count,
                "signature_size": len(signature),
                "claude_ranked": claude_reason is not None,
                "target_recs": target_recs,
                "reference_pages": len(reference_profiles),
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
                    "score": max(0.1, float(final_score)),
                    "reason": label[:500],
                    "factors": json.dumps(factors),
                },
            )
            inserted += 1

        matched_count = sum(1 for s, m, _ in scored if m)
        logger.info(
            "Inserted %d/%d recs for %s (%d kw matches, %d Claude-scored, %d ref pages)",
            inserted, target_recs, user_page_id,
            matched_count, len(claude_scores), len(reference_profiles),
        )

    return {
        "inserted": inserted,
        "target_recs": target_recs,
        "pool_size": len(candidates),
        "signature_size": len(signature),
        "matched_candidates": matched_count,
        "claude_reranked": rerank_used,
        "reference_pages": len(reference_profiles),
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
