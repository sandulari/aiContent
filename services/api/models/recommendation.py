from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import Boolean, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user_page import UserPage
    from models.viral_reel import ViralReel

class UserReelRecommendation(UUIDMixin, Base):
    __tablename__ = "user_reel_recommendations"
    user_page_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    viral_reel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_factors: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    recommended_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    user_page: Mapped[Optional["UserPage"]] = relationship("UserPage")
    viral_reel: Mapped[Optional["ViralReel"]] = relationship("ViralReel")
