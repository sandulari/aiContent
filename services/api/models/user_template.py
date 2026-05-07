from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user import User

class UserTemplate(UUIDMixin, Base):
    __tablename__ = "user_templates"
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    user_page_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="SET NULL"), nullable=True)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_minio_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_position: Mapped[dict] = mapped_column(JSONB, default=dict)
    headline_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)
    subtitle_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Multi-layer text support. Each element is a layer dict matching the
    # schema documented in services/worker/lib/video_proc.py. When empty,
    # the renderer falls back to headline_defaults + subtitle_defaults so
    # legacy templates keep working unchanged.
    text_layers: Mapped[list] = mapped_column(JSONB, default=list)
    background_color: Mapped[str] = mapped_column(String(20), default="#000000")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ownerless template shipped with the app. Visible to every user via
    # GET /api/templates which unions WHERE user_id = :me OR is_master.
    is_master: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # When TRUE the editor renders text layers read-only with a per-layer
    # unlock toggle. Master templates default-locked; user-created ones
    # default-unlocked.
    lock_layout: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now(), onupdate=datetime.utcnow)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="templates")
