from sqlalchemy import Column, String, BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from models.base import Base
import uuid


class UserPageReel(Base):
    __tablename__ = "user_page_reels"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_page_id = Column(UUID(as_uuid=True), ForeignKey("user_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    ig_code = Column(String(50), nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    view_count = Column(BigInteger, default=0)
    like_count = Column(BigInteger, default=0)
    comment_count = Column(BigInteger, default=0)
    caption = Column(Text, nullable=True)
    scraped_at = Column(DateTime(timezone=True), nullable=True)
