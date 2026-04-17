-- ============================================================
-- Viral Reel Engine v2 — Complete Schema
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users ──────────────────────────────────────────────────
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(320) UNIQUE NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    ig_username     VARCHAR(200),
    ig_auth_method  VARCHAR(30) DEFAULT 'username_only',
    ig_session_data JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── User Pages (Instagram pages the user cares about) ─────
-- page_type = 'own'       → the user's own page, drives weekly dashboard
-- page_type = 'reference' → an inspiration page, drives similar-content recs
CREATE TABLE user_pages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ig_username          VARCHAR(200) NOT NULL,
    ig_display_name      VARCHAR(200),
    ig_profile_pic_url   TEXT,
    page_type            VARCHAR(20) NOT NULL DEFAULT 'own',
    follower_count       BIGINT,
    following_count      BIGINT,
    total_posts          INTEGER,
    avg_views_per_reel   BIGINT,
    avg_engagement_rate  FLOAT,
    is_active            BOOLEAN DEFAULT true,
    last_analyzed_at     TIMESTAMP,
    last_scraped_at      TIMESTAMP,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, ig_username)
);

-- ── Page Snapshots (weekly dashboard data for user's OWN pages) ─
CREATE TABLE page_snapshots (
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
);

-- ── Page Profiles (AI analysis of user's page) ────────────
CREATE TABLE page_profiles (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_page_id            UUID NOT NULL REFERENCES user_pages(id) ON DELETE CASCADE,
    niche_primary           VARCHAR(100),
    niche_secondary         VARCHAR(100),
    top_topics              JSONB DEFAULT '[]',
    top_formats             JSONB DEFAULT '[]',
    content_style           JSONB DEFAULT '{}',
    best_duration_range     JSONB DEFAULT '{}',
    caption_style           JSONB DEFAULT '{}',
    posting_frequency       FLOAT,
    top_performing_reel_ids JSONB DEFAULT '[]',
    analysis_model          VARCHAR(100),
    raw_analysis            JSONB,
    analyzed_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── Niches ─────────────────────────────────────────────────
CREATE TABLE niches (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name      VARCHAR(100) UNIQUE NOT NULL,
    slug      VARCHAR(120) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT true
);

-- ── Niche Hashtags ─────────────────────────────────────────
CREATE TABLE niche_hashtags (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    niche_id            UUID NOT NULL REFERENCES niches(id) ON DELETE CASCADE,
    hashtag             VARCHAR(200) NOT NULL,
    last_used_at        TIMESTAMP,
    candidates_produced INTEGER DEFAULT 0,
    is_active           BOOLEAN DEFAULT true
);

-- ── Theme Pages (discovered external pages) ────────────────
CREATE TABLE theme_pages (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                VARCHAR(200) UNIQUE NOT NULL,
    display_name            VARCHAR(200),
    profile_url             TEXT DEFAULT '',
    niche_id                UUID REFERENCES niches(id) ON DELETE SET NULL,
    follower_count          BIGINT,
    is_active               BOOLEAN DEFAULT true,
    scrape_interval_minutes INTEGER DEFAULT 60,
    min_views_threshold     BIGINT DEFAULT 500000,
    last_scraped_at         TIMESTAMP,
    discovered_via          VARCHAR(30) DEFAULT 'manual_seed',
    discovered_from_page_id UUID REFERENCES theme_pages(id) ON DELETE SET NULL,
    heuristic_score         INTEGER DEFAULT 0,
    viral_hit_rate          FLOAT,
    evaluation_status       VARCHAR(20) DEFAULT 'confirmed',
    created_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── Viral Reels (discovered from theme pages) ──────────────
CREATE TABLE viral_reels (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_page_id    UUID NOT NULL REFERENCES theme_pages(id) ON DELETE CASCADE,
    ig_video_id      VARCHAR(100) UNIQUE NOT NULL,
    ig_url           TEXT NOT NULL,
    thumbnail_url    TEXT,
    view_count       BIGINT DEFAULT 0,
    like_count       BIGINT DEFAULT 0,
    comment_count    BIGINT,
    duration_seconds FLOAT,
    caption          TEXT,
    posted_at        TIMESTAMP NOT NULL,
    scraped_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    niche_id         UUID REFERENCES niches(id) ON DELETE SET NULL,
    status           VARCHAR(30) DEFAULT 'discovered',
    error_message    TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── User Reel Recommendations (AI-matched) ─────────────────
CREATE TABLE user_reel_recommendations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_page_id    UUID NOT NULL REFERENCES user_pages(id) ON DELETE CASCADE,
    viral_reel_id   UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
    match_score     FLOAT NOT NULL,
    match_reason    VARCHAR(500),
    match_factors   JSONB DEFAULT '{}',
    is_dismissed    BOOLEAN DEFAULT false,
    is_used         BOOLEAN DEFAULT false,
    recommended_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_page_id, viral_reel_id)
);

-- ── Video Sources (alternative platform matches) ───────────
CREATE TABLE video_sources (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    viral_reel_id        UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
    source_type          VARCHAR(30) NOT NULL,
    source_url           TEXT NOT NULL,
    source_title         VARCHAR(500),
    source_thumbnail_url TEXT,
    resolution           VARCHAR(20),
    match_confidence     FLOAT,
    is_selected          BOOLEAN DEFAULT false,
    found_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── Video Files ────────────────────────────────────────────
CREATE TABLE video_files (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    viral_reel_id    UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
    user_id          UUID REFERENCES users(id) ON DELETE SET NULL,
    file_type        VARCHAR(30) NOT NULL,
    minio_bucket     VARCHAR(100) NOT NULL,
    minio_key        TEXT NOT NULL,
    file_size_bytes  BIGINT NOT NULL,
    resolution       VARCHAR(20) NOT NULL DEFAULT '',
    duration_seconds FLOAT NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── User Templates ─────────────────────────────────────────
CREATE TABLE user_templates (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_page_id      UUID REFERENCES user_pages(id) ON DELETE SET NULL,
    template_name     VARCHAR(200) NOT NULL,
    logo_minio_key    TEXT,
    logo_position     JSONB DEFAULT '{"x":0.5,"y":0.08,"size":1.0,"opacity":100,"border_width":2,"border_color":"#484f58"}',
    headline_defaults JSONB DEFAULT '{"font_family":"Inter","font_size":48,"font_weight":700,"color":"#FFFFFF","position":{"x":0.5,"y":0.65},"shadow_enabled":true,"shadow_color":"#000000","shadow_blur":6,"shadow_x":0,"shadow_y":2}',
    subtitle_defaults JSONB DEFAULT '{"font_family":"Inter","font_size":22,"font_weight":400,"color":"#C9D1D9","position":{"x":0.5,"y":0.78},"shadow_enabled":true,"shadow_color":"#000000","shadow_blur":4,"shadow_x":0,"shadow_y":1}',
    background_color  VARCHAR(20) DEFAULT '#000000',
    is_default        BOOLEAN DEFAULT false,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── User Exports ───────────────────────────────────────────
CREATE TABLE user_exports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_page_id     UUID REFERENCES user_pages(id) ON DELETE SET NULL,
    viral_reel_id    UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
    template_id      UUID NOT NULL REFERENCES user_templates(id) ON DELETE CASCADE,
    headline_text    TEXT NOT NULL,
    headline_style   JSONB DEFAULT '{}',
    subtitle_text    TEXT NOT NULL,
    subtitle_style   JSONB DEFAULT '{}',
    caption_text     TEXT,
    video_transform  JSONB DEFAULT '{}',
    video_trim       JSONB DEFAULT '{}',
    audio_config     JSONB DEFAULT '{}',
    logo_overrides   JSONB,
    export_minio_key TEXT,
    export_status    VARCHAR(20) DEFAULT 'editing',
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    exported_at      TIMESTAMP
);

-- ── AI Text Generations ────────────────────────────────────
CREATE TABLE ai_text_generations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    viral_reel_id   UUID NOT NULL REFERENCES viral_reels(id) ON DELETE CASCADE,
    user_page_id    UUID NOT NULL REFERENCES user_pages(id) ON DELETE CASCADE,
    headlines       JSONB NOT NULL DEFAULT '[]',
    subtitles       JSONB NOT NULL DEFAULT '[]',
    caption_suggestion TEXT,
    style_hint      VARCHAR(200),
    model_used      VARCHAR(100) NOT NULL,
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ── Discovery Runs ─────────────────────────────────────────
CREATE TABLE discovery_runs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    niche_id             UUID NOT NULL REFERENCES niches(id) ON DELETE CASCADE,
    run_type             VARCHAR(30) NOT NULL,
    started_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at          TIMESTAMP,
    candidates_found     INTEGER DEFAULT 0,
    candidates_confirmed INTEGER DEFAULT 0,
    candidates_rejected  INTEGER DEFAULT 0,
    hashtags_used        JSONB,
    pages_crawled        JSONB
);

-- ── Jobs ───────────────────────────────────────────────────
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    celery_task_id  VARCHAR(255) NOT NULL,
    job_type        VARCHAR(30) NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    reference_id    UUID,
    reference_type  VARCHAR(50),
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    attempts        INTEGER DEFAULT 0,
    logs            JSONB DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_user_pages_user ON user_pages(user_id);
CREATE INDEX idx_user_pages_type ON user_pages(user_id, page_type);
CREATE INDEX idx_page_snapshots_page_time ON page_snapshots(user_page_id, taken_at DESC);
CREATE INDEX idx_page_snapshots_week ON page_snapshots(user_page_id, week_key);
CREATE INDEX idx_page_profiles_page ON page_profiles(user_page_id);
CREATE INDEX idx_theme_pages_niche ON theme_pages(niche_id);
CREATE INDEX idx_theme_pages_status ON theme_pages(evaluation_status);
CREATE INDEX idx_viral_reels_page ON viral_reels(theme_page_id);
CREATE INDEX idx_viral_reels_niche ON viral_reels(niche_id);
CREATE INDEX idx_viral_reels_views ON viral_reels(view_count DESC);
CREATE INDEX idx_viral_reels_ig_id ON viral_reels(ig_video_id);
CREATE INDEX idx_recommendations_page ON user_reel_recommendations(user_page_id);
CREATE INDEX idx_recommendations_score ON user_reel_recommendations(match_score DESC);
CREATE INDEX idx_video_sources_reel ON video_sources(viral_reel_id);
CREATE INDEX idx_video_files_reel ON video_files(viral_reel_id);
CREATE INDEX idx_user_templates_user ON user_templates(user_id);
CREATE INDEX idx_user_exports_user ON user_exports(user_id);
CREATE INDEX idx_jobs_type ON jobs(job_type);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_niche_hashtags_niche ON niche_hashtags(niche_id);

-- ============================================================
-- SEED: Niches
-- ============================================================
INSERT INTO niches (name, slug) VALUES
    ('Business/Entrepreneurship', 'business'),
    ('Fitness/Health', 'fitness'),
    ('Beauty/Skincare', 'beauty'),
    ('Money-Making/Side Hustles', 'money'),
    ('Lifestyle', 'lifestyle'),
    ('Motivation/Mindset', 'motivation'),
    ('Finance/Investing', 'finance'),
    ('Tech/AI', 'tech'),
    ('Fashion', 'fashion'),
    ('Food/Recipes', 'food'),
    ('Travel', 'travel'),
    ('Education/Learning', 'education'),
    ('Luxury/Wealth', 'luxury'),
    ('Relationships/Dating', 'relationships'),
    ('Comedy/Entertainment', 'comedy');

-- ============================================================
-- SEED: Niche Hashtags
-- ============================================================
INSERT INTO niche_hashtags (niche_id, hashtag, candidates_produced, is_active) VALUES
    ((SELECT id FROM niches WHERE slug='business'), 'entrepreneurmindset', 0, true),
    ((SELECT id FROM niches WHERE slug='business'), 'hustleculture', 0, true),
    ((SELECT id FROM niches WHERE slug='business'), 'businesstips', 0, true),
    ((SELECT id FROM niches WHERE slug='business'), 'startuplife', 0, true),
    ((SELECT id FROM niches WHERE slug='fitness'), 'gymtok', 0, true),
    ((SELECT id FROM niches WHERE slug='fitness'), 'fitnessmotivation', 0, true),
    ((SELECT id FROM niches WHERE slug='fitness'), 'workoutreels', 0, true),
    ((SELECT id FROM niches WHERE slug='beauty'), 'skincareroutine', 0, true),
    ((SELECT id FROM niches WHERE slug='beauty'), 'beautyhacks', 0, true),
    ((SELECT id FROM niches WHERE slug='beauty'), 'glowup', 0, true),
    ((SELECT id FROM niches WHERE slug='money'), 'sidehustle', 0, true),
    ((SELECT id FROM niches WHERE slug='money'), 'makemoneyonline', 0, true),
    ((SELECT id FROM niches WHERE slug='money'), 'passiveincome', 0, true),
    ((SELECT id FROM niches WHERE slug='motivation'), 'motivationreels', 0, true),
    ((SELECT id FROM niches WHERE slug='motivation'), 'mindsetshift', 0, true),
    ((SELECT id FROM niches WHERE slug='motivation'), 'successmindset', 0, true),
    ((SELECT id FROM niches WHERE slug='finance'), 'moneytips', 0, true),
    ((SELECT id FROM niches WHERE slug='finance'), 'investing101', 0, true),
    ((SELECT id FROM niches WHERE slug='finance'), 'financialfreedom', 0, true),
    ((SELECT id FROM niches WHERE slug='tech'), 'techtok', 0, true),
    ((SELECT id FROM niches WHERE slug='tech'), 'aifacts', 0, true),
    ((SELECT id FROM niches WHERE slug='fashion'), 'fashionreels', 0, true),
    ((SELECT id FROM niches WHERE slug='fashion'), 'outfitinspo', 0, true),
    ((SELECT id FROM niches WHERE slug='food'), 'foodtok', 0, true),
    ((SELECT id FROM niches WHERE slug='food'), 'easyrecipes', 0, true),
    ((SELECT id FROM niches WHERE slug='travel'), 'travelreels', 0, true),
    ((SELECT id FROM niches WHERE slug='travel'), 'wanderlust', 0, true),
    ((SELECT id FROM niches WHERE slug='luxury'), 'luxurylifestyle', 0, true),
    ((SELECT id FROM niches WHERE slug='luxury'), 'billionairemindset', 0, true),
    ((SELECT id FROM niches WHERE slug='comedy'), 'funnyreels', 0, true),
    ((SELECT id FROM niches WHERE slug='comedy'), 'comedyreels', 0, true);
