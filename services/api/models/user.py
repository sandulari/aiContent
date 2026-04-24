from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.user_page import UserPage
    from models.user_template import UserTemplate
    from models.user_export import UserExport
    from models.scheduled_reel import ScheduledReel

class User(UUIDMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    ig_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ig_auth_method: Mapped[str] = mapped_column(String(30), default="username_only")
    ig_session_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Instagram API with Instagram Login (OAuth). Populated after the
    # user completes the Connect Instagram flow. ig_access_token is
    # Fernet-encrypted ciphertext — never the raw token.
    ig_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ig_account_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ig_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ig_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ig_token_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ig_profile_picture_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ig_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now(), onupdate=datetime.utcnow)
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    refresh_token_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pages: Mapped[List["UserPage"]] = relationship("UserPage", back_populates="user", cascade="all, delete-orphan")
    templates: Mapped[List["UserTemplate"]] = relationship("UserTemplate", back_populates="user", cascade="all, delete-orphan")
    exports: Mapped[List["UserExport"]] = relationship("UserExport", back_populates="user", cascade="all, delete-orphan")
    scheduled_reels: Mapped[List["ScheduledReel"]] = relationship("ScheduledReel", back_populates="user", cascade="all, delete-orphan")
