"""AI-curated reel recommendations for user's pages."""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from models.user_page import UserPage
from models.recommendation import UserReelRecommendation
from models.viral_reel import ViralReel
from models.theme_page import ThemePage

router = APIRouter(prefix="/api/my-pages", tags=["recommendations"])


class RecommendationResponse(BaseModel):
    id: str
    viral_reel_id: str
    match_score: float
    match_reason: str | None = None
    match_factors: dict | None = None
    is_used: bool
    recommended_at: str
    # Reel data
    ig_url: str | None = None
    thumbnail_url: str | None = None
    view_count: int = 0
    like_count: int = 0
    duration_seconds: float | None = None
    caption: str | None = None
    posted_at: str | None = None
    source_page: str | None = None

    model_config = {"from_attributes": True}


VIRAL_VIEW_FLOOR = 500_000


@router.get("/{page_id}/recommendations", response_model=List[RecommendationResponse])
async def get_recommendations(
    page_id: UUID,
    sort_by: str = Query("score", regex="^(score|views|recent)$"),
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    min_views: int = Query(VIRAL_VIEW_FLOOR, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the recommendation pool for a page.

    Defaults enforce the product requirement: at least 100 reels with
    ≥500K views. Callers can widen the floor via `min_views` for the
    discover feed.
    """
    page = await db.execute(
        select(UserPage).where(UserPage.id == page_id, UserPage.user_id == current_user.id)
    )
    if not page.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Page not found")

    stmt = (
        select(UserReelRecommendation, ViralReel, ThemePage.username)
        .join(ViralReel, ViralReel.id == UserReelRecommendation.viral_reel_id)
        .outerjoin(ThemePage, ThemePage.id == ViralReel.theme_page_id)
        .where(
            UserReelRecommendation.user_page_id == page_id,
            UserReelRecommendation.is_dismissed.is_(False),
            ViralReel.view_count >= min_views,
        )
    )

    if sort_by == "views":
        stmt = stmt.order_by(ViralReel.view_count.desc())
    elif sort_by == "recent":
        stmt = stmt.order_by(ViralReel.posted_at.desc())
    else:
        stmt = stmt.order_by(
            UserReelRecommendation.match_score.desc(),
            ViralReel.view_count.desc(),
        )

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for rec, reel, source_page in rows:
        items.append(
            RecommendationResponse(
                id=str(rec.id),
                viral_reel_id=str(rec.viral_reel_id),
                match_score=rec.match_score,
                match_reason=rec.match_reason,
                match_factors=rec.match_factors,
                is_used=rec.is_used,
                recommended_at=str(rec.recommended_at),
                ig_url=reel.ig_url,
                thumbnail_url=reel.thumbnail_url,
                view_count=reel.view_count,
                like_count=reel.like_count,
                duration_seconds=reel.duration_seconds,
                caption=reel.caption,
                posted_at=str(reel.posted_at) if reel.posted_at else None,
                source_page=source_page,
            )
        )
    return items


@router.get("/{page_id}/recommendations/summary")
async def get_recommendations_summary(
    page_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report how full the recommendation pool is for a page.

    Drives UI warnings like "still building your feed" when the 100+
    / 500K+ target hasn't been hit yet.
    """
    page = await db.execute(
        select(UserPage).where(UserPage.id == page_id, UserPage.user_id == current_user.id)
    )
    if not page.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Page not found")

    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(ViralReel.view_count >= VIRAL_VIEW_FLOOR)
                .label("viral"),
            )
            .select_from(UserReelRecommendation)
            .join(ViralReel, ViralReel.id == UserReelRecommendation.viral_reel_id)
            .where(
                UserReelRecommendation.user_page_id == page_id,
                UserReelRecommendation.is_dismissed.is_(False),
            )
        )
    ).one()
    total = row.total or 0
    viral = row.viral or 0

    return {
        "total": total,
        "at_least_500k": viral,
        "target_min": 100,
        "view_floor": VIRAL_VIEW_FLOOR,
        "meets_target": viral >= 100,
    }


@router.post("/recommendations/{rec_id}/dismiss")
async def dismiss_recommendation(
    rec_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserReelRecommendation)
        .join(UserPage, UserPage.id == UserReelRecommendation.user_page_id)
        .where(UserReelRecommendation.id == rec_id, UserPage.user_id == current_user.id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.is_dismissed = True
    await db.flush()
    return {"status": "dismissed"}


@router.post("/recommendations/{rec_id}/use")
async def use_recommendation(
    rec_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserReelRecommendation)
        .join(UserPage, UserPage.id == UserReelRecommendation.user_page_id)
        .where(UserReelRecommendation.id == rec_id, UserPage.user_id == current_user.id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.is_used = True
    await db.flush()

    # Return the viral reel ID so frontend can navigate to source search
    return {"status": "used", "viral_reel_id": str(rec.viral_reel_id)}
