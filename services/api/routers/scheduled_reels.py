"""Scheduled IG reel publishes — CRUD + cancel + retry.

Rows created here are picked up by the cron dispatcher. The router owns
validation only; it never talks to the Graph API directly (except for
read-only insights on published reels). Every write is scoped to the
authenticated user.
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.scheduled_reel import ScheduledReel
from models.user import User
from models.user_export import UserExport
from services.crypto import decrypt_token, TokenDecryptionError

logger = logging.getLogger(__name__)

META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")

# Canonical Reels insight metric names (Graph v25, 2024+).
# If a metric is unavailable for a given media, it's simply omitted from
# the response — we default to 0 on the client side.
_INSIGHT_METRICS = "reach,views,likes,comments,shares,saved,total_interactions"
_INSIGHT_METRIC_KEYS = ("reach", "views", "likes", "comments", "shares", "saved", "total_interactions")

# Graph error subcodes that specifically mean "token is no longer valid".
# 463 = session expired; 467 = invalid access token.
_TOKEN_INVALID_SUBCODES = {463, 467}

router = APIRouter(prefix="/api/scheduled-reels", tags=["scheduled-reels"])

# ---------------------------------------------------------------------------
# Constants — tuned to Meta's published limits.
# ---------------------------------------------------------------------------

# Caption length: Meta's docs cap captions at 2200 chars.
_CAPTION_MAX = 2200
# Hashtag limit: Instagram silently drops posts with >30 hashtags.
_HASHTAG_MAX = 30
# User-tag limit on a Reels container (Graph API).
_USER_TAG_MAX = 20
# How far in the future we allow scheduling. Long-lived IG tokens are
# valid for 60 days; scheduling past that guarantees a refresh-or-fail.
_MAX_SCHEDULE_DAYS = 60
# Minimum lead time — gives the worker a safe window to pick the row up
# without racing the dispatcher's next tick.
_MIN_SCHEDULE_LEAD = timedelta(minutes=2)
# Meta rate limit: 100 publishes per IG user per rolling 24h.
_PUBLISH_DAILY_CAP = 100
# Account types that can use the Content Publishing API.
_PUBLISHING_ACCOUNT_TYPES = {"BUSINESS", "CREATOR", "MEDIA_CREATOR"}

_HASHTAG_RE = re.compile(r"\B#\w+")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ScheduleCreateRequest(BaseModel):
    user_export_id: UUID
    scheduled_at: datetime
    timezone: str = Field(default="UTC", max_length=64)
    caption: Optional[str] = Field(default=None, max_length=_CAPTION_MAX)
    user_tags: Optional[List[Any]] = None
    share_to_feed: bool = True

    @field_validator("scheduled_at")
    @classmethod
    def _scheduled_at_tz_aware(cls, v: datetime) -> datetime:
        # Reject naive datetimes; callers must send ISO8601 with an
        # explicit offset so we don't silently assume UTC.
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v.astimezone(timezone.utc)

    @field_validator("caption")
    @classmethod
    def _caption_trim(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("timezone")
    @classmethod
    def _timezone_nonblank(cls, v: str) -> str:
        v = v.strip()
        return v or "UTC"


class ScheduleUpdateRequest(BaseModel):
    scheduled_at: Optional[datetime] = None
    caption: Optional[str] = Field(default=None, max_length=_CAPTION_MAX)
    user_tags: Optional[List[Any]] = None
    share_to_feed: Optional[bool] = None

    @field_validator("scheduled_at")
    @classmethod
    def _scheduled_at_tz_aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v.astimezone(timezone.utc)

    @field_validator("caption")
    @classmethod
    def _caption_trim(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue a reel for a future Instagram publish."""
    _require_ig_publishing(current_user)

    # Export must be owned, rendered, and have a MinIO object we can
    # pull. The worker later fetches `export_minio_key` to hand Meta a
    # public URL.
    export = (
        await db.execute(
            select(UserExport).where(
                UserExport.id == body.user_export_id,
                UserExport.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not export or export.export_status != "done" or not export.export_minio_key:
        raise HTTPException(status_code=404, detail="Export not ready or not found")

    _validate_schedule_window(body.scheduled_at)
    _validate_caption(body.caption)
    tags = _normalize_user_tags(body.user_tags)

    row = ScheduledReel(
        user_id=current_user.id,
        user_export_id=body.user_export_id,
        caption=body.caption,
        user_tags=tags,
        scheduled_at=body.scheduled_at,
        timezone=body.timezone,
        status="queued",
        share_to_feed=body.share_to_feed,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _schedule_to_dict(row)


@router.get("")
async def list_schedules(
    status: Optional[str] = None,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's schedules with status counts and remaining quota."""
    # Cap `limit` so a runaway client can't page through the entire
    # table in one request.
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    filters = [ScheduledReel.user_id == current_user.id]
    if status:
        filters.append(ScheduledReel.status == status)
    if from_:
        try:
            from_dt = datetime.fromisoformat(from_)
            if from_dt.tzinfo is None:
                from_dt = from_dt.replace(tzinfo=timezone.utc)
            filters.append(ScheduledReel.scheduled_at >= from_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'from' date")
    if to:
        try:
            to_dt = datetime.fromisoformat(to)
            if to_dt.tzinfo is None:
                to_dt = to_dt.replace(tzinfo=timezone.utc)
            filters.append(ScheduledReel.scheduled_at <= to_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'to' date")

    result = await db.execute(
        select(ScheduledReel)
        .where(and_(*filters))
        .order_by(ScheduledReel.scheduled_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_schedule_to_dict(s) for s in result.scalars().all()]

    # Status counts across the entire user's schedule table (unfiltered
    # by the query params — a UI badge shouldn't change when you apply
    # a filter).
    counts_raw = (
        await db.execute(
            select(ScheduledReel.status, func.count())
            .where(ScheduledReel.user_id == current_user.id)
            .group_by(ScheduledReel.status)
        )
    ).all()
    counts = {"queued": 0, "processing": 0, "published": 0, "failed": 0, "cancelled": 0}
    for s, n in counts_raw:
        if s in counts:
            counts[s] = int(n)

    now = datetime.now(timezone.utc)
    last_24h_cutoff = now - timedelta(hours=24)
    publishes_last_24h = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ScheduledReel)
                .where(
                    ScheduledReel.user_id == current_user.id,
                    ScheduledReel.status == "published",
                    ScheduledReel.published_at >= last_24h_cutoff,
                )
            )
        ).scalar()
        or 0
    )

    return {
        "items": items,
        "counts": counts,
        "publishes_last_24h": publishes_last_24h,
        "publishes_remaining_today": max(0, _PUBLISH_DAILY_CAP - publishes_last_24h),
    }


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _load_owned(db, schedule_id, current_user.id)
    return _schedule_to_dict(row)


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: UUID,
    body: ScheduleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a schedule while it is still queued.

    Once a row flips to `processing` the worker owns it — we refuse to
    mutate state under it to avoid racing the Graph API call.
    """
    row = await _load_owned(db, schedule_id, current_user.id)
    if row.status != "queued":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_editable",
                "detail": f"Cannot edit schedule in status '{row.status}'",
            },
        )

    data = body.model_dump(exclude_unset=True)

    if "scheduled_at" in data and data["scheduled_at"] is not None:
        _validate_schedule_window(data["scheduled_at"])
        row.scheduled_at = data["scheduled_at"]
    if "caption" in data:
        _validate_caption(data["caption"])
        row.caption = data["caption"]
    if "user_tags" in data:
        row.user_tags = _normalize_user_tags(data["user_tags"])
    if "share_to_feed" in data and data["share_to_feed"] is not None:
        row.share_to_feed = data["share_to_feed"]

    await db.flush()
    await db.refresh(row)
    return _schedule_to_dict(row)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a queued schedule. Terminal states are immutable."""
    row = await _load_owned(db, schedule_id, current_user.id)
    if row.status != "queued":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_cancellable",
                "detail": f"Cannot cancel schedule in status '{row.status}'",
            },
        )
    row.status = "cancelled"
    await db.flush()


@router.post("/{schedule_id}/retry")
async def retry_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-queue a failed schedule with a fresh 2-minute lead time."""
    row = await _load_owned(db, schedule_id, current_user.id)
    if row.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_retryable",
                "detail": f"Cannot retry schedule in status '{row.status}'",
            },
        )
    # Require IG to be usable right now — otherwise we just fail again.
    _require_ig_publishing(current_user)

    row.status = "queued"
    row.scheduled_at = datetime.now(timezone.utc) + _MIN_SCHEDULE_LEAD
    row.attempt_count = 0
    row.last_error = None
    row.ig_container_id = None
    row.celery_task_id = None
    row.processing_started_at = None
    await db.flush()
    await db.refresh(row)
    return _schedule_to_dict(row)


@router.get("/{schedule_id}/insights")
async def get_schedule_insights(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch post-publish metrics from Meta Graph for a published reel.

    No caching — Graph is the source of truth, calls are cheap, and we
    want a live number every time the user clicks "View insights".
    """
    row = await _load_owned(db, schedule_id, current_user.id)

    # Only published rows with a real media id have insights to fetch.
    if row.status != "published" or not row.ig_media_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_published",
                "detail": f"Insights are only available for published reels (current status: '{row.status}')",
            },
        )

    # Token must be present, decryptable, and not obviously expired.
    if not current_user.ig_access_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "ig_not_connected", "detail": "Instagram not connected"},
        )

    expires = current_user.ig_token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is None or expires <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401,
            detail={"code": "ig_token_expired", "detail": "Instagram not connected or token expired"},
        )

    try:
        access_token = decrypt_token(current_user.ig_access_token)
    except TokenDecryptionError:
        raise HTTPException(
            status_code=401,
            detail={"code": "ig_token_invalid", "detail": "Stored Instagram token is unreadable — please reconnect"},
        )

    metrics = await _fetch_ig_insights(row.ig_media_id, access_token)

    return {
        "scheduled_reel_id": str(row.id),
        "ig_media_id": row.ig_media_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned(db: AsyncSession, schedule_id: UUID, user_id: UUID) -> ScheduledReel:
    row = (
        await db.execute(
            select(ScheduledReel).where(
                ScheduledReel.id == schedule_id,
                ScheduledReel.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Scheduled reel not found")
    return row


def _require_ig_publishing(user: User) -> None:
    """Guard against scheduling on an account that can't publish."""
    if not user.ig_user_id or not user.ig_access_token:
        raise HTTPException(
            status_code=409,
            detail={"code": "ig_not_connected", "detail": "Instagram not connected"},
        )
    expires = user.ig_token_expires_at
    if expires is not None:
        # Normalise to aware UTC so the comparison can't blow up on a
        # legacy naive timestamp.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=409,
                detail={"code": "ig_token_expired", "detail": "Instagram token expired"},
            )
    else:
        raise HTTPException(
            status_code=409,
            detail={"code": "ig_token_expired", "detail": "Instagram token expired"},
        )
    account_type = (user.ig_account_type or "").upper()
    if account_type not in _PUBLISHING_ACCOUNT_TYPES:
        if account_type == "PERSONAL":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ig_account_type_personal",
                    "detail": "Personal Instagram accounts cannot publish via API",
                },
            )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ig_account_type_unsupported",
                "detail": f"Instagram account type '{account_type or 'unknown'}' cannot publish",
            },
        )


