"""Off-IG similar content via RapidAPI TikTok search.

Powers the "Find similar elsewhere" action on the /sources discovery feed:
given a reference reel, search TikTok for related videos by keyword/hashtag
and return the same ``DiscoveryItem`` shape so the frontend reuses
``SourcesGrid``/``SourcesCard``.

Provider: env-configurable, defaults to ``tiktok-scraper7.p.rapidapi.com``.
A small projection layer maps the response to our internal shape so a
future provider swap (different RapidAPI host with a slightly different
JSON shape) only needs ``_project_tiktok_item`` updated, not the call site.

Why TikTok over YT Shorts: documented in ARCHITECTURE.md.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config — env-driven so a provider swap stays in env + one parser.
# ---------------------------------------------------------------------------

_RAPIDAPI_KEY = os.getenv("RAPIDAPI_TIKTOK_KEY") or os.getenv("RAPIDAPI_KEY", "")
_RAPIDAPI_HOST = os.getenv(
    "RAPIDAPI_TIKTOK_HOST", "tiktok-scraper7.p.rapidapi.com"
)
_RAPIDAPI_SEARCH_PATH = os.getenv("RAPIDAPI_TIKTOK_SEARCH_PATH", "/feed/search")
_BASE_URL = f"https://{_RAPIDAPI_HOST}"
_TIMEOUT = httpx.Timeout(15.0)


def _headers() -> dict[str, str]:
    key = (
        os.getenv("RAPIDAPI_TIKTOK_KEY")
        or os.getenv("RAPIDAPI_KEY")
        or _RAPIDAPI_KEY
    )
    return {
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "x-rapidapi-key": key,
    }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TikTokErrorKind(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    UPSTREAM_ERROR = "upstream"
    MALFORMED = "malformed"
    NOT_CONFIGURED = "not_configured"


class TikTokSearchError(Exception):
    def __init__(self, kind: TikTokErrorKind, message: str, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Query building — pulled out for testability + reuse
# ---------------------------------------------------------------------------


_HASHTAG_RE = re.compile(r"#(\w+)")


def build_query_from_caption(caption: str | None, *, fallback: str = "") -> str:
    """Extract a search query from an IG caption.

    Hashtags win (signal-rich, platform-cross-pollinating). If the caption
    has no hashtags, fall back to the first few non-tag/non-mention words.
    Finally, fall back to whatever the caller supplies (typically the
    reel's ``ig_code`` so we always send something).
    """
    if caption:
        tags = _HASHTAG_RE.findall(caption)
        if tags:
            return " ".join(tags[:3])
        words = [
            w for w in caption.split()
            if not w.startswith("#") and not w.startswith("@") and len(w) > 1
        ][:5]
        if words:
            return " ".join(words)
    return fallback


# ---------------------------------------------------------------------------
# Response projection — adapts the provider's shape to our DiscoveryItem shape
# ---------------------------------------------------------------------------


def _first_url_from(candidate: Any) -> Optional[str]:
    """A cover/video URL might be a string, an object with ``url``, or a
    {"url_list": [...]} array. Walk all three."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        for k in ("url", "play_addr", "url_list", "uri"):
            v = candidate.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, str) and first.startswith("http"):
                    return first
    return None


