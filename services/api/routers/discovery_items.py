"""Per-reference-page discovery feed — read endpoint + manual refresh.

Reads from the ``reference_reels`` cache populated by
:func:`refresh_pages_background`. Applies the caller's saved
``discovery_filter`` (or defaults), ranks, paginates.

The refresh endpoint kicks the fetch off via FastAPI's BackgroundTasks
so the response returns immediately — same uvicorn worker, no Celery.
Per-user and global rate limits guard the RapidAPI quota. Replacing
BackgroundTasks with a Celery worker is a P1 follow-up (FOUND-ISSUES).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session, get_db
from middleware.auth import get_current_user
from models.discovery_filter import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MIN_COMMENTS,
    DEFAULT_MIN_ENGAGEMENT_RATE,
    DEFAULT_MIN_LIKES,
    DEFAULT_MIN_VIEWS,
    DEFAULT_SORT_BY,
    DiscoveryFilter,
)
from models.download import Download
from models.reference_page import ReferencePage
from models.reference_reel import ReferenceReel
from models.user import User
from services.discovery_download import perform_download
from services.offsite_search import (
    TikTokSearchError,
    build_query_from_caption,
    search_similar_tiktok,
)
from services.rate_limiter import RateLimitExceeded, check_and_bump
from services.reference_discovery import (
    DiscoveryItem,
    RapidAPIError,
    apply_filter,
    fetch_handle_reels,
    rank_items,
    to_discovery_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discovery", tags=["discovery"])

# Per-user RapidAPI refresh budget. Conservative — every refresh on a
# user with 5 ref pages burns up to 5 profile + 15 reels calls.
_REFRESH_PER_USER = 5
_REFRESH_GLOBAL = 200
_REFRESH_WINDOW_SECONDS = 3600

_MAX_LIMIT = 100


def _current_filter(row: DiscoveryFilter | None) -> dict:
    """Return the active filter payload — saved row or defaults."""
    if row is None:
        return {
            "min_views": DEFAULT_MIN_VIEWS,
            "min_likes": DEFAULT_MIN_LIKES,
            "min_comments": DEFAULT_MIN_COMMENTS,
            "min_engagement_rate": DEFAULT_MIN_ENGAGEMENT_RATE,
            "max_age_days": DEFAULT_MAX_AGE_DAYS,
            "sort_by": DEFAULT_SORT_BY,
        }
    return {
        "min_views": row.min_views,
        "min_likes": row.min_likes,
        "min_comments": row.min_comments,
        "min_engagement_rate": row.min_engagement_rate,
        "max_age_days": row.max_age_days,
        "sort_by": row.sort_by,
    }


# ---------------------------------------------------------------------------
# GET /api/discovery/items
# ---------------------------------------------------------------------------


@router.get("/items")
async def list_discovery_items(
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated discovery feed: cached reels from the caller's reference
    pages, filtered by the saved discovery_filter and ranked by ``sort_by``.

    Empty cache returns ``{items: [], total: 0, has_cache: false}`` so the UI
    can show "Run discovery to populate" rather than a misleading zero.
    """
    f_row = (
        await db.execute(
            select(DiscoveryFilter).where(DiscoveryFilter.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    f = _current_filter(f_row)

    # Pull every cached reel for this user's reference pages. For the
    # realistic ceiling (5 pages * ~120 reels = ~600 rows) Python-side
    # filter + rank is faster than a SQL ORDER BY + offset/limit because
    # the engagement_desc sort is computed, not stored.
    rows = (
        await db.execute(
            select(ReferenceReel, ReferencePage.ig_handle)
            .join(ReferencePage, ReferenceReel.reference_page_id == ReferencePage.id)
            .where(ReferencePage.user_id == current_user.id)
        )
    ).all()

    if not rows:
        return {
            "items": [],
            "total": 0,
            "filter": f,
            "has_cache": False,
        }

    items: list[DiscoveryItem] = [
        to_discovery_item(handle, reel, sort_by=f["sort_by"])
        for reel, handle in rows
    ]
    filtered = apply_filter(
        items,
        min_views=f["min_views"],
        min_likes=f["min_likes"],
        min_comments=f["min_comments"],
        min_engagement_rate=f["min_engagement_rate"],
        max_age_days=f["max_age_days"],
    )
    ranked = rank_items(filtered, f["sort_by"])

    page = ranked[offset : offset + limit]
    return {
        "items": [it.to_dict() for it in page],
        "total": len(ranked),
        "filter": f,
        "has_cache": True,
    }


# ---------------------------------------------------------------------------
# POST /api/discovery/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def trigger_refresh(
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kick off a RapidAPI fetch for every reference page this user owns.

    Returns 202 immediately; the actual fetch + upsert runs via
    BackgroundTasks in the same uvicorn worker. Rate-limited per-user
    (``_REFRESH_PER_USER``) and globally (``_REFRESH_GLOBAL``) — both
    counters share the same 1-hour window.
    """
    try:
        await check_and_bump(
            f"discovery:rl:user:{current_user.id}",
            max_per_window=_REFRESH_PER_USER,
            window_seconds=_REFRESH_WINDOW_SECONDS,
        )
        await check_and_bump(
            "discovery:rl:global",
            max_per_window=_REFRESH_GLOBAL,
            window_seconds=_REFRESH_WINDOW_SECONDS,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit",
                "detail": "Too many refreshes. Try again later.",
                "retry_after": exc.retry_after,
            },
        )

    page_rows = (
        await db.execute(
            select(ReferencePage.id, ReferencePage.ig_handle).where(
                ReferencePage.user_id == current_user.id
            )
        )
    ).all()
    pages: list[tuple[UUID, str]] = [(r[0], r[1]) for r in page_rows]

    if not pages:
        return {
            "queued": False,
            "page_count": 0,
            "detail": "No reference pages to refresh — add one first.",
        }

    background.add_task(refresh_pages_background, pages)
    return {"queued": True, "page_count": len(pages)}


# ---------------------------------------------------------------------------
# Background refresh — split into a pure inner ``do_refresh`` (uses the
# caller's session, does not commit) and an outer wrapper that opens a
# fresh session + commits. Tests drive the inner directly on the savepoint-
# mode test session so writes roll back at teardown instead of polluting
# the DB across tests.
# ---------------------------------------------------------------------------


async def do_refresh(
    pages: Iterable[tuple[UUID, str]],
    db: AsyncSession,
) -> dict:
    """Inner refresh — fetch each (page_id, handle) via RapidAPI and upsert
    into ``reference_reels`` using the caller's session. Returns a small
    summary. Does NOT commit; the wrapper or test controls that.

    Errors on one page do NOT halt the rest. The caller already received
    its 202 — partial success beats whole-batch failure.
    """
    refreshed = 0
    failed_handles: list[str] = []

    for page_id, handle in pages:
        try:
            reels = await fetch_handle_reels(handle, max_pages=3)
        except RapidAPIError as exc:
            logger.warning(
                "Discovery refresh: RapidAPI %s on @%s (status=%s)",
                exc.kind.value, handle, exc.status_code,
            )
            failed_handles.append(handle)
            continue
        except Exception:  # noqa: BLE001 — log + continue, never crash worker
            logger.exception("Discovery refresh: unexpected error on @%s", handle)
            failed_handles.append(handle)
            continue

        for r in reels:
            posted_at = None
            if r.get("taken_at_unix"):
                posted_at = datetime.fromtimestamp(
                    int(r["taken_at_unix"]), tz=timezone.utc
                )

            stmt = pg_insert(ReferenceReel).values(
                reference_page_id=page_id,
                ig_media_id=r["ig_media_id"],
                ig_code=r["ig_code"],
                permalink=r["permalink"],
                thumbnail_url=r.get("thumbnail_url"),
                caption=r.get("caption"),
                view_count=r["view_count"],
                like_count=r["like_count"],
                comment_count=r["comment_count"],
                duration_seconds=r.get("duration_seconds"),
                posted_at=posted_at,
                fetched_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["reference_page_id", "ig_media_id"],
                set_={
                    "view_count": stmt.excluded.view_count,
                    "like_count": stmt.excluded.like_count,
                    "comment_count": stmt.excluded.comment_count,
                    "thumbnail_url": stmt.excluded.thumbnail_url,
                    "caption": stmt.excluded.caption,
                    "duration_seconds": stmt.excluded.duration_seconds,
                    "posted_at": stmt.excluded.posted_at,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await db.execute(stmt)
            refreshed += 1

    return {"refreshed": refreshed, "failed_handles": failed_handles}


async def refresh_pages_background(pages: Iterable[tuple[UUID, str]]) -> dict:
    """Production wrapper — opens a fresh async session, runs the refresh,
    commits. Invoked by FastAPI BackgroundTasks; safe to call directly
    from other coroutines too.
    """
    async with async_session() as db:
        result = await do_refresh(pages, db)
        await db.commit()
        return result


# ---------------------------------------------------------------------------
# POST /api/discovery/items/{reel_id}/download
# GET  /api/discovery/downloads/{download_id}
# ---------------------------------------------------------------------------


def _download_to_dict(row: Download) -> dict:
    return {
        "id": str(row.id),
        "reference_reel_id": str(row.reference_reel_id),
        "status": row.status,
        "minio_key": row.minio_key,
        "file_size_bytes": row.file_size_bytes,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/items/{reel_id}/download")
async def request_item_download(
    reel_id: UUID,
    background: BackgroundTasks,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a discovery reel's media into our MinIO storage.

    Idempotent at the (user, reel) level via the UNIQUE constraint on
    ``downloads``. Re-posting the same item returns the existing row with
    HTTP 200; the first POST returns 202 + a freshly-created row whose
    BackgroundTask is in-flight. Ownership is enforced via the join to
    ``reference_pages.user_id`` — User A can't trigger a download of User
    B's reel even with the right UUID.

    Spec literal path is ``POST /api/items/:id/download``; we namespace
    under ``/api/discovery`` to avoid colliding with the legacy
    ``/api/reels/{id}/download`` (which serves viral_reels, a different
    table).
    """
    owned_reel = (
        await db.execute(
            select(ReferenceReel)
            .join(ReferencePage, ReferenceReel.reference_page_id == ReferencePage.id)
            .where(
                ReferenceReel.id == reel_id,
                ReferencePage.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not owned_reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    # Idempotent: return existing row if there's already a download for
    # this (user, reel). Status carries the truth — ``done`` means the file
    # is in MinIO, ``failed`` means caller can choose to retry by deleting
    # and re-POSTing (Phase 2.2 will add proper Idempotency-Key replay).
    existing = (
        await db.execute(
            select(Download).where(
                Download.user_id == current_user.id,
                Download.reference_reel_id == reel_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        response.status_code = status.HTTP_200_OK
        return _download_to_dict(existing)

    row = Download(
        user_id=current_user.id,
        reference_reel_id=reel_id,
        status="queued",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    background.add_task(_perform_download_background, row.id)
    response.status_code = status.HTTP_202_ACCEPTED
    return _download_to_dict(row)


@router.get("/downloads/{download_id}")
async def get_download(
    download_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll status of a download. 404 if it's not the caller's."""
    row = (
        await db.execute(
            select(Download).where(
                Download.id == download_id,
                Download.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Download not found")
    return _download_to_dict(row)


async def _perform_download_background(download_id: UUID) -> None:
    """Production wrapper for ``perform_download`` — opens its own session,
    commits, never raises. Invoked by FastAPI BackgroundTasks."""
    async with async_session() as db:
        try:
            await perform_download(download_id, db)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("download %s wrapper failed", download_id)
            await db.rollback()


# ---------------------------------------------------------------------------
# GET /api/discovery/items/{reel_id}/similar  (Task 1.6)
# ---------------------------------------------------------------------------

# Per-user budget for "Find similar" calls. Each call burns one RapidAPI
# TikTok search request — generous enough for casual browsing, tight
# enough to keep a runaway client from exhausting quota.
_SIMILAR_PER_USER = 20
_SIMILAR_GLOBAL = 500
_SIMILAR_WINDOW_SECONDS = 3600

_SIMILAR_LIMIT = 12


@router.get("/items/{reel_id}/similar")
async def find_similar(
    reel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find off-IG similar content for a discovery reel.

    Ownership: the reel must belong to the caller (via reference_pages.user_id).
    Source: TikTok via RapidAPI (see ARCHITECTURE.md for the why-this-not-YT).
    Query: hashtags from the reel's caption (3 max), then keyword fallback,
    then the reel's ig_code so we always send something.

    Returns ``{items: [DiscoveryItem], source: {handle, permalink}, query,
    error: null | string}``. Upstream RapidAPI failures land as
    ``items=[], error="..."``  rather than a 502 so the UI can render a
    graceful empty-with-explanation state per the spec's
    "error fallback" requirement.
    """
    try:
        await check_and_bump(
            f"similar:rl:user:{current_user.id}",
            max_per_window=_SIMILAR_PER_USER,
            window_seconds=_SIMILAR_WINDOW_SECONDS,
        )
        await check_and_bump(
            "similar:rl:global",
            max_per_window=_SIMILAR_GLOBAL,
            window_seconds=_SIMILAR_WINDOW_SECONDS,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit",
                "detail": "Too many similar-content lookups. Try again later.",
                "retry_after": exc.retry_after,
            },
        )

    reel = (
        await db.execute(
            select(ReferenceReel, ReferencePage.ig_handle)
            .join(ReferencePage, ReferenceReel.reference_page_id == ReferencePage.id)
            .where(
                ReferenceReel.id == reel_id,
                ReferencePage.user_id == current_user.id,
            )
        )
    ).first()
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    reel_row, ig_handle = reel

    query = build_query_from_caption(reel_row.caption, fallback=reel_row.ig_code or "")
    if not query:
        return {
            "items": [],
            "source": {
                "handle": ig_handle,
                "permalink": reel_row.permalink,
            },
            "query": "",
            "error": "no_query",
        }

    try:
        raw_items = await search_similar_tiktok(query, max_results=_SIMILAR_LIMIT)
    except TikTokSearchError as exc:
        logger.warning(
            "Find similar failed: kind=%s status=%s detail=%s",
            exc.kind.value, exc.status_code, exc,
        )
        return {
            "items": [],
            "source": {
                "handle": ig_handle,
                "permalink": reel_row.permalink,
            },
            "query": query,
            "error": exc.kind.value,
        }

    items = [
        to_discovery_item(it["source_handle"], it).to_dict()
        for it in raw_items
    ]
    return {
        "items": items,
        "source": {
            "handle": ig_handle,
            "permalink": reel_row.permalink,
        },
        "query": query,
        "error": None,
    }
