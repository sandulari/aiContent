from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import Boolean, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.viral_reel import ViralReel

class VideoSource(UUIDMixin, Base):
    __tablename__ = "video_sources"
    viral_reel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    found_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    viral_reel: Mapped[Optional["ViralReel"]] = relationship("ViralReel", back_populates="sources")
