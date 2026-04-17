"""AI text generation — headlines, subtitles, captions."""
import time
from collections import defaultdict
from typing import List, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.ai_text_generation import AITextGeneration
from models.page_profile import PageProfile
from models.theme_page import ThemePage
from models.user import User
from models.user_page import UserPage
from models.viral_reel import ViralReel
from services.ai_text import chat_with_claude, generate_ai_text

router = APIRouter(prefix="/api/ai", tags=["ai"])

# --- In-memory per-user rate limiter for AI endpoints ---
_rate_limits: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60  # seconds
_RATE_MAX = 10  # requests per window


def _check_rate_limit(user_id: str):
    now = time.time()
    timestamps = _rate_limits[user_id]
    _rate_limits[user_id] = [t for t in timestamps if now - t < _RATE_WINDOW]
    if len(_rate_limits[user_id]) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Too many AI requests. Please wait a minute.")
    _rate_limits[user_id].append(now)


class GenerateRequest(BaseModel):
    viral_reel_id: UUID
    user_page_id: UUID


class RegenerateRequest(BaseModel):
    viral_reel_id: UUID
    user_page_id: UUID
    style_hint: str | None = Field(default=None, max_length=200)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    viral_reel_id: UUID
    user_page_id: UUID
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=30)


async def _load_owned_page(
    user_page_id: UUID, current_user: User, db: AsyncSession
) -> UserPage:
    result = await db.execute(
        select(UserPage).where(
            UserPage.id == user_page_id, UserPage.user_id == current_user.id
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        # Hide existence vs ownership with a uniform 404.
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.post("/generate-text")
async def generate_text(
    body: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(str(current_user.id))
    reel = await db.get(ViralReel, body.viral_reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    page_obj = await _load_owned_page(body.user_page_id, current_user, db)

    prof_result = await db.execute(
        select(PageProfile)
        .where(PageProfile.user_page_id == page_obj.id)
        .order_by(PageProfile.analyzed_at.desc())
        .limit(1)
    )
    page_profile = prof_result.scalar_one_or_none()
    niche = (page_profile.niche_primary if page_profile else None) or "General"

    result = await generate_ai_text(
        niche=niche,
        caption=reel.caption or "",
        page_name=page_obj.ig_username,
        view_count=reel.view_count or 0,
        style_hint=None,
    )

    gen = AITextGeneration(
        viral_reel_id=reel.id,
        user_page_id=page_obj.id,
        headlines=result["headlines"],
        subtitles=result["subtitles"],
        caption_suggestion=result.get("caption_suggestion"),
        model_used=result.get("model_used", "unknown"),
    )
    db.add(gen)
    await db.flush()

    return {
        "headlines": result["headlines"],
        "subtitles": result["subtitles"],
        "caption_suggestion": result.get("caption_suggestion"),
    }


@router.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Multi-turn chat with Claude. The frontend sends the full
    conversation history every turn and we send back the assistant's
    next message plus parsed headline/subtitle/caption suggestions.
    """
    _check_rate_limit(str(current_user.id))
    reel = await db.get(ViralReel, body.viral_reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    page = await _load_owned_page(body.user_page_id, current_user, db)

    # Pull the latest page_profiles row for richer context.
    prof_result = await db.execute(
        select(PageProfile)
        .where(PageProfile.user_page_id == page.id)
        .order_by(PageProfile.analyzed_at.desc())
        .limit(1)
    )
    profile = prof_result.scalar_one_or_none()

    niche = (profile.niche_primary if profile else None) or "general"
    topics = []
    audience = ""
    if profile:
        if isinstance(profile.top_topics, list):
            topics = profile.top_topics
        elif isinstance(profile.top_topics, str):
            try:
                import json as _json

                topics = _json.loads(profile.top_topics)
            except Exception:
                topics = []
        style = profile.content_style or {}
        if isinstance(style, dict):
            audience = style.get("target_audience", "") or ""

    # Source page username for the reel.
    tp_result = await db.execute(
        select(ThemePage.username).where(ThemePage.id == reel.theme_page_id)
    )
    source_page = tp_result.scalar_one_or_none() or ""

    try:
        result = await chat_with_claude(
            messages=[m.model_dump() for m in body.messages],
            reel_caption=reel.caption or "",
            reel_views=int(reel.view_count or 0),
            reel_source_page=source_page,
            page_niche=niche,
            page_audience=audience,
            page_topics=topics,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI chat failed: {str(e)[:200]}")

    return {
        "assistant_message": result.get("assistant_message", ""),
        "suggestions": result.get("suggestions", {"headlines": [], "subtitles": [], "caption": ""}),
    }


@router.post("/regenerate")
async def regenerate_text(
    body: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(str(current_user.id))
    reel = await db.get(ViralReel, body.viral_reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    page_obj = await _load_owned_page(body.user_page_id, current_user, db)

    prof_result = await db.execute(
        select(PageProfile)
        .where(PageProfile.user_page_id == page_obj.id)
        .order_by(PageProfile.analyzed_at.desc())
        .limit(1)
    )
    page_profile = prof_result.scalar_one_or_none()
    niche = (page_profile.niche_primary if page_profile else None) or "General"

    result = await generate_ai_text(
        niche=niche,
        caption=reel.caption or "",
        page_name=page_obj.ig_username,
        view_count=reel.view_count or 0,
        style_hint=body.style_hint,
    )

    gen = AITextGeneration(
        viral_reel_id=reel.id,
        user_page_id=page_obj.id,
        headlines=result["headlines"],
        subtitles=result["subtitles"],
        caption_suggestion=result.get("caption_suggestion"),
        style_hint=body.style_hint,
        model_used=result.get("model_used", "unknown"),
    )
    db.add(gen)
    await db.flush()

    return {
        "headlines": result["headlines"],
        "subtitles": result["subtitles"],
        "caption_suggestion": result.get("caption_suggestion"),
    }
