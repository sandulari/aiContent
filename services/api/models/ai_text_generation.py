from datetime import datetime
from uuid import UUID
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, UUIDMixin

class AITextGeneration(UUIDMixin, Base):
    __tablename__ = "ai_text_generations"
    viral_reel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False, index=True)
    user_page_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    headlines: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    subtitles: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    caption_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
