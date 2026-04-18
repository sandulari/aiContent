"""
Instagram API integration via RapidAPI.
Handles profile scraping, reel fetching, and suggested accounts.
"""
import asyncio
import os
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "instagram-api-fast-reliable-data-scraper.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"

HEADERS = {
    "x-rapidapi-host": RAPIDAPI_HOST,
    "x-rapidapi-key": RAPIDAPI_KEY,
    "Content-Type": "application/json",
}


async def _request_with_retry(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response | None:
    """Make an HTTP request with retry on 429 (rate limit)."""
    for attempt in range(3):
        resp = await client.request(method, url, **kwargs)
        if resp.status_code == 429:
            wait = min(2 ** attempt * 5, 30)
            logger.warning("RapidAPI 429 rate limited, retrying in %ds (attempt %d/3)", wait, attempt + 1)
            await asyncio.sleep(wait)
            continue
        return resp
    return resp


async def get_profile(username: str) -> dict | None:
    """Get Instagram profile data by username."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await _request_with_retry(client, "GET", f"{BASE_URL}/profile", params={"username": username}, headers=HEADERS)
            if not resp or resp.status_code != 200:
                logger.warning("Profile fetch failed for @%s: HTTP %s", username, resp.status_code if resp else "no response")
                return None
            data = resp.json()
            if not data.get("username"):
                return None
            return data
    except Exception as e:
        logger.error("Profile fetch error for @%s: %s", username, e)
        return None


async def get_user_reels(user_id: str | int, max_pages: int = 5) -> list[dict]:
    """Get reels for a user with pagination. Fetches up to max_pages * 12 reels."""
    all_reels = []
    max_id = ""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for page in range(max_pages):
                params = {"user_id": str(user_id)}
                if max_id:
                    params["max_id"] = max_id

                resp = await _request_with_retry(client, "GET", f"{BASE_URL}/reels", params=params, headers=HEADERS)
                if not resp or resp.status_code != 200:
                    logger.warning("Reels fetch failed for user %s page %d: HTTP %s", user_id, page, resp.status_code if resp else "no response")
                    break

                data = resp.json()
                items = data.get("data", {}).get("items", [])
                paging = data.get("data", {}).get("paging_info", {})

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

                    all_reels.append({
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

                if not paging.get("more_available"):
                    break
                max_id = paging.get("max_id", "")
                if not max_id:
                    break

                # Small delay between pages to avoid rate limits
                import asyncio
                await asyncio.sleep(1)

            logger.info("Fetched %d reels for user %s (%d pages)", len(all_reels), user_id, page + 1)
    except Exception as e:
        logger.error("Reels fetch error for user %s: %s", user_id, e)
    return all_reels


async def get_suggested_accounts(user_id: str | int) -> list[dict]:
    """Get suggested/similar accounts for a user."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await _request_with_retry(client, "GET", f"{BASE_URL}/discover_chaining", params={"user_id": str(user_id)}, headers=HEADERS)
            if not resp or resp.status_code != 200:
                return []
            data = resp.json()
            users = data.get("users", []) or data.get("data", [])
            return [{"username": u.get("username", ""), "pk": u.get("pk", ""), "full_name": u.get("full_name", "")} for u in users if u.get("username")]
    except Exception as e:
        logger.error("Suggested accounts error: %s", e)
        return []
