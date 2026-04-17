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
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_page_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="SET NULL"), nullable=True)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_minio_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_position: Mapped[dict] = mapped_column(JSONB, default=dict)
    headline_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)
    subtitle_defaults: Mapped[dict] = mapped_column(JSONB, default=dict)
    background_color: Mapped[str] = mapped_column(String(20), default="#000000")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now(), onupdate=datetime.utcnow)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="templates")
