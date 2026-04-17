"""
YouTube Data API v3 search for finding source videos.
"""

import logging
import os
import re
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"


def _parse_iso8601_duration(duration_str: str) -> float:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    if not duration_str:
        return 0.0
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration_str,
    )
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return float(hours * 3600 + minutes * 60 + seconds)


def search_youtube(keywords: str, max_results: int = 10) -> List[Dict]:
    """
    Search YouTube for videos matching keywords.

    Args:
        keywords: Search query string.
        max_results: Maximum results to return (max 50 per API page).

    Returns:
        List of dicts with: source_type, url, title, thumbnail_url, resolution, duration.
    """
    api_key = os.environ.get("YOUTUBE_DATA_API_KEY")
    if not api_key:
        logger.error("YOUTUBE_DATA_API_KEY not set")
        return []

    # Step 1: Search for video IDs
    search_params = {
        "part": "snippet",
        "q": keywords,
        "type": "video",
        "maxResults": min(max_results, 50),
        "order": "relevance",
        "key": api_key,
    }

    try:
        resp = requests.get(YOUTUBE_API_URL, params=search_params, timeout=15)
        resp.raise_for_status()
        search_data = resp.json()
    except requests.RequestException as exc:
        logger.error("YouTube search API failed: %s", exc)
        return []

    items = search_data.get("items", [])
    if not items:
        logger.info("YouTube search returned 0 results for: %s", keywords)
        return []

    video_ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]

    # Step 2: Get video details (duration, resolution)
    details_params = {
        "part": "contentDetails,snippet",
        "id": ",".join(video_ids),
        "key": api_key,
    }

    video_details = {}
    try:
        resp = requests.get(YOUTUBE_VIDEO_URL, params=details_params, timeout=15)
        resp.raise_for_status()
        details_data = resp.json()
        for item in details_data.get("items", []):
            vid = item["id"]
            duration_iso = item.get("contentDetails", {}).get("duration", "")
            definition = item.get("contentDetails", {}).get("definition", "sd")
            video_details[vid] = {
                "duration": _parse_iso8601_duration(duration_iso),
                "resolution": "1080p" if definition == "hd" else "720p",
            }
    except requests.RequestException as exc:
        logger.warning("YouTube video details API failed: %s", exc)

    # Step 3: Build results
    results = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            continue

        snippet = item.get("snippet", {})
        details = video_details.get(video_id, {})

        results.append({
            "source_type": "youtube",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "resolution": details.get("resolution", ""),
            "duration": details.get("duration", 0.0),
        })

    logger.info("YouTube search returned %d results for: %s", len(results), keywords)
    return results