def _validate_schedule_window(when: datetime) -> None:
    """Enforce the [now + 2 min, now + 60 days] window."""
    now = datetime.now(timezone.utc)
    earliest = now + _MIN_SCHEDULE_LEAD
    latest = now + timedelta(days=_MAX_SCHEDULE_DAYS)
    if when < earliest:
        raise HTTPException(
            status_code=400,
            detail=f"scheduled_at must be at least {int(_MIN_SCHEDULE_LEAD.total_seconds() // 60)} minutes in the future",
        )
    if when > latest:
        raise HTTPException(
            status_code=400,
            detail=f"scheduled_at cannot be more than {_MAX_SCHEDULE_DAYS} days in the future",
        )


def _validate_caption(caption: Optional[str]) -> None:
    if caption is None:
        return
    if len(caption) > _CAPTION_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Caption exceeds {_CAPTION_MAX} characters",
        )
    if _count_hashtags(caption) > _HASHTAG_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Caption contains more than {_HASHTAG_MAX} hashtags (Instagram will reject the post)",
        )


def _normalize_user_tags(raw: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    """Accept either bare usernames or `{username, x?, y?}` dicts and
    return the canonical dict form the worker expects.
    """
    if raw is None:
        return None
    if len(raw) > _USER_TAG_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Instagram allows at most {_USER_TAG_MAX} user tags per post",
        )
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            username = item.strip().lstrip("@")
            if not username:
                raise HTTPException(status_code=400, detail=f"user_tags[{idx}]: empty username")
            out.append({"username": username})
            continue
        if isinstance(item, dict):
            username = (item.get("username") or "").strip().lstrip("@")
            if not username:
                raise HTTPException(
                    status_code=400,
                    detail=f"user_tags[{idx}]: missing 'username'",
                )
            tag: Dict[str, Any] = {"username": username}
            for coord in ("x", "y"):
                if coord in item and item[coord] is not None:
                    try:
                        val = float(item[coord])
                    except (TypeError, ValueError):
                        raise HTTPException(
                            status_code=400,
                            detail=f"user_tags[{idx}].{coord} must be numeric",
                        )
                    if not (0.0 <= val <= 1.0):
                        raise HTTPException(
                            status_code=400,
                            detail=f"user_tags[{idx}].{coord} must be between 0 and 1",
                        )
                    tag[coord] = val
            out.append(tag)
            continue
        raise HTTPException(
            status_code=400,
            detail=f"user_tags[{idx}] must be a string or an object",
        )
    return out


