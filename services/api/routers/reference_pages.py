"""Per-user reference page list — inspiration sources for the new
per-reference-page discovery pipeline. Capped at 5 per user, idempotent
add semantics, scoped to the authenticated user on every operation.

Kept deliberately separate from the legacy ``user_pages.page_type='reference'``
rows that feed the niche-based recommendation feed — those are not affected
by writes here.
"""
from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.reference_page import ReferencePage
from models.user import User

router = APIRouter(prefix="/api/reference-pages", tags=["reference-pages"])

# Hard cap. Enforced both here (friendly 409 before the trigger fires) and
# by the BEFORE-INSERT trigger in db/migrations.py (race-safe backstop).
MAX_REFERENCE_PAGES = 5

# Instagram handle format. IG allows letters, digits, ``.`` and ``_``, max 30.
_IG_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")


class ReferencePageCreate(BaseModel):
    ig_handle: str = Field(..., min_length=1, max_length=200)

    @field_validator("ig_handle")
    @classmethod
    def _normalize(cls, raw: str) -> str:
        # Accept any of: "natgeo", "@natgeo", "https://instagram.com/natgeo",
        # "https://www.instagram.com/natgeo/?hl=en". Always store lowercase.
        v = raw.strip()
        v = re.sub(r"^https?://(www\.)?instagram\.com/", "", v, flags=re.I)
        v = v.split("?", 1)[0].split("/", 1)[0]
        v = v.lstrip("@").lower()
        if not _IG_HANDLE_RE.match(v):
            raise ValueError(
                "ig_handle must be 1–30 chars of letters, digits, '.' or '_'"
            )
        return v


def _row_to_dict(row: ReferencePage) -> dict:
    return {
        "id": str(row.id),
        "ig_handle": row.ig_handle,
        "ig_user_id": row.ig_user_id,
        "ig_display_name": row.ig_display_name,
        "ig_profile_pic_url": row.ig_profile_pic_url,
        "added_at": row.added_at.isoformat() if row.added_at else None,
    }


@router.get("")
async def list_reference_pages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's reference pages, newest first, with count + cap."""
    rows = (
        await db.execute(
            select(ReferencePage)
            .where(ReferencePage.user_id == current_user.id)
            .order_by(ReferencePage.added_at.desc())
        )
    ).scalars().all()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "max": MAX_REFERENCE_PAGES,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_reference_page(
    body: ReferencePageCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a reference page for the caller.

    Idempotent: if the handle is already present for this user we return
    the existing row with HTTP 200 instead of 201. Idempotency-Key header
    support comes in Phase 2.2 — for now, idempotency is just "same handle
    twice is a no-op".

    The DB trigger ``trg_reference_pages_max`` is the race-safe backstop
    for the per-user cap; the service-layer check below trades a tiny
    extra SELECT for a much friendlier error message in the common case.
    """
    # Idempotent: same handle = return existing
    existing = (
        await db.execute(
            select(ReferencePage).where(
                ReferencePage.user_id == current_user.id,
                ReferencePage.ig_handle == body.ig_handle,
            )
        )
    ).scalar_one_or_none()
    if existing:
        response.status_code = status.HTTP_200_OK
        return _row_to_dict(existing)

    # Friendly cap check — race-safe backstop is the trigger.
    count = (
        await db.execute(
            select(func.count())
            .select_from(ReferencePage)
            .where(ReferencePage.user_id == current_user.id)
        )
    ).scalar() or 0
    if count >= MAX_REFERENCE_PAGES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "max_reference_pages",
                "detail": (
                    f"At most {MAX_REFERENCE_PAGES} reference pages per user. "
                    "Remove one before adding another."
                ),
            },
        )

    row = ReferencePage(user_id=current_user.id, ig_handle=body.ig_handle)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Postgres raises with our trigger's message; surface as 409.
        orig = (str(exc.orig) if exc.orig is not None else "").lower()
        if "max 5 reference pages" in orig:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "max_reference_pages",
                    "detail": (
                        f"At most {MAX_REFERENCE_PAGES} reference pages per user."
                    ),
                },
            )
        # UNIQUE(user_id, ig_handle) — concurrent duplicate insert.
        if "uq_reference_pages_user_handle" in orig or "unique" in orig:
            again = (
                await db.execute(
                    select(ReferencePage).where(
                        ReferencePage.user_id == current_user.id,
                        ReferencePage.ig_handle == body.ig_handle,
                    )
                )
            ).scalar_one_or_none()
            if again:
                response.status_code = status.HTTP_200_OK
                return _row_to_dict(again)
        raise

    await db.refresh(row)
    return _row_to_dict(row)


@router.delete("/{ref_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reference_page(
    ref_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a reference page. Scoped to the caller — 404 if it's not theirs."""
    row = (
        await db.execute(
            select(ReferencePage).where(
                ReferencePage.id == ref_id,
                ReferencePage.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Reference page not found")
    await db.delete(row)
    await db.flush()
