"""
Google Video search using SerpAPI.
"""

import logging
import os
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"


def search_google_video(keywords: str, max_results: int = 10) -> List[Dict]:
    """
    Search Google Videos for matching content using SerpAPI.

    Args:
        keywords: Search query string.
        max_results: Maximum results to return.

    Returns:
        List of dicts with: source_type, url, title, thumbnail_url, resolution, duration.
    """
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        logger.error("SERPAPI_KEY not set")
        return []

    params = {
        "engine": "google_videos",
        "q": keywords,
        "num": min(max_results, 20),
        "api_key": api_key,
    }

    try:
        resp = requests.get(SERPAPI_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("SerpAPI request failed: %s", exc)
        return []

    video_results = data.get("video_results", [])
    results: List[Dict] = []

    for item in video_results[:max_results]:
        link = item.get("link", "")
        if not link:
            continue

        # Determine source type from URL
        source_type = "web"
        if "youtube.com" in link or "youtu.be" in link:
            source_type = "youtube"
        elif "tiktok.com" in link:
            source_type = "tiktok"
        elif "instagram.com" in link:
            source_type = "instagram"
        elif "vimeo.com" in link:
            source_type = "vimeo"

        # Parse duration string like "2:30" to seconds
        duration_str = item.get("duration", "")
        duration = _parse_duration_string(duration_str)

        results.append({
            "source_type": source_type,
            "url": link,
            "title": item.get("title", ""),
            "thumbnail_url": item.get("thumbnail", {}).get("static", "") if isinstance(item.get("thumbnail"), dict) else "",
            "resolution": "",
            "duration": duration,
        })

    logger.info("Google Video search returned %d results for: %s", len(results), keywords)
    return results


def _parse_duration_string(duration_str: str) -> float:
    """Parse duration strings like '2:30', '1:05:30' to seconds."""
    if not duration_str:
        return 0.0
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 3:
            return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
        elif len(parts) == 2:
            return float(int(parts[0]) * 60 + int(parts[1]))
        elif len(parts) == 1:
            return float(int(parts[0]))
    except (ValueError, TypeError):
        pass
    return 0.0
