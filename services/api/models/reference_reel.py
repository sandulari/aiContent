"""Cached reels for the per-reference-page discovery pipeline.

One row per (reference_page, IG media id). Refreshed in the background by
a worker task; the API reads from this table when it needs to render the
discovery feed or compute a filter preview. Acts as the durable RapidAPI
response cache (Task 1.3 spec: "minimum 1h TTL to avoid burning quota").
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class ReferenceReel(UUIDMixin, Base):
    __tablename__ = "reference_reels"

    reference_page_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reference_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    ig_media_id: Mapped[str] = mapped_column(String(50), nullable=False)
    ig_code: Mapped[str] = mapped_column(String(50), nullable=False)
    permalink: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    like_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    comment_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "reference_page_id", "ig_media_id", name="uq_reference_reels_page_media"
        ),
        Index("idx_reference_reels_page_posted", "reference_page_id", "posted_at"),
        # Supports rank-by-views and the discovery /preview count query.
        Index("idx_reference_reels_views", "view_count"),
        # Supports "rows older than X" sweep in the periodic refresh task.
        Index("idx_reference_reels_fetched", "fetched_at"),
    )
