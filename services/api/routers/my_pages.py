"""Instagram pages a user has connected — both their own pages and
reference pages they want to draw inspiration from."""
import re
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.page_profile import PageProfile
from models.page_snapshot import PageSnapshot
from models.user import User
from models.user_page import UserPage

router = APIRouter(prefix="/api/my-pages", tags=["my-pages"])


PageType = Literal["own", "reference"]


class AddPageRequest(BaseModel):
    ig_username: str = Field(..., min_length=1, max_length=30)
    page_type: PageType = Field(default="own")


class PageResponse(BaseModel):
    id: str
    ig_username: str
    ig_display_name: str | None = None
    ig_profile_pic_url: str | None = None
    page_type: str = "own"
    follower_count: int | None = None
    total_posts: int | None = None
    avg_views_per_reel: int | None = None
    avg_engagement_rate: float | None = None
    is_active: bool
    last_analyzed_at: str | None = None
    created_at: str
    niche: str | None = None
    top_topics: list | None = None

    model_config = {"from_attributes": True}


class PageProfileResponse(BaseModel):
    id: str
    niche_primary: str | None = None
    niche_secondary: str | None = None
    top_topics: list | None = None
    top_formats: list | None = None
    content_style: dict | None = None
    best_duration_range: dict | None = None
    caption_style: dict | None = None
    posting_frequency: float | None = None
    analyzed_at: str | None = None

    model_config = {"from_attributes": True}


class WeeklyDashboardResponse(BaseModel):
    page_id: str
    ig_username: str
    has_data: bool
    week_key: str | None = None
    follower_count: int | None = None
    follower_delta: int | None = None
    total_posts: int | None = None
    total_posts_delta: int | None = None
    total_views_week: int | None = None
    total_likes_week: int | None = None
    total_comments_week: int | None = None
    comments_gained_wow: int | None = None
    engagement_rate_delta: float | None = None
    top_reel: dict | None = None
    snapshots_available: int = 0


