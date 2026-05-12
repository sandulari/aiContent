"""Refresh tokens — separate table enabling rotation + reuse detection.

Each ``/api/auth/login`` (or register) starts a new *family*. Every
``/api/auth/refresh`` rotates: the presented token is marked revoked
and a successor is inserted in the SAME family. If a token that's
already ``revoked_at IS NOT NULL`` is ever presented again, that's a
replay of an old token — we delete every row in the family so the
attacker AND the legitimate user are forced to log in again, and the
session can't continue to rotate forward.

Why a dedicated table and not just ``users.refresh_token``: the legacy
column overwrote the hash on every rotation, so a replay of an older
token simply failed authentication — indistinguishable from an
expired token. With the per-row history here, we can tell "this token
was once valid and is no longer" apart from "this token was never
valid", and act accordingly.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class RefreshToken(UUIDMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # All rotations of one login share the same family_id. Not a FK to
    # anything — it's a group label, generated at login time.
    family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        Index("idx_refresh_tokens_user", "user_id"),
        Index("idx_refresh_tokens_family", "family_id"),
    )
