from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from models.base import Base
import uuid


class ReelProfile(Base):
    __tablename__ = "reel_profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    viral_reel_id = Column(UUID(as_uuid=True), ForeignKey("viral_reels.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    topic = Column(String(200), nullable=True)
    format = Column(String(100), nullable=True)
    hook_pattern = Column(String(200), nullable=True)
    visual_style = Column(String(100), nullable=True)
    audio_type = Column(String(100), nullable=True)
    content_summary = Column(Text, nullable=True)
    niche_tags = Column(ARRAY(String), nullable=True)
    confidence = Column(Float, default=0)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
