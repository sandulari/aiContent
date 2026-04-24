"""Seed the AiModernTimes-style default template for a newly-registered user.

Every new user gets a ready-to-edit template so the editor is not empty
on first visit. Idempotent: skips users who already have any template.
"""

import json
import logging
import uuid

from sqlalchemy import text

from celery_app import app
from lib.db import get_session

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "AiModernTimes"


def _default_text_layers() -> list[dict]:
    """AiModernTimes layout. Positions are percentages of the 1080x1920 canvas."""
    return [
        {
            "id": str(uuid.uuid4()),
            "role": "account_name",
            "text": "Your Name",
            "x": 23, "y": 6,
            "fontFamily": "Inter",
            "fontSize": 38,
            "fontWeight": 700,
            "color": "#FFFFFF",
            "alignment": "left",
            "letterSpacing": 0,
            "textTransform": "none",
            "shadowEnabled": False,
            "shadowColor": "#000000",
            "shadowBlur": 0,
            "shadowX": 0,
            "shadowY": 0,
            "strokeEnabled": False,
            "strokeColor": "#000000",
            "strokeWidth": 0,
            "opacity": 100,
            "anchor": "top-left",
        },
        {
            "id": str(uuid.uuid4()),
            "role": "handle",
            "text": "@yourhandle",
            "x": 23, "y": 10,
            "fontFamily": "Inter",
            "fontSize": 30,
            "fontWeight": 400,
            "color": "#9CA3AF",
            "alignment": "left",
            "letterSpacing": 0,
            "textTransform": "none",
            "shadowEnabled": False,
            "shadowColor": "#000000",
            "shadowBlur": 0,
            "shadowX": 0,
            "shadowY": 0,
            "strokeEnabled": False,
            "strokeColor": "#000000",
            "strokeWidth": 0,
            "opacity": 100,
            "anchor": "top-left",
        },
        {
            "id": str(uuid.uuid4()),
            "role": "headline",
            "text": "Your headline goes here",
            "x": 4, "y": 15,
            "width": 92,
            "fontFamily": "Inter",
            "fontSize": 62,
            "fontWeight": 800,
            "color": "#FFFFFF",
            "alignment": "left",
            "letterSpacing": 0,
            "textTransform": "none",
            "shadowEnabled": True,
            "shadowColor": "#000000",
            "shadowBlur": 4,
            "shadowX": 0,
            "shadowY": 2,
            "strokeEnabled": False,
            "strokeColor": "#000000",
            "strokeWidth": 0,
            "opacity": 100,
            "anchor": "top-left",
        },
    ]


def _default_logo_position() -> dict:
    """Circular avatar in the top-left of the header block."""
    return {
        "x": 12,
        "y": 7,
        "size": 10,
        "shape": "circle",
        "opacity": 100,
        "borderWidth": 0,
        "borderColor": "#FFFFFF",
    }


@app.task(name="tasks.seed_default_template.seed_for_user", bind=True, max_retries=2)
def seed_for_user(self, user_id: str):
    """Insert the AiModernTimes default template for one user."""
    try:
        with get_session() as session:
            existing = session.execute(
                text("SELECT 1 FROM user_templates WHERE user_id = :uid LIMIT 1"),
                {"uid": user_id},
            ).fetchone()
            if existing:
                logger.info("seed_default_template: user %s already has templates, skipping", user_id)
                return {"skipped": True, "user_id": user_id}

            session.execute(
                text(
                    """
                    INSERT INTO user_templates (
                        id, user_id, template_name, logo_position,
                        headline_defaults, subtitle_defaults, text_layers,
                        background_color, is_default, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :user_id, :name,
                        CAST(:logo_position AS jsonb),
                        CAST(:headline_defaults AS jsonb),
                        CAST(:subtitle_defaults AS jsonb),
                        CAST(:text_layers AS jsonb),
                        :bg, true, NOW(), NOW()
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "name": TEMPLATE_NAME,
                    "logo_position": json.dumps(_default_logo_position()),
                    "headline_defaults": json.dumps({}),
                    "subtitle_defaults": json.dumps({}),
                    "text_layers": json.dumps(_default_text_layers()),
                    "bg": "#000000",
                },
            )

        logger.info("seed_default_template: seeded AiModernTimes for user %s", user_id)
        return {"seeded": True, "user_id": user_id}

    except Exception as exc:
        logger.error("seed_default_template failed for user %s: %s", user_id, exc, exc_info=True)
        raise self.retry(exc=exc, countdown=60)


@app.task(name="tasks.seed_default_template.backfill_all")
def backfill_all():
    """One-shot: queue a seed for every user who has zero templates."""
    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT u.id::text AS id FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM user_templates t WHERE t.user_id = u.id
                )
                """
            )
        ).fetchall()

    queued = 0
    for row in rows:
        seed_for_user.delay(row.id)
        queued += 1

    logger.info("seed_default_template.backfill_all: queued %d users", queued)
    return {"queued": queued}
