"""Claude API client for semantic page analysis and reel ranking.

The worker is sync, so this uses `httpx.Client`. All calls degrade
gracefully to None when the API key is missing, the request fails, or
the model returns unparseable JSON — callers must fall back to the
legacy keyword-based logic when that happens.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL_ANALYSIS", "claude-sonnet-4-20250514")
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

_HEADERS = {
    "x-api-key": CLAUDE_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


def is_enabled() -> bool:
    return bool(CLAUDE_API_KEY) and CLAUDE_API_KEY.startswith("sk-")


def _extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of an LLM response.

    Handles the model wrapping JSON in ```json ... ``` fences despite
    the system prompt telling it not to.
    """
    if not text:
        return None
    cleaned = text.strip()
    # Strip code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back: find the first balanced { ... } or [ ... ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == opener:
                depth += 1
            elif cleaned[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def _call_claude(
    system: str,
    user_prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.3,
    timeout: float = 45.0,
) -> Optional[str]:
    """Raw API call with retry-on-429 and structured error logging."""
    if not is_enabled():
        return None

    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    for attempt in range(3):
        try:
            with httpx.Client(timeout=timeout, headers=_HEADERS) as client:
                response = client.post(CLAUDE_URL, json=body)

            if response.status_code == 429:
                wait = 2 * (attempt + 1)
                logger.warning("Claude 429, backing off %ds", wait)
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()
            content = data.get("content") or []
            if not content:
                return None
            return content[0].get("text", "")
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Claude API error %d: %s",
                e.response.status_code,
                e.response.text[:200] if e.response is not None else "",
            )
            return None
        except Exception as e:
            logger.warning("Claude API call failed (attempt %d): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            return None
    return None


# ══════════════════════════════════════════════════════════════════════
# 1. Page analysis
# ══════════════════════════════════════════════════════════════════════

_PAGE_ANALYSIS_SYSTEM = (
    "You are a social media content analyst. You deeply understand "
    "Instagram creator niches, content formats, and audience targeting. "
    "You always return valid JSON and nothing else — no prose, no code fences."
)


def analyze_page(
    username: str,
    display_name: str,
    bio: str,
    recent_reels: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Ask Claude to analyze an Instagram page and return a structured profile.

    `recent_reels` is a list of dicts with at least `caption` and `view_count`.
    Returns a dict with niche_primary/secondary/topics/content_style/
    target_audience/keyword_signature, or None on any failure.
    """
    if not is_enabled():
        return None
    if not username:
        return None

    # Skip the call entirely if we have almost no text to work with —
    # avoids burning the API on empty captions and the model hallucinating.
    total_caption_chars = sum(len((r.get("caption") or "")) for r in recent_reels[:15])
    if total_caption_chars < 80 and len(bio or "") < 20:
        logger.info("Skipping Claude page analysis — too little text for @%s", username)
        return None

    reels_text = ""
    for i, item in enumerate(recent_reels[:15], 1):
        caption = (item.get("caption") or "")[:220].replace("\n", " ")
        views = int(item.get("view_count") or 0)
        reels_text += f"{i}. ({views:,} views) {caption}\n"

    user_prompt = f"""Analyze this Instagram page. The creator wants to know
what kind of content to make that will resonate with their audience.

Username: @{username}
Display name: {display_name or username}
Bio: {bio or "(empty)"}

Recent reels (most recent first):
{reels_text}

Respond with exactly this JSON shape and nothing else:
{{
  "niche_primary": "one of: business, tech, money, finance, fitness, beauty, fashion, food, travel, motivation, comedy, luxury, lifestyle, education",
  "niche_secondary": "optional secondary niche or null",
  "topics": ["specific topic 1", "specific topic 2", ...],
  "content_style": {{
    "format": "educational | entertainment | inspirational | tutorial | vlog | storytelling",
    "tone": "motivational | analytical | humorous | aspirational | casual | authoritative",
    "visual_style": "talking-head | b-roll | text-overlay | vlog | animations | transitions"
  }},
  "target_audience": "one-sentence description of the target viewer",
  "keyword_signature": ["keyword1", "keyword2", ...]
}}

Rules:
- `topics` must be 6-10 specific topics (e.g. "startup fundraising", "protein recipes" — NOT generic words like "business" or "food")
- `keyword_signature` must be 15-25 distinctive single words that appear frequently when matching content
- No markdown, no code fences, no explanation. JSON only."""

    raw = _call_claude(
        system=_PAGE_ANALYSIS_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=1000,
        temperature=0.2,
    )
    if not raw:
        return None
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("Claude page analysis returned non-dict: %s", str(raw)[:200])
        return None
    # Minimal shape validation so downstream code never crashes on garbage.
    parsed.setdefault("niche_primary", "lifestyle")
    parsed.setdefault("topics", [])
    parsed.setdefault("keyword_signature", [])
    parsed.setdefault("content_style", {})
    parsed.setdefault("target_audience", "")
    if not isinstance(parsed.get("topics"), list):
        parsed["topics"] = []
    if not isinstance(parsed.get("keyword_signature"), list):
        parsed["keyword_signature"] = []
    return parsed


# ══════════════════════════════════════════════════════════════════════
# 2. Multi-page reference synthesis
# ══════════════════════════════════════════════════════════════════════

def synthesize_multi_page(
    pages: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Combine N per-page analyses into one unified target profile.

    `pages` is a list of dicts with {"username", "niche_primary", "topics",
    "keyword_signature"} produced by analyze_page.
    """
    if not is_enabled() or not pages:
        return None
    if len(pages) == 1:
        # Nothing to synthesize — just project the single page's profile
        # into the synthesis shape the ranker expects.
        p = pages[0]
        return {
            "combined_niche": p.get("niche_primary"),
            "primary_themes": p.get("topics", [])[:8],
            "keyword_signature": p.get("keyword_signature", [])[:25],
            "target_audience": p.get("target_audience", ""),
        }

    pages_text = ""
    for p in pages:
        pages_text += (
            f"- @{p.get('username', '?')} "
            f"[niche={p.get('niche_primary', 'unknown')}] "
            f"topics={', '.join(p.get('topics', [])[:6])}; "
            f"keywords={', '.join(p.get('keyword_signature', [])[:10])}\n"
        )

    user_prompt = f"""A creator admires {len(pages)} reference Instagram pages.
Synthesize a unified content profile that captures what these pages have in common.

Reference pages:
{pages_text}

Respond with exactly this JSON:
{{
  "combined_niche": "primary niche shared across these pages",
  "primary_themes": ["up to 8 specific themes"],
  "keyword_signature": ["up to 30 keywords that describe the shared content"],
  "target_audience": "one sentence"
}}

No markdown, no commentary. JSON only."""

    raw = _call_claude(
        system="You synthesize multiple social-media profiles into a unified content target. Return JSON only.",
        user_prompt=user_prompt,
        max_tokens=800,
        temperature=0.2,
    )
    if not raw:
        return None
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    return parsed


# ══════════════════════════════════════════════════════════════════════
# 3. Batch reel ranking
# ══════════════════════════════════════════════════════════════════════

_RANKING_SYSTEM = (
    "You are a viral content strategist. Given a target creator profile "
    "and a list of candidate reels, you rank them by relevance to the "
    "creator's niche, topics, and audience. You return valid JSON only."
)


def rank_reels(
    target_profile: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    batch_size: int = 40,
) -> Dict[str, Dict[str, Any]]:
    """Batch-score candidate reels by relevance to the target profile.

    Returns a dict mapping candidate_id -> {"score": float, "reason": str}.
    Failed calls yield an empty dict so the caller can fall back to its
    keyword-based ranking.
    """
    if not is_enabled() or not candidates:
        return {}

    niche = target_profile.get("niche_primary") or target_profile.get("combined_niche", "")
    topics = target_profile.get("topics") or target_profile.get("primary_themes", [])
    signature = target_profile.get("keyword_signature", [])
    audience = target_profile.get("target_audience", "")

    results: Dict[str, Dict[str, Any]] = {}

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        if not batch:
            break
        batch_text = ""
        for c in batch:
            cap = (c.get("caption") or "")[:160].replace("\n", " ")
            batch_text += f'id="{c["id"]}" caption="{cap}"\n'

        user_prompt = f"""Target creator profile:
- Niche: {niche}
- Topics: {', '.join(topics[:10])}
- Signature keywords: {', '.join(signature[:20])}
- Target audience: {audience}

Rank these {len(batch)} candidate reels by relevance to the target
creator (0.0 = irrelevant, 1.0 = perfect match). Consider topical
alignment, tone fit, and whether the creator's audience would engage.

Candidates:
{batch_text}

Respond with a JSON array. Include every candidate id exactly once:
[
  {{"id": "...", "score": 0.92, "reason": "short reason"}},
  ...
]

JSON only."""

        raw = _call_claude(
            system=_RANKING_SYSTEM,
            user_prompt=user_prompt,
            max_tokens=3000,
            temperature=0.1,
        )
        if not raw:
            continue
        parsed = _extract_json(raw)
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            if not isinstance(item, dict):
                continue
            cid = item.get("id") or item.get("candidate_id")
            if not cid:
                continue
            try:
                score = float(item.get("score") or item.get("relevance_score") or 0)
            except Exception:
                score = 0.0
            results[str(cid)] = {
                "score": max(0.0, min(1.0, score)),
                "reason": (item.get("reason") or "")[:180],
            }

    return results
