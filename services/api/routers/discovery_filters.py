"""Per-user discovery filter — GET (with defaults), PUT (upsert), POST /preview.

The DB's CHECK constraints are the authoritative validation; Pydantic mirrors
them on the way in so users see friendly 422 messages instead of a 500 from
a constraint violation.

`/preview` is the live-preview hook the filter editor calls on every change.
Until Task 1.3 lands its `reference_reels` cache the endpoint always returns
``count=0, has_cache=False`` — the UI uses ``has_cache`` to show "no data
yet" copy instead of a misleading zero.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.discovery_filter import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MIN_COMMENTS,
    DEFAULT_MIN_ENGAGEMENT_RATE,
    DEFAULT_MIN_LIKES,
    DEFAULT_MIN_VIEWS,
    DEFAULT_SORT_BY,
    MAX_AGE_DAYS_CEILING,
    DiscoveryFilter,
)
from models.user import User

router = APIRouter(prefix="/api/discovery-filter", tags=["discovery-filter"])

SortBy = Literal[
    "views_desc",
    "posted_at_desc",
    "engagement_desc",
    "likes_desc",
    "comments_desc",
]


class DiscoveryFilterPayload(BaseModel):
    """All fields optional on PUT so the UI can ship a partial update —
    unspecified fields fall back to whatever the row already has (or the
    defaults below for a brand-new row).
    """
    model_config = ConfigDict(extra="forbid")

    min_views: int = Field(default=DEFAULT_MIN_VIEWS, ge=0)
    min_likes: int = Field(default=DEFAULT_MIN_LIKES, ge=0)
    min_comments: int = Field(default=DEFAULT_MIN_COMMENTS, ge=0)
    min_engagement_rate: float = Field(
        default=DEFAULT_MIN_ENGAGEMENT_RATE, ge=0.0, le=1.0
    )
    max_age_days: int = Field(
        default=DEFAULT_MAX_AGE_DAYS, ge=1, le=MAX_AGE_DAYS_CEILING
    )
    sort_by: SortBy = Field(default=DEFAULT_SORT_BY)


def _defaults_dict() -> dict:
    return {
        "min_views": DEFAULT_MIN_VIEWS,
        "min_likes": DEFAULT_MIN_LIKES,
        "min_comments": DEFAULT_MIN_COMMENTS,
        "min_engagement_rate": DEFAULT_MIN_ENGAGEMENT_RATE,
        "max_age_days": DEFAULT_MAX_AGE_DAYS,
        "sort_by": DEFAULT_SORT_BY,
    }


def _row_to_dict(row: DiscoveryFilter) -> dict:
    return {
        "min_views": row.min_views,
        "min_likes": row.min_likes,
        "min_comments": row.min_comments,
        "min_engagement_rate": row.min_engagement_rate,
        "max_age_days": row.max_age_days,
        "sort_by": row.sort_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def get_discovery_filter(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's saved filter, or the defaults if they haven't
    saved one yet. ``is_default`` lets the UI render a "These are the
    defaults — save them once to lock them in" hint."""
    row = (
        await db.execute(
            select(DiscoveryFilter).where(DiscoveryFilter.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if not row:
        return {**_defaults_dict(), "updated_at": None, "is_default": True}
    return {**_row_to_dict(row), "is_default": False}


@router.put("")
async def put_discovery_filter(
    body: DiscoveryFilterPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert the caller's filter. Postgres ``INSERT ... ON CONFLICT (user_id)
    DO UPDATE SET ...`` so creation + update share one round trip and the
    UNIQUE constraint is race-safe."""
    values = body.model_dump()
    stmt = pg_insert(DiscoveryFilter).values(user_id=current_user.id, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            **values,
            # Bump updated_at on UPDATE (the column's DEFAULT NOW() only
            # fires on INSERT; Postgres has no built-in ON UPDATE). UI
            # reads this for the "last saved Xs ago" label.
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
    await db.flush()

    row = (
        await db.execute(
            select(DiscoveryFilter).where(DiscoveryFilter.user_id == current_user.id)
        )
    ).scalar_one()
    return {**_row_to_dict(row), "is_default": False}


@router.post("/preview", status_code=status.HTTP_200_OK)
async def preview_filter(
    body: DiscoveryFilterPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the count of reels that would match ``body`` for the caller.

    No persistence — accepts a hypothetical filter for the editor's live
    preview. Returns ``has_cache=False`` until Task 1.3's ``reference_reels``
    cache table exists; the UI reads that flag to render an explainer
    instead of a misleading zero. The validation lives in
    ``DiscoveryFilterPayload`` so an invalid preview body 422s identically
    to an invalid PUT.
    """
    # Placeholder until Task 1.3 populates `reference_reels`. The filter
    # body is still validated end-to-end so the editor's debounced
    # /preview calls give the same 422 feedback as the eventual Save.
    return {"count": 0, "has_cache": False}
