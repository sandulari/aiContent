"""Idempotent master template seed.

Runs on every API boot (after migrations). Inserts the two default
master templates (AiModernTimes + TechKnowledgebase) if they don't
already exist. Master templates are owned by no user (user_id NULL)
and visible to every user via the templates list endpoint.

Layer positions are percentages of the 1080×1920 export canvas. The
schema for each layer is documented in services/worker/lib/video_proc.py
("Each layer dict" comment block).
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


_AI_MODERN_TIMES_LAYERS = [
    # 1. News-broadcaster style "AI NEWS" badge at the very top — the
    # cyan colour + heavy letter-spacing reads like a CNN-style banner.
    {
        "id": "badge",
        "role": "custom",
        "text": "AI NEWS",
        "x": 50, "y": 4,
        "width": 60,
        "fontFamily": "Inter",
        "fontSize": 18,
        "fontWeight": 800,
        "color": "#22D3EE",
        "alignment": "center",
        "letterSpacing": 6,
        "textTransform": "uppercase",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 5,
        "shadowX": 0,
        "shadowY": 2,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
    },
    # 2. Handle directly below the badge — small, restrained.
    {
        "id": "handle",
        "role": "handle",
        "text": "@aimoderntimes",
        "x": 50, "y": 8,
        "width": 80,
        "fontFamily": "Inter",
        "fontSize": 18,
        "fontWeight": 500,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 0,
        "textTransform": "none",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 6,
        "shadowX": 0,
        "shadowY": 2,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 90,
        "anchor": "center",
    },
    # 3. Big bold headline anchored to the lower third — black weight +
    # heavy stroke gives it that tabloid/Twitter-screenshot feel that
    # reads at any thumbnail size.
    {
        "id": "headline",
        "role": "headline",
        "text": "FUTURE IS NOW",
        "x": 50, "y": 76,
        "width": 95,
        "fontFamily": "Inter",
        "fontSize": 50,
        "fontWeight": 900,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 1,
        "textTransform": "uppercase",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 12,
        "shadowX": 0,
        "shadowY": 4,
        "strokeEnabled": True,
        "strokeColor": "#000000",
        "strokeWidth": 5,
        "opacity": 100,
        "anchor": "center",
    },
    # 4. Subtitle — small, light, anchored at the very bottom edge.
    {
        "id": "subtitle",
        "role": "subtitle",
        "text": "AI is rewriting every industry",
        "x": 50, "y": 93,
        "width": 92,
        "fontFamily": "Inter",
        "fontSize": 20,
        "fontWeight": 400,
        "color": "#C9D1D9",
        "alignment": "center",
        "letterSpacing": 0,
        "textTransform": "none",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 5,
        "shadowX": 0,
        "shadowY": 1,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
    },
]


_TECH_KNOWLEDGEBASE_LAYERS = [
    # 1. Handle in mint green at the top — sets the brand colour and
    # immediately tells viewers which page it's from.
    {
        "id": "handle",
        "role": "handle",
        "text": "@techknowledgebase",
        "x": 50, "y": 4,
        "width": 80,
        "fontFamily": "Inter",
        "fontSize": 20,
        "fontWeight": 600,
        "color": "#34D399",
        "alignment": "center",
        "letterSpacing": 1,
        "textTransform": "lowercase",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 5,
        "shadowX": 0,
        "shadowY": 1,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
    },
    # 2. The headline question — bold and uppercase but tuned to fit on
    # a single line at 92% canvas width. fontSize/letterSpacing must
    # multiply to <= the available width, so we keep letterSpacing
    # restrained.
    {
        "id": "headline",
        "role": "headline",
        "text": "DID YOU KNOW?",
        "x": 50, "y": 13,
        "width": 95,
        "fontFamily": "Inter",
        "fontSize": 38,
        "fontWeight": 800,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 2,
        "textTransform": "uppercase",
        "shadowEnabled": True,
        "shadowColor": "#0F2F23",
        "shadowBlur": 10,
        "shadowX": 0,
        "shadowY": 3,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
    },
    # 3. Subtitle at the bottom — uses the renderer's `highlights`
    # feature to put a green pill behind the word "actually". Shorter
    # phrasing keeps the highlighted word + its neighbours on one line
    # so the pill doesn't kiss the canvas edge.
    {
        "id": "subtitle",
        "role": "subtitle",
        "text": "Tech tips that actually matter",
        "x": 50, "y": 92,
        "width": 90,
        "fontFamily": "Inter",
        "fontSize": 22,
        "fontWeight": 600,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 0,
        "textTransform": "none",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 5,
        "shadowX": 0,
        "shadowY": 1,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
        "highlights": [
            {
                "match": "actually",
                "bgColor": "#34D399",
                "textColor": "#0F172A",
                "borderRadius": 6,
                "paddingX": 6,
            }
        ],
    },
]


_VIRAL_HOOK_LAYERS = [
    # 1. Handle small at the very top — restrained, lets the hook shine.
    {
        "id": "handle",
        "role": "handle",
        "text": "@viralhook",
        "x": 50, "y": 4,
        "width": 80,
        "fontFamily": "Inter",
        "fontSize": 18,
        "fontWeight": 500,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 1,
        "textTransform": "lowercase",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 5,
        "shadowX": 0,
        "shadowY": 1,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 90,
        "anchor": "center",
    },
    # 2. The hook — yellow-highlight tabloid format. The `highlights`
    # entry matches the entire headline so the renderer wraps every
    # line in a yellow pill (per-line segmentation handles wrapping).
    # Black bold text on yellow = highest contrast we can ship; reads
    # at thumbnail size and stops the scroll.
    {
        "id": "hook",
        "role": "headline",
        "text": "WAIT FOR IT",
        "x": 50, "y": 22,
        "width": 96,
        "fontFamily": "Inter",
        "fontSize": 42,
        "fontWeight": 900,
        "color": "#0A0A0A",
        "alignment": "center",
        "letterSpacing": 1,
        "textTransform": "uppercase",
        "shadowEnabled": False,
        "shadowColor": "#000000",
        "shadowBlur": 0,
        "shadowX": 0,
        "shadowY": 0,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
        # Single full-phrase match — yields one continuous yellow pill
        # behind the headline. Font/width are tuned (42pt + 96% width)
        # so the default phrase fits on one line; if a user types longer
        # text, the match still fires per-line wherever the full phrase
        # lands. Per-word matches were considered but rejected — short
        # tokens like "IT" / "FOR" would match aggressively inside any
        # user-edited content.
        "highlights": [
            {
                "match": "WAIT FOR IT",
                "bgColor": "#FBBF24",
                "textColor": "#0A0A0A",
                "borderRadius": 4,
                "paddingX": 14,
            }
        ],
    },
    # 3. Subtitle/payoff at the bottom — primes the user for the reveal.
    {
        "id": "subtitle",
        "role": "subtitle",
        "text": "You won't believe what happens next",
        "x": 50, "y": 92,
        "width": 90,
        "fontFamily": "Inter",
        "fontSize": 22,
        "fontWeight": 600,
        "color": "#FFFFFF",
        "alignment": "center",
        "letterSpacing": 0,
        "textTransform": "none",
        "shadowEnabled": True,
        "shadowColor": "#000000",
        "shadowBlur": 6,
        "shadowX": 0,
        "shadowY": 2,
        "strokeEnabled": False,
        "strokeColor": "#000000",
        "strokeWidth": 0,
        "opacity": 100,
        "anchor": "center",
    },
]


_LOGO_POSITION_DEFAULT = {
    "x": 0.5, "y": 0.08, "size": 0.7, "opacity": 100,
    "border_width": 0, "border_color": "#484f58",
}


_MASTER_TEMPLATES = [
    {
        "name": "AiModernTimes",
        "background_color": "#000000",
        "text_layers": _AI_MODERN_TIMES_LAYERS,
    },
    {
        "name": "ViralHook",
        "background_color": "#000000",
        "text_layers": _VIRAL_HOOK_LAYERS,
    },
    {
        "name": "TechKnowledgebase",
        "background_color": "#000000",
        "text_layers": _TECH_KNOWLEDGEBASE_LAYERS,
    },
]


async def seed_master_templates(engine: AsyncEngine) -> None:
    """Insert master templates if missing. Match by template_name +
    is_master so a re-run never duplicates, but if an admin renames a
    seeded template in the DB it will get re-created (acceptable —
    masters are app-provided defaults, not user data)."""
    import json
    async with engine.begin() as conn:
        for tpl in _MASTER_TEMPLATES:
            existing = await conn.execute(
                text(
                    "SELECT id FROM user_templates "
                    "WHERE is_master = TRUE AND template_name = :name "
                    "LIMIT 1"
                ),
                {"name": tpl["name"]},
            )
            if existing.first():
                continue
            await conn.execute(
                text(
                    """
                    INSERT INTO user_templates
                        (user_id, template_name, logo_position,
                         text_layers, background_color,
                         is_default, is_master, lock_layout)
                    VALUES
                        (NULL, :name, CAST(:logo_pos AS jsonb),
                         CAST(:layers AS jsonb), :bg,
                         FALSE, TRUE, TRUE)
                    """
                ),
                {
                    "name": tpl["name"],
                    "logo_pos": json.dumps(_LOGO_POSITION_DEFAULT),
                    "layers": json.dumps(tpl["text_layers"]),
                    "bg": tpl["background_color"],
                },
            )
            logger.info("Seeded master template: %s", tpl["name"])
