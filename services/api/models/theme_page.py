from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.niche import Niche
    from models.viral_reel import ViralReel

class ThemePage(UUIDMixin, Base):
    __tablename__ = "theme_pages"
    username: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_url: Mapped[str] = mapped_column(Text, default="")
    niche_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("niches.id", ondelete="SET NULL"), nullable=True, index=True)
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    scrape_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    min_views_threshold: Mapped[int] = mapped_column(BigInteger, default=500000)
    last_scraped_at: Mapped[datetime | None] = mapped_column(nullable=True)
    discovered_via: Mapped[str] = mapped_column(String(30), default="manual_seed")
    discovered_from_page_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("theme_pages.id", ondelete="SET NULL"), nullable=True)
    heuristic_score: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    viral_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_status: Mapped[str] = mapped_column(String(20), default="confirmed")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    niche: Mapped[Optional["Niche"]] = relationship("Niche", back_populates="theme_pages")
    reels: Mapped[List["ViralReel"]] = relationship("ViralReel", back_populates="theme_page", cascade="all, delete-orphan")