def _project_tiktok_item(raw: Any) -> dict[str, Any] | None:
    """RapidAPI response item -> internal projection.

    Returns ``None`` for items we can't make sense of (missing id or
    permalink). Defensive across the various TikTok endpoint shapes:
    different providers use ``aweme_id``, ``id``, ``video_id`` for the
    primary key; ``author.unique_id`` vs ``author.username``; ``digg_count``
    vs ``like_count``; etc.
    """
    if not isinstance(raw, dict):
        return None

    aweme_id = raw.get("aweme_id") or raw.get("id") or raw.get("video_id")
    if not aweme_id:
        return None

    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    handle = (
        author.get("unique_id")
        or author.get("username")
        or raw.get("author_unique_id")
        or "tiktok"
    )
    handle = str(handle).lstrip("@").lower() or "tiktok"

    permalink = (
        raw.get("share_url")
        or raw.get("url")
        or f"https://www.tiktok.com/@{handle}/video/{aweme_id}"
    )

    video_blob = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    cover_candidate = (
        raw.get("cover")
        or raw.get("origin_cover")
        or video_blob.get("cover")
        or video_blob.get("origin_cover")
    )
    thumbnail = _first_url_from(cover_candidate)

    # Stats live either at the root or nested under ``statistics`` /
    # ``stats``. Walk both to keep the projector provider-agnostic.
    stats_blob = (
        raw.get("statistics") if isinstance(raw.get("statistics"), dict)
        else raw.get("stats") if isinstance(raw.get("stats"), dict)
        else raw
    )

    def _i(*keys: str) -> int:
        for k in keys:
            v = stats_blob.get(k) if isinstance(stats_blob, dict) else None
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
            # Some shapes only have it at the root.
            v = raw.get(k)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
        return 0

    return {
        "tiktok_id": str(aweme_id),
        "source_handle": handle,
        "permalink": str(permalink),
        "thumbnail_url": thumbnail,
        "caption": raw.get("desc") or raw.get("description") or raw.get("title") or None,
        "view_count": _i("play_count", "view_count", "views"),
        "like_count": _i("digg_count", "like_count", "likes", "favorited_count"),
        "comment_count": _i("comment_count", "comments"),
        "duration_seconds": (
            float(video_blob.get("duration") or raw.get("duration") or 0) or None
        ),
        "taken_at_unix": (
            int(raw.get("create_time") or raw.get("createTime") or 0) or None
        ),
    }


def _classify_status(status: int) -> TikTokErrorKind | None:
    if status == 200:
        return None
    if status == 429:
        return TikTokErrorKind.RATE_LIMIT
    return TikTokErrorKind.UPSTREAM_ERROR


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def search_similar_tiktok(
    query: str,
    *,
    max_results: int = 12,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Search TikTok via RapidAPI for ``query``. Returns projected items
    (the dict shape ``_project_tiktok_item`` produces) ready to feed into
    ``to_discovery_item``.

    Raises :class:`TikTokSearchError` with a kind so the router can decide
    whether to surface "no results" vs. "upstream down". Note that the
    *router* converts errors into a soft "items=[], error=..." response —
    this function is the strict layer.
    """
    if not _headers().get("x-rapidapi-key"):
        raise TikTokSearchError(
            TikTokErrorKind.NOT_CONFIGURED, "RAPIDAPI_TIKTOK_KEY not set"
        )

    params = {"keywords": query, "count": str(max_results), "cursor": "0"}

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, transport=transport, headers=_headers()
    ) as client:
        try:
            resp = await client.get(_BASE_URL + _RAPIDAPI_SEARCH_PATH, params=params)
        except httpx.TimeoutException as exc:
            raise TikTokSearchError(TikTokErrorKind.TIMEOUT, "tiktok search timed out") from exc
        except httpx.RequestError as exc:
            raise TikTokSearchError(
                TikTokErrorKind.UPSTREAM_ERROR, f"tiktok search: {exc}"
            ) from exc

    err = _classify_status(resp.status_code)
    if err is not None:
        raise TikTokSearchError(
            err, f"tiktok search HTTP {resp.status_code}", resp.status_code
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise TikTokSearchError(TikTokErrorKind.MALFORMED, "tiktok body not JSON") from exc

    # Providers nest the array under ``data.videos`` or ``data`` or just
    # ``videos``. Walk the common keys.
    items_blob: Any = None
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            items_blob = data.get("videos") or data.get("data") or data.get("items")
        elif isinstance(data, list):
            items_blob = data
        if items_blob is None:
            items_blob = payload.get("videos") or payload.get("items")

    if not isinstance(items_blob, list):
        raise TikTokSearchError(
            TikTokErrorKind.MALFORMED, "tiktok payload missing items list"
        )

    out: list[dict[str, Any]] = []
    for raw in items_blob[:max_results]:
        projected = _project_tiktok_item(raw)
        if projected is not None:
            out.append(projected)
    return out
