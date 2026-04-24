"""Scheduled reel: a row the cron dispatcher picks up to publish to IG.

Lifecycle: queued -> processing -> (published | failed) | cancelled.
cancelled is a terminal state set by the user while still queued.
"""
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user import User
    from models.user_export import UserExport


class ScheduledReel(UUIDMixin, Base):
    __tablename__ = "scheduled_reels"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT so we can't orphan queued publishes by deleting the export.
    # Frontend should block export deletion while a schedule exists.
    user_export_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_exports.id", ondelete="RESTRICT"),
        nullable=False,
    )
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # user_tags JSONB — array of {username, x?, y?} or just [username, ...].
    # Graph API supports up to 20 user tags on a Reels container.
    user_tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # IANA tz name stored for display purposes only; scheduled_at is UTC.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # queued | processing | published | failed | cancelled
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    share_to_feed: Mapped[bool] = mapped_column(
        default=True, server_default="true", nullable=False
    )

    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Set when we POST /{ig_user_id}/media — used to poll + publish.
    ig_container_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Final published media id after POST /media_publish succeeds.
    ig_media_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Celery task id — lets the stuck-processing cleanup job revoke a
    # task before flipping the row to failed, so we don't orphan one.
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Composite indexes match the two hot access patterns:
    #   1) cron picker: WHERE status='queued' AND scheduled_at <= now()
    #   2) user list:   WHERE user_id=? ORDER BY scheduled_at DESC
    __table_args__ = (
        Index("idx_scheduled_reels_status_time", "status", "scheduled_at"),
        Index("idx_scheduled_reels_user_time", "user_id", "scheduled_at"),
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="scheduled_reels")
    export: Mapped[Optional["UserExport"]] = relationship("UserExport")
