"""
Theme page heuristic evaluation and quality gate.
Scores candidates on 7 signals to determine if they are theme pages.
"""
import logging
import os
import random
import re
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Heuristic signals
THEME_PAGE_KEYWORDS = {
    "dm for promo", "business inquiries", "ad placements", "collab",
    "promotions", "paid partnerships", "contact for promo", "brand deals",
    "submit your content", "tag us", "feature page", "repost",
    "daily content", "daily posts", "curated content",
}

NICHE_USERNAME_KEYWORDS = {
    "business", "money", "wealth", "fitness", "gym", "beauty", "motivation",
    "success", "luxury", "mindset", "hustle", "grind", "crypto", "invest",
    "fashion", "style", "food", "recipe", "travel", "comedy", "funny",
    "tech", "ai", "entrepreneur", "lifestyle", "health",
}

DISQUALIFYING_BIO_PATTERNS = [
    r"(my|personal)\s+(journey|brand|life|story)",
    r"(actor|actress|singer|artist|comedian|influencer)\b",
    r"(dm me|link in bio|linktree)\b",  # common but not disqualifying alone
]


def _random_delay(min_s: float = 1.0, max_s: float = 3.0):
    time.sleep(random.uniform(min_s, max_s))


def evaluate_candidate(username: str) -> Dict[str, Any]:
    """
    Evaluate a candidate username against 7 heuristic signals.
    Returns dict with score (0-7), breakdown, and bio_text.
    """
    score = 0
    breakdown = {}
    bio_text = ""

    try:
        profile_data = _fetch_profile_metadata(username)
        bio_text = profile_data.get("bio", "")
        follower_count = profile_data.get("followers", 0)
        post_count = profile_data.get("posts", 0)
        is_verified = profile_data.get("is_verified", False)
        full_name = profile_data.get("full_name", "")

        # Signal 1: Username is generic/topical
        username_lower = username.lower()
        if any(kw in username_lower for kw in NICHE_USERNAME_KEYWORDS):
            score += 1
            breakdown["niche_username"] = True
        else:
            breakdown["niche_username"] = False

        # Signal 2: Bio contains theme page keywords
        bio_lower = bio_text.lower()
        if any(kw in bio_lower for kw in THEME_PAGE_KEYWORDS):
            score += 1
            breakdown["theme_bio_keywords"] = True
        else:
            breakdown["theme_bio_keywords"] = False

        # Signal 3: Profile picture is likely a logo (heuristic: no personal name in display name)
        name_words = full_name.lower().split()
        looks_like_person = len(name_words) == 2 and all(w.isalpha() and len(w) > 2 for w in name_words)
        if not looks_like_person:
            score += 1
            breakdown["non_personal_name"] = True
        else:
            breakdown["non_personal_name"] = False

        # Signal 4: High posting frequency (estimate: posts / account age)
        if post_count >= 100:
            score += 1
            breakdown["high_post_count"] = True
        else:
            breakdown["high_post_count"] = False

        # Signal 5: Username contains niche keywords (different from signal 1 — checks full_name too)
        combined = f"{username_lower} {full_name.lower()}"
        niche_keyword_count = sum(1 for kw in NICHE_USERNAME_KEYWORDS if kw in combined)
        if niche_keyword_count >= 2:
            score += 1
            breakdown["strong_niche_signals"] = True
        else:
            breakdown["strong_niche_signals"] = False

        # Signal 6: Not a personal brand (no consistent face reference)
        has_personal_indicators = False
        for pattern in DISQUALIFYING_BIO_PATTERNS[:2]:  # Only check strong disqualifiers
            if re.search(pattern, bio_lower):
                has_personal_indicators = True
                break
        if not has_personal_indicators and not is_verified:
            score += 1
            breakdown["not_personal_brand"] = True
        else:
            breakdown["not_personal_brand"] = False

        # Signal 7: Has substantial following (theme pages usually have 10K+)
        if follower_count >= 10000:
            score += 1
            breakdown["substantial_following"] = True
        else:
            breakdown["substantial_following"] = False

        # Disqualifying checks
        if is_verified and looks_like_person:
            score = min(score, 2)  # Hard cap for verified personal accounts
            breakdown["disqualified_verified_personal"] = True

        if post_count < 10:
            score = 0  # Too new
            breakdown["disqualified_too_few_posts"] = True

    except Exception as e:
        logger.warning("Evaluation failed for @%s: %s", username, e)
        breakdown["error"] = str(e)

    return {
        "username": username,
        "score": score,
        "breakdown": breakdown,
        "bio_text": bio_text,
    }


def _fetch_profile_metadata(username: str) -> Dict[str, Any]:
    """Fetch basic profile metadata using instaloader."""
    try:
        import instaloader
        L = instaloader.Instaloader(
            download_videos=False, download_video_thumbnails=False,
            download_geotags=False, download_comments=False,
            save_metadata=False, quiet=True,
        )
        _random_delay()
        profile = instaloader.Profile.from_username(L.context, username)
        return {
            "bio": profile.biography or "",
            "followers": profile.followers,
            "posts": profile.mediacount,
            "is_verified": profile.is_verified,
            "full_name": profile.full_name or "",
            "is_private": profile.is_private,
        }
    except Exception as e:
        logger.warning("Failed to fetch profile for @%s: %s", username, e)
        return {"bio": "", "followers": 0, "posts": 0, "is_verified": False, "full_name": ""}


def quality_gate_check(username: str) -> Dict[str, Any]:
    """
    Quick-scrape last 20 reels and check viral hit rate.
    Returns dict with passes (bool), viral_rate, avg_views, total_reels.
    """
    try:
        from lib.instagram import scrape_profile

        videos = scrape_profile(username, max_posts=20)
        if not videos:
            return {"passes": False, "viral_rate": 0.0, "avg_views": 0, "total_reels": 0}

        total_views = sum(v.view_count for v in videos)
        avg_views = total_views // len(videos) if videos else 0
        viral_count = sum(1 for v in videos if v.view_count >= 100000)
        viral_rate = viral_count / len(videos) if videos else 0.0

        min_viral_rate = float(os.environ.get("QUALITY_GATE_MIN_VIRAL_RATE", "0.10"))
        min_threshold = int(os.environ.get("DEFAULT_VIEW_THRESHOLD", "500000"))

        has_viral = any(v.view_count >= min_threshold for v in videos)
        passes = has_viral and viral_rate >= min_viral_rate

        return {
            "passes": passes,
            "viral_rate": round(viral_rate, 3),
            "avg_views": avg_views,
            "total_reels": len(videos),
            "viral_count": viral_count,
        }

    except Exception as e:
        logger.warning("Quality gate check failed for @%s: %s", username, e)
        return {"passes": False, "viral_rate": 0.0, "avg_views": 0, "total_reels": 0}