@router.get("", response_model=List[PageResponse])
async def list_my_pages(
    page_type: Optional[PageType] = Query(None, description="Filter by 'own' or 'reference'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(UserPage).where(UserPage.user_id == current_user.id)
    if page_type:
        stmt = stmt.where(UserPage.page_type == page_type)
    stmt = stmt.order_by(UserPage.created_at.desc())

    result = await db.execute(stmt)
    pages = result.scalars().all()

    # Batch-load the latest PageProfile for every page in one query
    page_ids = [p.id for p in pages]
    profile_map: dict = {}
    if page_ids:
        latest_analyzed = (
            select(
                PageProfile.user_page_id,
                func.max(PageProfile.analyzed_at).label("max_analyzed"),
            )
            .where(PageProfile.user_page_id.in_(page_ids))
            .group_by(PageProfile.user_page_id)
            .subquery()
        )
        prof_stmt = (
            select(PageProfile)
            .join(
                latest_analyzed,
                (PageProfile.user_page_id == latest_analyzed.c.user_page_id)
                & (PageProfile.analyzed_at == latest_analyzed.c.max_analyzed),
            )
        )
        prof_result = await db.execute(prof_stmt)
        for prof in prof_result.scalars().all():
            profile_map[prof.user_page_id] = prof

    items: list[PageResponse] = []
    for p in pages:
        resp = PageResponse(
            id=str(p.id),
            ig_username=p.ig_username,
            ig_display_name=p.ig_display_name,
            ig_profile_pic_url=p.ig_profile_pic_url,
            page_type=p.page_type,
            follower_count=p.follower_count,
            total_posts=p.total_posts,
            avg_views_per_reel=p.avg_views_per_reel,
            avg_engagement_rate=p.avg_engagement_rate,
            is_active=p.is_active,
            last_analyzed_at=str(p.last_analyzed_at) if p.last_analyzed_at else None,
            created_at=str(p.created_at),
        )
        prof = profile_map.get(p.id)
        if prof:
            resp.niche = prof.niche_primary
            resp.top_topics = prof.top_topics if isinstance(prof.top_topics, list) else []
        items.append(resp)
    return items


@router.post("", response_model=PageResponse, status_code=status.HTTP_201_CREATED)
async def add_page(
    body: AddPageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    username = body.ig_username.strip().lstrip("@")
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not re.match(r'^[a-zA-Z0-9_.]{1,30}$', username):
        raise HTTPException(
            status_code=400,
            detail="Invalid Instagram username. Use only letters, numbers, underscores, and periods.",
        )

    existing = await db.execute(
        select(UserPage).where(
            UserPage.user_id == current_user.id, UserPage.ig_username == username
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Page already connected")

    page = UserPage(
        user_id=current_user.id,
        ig_username=username,
        ig_display_name=username,
        page_type=body.page_type,
    )
    db.add(page)
    await db.flush()
    await db.refresh(page)

    # Snapshot sibling IDs BEFORE we commit + dispatch, so we can queue
    # their re-analysis in the same request. Every time a page is added,
    # every surviving page's combined signature (own + all refs) changes,
    # so each one must be re-analyzed so Claude sees the new reference set.
    sibling_rows = await db.execute(
        select(UserPage.id).where(
            UserPage.user_id == current_user.id,
            UserPage.id != page.id,
            UserPage.is_active.is_(True),
        )
    )
    sibling_ids = [str(r[0]) for r in sibling_rows.all()]

    await db.commit()

    import logging

    logger = logging.getLogger(__name__)
    try:
        from celery_client import trigger_analyze_page

        # Queue the new page first so its own analysis starts.
        trigger_analyze_page(page.id)

        # Explicitly queue re-analysis for every surviving sibling.
        # The API owns this cascade (not the worker's internal fan-out)
        # so it bypasses the cooldown check and triggers reliably.
        for sib_id in sibling_ids:
            try:
                trigger_analyze_page(UUID(sib_id))
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue sibling re-analysis for %s: %s", sib_id, exc
                )
    except Exception as exc:
        logger.warning("Failed to enqueue analyze_page for @%s: %s", username, exc)
        # Last-ditch: run the in-process path so the user isn't blocked
        # forever if the broker is down. Slower but still works.
        try:
            from services.page_analyzer import analyze_and_recommend

            await analyze_and_recommend(str(page.id), username, db)
            await db.refresh(page)
        except Exception as exc2:
            logger.warning("In-process fallback also failed for @%s: %s", username, exc2)

    return PageResponse(
        id=str(page.id),
        ig_username=page.ig_username,
        ig_display_name=page.ig_display_name,
        ig_profile_pic_url=page.ig_profile_pic_url,
        page_type=page.page_type,
        follower_count=page.follower_count,
        total_posts=page.total_posts,
        is_active=True,
        created_at=str(page.created_at),
        niche=None,
    )


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_page(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPage).where(
            UserPage.id == page_id, UserPage.user_id == current_user.id
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    # Snapshot the surviving sibling IDs BEFORE deletion so we can
    # re-analyze them — their combined signature (own + all refs) just
    # lost one component.
    sibling_rows = await db.execute(
        select(UserPage.id).where(
            UserPage.user_id == current_user.id,
            UserPage.id != page_id,
            UserPage.is_active.is_(True),
        )
    )
    sibling_ids = [str(r[0]) for r in sibling_rows.all()]

    await db.delete(page)
    await db.commit()

    # Re-analyze every surviving page asynchronously so each one picks
    # up a fresh Claude profile reflecting the new sibling set.
    import logging

    logger = logging.getLogger(__name__)
    try:
        from celery_client import trigger_analyze_page

        for sib_id in sibling_ids:
            try:
                trigger_analyze_page(UUID(sib_id))
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue re-analysis for sibling %s after delete: %s",
                    sib_id, exc,
                )
    except Exception as exc:
        logger.warning("Failed to dispatch sibling re-analysis after delete: %s", exc)


@router.get("/{page_id}/profile", response_model=PageProfileResponse)
async def get_page_profile(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page = await db.execute(
        select(UserPage).where(UserPage.id == page_id, UserPage.user_id == current_user.id)
    )
    if not page.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Page not found")

    result = await db.execute(
        select(PageProfile)
        .where(PageProfile.user_page_id == page_id)
        .order_by(PageProfile.analyzed_at.desc())
        .limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Page not yet analyzed")

    return PageProfileResponse(
        id=str(profile.id),
        niche_primary=profile.niche_primary,
        niche_secondary=profile.niche_secondary,
        top_topics=profile.top_topics if isinstance(profile.top_topics, list) else [],
        top_formats=profile.top_formats if isinstance(profile.top_formats, list) else [],
        content_style=profile.content_style if isinstance(profile.content_style, dict) else {},
        best_duration_range=profile.best_duration_range
        if isinstance(profile.best_duration_range, dict)
        else {},
        caption_style=profile.caption_style if isinstance(profile.caption_style, dict) else {},
        posting_frequency=profile.posting_frequency,
        analyzed_at=str(profile.analyzed_at) if profile.analyzed_at else None,
    )


@router.get("/{page_id}/stats")
async def get_page_stats(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPage).where(
            UserPage.id == page_id, UserPage.user_id == current_user.id
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    return {
        "follower_count": page.follower_count,
        "total_posts": page.total_posts,
        "avg_views_per_reel": page.avg_views_per_reel,
        "avg_engagement_rate": page.avg_engagement_rate,
        "page_type": page.page_type,
    }


def _safe_sub(a: int | None, b: int | None) -> int | None:
    if a is None or b is None:
        return None
    return a - b


@router.get("/{page_id}/weekly-dashboard", response_model=WeeklyDashboardResponse)
async def get_weekly_dashboard(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return this-week vs last-week stats for a user's own page.

    Only applies to page_type='own'. Reference pages get a 404 — they
    don't need a growth dashboard.
    """
    result = await db.execute(
        select(UserPage).where(
            UserPage.id == page_id, UserPage.user_id == current_user.id
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if page.page_type != "own":
        raise HTTPException(
            status_code=400,
            detail="Weekly dashboard is only available for your own pages",
        )

    snap_result = await db.execute(
        select(PageSnapshot)
        .where(PageSnapshot.user_page_id == page_id)
        .order_by(desc(PageSnapshot.taken_at))
        .limit(8)
    )
    snaps = snap_result.scalars().all()

    if not snaps:
        return WeeklyDashboardResponse(
            page_id=str(page.id),
            ig_username=page.ig_username,
            has_data=False,
            snapshots_available=0,
        )

    latest = snaps[0]
    prev = snaps[1] if len(snaps) > 1 else None

    follower_delta = _safe_sub(latest.follower_count, prev.follower_count if prev else None)
    posts_delta = _safe_sub(latest.total_posts, prev.total_posts if prev else None)
    comments_wow = _safe_sub(
        latest.total_comments_week, prev.total_comments_week if prev else None
    )

    engagement_delta: float | None = None
    if latest.follower_count and latest.total_likes_week is not None:
        latest_rate = latest.total_likes_week / max(latest.follower_count, 1)
        prev_rate = None
        if prev and prev.follower_count and prev.total_likes_week is not None:
            prev_rate = prev.total_likes_week / max(prev.follower_count, 1)
        if prev_rate is not None:
            engagement_delta = round(latest_rate - prev_rate, 4)

    top_reel = None
    if latest.top_reel_ig_id:
        top_reel = {
            "ig_video_id": latest.top_reel_ig_id,
            "ig_url": latest.top_reel_url,
            "view_count": latest.top_reel_views,
            "like_count": latest.top_reel_likes,
            "caption": latest.top_reel_caption,
        }

    return WeeklyDashboardResponse(
        page_id=str(page.id),
        ig_username=page.ig_username,
        has_data=True,
        week_key=latest.week_key,
        follower_count=latest.follower_count,
        follower_delta=follower_delta,
        total_posts=latest.total_posts,
        total_posts_delta=posts_delta,
        total_views_week=latest.total_views_week,
        total_likes_week=latest.total_likes_week,
        total_comments_week=latest.total_comments_week,
        comments_gained_wow=comments_wow,
        engagement_rate_delta=engagement_delta,
        top_reel=top_reel,
        snapshots_available=len(snaps),
    )


@router.post("/{page_id}/refresh-stats", status_code=status.HTTP_202_ACCEPTED)
async def refresh_stats_now(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a fresh snapshot for the user's own page."""
    result = await db.execute(
        select(UserPage).where(
            UserPage.id == page_id, UserPage.user_id == current_user.id
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if page.page_type != "own":
        raise HTTPException(
            status_code=400,
            detail="Stats refresh is only available for your own pages",
        )

    from celery_client import trigger_page_stats_snapshot

    task_id = trigger_page_stats_snapshot(page.id)
    return {"status": "queued", "task_id": task_id}
