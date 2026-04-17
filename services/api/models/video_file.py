from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import BigInteger, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.viral_reel import ViralReel

class VideoFile(UUIDMixin, Base):
    __tablename__ = "video_files"
    viral_reel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    file_type: Mapped[str] = mapped_column(String(30), nullable=False)
    minio_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    viral_reel: Mapped[Optional["ViralReel"]] = relationship("ViralReel", back_populates="files")
