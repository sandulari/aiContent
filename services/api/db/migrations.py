"""Idempotent schema migrations applied on every API boot.

init.sql runs once on Postgres first init. Anything added after that
must live here so existing databases stay in sync.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


MIGRATION_STATEMENTS: list[str] = [
    # user_pages: page_type column distinguishes own vs reference pages
    """
    ALTER TABLE user_pages
    ADD COLUMN IF NOT EXISTS page_type VARCHAR(20) NOT NULL DEFAULT 'own'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_pages_type
    ON user_pages(user_id, page_type)
    """,
    # page_snapshots: weekly stats for the user's own pages
    """
    CREATE TABLE IF NOT EXISTS page_snapshots (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_page_id        UUID NOT NULL REFERENCES user_pages(id) ON DELETE CASCADE,
        taken_at            TIMESTAMP NOT NULL DEFAULT NOW(),
        week_key            VARCHAR(10) NOT NULL,
        follower_count      BIGINT,
        following_count     BIGINT,
        total_posts         INTEGER,
        total_views_week    BIGINT,
        total_likes_week    BIGINT,
        total_comments_week BIGINT,
        top_reel_ig_id      VARCHAR(100),
        top_reel_url        TEXT,
        top_reel_views      BIGINT,
        top_reel_likes      BIGINT,
        top_reel_caption    TEXT,
        raw_payload         JSONB DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_snapshots_page_time
    ON page_snapshots(user_page_id, taken_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_snapshots_week
    ON page_snapshots(user_page_id, week_key)
    """,
    # user_exports: optional per-export logo override so the editor can
    # swap a logo for a single reel without touching the parent template.
    """
    ALTER TABLE user_exports
    ADD COLUMN IF NOT EXISTS logo_override_key TEXT
    """,
    # user_exports: user-editable download filename (without extension).
    # Lets the user set "how-to-scale-a-startup" instead of exporting
    # every reel as "export_<uuid>.mp4".
    """
    ALTER TABLE user_exports
    ADD COLUMN IF NOT EXISTS download_filename VARCHAR(200)
    """,
    # users: password reset token + expiry for the forgot-password flow
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(64)
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ
    """,
    # users: role column for RBAC
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'
    """,
    # users: refresh token (hashed) + expiry for httpOnly cookie auth
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS refresh_token VARCHAR(64)
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS refresh_token_expires TIMESTAMPTZ
    """,
]


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for stmt in MIGRATION_STATEMENTS:
            try:
                await conn.execute(text(stmt))
            except Exception as exc:
                logger.warning("Migration skipped (%s): %s", stmt.split()[0:3], exc)
    logger.info("Migrations applied")
