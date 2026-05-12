"""Per-user download record for a reference reel.

One row per (user, reference_reel). UNIQUE(user_id, reference_reel_id)
makes the POST endpoint idempotent at the (user, item) level — re-posting
the same item returns the existing row instead of duplicating.

Status transitions: ``queued`` -> ``downloading`` -> ``done`` | ``failed``.
``minio_key`` is populated on ``done``; ``error_message`` on ``failed``.

Task 1.7 (editor handoff) reads this table to surface a "Edit downloaded
reel" action once status is ``done``.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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


# Single source of truth for the status enum — kept in lockstep with the
# DB CHECK constraint in migrations.py.
STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
ALL_STATUSES = (STATUS_QUEUED, STATUS_DOWNLOADING, STATUS_DONE, STATUS_FAILED)


class Download(UUIDMixin, Base):
    __tablename__ = "downloads"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference_reel_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reference_reels.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_QUEUED,
        server_default=STATUS_QUEUED,
    )
    minio_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "reference_reel_id", name="uq_downloads_user_reel"
        ),
        CheckConstraint(
            "status IN ('queued','downloading','done','failed')",
            name="ck_downloads_status",
        ),
        Index("idx_downloads_user_created", "user_id", "created_at"),
    )
