"""RapidAPI video downloader — primary download path.

Wraps the RapidAPI marketplace `social-download-all-in-one`
endpoint (nguyenmanhict) which handles the IP-block dance our datacenter
yt-dlp can't beat (YouTube/TikTok increasingly serve "sign in to confirm
you're not a bot" or 403 to cloud IPs). Supports IG reels/posts, TikTok,
YouTube, Facebook, Twitter/X via a single autolink endpoint.

Returns None on any failure so callers gracefully fall through to
yt-dlp + Playwright. Auth uses the existing RAPIDAPI_KEY by default
(RapidAPI accounts use one key across all subscribed endpoints), with
the option to override via RAPIDAPI_VIDEO_DL_KEY.

Env:
  RAPIDAPI_VIDEO_DL_KEY   — optional override (defaults to RAPIDAPI_KEY)
  RAPIDAPI_VIDEO_DL_HOST  — optional, defaults to social-download-all-in-one
  RAPIDAPI_VIDEO_DL_PATH  — optional, defaults to "/v1/social/autolink"
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from lib.ytdlp import DOWNLOAD_DIR, DownloadResult

logger = logging.getLogger(__name__)


# RapidAPI accepts a single account-wide key for any subscribed endpoint,
# so most users will already have RAPIDAPI_KEY set from the IG scraper
# integration. The dedicated env exists for cases where someone wants to
# bill the video downloader to a different account.
_KEY = os.getenv("RAPIDAPI_VIDEO_DL_KEY") or os.getenv("RAPIDAPI_KEY", "")
_HOST = os.getenv(
    "RAPIDAPI_VIDEO_DL_HOST",
    "social-download-all-in-one.p.rapidapi.com",
)
# nguyenmanhict's autolink endpoint — JSON body, returns medias[] +
# result.video_url. If a future provider lands on RapidAPI with a
# different shape, override host + path via env without code changes.
_PATH = os.getenv("RAPIDAPI_VIDEO_DL_PATH", "/v1/social/autolink")

# Per-attempt timeouts. The resolution call is fast (≤10s) but the
# actual MP4 stream can be a 30 MB+ download — give it real headroom.
_RESOLVE_TIMEOUT = 30.0
_DOWNLOAD_TIMEOUT = 180.0


def is_configured() -> bool:
    """Whether the RapidAPI path is even worth trying."""
    return bool(_KEY)


def _extract_media_url(data) -> Optional[str]:
    """Defensively pull a downloadable URL from various RapidAPI shapes.

    Different providers and even different responses from the same
    endpoint vary — `medias: [{url}]`, top-level `download_url`, nested
    `result.video_url`, etc. We walk all the common patterns rather
    than pinning to one.

    Order matters: we check arrays FIRST because providers like
    social-download-all-in-one echo the input URL as top-level "url",
    so a naive top-level scan would return the input back to us.
    Unambiguous keys (`download_url`, `video_url`) are still safe at
    the top level because they're never used for input echo.
    """
    if not isinstance(data, dict):
        return None

    # `medias` / `links` / `downloadLinks` / `media` arrays. Prefer
    # mp4-flagged entries with explicit quality, but fall back to any
    # link. `medias` is what social-download-all-in-one returns.
    for arr_key in ("medias", "links", "downloadLinks", "media", "videos"):
        arr = data.get(arr_key)
        if isinstance(arr, list) and arr:
            best: Optional[str] = None
            for link in arr:
                if not isinstance(link, dict):
                    continue
                url = link.get("url") or link.get("link") or link.get("downloadUrl")
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                # Skip audio-only entries when the array also has video.
                if str(link.get("type", "")).lower() == "audio":
                    continue
                # Prefer non-watermarked, mp4, hd hints if available.
                hints = " ".join(
                    str(link.get(k, "")).lower()
                    for k in ("quality", "format", "type", "label")
                )
                if "no_watermark" in hints or "hd" in hints or "1080" in hints or "720" in hints:
                    return url
                if best is None:
                    best = url
            if best:
                return best

    # Unambiguous top-level direct URL fields. Intentionally NOT
    # checking plain `url` — providers commonly echo input there.
    for key in ("download_url", "video_url", "downloadUrl", "media_url"):
        v = data.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v

    # Nested wrappers — many APIs wrap payload in `data` or `video`.
    for nested_key in ("video", "data", "result"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            url = _extract_media_url(nested)
            if url:
                return url
    return None


def download_via_rapidapi(source_url: str, video_id: str) -> Optional[DownloadResult]:
    """Resolve via RapidAPI then stream the MP4 to disk. Returns None on
    any failure — caller falls through to yt-dlp / Playwright."""
    if not is_configured():
        logger.debug("RapidAPI not configured (no key); skipping primary path")
        return None

    # nguyenmanhict's autolink expects POST with a JSON body.
    headers = {
        "x-rapidapi-key": _KEY,
        "x-rapidapi-host": _HOST,
        "content-type": "application/json",
        "accept": "application/json",
    }

    # Step 1: ask RapidAPI to resolve the source URL → MP4 download URL
    try:
        with httpx.Client(timeout=_RESOLVE_TIMEOUT, headers=headers) as client:
            resp = client.post(
                f"https://{_HOST}{_PATH}",
                json={"url": source_url},
            )
    except httpx.RequestError as exc:
        logger.warning("RapidAPI resolve request failed: %s", exc)
        return None

    if resp.status_code == 429:
        logger.warning("RapidAPI rate-limited (429); falling through to yt-dlp")
        return None
    if resp.status_code in (401, 403):
        # Auth failed or quota exhausted — won't recover by retry, log
        # loudly so ops sees it instead of silently degrading.
        logger.warning(
            "RapidAPI auth/quota error %d: %s",
            resp.status_code,
            resp.text[:200] if resp.text else "",
        )
        return None
    if resp.status_code != 200:
        logger.warning("RapidAPI HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    try:
        data = resp.json()
    except Exception:
        logger.warning("RapidAPI returned non-JSON response")
        return None

    media_url = _extract_media_url(data)
    if not media_url:
        # Log the response shape (truncated) so we can update
        # _extract_media_url if a new provider shape lands.
        logger.warning(
            "RapidAPI response had no extractable media URL — shape: %s",
            str(data)[:300],
        )
        return None

    # Step 2: stream the MP4 to disk. Don't load into memory — these can
    # be 50 MB+.
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", media_url) as r:
                if r.status_code != 200:
                    logger.warning(
                        "RapidAPI media URL HTTP %d (was the URL a tracker / preview?)",
                        r.status_code,
                    )
                    return None
                with open(file_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
    except Exception as exc:
        logger.warning("RapidAPI media stream failed: %s", exc)
        # Best-effort cleanup of partial file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        return None

    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    if file_size < 10_000:
        # Likely an HTML error page or tracker pixel mistakenly served.
        logger.warning("RapidAPI download too small (%d bytes) — discarding", file_size)
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None

    # Step 3: probe metadata. Reuse the same helpers the enhancer uses.
    resolution = ""
    fps = 0.0
    duration = 0.0
    try:
        from lib.video_proc import (
            get_video_duration,
            get_video_fps,
            get_video_resolution,
        )
        resolution = get_video_resolution(file_path) or ""
        fps = float(get_video_fps(file_path) or 0)
        duration = float(get_video_duration(file_path) or 0)
    except Exception as exc:
        # Probe failure isn't fatal — we still have a working video file
        # the rest of the pipeline can use; metadata gets backfilled at
        # enhance time.
        logger.warning("Metadata probe failed for RapidAPI download: %s", exc)

    logger.info(
        "RapidAPI download succeeded: %s → %s (%.1fMB, %s, %.1fs)",
        source_url[:80],
        file_path,
        file_size / 1024 / 1024,
        resolution or "?",
        duration,
    )

    return DownloadResult(
        file_path=file_path,
        info_json_path="",
        resolution=resolution,
        fps=fps,
        codec="",
        bitrate=0,
        duration=duration,
        file_size=file_size,
    )
