from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, UUIDMixin

class NicheHashtag(UUIDMixin, Base):
    __tablename__ = "niche_hashtags"
    niche_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("niches.id", ondelete="CASCADE"), nullable=False, index=True)
    hashtag: Mapped[str] = mapped_column(String(200), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    candidates_produced: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
