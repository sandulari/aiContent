"""Per-user discovery filter config — one row per user, lazily created.

Controls which reels surface in the per-reference-page discovery feed.
Schema-level CHECK constraints are the authoritative validation; the
Pydantic schema in ``routers/discovery_filters.py`` mirrors them with
friendlier error messages on the way in.
"""
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    pass


# Names exported for the router to reuse as the source of truth.
SORT_BY_OPTIONS = (
    "views_desc",
    "posted_at_desc",
    "engagement_desc",
    "likes_desc",
    "comments_desc",
)

DEFAULT_MIN_VIEWS = 1000
DEFAULT_MIN_LIKES = 10
DEFAULT_MIN_COMMENTS = 0
DEFAULT_MIN_ENGAGEMENT_RATE = 0.0
DEFAULT_MAX_AGE_DAYS = 60
DEFAULT_SORT_BY = "views_desc"

MAX_AGE_DAYS_CEILING = 365


class DiscoveryFilter(UUIDMixin, Base):
    __tablename__ = "discovery_filters"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    min_views: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=DEFAULT_MIN_VIEWS,
        server_default=str(DEFAULT_MIN_VIEWS),
    )
    min_likes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=DEFAULT_MIN_LIKES,
        server_default=str(DEFAULT_MIN_LIKES),
    )
    min_comments: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=DEFAULT_MIN_COMMENTS,
        server_default=str(DEFAULT_MIN_COMMENTS),
    )
    min_engagement_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=DEFAULT_MIN_ENGAGEMENT_RATE,
        server_default=str(DEFAULT_MIN_ENGAGEMENT_RATE),
    )
    max_age_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_AGE_DAYS,
        server_default=str(DEFAULT_MAX_AGE_DAYS),
    )
    sort_by: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DEFAULT_SORT_BY,
        server_default=DEFAULT_SORT_BY,
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_discovery_filters_user"),
        CheckConstraint("min_views >= 0", name="ck_discovery_filters_min_views"),
        CheckConstraint("min_likes >= 0", name="ck_discovery_filters_min_likes"),
        CheckConstraint("min_comments >= 0", name="ck_discovery_filters_min_comments"),
        CheckConstraint(
            "min_engagement_rate >= 0 AND min_engagement_rate <= 1",
            name="ck_discovery_filters_engagement_rate",
        ),
        CheckConstraint(
            f"max_age_days >= 1 AND max_age_days <= {MAX_AGE_DAYS_CEILING}",
            name="ck_discovery_filters_max_age_days",
        ),
        CheckConstraint(
            "sort_by IN ('views_desc','posted_at_desc','engagement_desc','likes_desc','comments_desc')",
            name="ck_discovery_filters_sort_by",
        ),
    )
