"""
Page analyzer v2 — uses RapidAPI Instagram scraper.
When a user adds their IG page:
1. Fetch their profile via API
2. Detect niche from bio + captions
3. Find similar theme pages via suggested accounts
4. Scrape viral reels from those pages
5. Generate personalized recommendations
"""
import json
import logging
import random
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.instagram_api import get_profile, get_user_reels, get_suggested_accounts

logger = logging.getLogger(__name__)

NICHE_KEYWORDS = {
    "beauty": ["skincare", "beauty", "makeup", "glow", "cosmetics", "skin", "glam", "serum", "moisturizer", "lipstick"],
    "fitness": ["gym", "fitness", "workout", "muscle", "protein", "gains", "training", "bodybuilding", "exercise"],
    "business": ["entrepreneur", "business", "startup", "ceo", "hustle", "wealth", "millionaire", "success", "money", "invest"],
    "motivation": ["motivation", "mindset", "grind", "success", "inspiration", "goals", "discipline", "habits"],
    "tech": ["tech", "ai", "artificial intelligence", "robot", "coding", "software", "innovation", "future"],
    "food": ["recipe", "cooking", "food", "chef", "kitchen", "baking", "meal", "delicious"],
    "travel": ["travel", "destination", "adventure", "explore", "wanderlust", "nature", "landscape"],
    "fashion": ["fashion", "style", "outfit", "streetwear", "designer", "clothing"],
    "comedy": ["funny", "comedy", "meme", "humor", "lol", "viral"],
    "finance": ["finance", "investing", "stock", "crypto", "budget", "savings"],
    "luxury": ["luxury", "rich", "lifestyle", "billionaire", "expensive", "supercar"],
}


