from typing import List
from uuid import UUID

from pydantic import BaseModel


class AIGenerateRequest(BaseModel):
    video_id: UUID
    niche: str | None = None
    caption: str | None = None
    page_name: str | None = None
    view_count: int | None = None


class AIRegenerateRequest(BaseModel):
    video_id: UUID
    style_hint: str | None = None


class AIGenerateResponse(BaseModel):
    headlines: List[str]
    subtitles: List[str]
    caption_suggestion: str | None = None
