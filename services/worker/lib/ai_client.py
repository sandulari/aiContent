"""
AI text generation client for Celery workers (synchronous).
Supports Anthropic Claude and OpenAI GPT-4.
"""
import json
import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-20250514")


def _build_prompt(niche: str, caption: str, page_name: str, view_count: int, style_hint: str | None = None) -> str:
    view_str = f"{view_count:,}" if view_count else "unknown"
    parts = [
        "You are a viral social media content strategist.",
        f"Niche: {niche}",
        f"Original caption: {caption}" if caption else "",
        f"Source page: {page_name}" if page_name else "",
        f"View count: {view_str}",
    ]
    if style_hint:
        parts.append(f"Style hint: {style_hint}")

    parts.append("""
Generate exactly 3 headline options and 3 subtitle options for an Instagram Reel overlay.

Headlines: Punchy, attention-grabbing, 3-8 words max.
Subtitles: Supporting line, 5-15 words.
Caption: A full Instagram caption (2-3 sentences with hashtags).

Respond in this exact JSON format only:
{
  "headlines": ["headline1", "headline2", "headline3"],
  "subtitles": ["subtitle1", "subtitle2", "subtitle3"],
  "caption_suggestion": "full caption text"
}""")

    return "\n".join(p for p in parts if p)


def generate_text_sync(
    niche: str,
    caption: str,
    page_name: str,
    view_count: int,
    style_hint: str | None = None,
) -> Dict[str, Any]:
    """Synchronous AI text generation for use in Celery tasks."""
    prompt = _build_prompt(niche, caption, page_name, view_count, style_hint)

    try:
        if AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
            return _call_anthropic_sync(prompt)
        elif AI_PROVIDER == "openai" and OPENAI_API_KEY:
            return _call_openai_sync(prompt)
        else:
            return _fallback(niche, caption)
    except Exception as e:
        logger.warning("AI generation failed, using fallback: %s", e)
        return _fallback(niche, caption)


def _call_anthropic_sync(prompt: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        result = json.loads(text)
        result["model_used"] = AI_MODEL
        return result


def _call_openai_sync(prompt: str) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.8,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        result = json.loads(text)
        result["model_used"] = AI_MODEL
        return result


def _fallback(niche: str, caption: str) -> Dict[str, Any]:
    words = caption.split()[:5] if caption else ["This", "Changes", "Everything"]
    headline = " ".join(words).title()
    tag = niche.lower().replace("/", "").replace(" ", "")
    return {
        "headlines": [headline, f"The {niche} Secret", "Watch This Now"],
        "subtitles": [
            f"The {niche.lower()} tip everyone needs",
            "You won't believe what happens next",
            "This is what success looks like",
        ],
        "caption_suggestion": f"{headline}. Double tap if you agree! #{tag} #viral #reels",
        "model_used": "fallback",
    }