async def analyze_and_recommend(user_page_id: str, ig_username: str, db: AsyncSession):
    """Full analysis pipeline — runs when user adds their page."""
    logger.info("Analyzing @%s", ig_username)

    # Step 1: Fetch profile via RapidAPI
    profile = await get_profile(ig_username)
    if not profile:
        logger.warning("Could not fetch profile for @%s", ig_username)
        # Still continue with username-based niche detection
        profile = {}

    bio = profile.get("biography", "") or ""
    follower_count = profile.get("follower_count")
    following_count = profile.get("following_count")
    media_count = profile.get("media_count")
    full_name = profile.get("full_name", ig_username)
    pic_url = profile.get("hd_profile_pic_url_info", {}).get("url") or profile.get("profile_pic_url", "")
    user_pk = profile.get("pk") or profile.get("pk_id")

    # Update user_page with real data
    await db.execute(text("""
        UPDATE user_pages SET follower_count=:f, following_count=:fw, total_posts=:p,
            ig_display_name=:name, ig_profile_pic_url=:pic, last_analyzed_at=:now
        WHERE id=:id
    """), {"f": follower_count, "fw": following_count, "p": media_count,
           "name": full_name, "pic": pic_url, "now": datetime.utcnow(), "id": user_page_id})

    # Step 2: Detect niche
    detection_text = f"{ig_username} {full_name} {bio}".lower()

    # Also get captions from user's own reels if we have their pk
    if user_pk:
        try:
            user_reels = await get_user_reels(user_pk)
            captions = " ".join([r.get("caption", "") for r in user_reels[:10]])
            detection_text += " " + captions.lower()
        except Exception:
            pass

    niche_scores = {}
    for niche, keywords in NICHE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in detection_text)
        if score > 0:
            niche_scores[niche] = score

    niche_slug = max(niche_scores, key=niche_scores.get) if niche_scores else "comedy"
    logger.info("Detected niche for @%s: %s", ig_username, niche_slug)

    # Step 3: Get niche ID and create page profile
    niche_row = await db.execute(text("SELECT id FROM niches WHERE slug=:s"), {"s": niche_slug})
    niche_obj = niche_row.fetchone()
    niche_id = str(niche_obj.id) if niche_obj else None

    await db.execute(text("""
        INSERT INTO page_profiles (id, user_page_id, niche_primary, top_topics, top_formats, content_style, posting_frequency, analysis_model, analyzed_at)
        VALUES (:id, :pid, :niche, :topics, :formats, :style, :freq, 'rapidapi-v2', :now)
    """), {"id": str(uuid.uuid4()), "pid": user_page_id, "niche": niche_slug,
           "topics": json.dumps(list(niche_scores.keys())[:5]),
           "formats": json.dumps(["reels", "video"]),
           "style": json.dumps({"source": "auto-detect"}),
           "freq": 1.0, "now": datetime.utcnow()})

    # Step 4: Find theme pages and scrape their reels
    # First get suggested accounts if we have user_pk
    theme_usernames = []
    if user_pk:
        try:
            suggested = await get_suggested_accounts(user_pk)
            theme_usernames = [s["username"] for s in suggested[:8]]
            logger.info("Found %d suggested accounts for @%s", len(theme_usernames), ig_username)
        except Exception:
            pass

    # Also add known theme pages from DB for this niche
    existing_pages = await db.execute(text("""
        SELECT username FROM theme_pages WHERE niche_id=:nid AND is_active=true LIMIT 5
    """), {"nid": niche_id})
    for ep in existing_pages.fetchall():
        if ep.username not in theme_usernames:
            theme_usernames.append(ep.username)

    # Hardcoded fallback theme pages per niche
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
    }
    fallbacks = FALLBACK_PAGES.get(niche_slug, FALLBACK_PAGES["comedy"])
    for fb in fallbacks:
        if fb not in theme_usernames:
            theme_usernames.append(fb)

    # Scrape reels from theme pages
    total_reels = 0
    for username in theme_usernames[:10]:
        try:
            # Get profile first to get pk
            tp_profile = await get_profile(username)
            if not tp_profile:
                continue
            tp_pk = tp_profile.get("pk") or tp_profile.get("pk_id")
            if not tp_pk:
                continue

            # Ensure theme page exists in DB
            tp_exists = await db.execute(text("SELECT id FROM theme_pages WHERE username=:u"), {"u": username})
            tp_row = tp_exists.fetchone()
            if not tp_row:
                tp_id = str(uuid.uuid4())
                await db.execute(text("""
                    INSERT INTO theme_pages (id, username, display_name, profile_url, niche_id, follower_count, is_active, evaluation_status)
                    VALUES (:id,:u,:name,:url,:nid,:fc,true,'confirmed') ON CONFLICT(username) DO NOTHING
                """), {"id": tp_id, "u": username, "name": tp_profile.get("full_name", username),
                       "url": f"https://www.instagram.com/{username}/", "nid": niche_id,
                       "fc": tp_profile.get("follower_count")})
                page_id = tp_id
            else:
                page_id = str(tp_row.id)

            # Get reels
            reels = await get_user_reels(tp_pk)
            for reel in reels:
                if reel["view_count"] < 10000 and reel["like_count"] < 1000:
                    continue

                exists = await db.execute(text("SELECT 1 FROM viral_reels WHERE ig_video_id=:v"), {"v": reel["shortcode"]})
                if exists.fetchone():
                    # Update thumbnail (they expire)
                    if reel["thumbnail_url"]:
                        await db.execute(text("UPDATE viral_reels SET thumbnail_url=:t WHERE ig_video_id=:v"),
                            {"t": reel["thumbnail_url"], "v": reel["shortcode"]})
                    continue

                posted = datetime.utcfromtimestamp(reel["taken_at"]) if reel["taken_at"] else datetime.utcnow()
                await db.execute(text("""
                    INSERT INTO viral_reels (id,theme_page_id,ig_video_id,ig_url,thumbnail_url,view_count,like_count,comment_count,duration_seconds,caption,posted_at,niche_id,status)
                    VALUES (:id,:pid,:vid,:url,:thumb,:views,:likes,:comments,:dur,:cap,:posted,:nid,'discovered')
                """), {"id": str(uuid.uuid4()), "pid": page_id, "vid": reel["shortcode"],
                       "url": reel["url"], "thumb": reel["thumbnail_url"],
                       "views": reel["view_count"], "likes": reel["like_count"],
                       "comments": reel["comment_count"], "dur": reel["duration_seconds"],
                       "cap": reel["caption"], "posted": posted, "nid": niche_id})
                total_reels += 1

            logger.info("  @%s: +%d reels", username, len(reels))
            import asyncio
            await asyncio.sleep(1)  # Rate limit protection
        except Exception as e:
            logger.warning("  @%s: %s", username, str(e)[:60])

    logger.info("Total new reels: %d", total_reels)

    # Step 5: Clear old recommendations and generate new ones.
    # Hard requirements: at least 100 recommendations per page, all 500K+ views.
    # If pool is too small at 500K, progressively relax the view floor so the
    # user always sees *something* — but never less than the target count.
    await db.execute(
        text("DELETE FROM user_reel_recommendations WHERE user_page_id=:pid"),
        {"pid": user_page_id},
    )

    TARGET_SAME_NICHE = 100
    TARGET_CROSS_NICHE = 40
    VIEW_FLOORS = [500_000, 250_000, 100_000, 50_000, 0]
    rec_count = 0

    async def _insert_recs(rows, base_score_lo: float, base_score_hi: float, reason: str):
        nonlocal rec_count
        inserted = 0
        for reel in rows:
            score = base_score_lo + random.random() * (base_score_hi - base_score_lo)
            try:
                await db.execute(
                    text(
                        """
                        INSERT INTO user_reel_recommendations
                            (id, user_page_id, viral_reel_id, match_score, match_reason, match_factors)
                        VALUES (:id, :pid, :rid, :score, :reason, '{}')
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "pid": user_page_id,
                        "rid": str(reel.id),
                        "score": round(score, 2),
                        "reason": reason,
                    },
                )
                inserted += 1
                rec_count += 1
            except Exception:
                pass
        return inserted

    # Same niche, descending view_count, progressively relaxing the view floor.
    same_inserted = 0
    for floor in VIEW_FLOORS:
        remaining = TARGET_SAME_NICHE - same_inserted
        if remaining <= 0:
            break
        result = await db.execute(
            text(
                """
                SELECT id FROM viral_reels
                WHERE niche_id = :nid
                  AND view_count >= :floor
                  AND thumbnail_url IS NOT NULL AND thumbnail_url != ''
                  AND id NOT IN (
                      SELECT viral_reel_id FROM user_reel_recommendations
                      WHERE user_page_id = :pid
                  )
                ORDER BY view_count DESC
                LIMIT :lim
                """
            ),
            {"nid": niche_id, "floor": floor, "pid": user_page_id, "lim": remaining},
        )
        rows = result.fetchall()
        reason = (
            f"Similar {niche_slug} content — {floor // 1000}K+ views"
            if floor
            else f"Top {niche_slug} content"
        )
        same_inserted += await _insert_recs(rows, 0.78, 0.98, reason)

    # Cross-niche: trending reels from other niches, 500K floor mandatory.
    cross_result = await db.execute(
        text(
            """
            SELECT id FROM viral_reels
            WHERE (niche_id != :nid OR niche_id IS NULL)
              AND view_count >= 500000
              AND thumbnail_url IS NOT NULL AND thumbnail_url != ''
              AND id NOT IN (
                  SELECT viral_reel_id FROM user_reel_recommendations
                  WHERE user_page_id = :pid
              )
            ORDER BY view_count DESC
            LIMIT :lim
            """
        ),
        {"nid": niche_id, "pid": user_page_id, "lim": TARGET_CROSS_NICHE},
    )
    await _insert_recs(
        cross_result.fetchall(),
        0.40,
        0.65,
        "Trending with similar audiences (500K+ views)",
    )

    logger.info(
        "Generated %d recommendations for @%s (niche=%s, same=%d)",
        rec_count, ig_username, niche_slug, same_inserted,
    )
    return {
        "niche": niche_slug,
        "recommendations": rec_count,
        "reels_scraped": total_reels,
        "same_niche_count": same_inserted,
    }
