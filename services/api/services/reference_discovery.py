"""Per-reference-page discovery service — pure logic + RapidAPI wrapper.

This module is the foundation for the new discovery flow:

  - :class:`DiscoveryItem` is the shape the frontend grid renders. Field names
    match Phase 1.3 spec verbatim (``views`` not ``view_count``, etc.).
  - :func:`apply_filter` / :func:`rank_items` are pure functions over an
    iterable of items. Tests can exercise them without any I/O.
  - :func:`to_discovery_item` adapts the two row shapes we'll see in practice:
    the RapidAPI projection (dicts coming back from the upstream client) and
    the ORM row in ``reference_reels`` (the durable cache).
  - :func:`fetch_handle_reels` is the thin RapidAPI client wrapper used by
    the (later) refresh worker. It raises :class:`RapidAPIError` with an
    explicit :class:`RapidAPIErrorKind` so callers can branch on
    rate-limit vs. timeout vs. malformed response without grepping strings.

Notes:
  - The legacy ``services/instagram_api.py`` swallows errors and returns
    ``None`` — kept untouched on purpose (the niche-discovery pipeline still
    uses it). This module is the per-reference-page flow's surface, and it
    surfaces errors so the worker can handle them and the tests can assert.
  - The Redis-backed rate limiter + DB persistence + API endpoints land in
    Task 1.3 commit B.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Optional

import httpx

# ---------------------------------------------------------------------------
# Sort + filter constants — single source of truth, re-exported via the
# discovery_filter model for the Pydantic Literal.
# ---------------------------------------------------------------------------

SORT_VIEWS_DESC = "views_desc"
SORT_POSTED_AT_DESC = "posted_at_desc"
SORT_ENGAGEMENT_DESC = "engagement_desc"
SORT_LIKES_DESC = "likes_desc"
SORT_COMMENTS_DESC = "comments_desc"

ALL_SORT_KEYS = frozenset(
    {
        SORT_VIEWS_DESC,
        SORT_POSTED_AT_DESC,
        SORT_ENGAGEMENT_DESC,
        SORT_LIKES_DESC,
        SORT_COMMENTS_DESC,
    }
)


# ---------------------------------------------------------------------------
# RapidAPI errors
# ---------------------------------------------------------------------------


class RapidAPIErrorKind(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"      # HTTP 429
    NOT_FOUND = "not_found"        # handle doesn't exist on IG (404)
    UPSTREAM_ERROR = "upstream"    # any 5xx or unexpected transport failure
    MALFORMED = "malformed"        # 200 but the body isn't what we expected


class RapidAPIError(Exception):
    """Raised by :func:`fetch_handle_reels`. Callers branch on ``kind``."""

    def __init__(
        self,
        kind: RapidAPIErrorKind,
        message: str,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


# ---------------------------------------------------------------------------
# DiscoveryItem — wire shape used by the frontend grid
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryItem:
    source_handle: str          # the reference page's IG handle (lowercase)
    permalink: str              # full IG URL — always a valid link
    media_url: Optional[str]    # signed IG CDN URL when known (else None)
    thumbnail: Optional[str]    # CDN URL for the cover image
    caption: Optional[str]
    views: int
    likes: int
    comments: int
    posted_at: Optional[datetime]
    duration_seconds: Optional[float]
    score: float                # rank score under the active sort_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_handle": self.source_handle,
            "permalink": self.permalink,
            "media_url": self.media_url,
            "thumbnail": self.thumbnail,
            "caption": self.caption,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "duration_seconds": self.duration_seconds,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Pure helpers: engagement, score, filter, rank
# ---------------------------------------------------------------------------


def engagement_rate(views: int, likes: int, comments: int) -> float:
    """Engagement = (likes + comments) / views. Zero views -> zero (don't
    divide by zero, don't reward zero-view content)."""
    if views <= 0:
        return 0.0
    return (likes + comments) / views


def compute_score(
    sort_by: str,
    views: int,
    likes: int,
    comments: int,
    posted_at: datetime | None,
) -> float:
    """Return the rank score under ``sort_by``. Unknown sort keys fall back
    to views_desc so a bad client never crashes ranking — the filter
    validator catches bad input at the API edge."""
    if sort_by == SORT_VIEWS_DESC:
        return float(views)
    if sort_by == SORT_LIKES_DESC:
        return float(likes)
    if sort_by == SORT_COMMENTS_DESC:
        return float(comments)
    if sort_by == SORT_ENGAGEMENT_DESC:
        return engagement_rate(views, likes, comments)
    if sort_by == SORT_POSTED_AT_DESC:
        return float(posted_at.timestamp()) if posted_at else 0.0
    return float(views)


def apply_filter(
    items: Iterable[DiscoveryItem],
    *,
    min_views: int,
    min_likes: int,
    min_comments: int,
    min_engagement_rate: float,
    max_age_days: int,
    now: datetime | None = None,
) -> list[DiscoveryItem]:
    """Keep items meeting every threshold. Items with unknown ``posted_at``
    pass the age check (we don't penalize missing data — a refresh will
    populate it eventually)."""
    now = now or datetime.now(timezone.utc)
    out: list[DiscoveryItem] = []
    for it in items:
        if it.views < min_views:
            continue
        if it.likes < min_likes:
            continue
        if it.comments < min_comments:
            continue
        if engagement_rate(it.views, it.likes, it.comments) < min_engagement_rate:
            continue
        if it.posted_at is not None:
            # Use full UTC seconds, not days, so an item posted 60d + 1s
            # ago doesn't pass a max_age_days=60 filter.
            age = now - _ensure_utc(it.posted_at)
            if age.total_seconds() > max_age_days * 86400:
                continue
        out.append(it)
    return out


def rank_items(
    items: Iterable[DiscoveryItem],
    sort_by: str,
) -> list[DiscoveryItem]:
    """Sort items by score descending. Deterministic tiebreaker on permalink
    so the same input always produces the same order."""
    def key(it: DiscoveryItem) -> tuple[float, str]:
        score = compute_score(
            sort_by, it.views, it.likes, it.comments, it.posted_at
        )
        # Negative score gives descending; permalink ascending breaks ties.
        return (-score, it.permalink)
    return sorted(items, key=key)


# ---------------------------------------------------------------------------
# Mappers: dict (RapidAPI projection) / ORM row -> DiscoveryItem
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    """Always-aware UTC datetime. Existing legacy rows may have naive
    timestamps; treat them as UTC rather than crashing the comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_posted_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    return None


def to_discovery_item(
    source_handle: str,
    row: Any,
    *,
    sort_by: str = SORT_VIEWS_DESC,
) -> DiscoveryItem:
    """Adapt either a RapidAPI projection dict (the shape returned by
    :func:`fetch_handle_reels`) or a :class:`models.ReferenceReel` ORM row.
    Falls through to view-style sort_by when the caller hasn't picked one."""
    # Pull values without caring whether ``row`` is a dict or an attr object.
    def _get(name: str, *aliases: str, default: Any = None) -> Any:
        if isinstance(row, dict):
            for n in (name, *aliases):
                if n in row and row[n] is not None:
                    return row[n]
            return default
        for n in (name, *aliases):
            v = getattr(row, n, None)
            if v is not None:
                return v
        return default

    views = int(_get("view_count", "views", default=0) or 0)
    likes = int(_get("like_count", "likes", default=0) or 0)
    comments = int(_get("comment_count", "comments", default=0) or 0)
    posted_at = _coerce_posted_at(_get("posted_at", "taken_at", "taken_at_unix"))

    return DiscoveryItem(
        source_handle=source_handle,
        permalink=str(_get("permalink", "url", default="")),
        media_url=_get("media_url"),
        thumbnail=_get("thumbnail_url", "thumbnail"),
        caption=_get("caption"),
        views=views,
        likes=likes,
        comments=comments,
        posted_at=posted_at,
        duration_seconds=(
            float(_get("duration_seconds", default=0) or 0) or None
        ),
        score=compute_score(sort_by, views, likes, comments, posted_at),
    )


# ---------------------------------------------------------------------------
# RapidAPI client wrapper
# ---------------------------------------------------------------------------

_RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
_RAPIDAPI_HOST = os.getenv(
    "RAPIDAPI_PROFILE_HOST",
    "instagram-api-fast-reliable-data-scraper.p.rapidapi.com",
)
_BASE_URL = f"https://{_RAPIDAPI_HOST}"
_DEFAULT_TIMEOUT = httpx.Timeout(15.0)


def _headers() -> dict[str, str]:
    # Re-read the env each call so tests can monkeypatch ``RAPIDAPI_KEY``.
    return {
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY", _RAPIDAPI_KEY),
    }


def _classify_status(status: int) -> RapidAPIErrorKind | None:
    if status == 200:
        return None
    if status == 404:
        return RapidAPIErrorKind.NOT_FOUND
    if status == 429:
        return RapidAPIErrorKind.RATE_LIMIT
    if status >= 500:
        return RapidAPIErrorKind.UPSTREAM_ERROR
    return RapidAPIErrorKind.UPSTREAM_ERROR


async def fetch_handle_reels(
    handle: str,
    *,
    max_pages: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Fetch a handle's recent reels via RapidAPI. Returns a list of dicts
    in the projection the cache row understands:

        {ig_media_id, ig_code, permalink, thumbnail_url, view_count,
         like_count, comment_count, duration_seconds, caption,
         taken_at_unix}

    Raises :class:`RapidAPIError` with a specific ``kind`` on every failure
    mode so tests (and the calling worker) can branch deterministically.
    The ``transport`` kwarg is a test-only injection point for
    ``httpx.MockTransport``.
    """
    if not _headers().get("x-rapidapi-key"):
        raise RapidAPIError(
            RapidAPIErrorKind.UPSTREAM_ERROR, "RAPIDAPI_KEY is not configured"
        )

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT,
        transport=transport,
        headers=_headers(),
    ) as client:
        # ── Resolve handle -> user_id ────────────────────────────────
        try:
            resp = await client.get(
                f"{_BASE_URL}/profile", params={"username": handle}
            )
        except httpx.TimeoutException as exc:
            raise RapidAPIError(
                RapidAPIErrorKind.TIMEOUT, "profile fetch timed out"
            ) from exc
        except httpx.RequestError as exc:
            raise RapidAPIError(
                RapidAPIErrorKind.UPSTREAM_ERROR, f"profile fetch: {exc}"
            ) from exc

        err = _classify_status(resp.status_code)
        if err is not None:
            raise RapidAPIError(
                err,
                f"profile fetch HTTP {resp.status_code} for @{handle}",
                resp.status_code,
            )

        try:
            profile = resp.json()
        except ValueError as exc:
            raise RapidAPIError(
                RapidAPIErrorKind.MALFORMED, "profile body is not JSON"
            ) from exc

        user_id = profile.get("pk") or profile.get("id") or profile.get("user_id")
        if not user_id:
            raise RapidAPIError(
                RapidAPIErrorKind.MALFORMED,
                f"profile for @{handle} has no user id",
            )

        # ── Paginate reels ───────────────────────────────────────────
        items: list[dict[str, Any]] = []
        max_id = ""
        for _ in range(max_pages):
            params: dict[str, str] = {"user_id": str(user_id)}
            if max_id:
                params["max_id"] = max_id

            try:
                rr = await client.get(f"{_BASE_URL}/reels", params=params)
            except httpx.TimeoutException as exc:
                raise RapidAPIError(
                    RapidAPIErrorKind.TIMEOUT, "reels fetch timed out"
                ) from exc
            except httpx.RequestError as exc:
                raise RapidAPIError(
                    RapidAPIErrorKind.UPSTREAM_ERROR, f"reels fetch: {exc}"
                ) from exc

            err = _classify_status(rr.status_code)
            if err is RapidAPIErrorKind.NOT_FOUND:
                # Some pages have no reels at all — treat 404 here as "empty"
                # so we don't blow up the caller. Profile already exists.
                break
            if err is not None:
                raise RapidAPIError(
                    err,
                    f"reels fetch HTTP {rr.status_code} for @{handle}",
                    rr.status_code,
                )

            try:
                data = rr.json()
            except ValueError as exc:
                raise RapidAPIError(
                    RapidAPIErrorKind.MALFORMED, "reels body is not JSON"
                ) from exc

            data_blob = data.get("data") if isinstance(data, dict) else None
            if not isinstance(data_blob, dict):
                # Same shape as the legacy client expects. Anything else =
                # a provider change we want a loud signal for.
                raise RapidAPIError(
                    RapidAPIErrorKind.MALFORMED, "reels payload missing 'data'"
                )
            page_items = data_blob.get("items") or []
            paging = data_blob.get("paging_info") or {}

            for item in page_items:
                projected = _project_reel(item)
                if projected:
                    items.append(projected)

            max_id = paging.get("max_id") if isinstance(paging, dict) else ""
            if not max_id:
                break

        return items


def _project_reel(item: dict[str, Any]) -> dict[str, Any] | None:
    """RapidAPI reel item -> our cache projection. Drop items with no
    shortcode (they're un-linkable + useless to surface)."""
    media = item.get("media", item)
    code = media.get("code") or ""
    if not code:
        return None

    iv = media.get("image_versions2") or {}
    candidates = iv.get("candidates") if isinstance(iv, dict) else []
    thumb = candidates[0].get("url", "") if candidates else ""

    cap_obj = media.get("caption") or {}
    caption = cap_obj.get("text", "") if isinstance(cap_obj, dict) else ""

    media_id = str(media.get("pk") or media.get("id") or "")
    taken_at = media.get("taken_at") or 0

    return {
        "ig_media_id": media_id,
        "ig_code": code,
        "permalink": f"https://www.instagram.com/reel/{code}/",
        "thumbnail_url": thumb or None,
        "view_count": int(
            media.get("play_count") or media.get("view_count") or 0
        ),
        "like_count": int(media.get("like_count") or 0),
        "comment_count": int(media.get("comment_count") or 0),
        "duration_seconds": float(media.get("video_duration") or 0) or None,
        "caption": caption[:1000] if caption else None,
        "taken_at_unix": int(taken_at) if taken_at else None,
    }
