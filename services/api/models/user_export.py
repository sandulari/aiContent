from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user import User

class UserExport(UUIDMixin, Base):
    __tablename__ = "user_exports"
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_page_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="SET NULL"), nullable=True)
    viral_reel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_templates.id", ondelete="CASCADE"), nullable=False)
    headline_text: Mapped[str] = mapped_column(Text, nullable=False)
    headline_style: Mapped[dict] = mapped_column(JSONB, default=dict)
    subtitle_text: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_style: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Per-export overrides for the multi-layer text system. When NULL or
    # empty, the exporter falls back to the parent template's text_layers,
    # and if that is also empty, to the legacy headline/subtitle fields.
    text_layers_overrides: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_transform: Mapped[dict] = mapped_column(JSONB, default=dict)
    video_trim: Mapped[dict] = mapped_column(JSONB, default=dict)
    audio_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    logo_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    logo_override_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    export_minio_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_status: Mapped[str] = mapped_column(String(20), default="editing")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    exported_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="exports")
