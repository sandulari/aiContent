"""
Stock footage search: Pexels and Pixabay APIs.
"""

import logging
import os
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)


def search_pexels(keywords: str, max_results: int = 5) -> List[Dict]:
    """
    Search Pexels for stock video footage.

    Args:
        keywords: Search query string.
        max_results: Maximum results to return.

    Returns:
        List of dicts with: source_type, url, title, thumbnail_url, resolution, duration.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        logger.error("PEXELS_API_KEY not set")
        return []

    headers = {"Authorization": api_key}
    params = {
        "query": keywords,
        "per_page": min(max_results, 80),
        "orientation": "portrait",
    }

    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Pexels API request failed: %s", exc)
        return []

    results: List[Dict] = []
    for video in data.get("videos", [])[:max_results]:
        # Find best quality video file
        video_files = video.get("video_files", [])
        best_file = None
        best_height = 0
        for vf in video_files:
            h = vf.get("height", 0) or 0
            if h > best_height:
                best_height = h
                best_file = vf

        download_url = best_file.get("link", "") if best_file else ""
        width = best_file.get("width", 0) if best_file else 0
        height = best_file.get("height", 0) if best_file else 0

        # Thumbnail from video_pictures
        pictures = video.get("video_pictures", [])
        thumbnail_url = pictures[0].get("picture", "") if pictures else ""

        results.append({
            "source_type": "pexels",
            "url": download_url or video.get("url", ""),
            "title": video.get("url", "").split("/")[-1].replace("-", " ") if video.get("url") else "",
            "thumbnail_url": thumbnail_url,
            "resolution": f"{width}x{height}" if width and height else "",
            "duration": float(video.get("duration", 0) or 0),
        })

    logger.info("Pexels search returned %d results for: %s", len(results), keywords)
    return results


def search_pixabay(keywords: str, max_results: int = 5) -> List[Dict]:
    """
    Search Pixabay for stock video footage.

    Args:
        keywords: Search query string.
        max_results: Maximum results to return.

    Returns:
        List of dicts with: source_type, url, title, thumbnail_url, resolution, duration.
    """
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        logger.error("PIXABAY_API_KEY not set")
        return []

    params = {
        "key": api_key,
        "q": keywords,
        "video_type": "film",
        "per_page": min(max_results, 200),
        "order": "popular",
    }

    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Pixabay API request failed: %s", exc)
        return []

    results: List[Dict] = []
    for hit in data.get("hits", [])[:max_results]:
        videos = hit.get("videos", {})
        # Prefer large > medium > small
        for quality in ("large", "medium", "small"):
            vdata = videos.get(quality, {})
            if vdata.get("url"):
                download_url = vdata["url"]
                width = vdata.get("width", 0)
                height = vdata.get("height", 0)
                break
        else:
            download_url = ""
            width = 0
            height = 0

        results.append({
            "source_type": "pixabay",
            "url": download_url,
            "title": hit.get("tags", ""),
            "thumbnail_url": hit.get("picture_id", ""),
            "resolution": f"{width}x{height}" if width and height else "",
            "duration": float(hit.get("duration", 0) or 0),
        })

    logger.info("Pixabay search returned %d results for: %s", len(results), keywords)
    return results
