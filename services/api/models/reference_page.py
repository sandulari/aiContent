"""Reference pages — Instagram accounts a user has flagged as inspiration
sources for the per-reference-page discovery pipeline.

Capped at 5 per user via a Postgres trigger (defined in
``db/migrations.py``) plus a service-layer guard in the router. Duplicate
prevention via ``UNIQUE(user_id, ig_handle)``. This table is intentionally
separate from ``user_pages.page_type='reference'`` — the legacy niche-based
recommendation pipeline keeps writing there; the new per-page discovery
flow reads/writes here.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    pass


class ReferencePage(UUIDMixin, Base):
    __tablename__ = "reference_pages"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    ig_handle: Mapped[str] = mapped_column(String(200), nullable=False)
    ig_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ig_display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ig_profile_pic_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "ig_handle", name="uq_reference_pages_user_handle"),
        Index("idx_reference_pages_user_added", "user_id", "added_at"),
    )
