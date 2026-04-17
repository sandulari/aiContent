from datetime import datetime
from uuid import UUID
from sqlalchemy import ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, UUIDMixin

class DiscoveryRun(UUIDMixin, Base):
    __tablename__ = "discovery_runs"
    niche_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("niches.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    candidates_confirmed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    candidates_rejected: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    hashtags_used: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pages_crawled: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
