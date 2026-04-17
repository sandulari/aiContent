from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class PageSnapshot(UUIDMixin, Base):
    __tablename__ = "page_snapshots"

    user_page_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taken_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    week_key: Mapped[str] = mapped_column(String(10), nullable=False)
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_posts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_views_week: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_likes_week: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_comments_week: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top_reel_ig_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    top_reel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_reel_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top_reel_likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top_reel_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
