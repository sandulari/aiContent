from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user_page import UserPage

class PageProfile(UUIDMixin, Base):
    __tablename__ = "page_profiles"
    user_page_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    niche_primary: Mapped[str | None] = mapped_column(String(100), nullable=True)
    niche_secondary: Mapped[str | None] = mapped_column(String(100), nullable=True)
    top_topics: Mapped[dict] = mapped_column(JSONB, default=list)
    top_formats: Mapped[dict] = mapped_column(JSONB, default=list)
    content_style: Mapped[dict] = mapped_column(JSONB, default=dict)
    best_duration_range: Mapped[dict] = mapped_column(JSONB, default=dict)
    caption_style: Mapped[dict] = mapped_column(JSONB, default=dict)
    posting_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_performing_reel_ids: Mapped[dict] = mapped_column(JSONB, default=list)
    analysis_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    user_page: Mapped["UserPage"] = relationship("UserPage", back_populates="profiles")
