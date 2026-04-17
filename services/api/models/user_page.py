from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user import User
    from models.page_profile import PageProfile

class UserPage(UUIDMixin, Base):
    __tablename__ = "user_pages"
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ig_username: Mapped[str] = mapped_column(String(200), nullable=False)
    ig_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ig_profile_pic_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_type: Mapped[str] = mapped_column(String(20), nullable=False, default="own", server_default="own")
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_posts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_views_per_reel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="pages")
    profiles: Mapped[List["PageProfile"]] = relationship("PageProfile", back_populates="user_page", cascade="all, delete-orphan")
