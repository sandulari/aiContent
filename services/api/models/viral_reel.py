from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID
from sqlalchemy import BigInteger, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.theme_page import ThemePage
    from models.niche import Niche
    from models.video_source import VideoSource
    from models.video_file import VideoFile

class ViralReel(UUIDMixin, Base):
    __tablename__ = "viral_reels"
    theme_page_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("theme_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    ig_video_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    ig_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    niche_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("niches.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="discovered")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now(), onupdate=datetime.utcnow)

    theme_page: Mapped[Optional["ThemePage"]] = relationship("ThemePage", back_populates="reels")
    niche: Mapped[Optional["Niche"]] = relationship("Niche")
    sources: Mapped[List["VideoSource"]] = relationship("VideoSource", back_populates="viral_reel", cascade="all, delete-orphan")
    files: Mapped[List["VideoFile"]] = relationship("VideoFile", back_populates="viral_reel", cascade="all, delete-orphan")