def _schedule_to_dict(s: ScheduledReel) -> dict:
    return {
        "id": str(s.id),
        "user_id": str(s.user_id),
        "user_export_id": str(s.user_export_id),
        "caption": s.caption,
        "user_tags": s.user_tags,
        "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
        "timezone": s.timezone,
        "status": s.status,
        "share_to_feed": s.share_to_feed,
        "attempt_count": s.attempt_count,
        "last_error": s.last_error,
        "ig_container_id": s.ig_container_id,
        "ig_media_id": s.ig_media_id,
        "published_at": s.published_at.isoformat() if s.published_at else None,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _count_hashtags(caption: Optional[str]) -> int:
    if not caption:
        return 0
    return len(_HASHTAG_RE.findall(caption))


# ---------------------------------------------------------------------------
# Graph API — insights fetch (read-only, no DB cache)
# ---------------------------------------------------------------------------


def _safe_graph_error_body(resp: httpx.Response) -> Dict[str, Any]:
    """Parse Meta's error JSON defensively so we never blow up on a log line."""
    try:
        payload = resp.json()
    except Exception:
        return {"raw": resp.text[:500]}
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return payload["error"]
    return payload if isinstance(payload, dict) else {"body": payload}


async def _fetch_ig_insights(ig_media_id: str, access_token: str) -> Dict[str, int]:
    """Call Graph insights for a media id and return a flat {metric: value} dict.

    Raises HTTPException(401) when the token has been invalidated (Graph
    error subcode 463/467) so the frontend can prompt a reconnect.
    Raises HTTPException(502) for any other Graph failure.
    """
    url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/{ig_media_id}/insights"
    params = {"metric": _INSIGHT_METRICS, "access_token": access_token}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("IG insights network error for media=%s: %s", ig_media_id, exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "ig_graph_unreachable", "detail": f"Instagram Graph API unreachable: {exc}"},
        )

    if resp.status_code != 200:
        body = _safe_graph_error_body(resp)
        subcode = body.get("error_subcode") if isinstance(body, dict) else None
        code = body.get("code") if isinstance(body, dict) else None
        message = (
            body.get("error_user_msg")
            or body.get("message")
            or body.get("error_description")
            or "Failed to fetch Instagram insights"
        )
        logger.warning(
            "IG insights fetch failed media=%s status=%s body=%s",
            ig_media_id, resp.status_code, body,
        )
        # Token invalidated server-side — force a reconnect.
        if subcode in _TOKEN_INVALID_SUBCODES or code == 190:
            raise HTTPException(
                status_code=401,
                detail={"code": "ig_token_invalid", "detail": message},
            )
        raise HTTPException(
            status_code=502,
            detail={"code": "ig_graph_error", "detail": message},
        )

    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail={"code": "ig_graph_malformed", "detail": "Malformed insights response"},
        )

    # Flatten to {metric_name: int}. Default anything missing to 0 so the
    # UI can render the full grid without branching on null.
    flat: Dict[str, int] = {k: 0 for k in _INSIGHT_METRIC_KEYS}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name not in flat:
            continue
        values = entry.get("values")
        if isinstance(values, list) and values:
            raw_val = values[0].get("value") if isinstance(values[0], dict) else None
            try:
                flat[name] = int(raw_val) if raw_val is not None else 0
            except (TypeError, ValueError):
                flat[name] = 0
    return flat
