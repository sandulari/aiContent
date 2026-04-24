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
    # user_page_reels: cached reel data for date-range dashboard queries
    """
    CREATE TABLE IF NOT EXISTS user_page_reels (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_page_id UUID NOT NULL REFERENCES user_pages(id) ON DELETE CASCADE,
        ig_code VARCHAR(50) NOT NULL,
        posted_at TIMESTAMPTZ,
        view_count BIGINT DEFAULT 0,
        like_count BIGINT DEFAULT 0,
        comment_count BIGINT DEFAULT 0,
        caption TEXT,
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(user_page_id, ig_code)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_page_reels_page_posted
    ON user_page_reels(user_page_id, posted_at DESC)
    """,
    # reel_profiles: per-reel content profiling for Shadow Pages
    """
    CREATE TABLE IF NOT EXISTS reel_profiles (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        viral_reel_id UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
        topic VARCHAR(200),
        format VARCHAR(100),
        hook_pattern VARCHAR(200),
        visual_style VARCHAR(100),
        audio_type VARCHAR(100),
        content_summary TEXT,
        niche_tags TEXT[],
        confidence FLOAT DEFAULT 0,
        analyzed_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(viral_reel_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reel_profiles_reel ON reel_profiles(viral_reel_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reel_profiles_topic ON reel_profiles(topic)
    """,
    # user_pages: niche_tags array for onboarding niche selection
    """
    ALTER TABLE user_pages
    ADD COLUMN IF NOT EXISTS niche_tags TEXT[]
    """,
    # user_templates: multi-layer text support. `text_layers` is an
    # ordered array of text-layer dicts (see video_proc.py for the
    # schema). Legacy `headline_defaults`/`subtitle_defaults` are kept
    # for backwards compatibility.
    """
    ALTER TABLE user_templates
    ADD COLUMN IF NOT EXISTS text_layers JSONB NOT NULL DEFAULT '[]'::jsonb
    """,
    # user_exports: per-export override for the multi-layer text list.
    # NULL means "use the template's text_layers".
    """
    ALTER TABLE user_exports
    ADD COLUMN IF NOT EXISTS text_layers_overrides JSONB
    """,
    # NOTE: intentionally no back-fill of text_layers for pre-existing
    # templates. The legacy headline_defaults/subtitle_defaults carry
    # *style* only — the actual text lives on UserExport.headline_text /
    # subtitle_text. Back-filling would produce 2 empty-text layers and
    # the renderer (which prefers template.text_layers over the legacy
    # path) would then draw nothing for existing exports. Leaving
    # text_layers = '[]' on old templates keeps them on the legacy
    # render path; new templates (seeded or user-created going forward)
    # populate text_layers directly.
    #
    # -----------------------------------------------------------------
    # Perf indexes (from PERF.md April 2026 audit)
    # -----------------------------------------------------------------
    # viral_reels full-text search on caption — similar-reels endpoint
    # in routers/reels.py does to_tsvector(caption) @@ to_tsquery(...)
    # on every reel detail page. Without this it's a seq scan.
    """
    CREATE INDEX IF NOT EXISTS idx_viral_reels_caption_fts
    ON viral_reels USING GIN (to_tsvector('english', COALESCE(caption, '')))
    """,
    # Recommendation feed hot path: WHERE user_page_id = ? AND is_dismissed = FALSE
    # ORDER BY match_score DESC. Existing single-column indexes don't cover it.
    """
    CREATE INDEX IF NOT EXISTS idx_recs_page_active_score
    ON user_reel_recommendations(user_page_id, is_dismissed, match_score DESC)
    """,
    # Jobs endpoint: used by the polling UI every few seconds.
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_ref
    ON jobs(reference_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_created_desc
    ON jobs(created_at DESC)
    """,
    # -----------------------------------------------------------------
    # Instagram API with Instagram Login (OAuth)
    # -----------------------------------------------------------------
    # Additive columns on users — the existing ig_username +
    # ig_session_data are kept for the RapidAPI scraper path.
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_user_id VARCHAR(64)
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_account_type VARCHAR(32)
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_access_token TEXT
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_token_expires_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_token_scope TEXT
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_profile_picture_url TEXT
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ig_connected_at TIMESTAMPTZ
    """,
    # -----------------------------------------------------------------
    # scheduled_reels — cron-dispatched IG publishes.
    # ON DELETE RESTRICT on user_export_id so we never orphan a queued
    # publish by deleting the source export.
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS scheduled_reels (
        id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        user_export_id         UUID NOT NULL REFERENCES user_exports(id) ON DELETE RESTRICT,
        caption                TEXT,
        user_tags              JSONB,
        scheduled_at           TIMESTAMPTZ NOT NULL,
        timezone               VARCHAR(64) NOT NULL DEFAULT 'UTC',
        status                 VARCHAR(20) NOT NULL DEFAULT 'queued',
        share_to_feed          BOOLEAN NOT NULL DEFAULT TRUE,
        attempt_count          INTEGER NOT NULL DEFAULT 0,
        last_error             TEXT,
        ig_container_id        VARCHAR(64),
        ig_media_id            VARCHAR(64),
        published_at           TIMESTAMPTZ,
        celery_task_id         VARCHAR(64),
        processing_started_at  TIMESTAMPTZ,
        created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scheduled_reels_status_time
    ON scheduled_reels(status, scheduled_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scheduled_reels_user_time
    ON scheduled_reels(user_id, scheduled_at)
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
