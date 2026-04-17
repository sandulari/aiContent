"""Discovery helper — stats for a niche, backed by the real schema.

The worker does the heavy lifting (tasks/discovery.py). This module only
provides read helpers used by the API layer.
"""
from datetime import datetime, timedelta
from typing import Dict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.discovery_run import DiscoveryRun
from models.niche_hashtag import NicheHashtag
from models.theme_page import ThemePage
from models.viral_reel import ViralReel


async def get_niche_discovery_stats(niche_id: UUID, db: AsyncSession) -> Dict:
    confirmed = (await db.execute(
        select(func.count()).select_from(ThemePage).where(
            ThemePage.niche_id == niche_id,
            ThemePage.evaluation_status == "confirmed",
            ThemePage.is_active.is_(True),
        )
    )).scalar() or 0

    pending = (await db.execute(
        select(func.count()).select_from(ThemePage).where(
            ThemePage.niche_id == niche_id,
            ThemePage.evaluation_status.in_(["pending", "needs_review"]),
        )
    )).scalar() or 0

    recent_runs = (await db.execute(
        select(func.count()).select_from(DiscoveryRun).where(
            DiscoveryRun.niche_id == niche_id,
            DiscoveryRun.started_at >= datetime.utcnow() - timedelta(days=7),
        )
    )).scalar() or 0

    hashtag_count = (await db.execute(
        select(func.count()).select_from(NicheHashtag).where(
            NicheHashtag.niche_id == niche_id,
            NicheHashtag.is_active == True,  # noqa: E712
        )
    )).scalar() or 0

    viral_500k = (await db.execute(
        select(func.count()).select_from(ViralReel).where(
            ViralReel.niche_id == niche_id,
            ViralReel.view_count >= 500_000,
        )
    )).scalar() or 0

    return {
        "confirmed_pages": confirmed,
        "pending_candidates": pending,
        "recent_runs_7d": recent_runs,
        "active_hashtags": hashtag_count,
        "viral_reels_500k_plus": viral_500k,
    }
