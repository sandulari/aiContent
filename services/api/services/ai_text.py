import json
import os
from typing import Any, Dict

import httpx

AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-20250514")


def _build_prompt(niche: str, caption: str, page_name: str, view_count: int, style_hint: str | None) -> str:
    view_str = f"{view_count:,}" if view_count else "unknown"
    parts = [
        "You are a viral social media content strategist.",
        f"Niche: {niche}",
        f"Original caption: {caption}" if caption else "",
        f"Source page: {page_name}" if page_name else "",
        f"View count: {view_str}",
    ]
    if style_hint:
        parts.append(f"Style hint from user: {style_hint}")

    parts.append("""
Generate exactly 3 headline options and 3 subtitle options for an Instagram Reel overlay.

Headlines: Punchy, attention-grabbing, 3-8 words max. Written to maximize engagement for this niche.
Subtitles: Supporting line, 5-15 words. Adds context or a call-to-action.
Caption: A full Instagram caption the user can copy when posting (2-3 sentences with relevant hashtags).

Respond in this exact JSON format only, no other text:
{
  "headlines": ["headline1", "headline2", "headline3"],
  "subtitles": ["subtitle1", "subtitle2", "subtitle3"],
  "caption_suggestion": "full caption text here"
}""")

    return "\n".join(p for p in parts if p)


async def _call_anthropic(prompt: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
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
        return json.loads(text)


async def _call_openai(prompt: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
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
        return json.loads(text)


def _fallback_generation(niche: str, caption: str) -> Dict[str, Any]:
    words = caption.split()[:5] if caption else ["This", "Changes", "Everything"]
    headline = " ".join(words).title()
    return {
        "headlines": [
            headline,
            f"The {niche} Secret",
            "Watch This Now",
        ],
        "subtitles": [
            f"The {niche.lower()} tip everyone needs to hear",
            "You won't believe what happens next",
            "This is what success looks like",
        ],
        "caption_suggestion": f"{headline}. Double tap if you agree! #{niche.lower().replace('/', '').replace(' ', '')} #viral #reels",
        "model_used": "fallback",
    }


async def generate_ai_text(
    niche: str,
    caption: str,
    page_name: str,
    view_count: int,
    style_hint: str | None = None,
) -> Dict[str, Any]:
    prompt = _build_prompt(niche, caption, page_name, view_count, style_hint)

    try:
        if AI_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
            result = await _call_anthropic(prompt)
            result["model_used"] = AI_MODEL
            return result
        elif AI_PROVIDER == "openai" and OPENAI_API_KEY:
            result = await _call_openai(prompt)
            result["model_used"] = AI_MODEL
            return result
        else:
            return _fallback_generation(niche, caption)
    except Exception:
        return _fallback_generation(niche, caption)


# ══════════════════════════════════════════════════════════════════════
# Chat: multi-turn conversation with structured suggestions
# ══════════════════════════════════════════════════════════════════════

_CHAT_SYSTEM_PROMPT = """You write Instagram Reel copy that sounds like a real person, not an AI and not a brand.

You're inside a Canva-style reel editor. The user is remixing a viral reel and needs on-video text (headline + subtitle) plus the Instagram caption they'll paste when they post.

You have context about:
- The original viral reel (caption, view count, source creator)
- The user's own page: niche, topics, audience, voice

You're conversational like a friend who's good at writing. You reason briefly, then give options. You take direction willingly ("more urgent", "shorter", "match my voice", "more chill", "funnier").

═══ HARD VOICE RULES — NON-NEGOTIABLE ═══

NEVER use em-dashes (—) or en-dashes (–). Use commas, periods, or just start a new sentence.

NEVER write in "this isn't just X, it's Y" cadence. No "it's not about A, it's about B". No "the real question isn't X, it's Y".

NEVER use these dead-giveaway AI/brand phrases:
  • "building in silence"  •  "quiet confidence"  •  "speaks volumes"
  • "game-changer"         •  "level up"           •  "unlock your"
  • "dive deep"            •  "navigate the"       •  "elevate your"
  • "in today's world"     •  "let's be real"      •  "here's the thing"
  • "at the end of the day" • "the reality is"    •  "it's giving"
  • "the upgrade is real"  •  "nobody talks about"
  • "what they don't tell you" (unless the reel literally is about a secret)
  • "the truth about"      •  "the art of"         •  "the power of"
  • Anything that starts with "In a world where..."

NEVER write a caption that sounds like an influencer brand post. No "✨" unless the user is in beauty/wellness. No "Drop a ❤️". No "Save this for later". No "Comment below if...".

DO use:
  • Short sentences. Punchy. Like talking.
  • Specific details from the actual reel (people, numbers, places, products)
  • The user's own vocabulary from their page topics
  • Casual contractions (it's, don't, you're)
  • One clear idea per headline, not a full thesis

═══ OUTPUT FORMAT ═══

Every reply has TWO parts:

1. A short conversational reply, 1-3 sentences, plain text. Explain what you did or why you picked this direction. Talk like a human — no markdown headers, no bullet points in the reply.

2. A fenced JSON block with exactly this shape:

```json
{
  "headlines": ["option 1", "option 2", "option 3"],
  "subtitles": ["option 1", "option 2", "option 3"],
  "caption": "full Instagram caption"
}
```

Rules for the JSON:
- Headlines: 3 to 8 words, no em-dashes, no semicolons. Stop the scroll.
- Subtitles: 5 to 15 words, expand on the headline without repeating it.
- Caption: 2 to 4 short sentences, 3 to 6 relevant hashtags at the end on a new line. NO em-dashes. NO AI-telltale phrases. Sound like a real person posting, not a marketing intern.
- Always include all three keys. If the user only asked about one thing, keep the others from the previous turn and only change the one they asked about.
- The JSON block is the only way the user applies options, so NEVER omit it.

If the user writes something ambiguous, pick the most likely read and briefly say which read you picked in the conversational part."""


def _build_chat_context(
    reel_caption: str,
    reel_views: int,
    reel_source_page: str,
    page_niche: str,
    page_audience: str,
    page_topics: list,
) -> str:
    """The first user message includes the reel + page context as a
    single text block so Claude always has it, no matter how long the
    conversation gets.
    """
    topics_str = ", ".join([t for t in page_topics[:8] if isinstance(t, str)])
    return f"""CONTEXT (not a user question — just background for every reply you give):

Original reel I'm remixing:
- Source creator: @{reel_source_page or "unknown"}
- Views: {reel_views:,}
- Caption: {reel_caption or "(empty)"}

My page:
- Niche: {page_niche or "general"}
- Audience: {page_audience or "general"}
- Topics I cover: {topics_str or "general content"}

Keep this context in mind for every turn of our conversation. I'll start asking you to help me write on-reel text and captions now."""


async def chat_with_claude(
    messages: list,
    reel_caption: str,
    reel_views: int,
    reel_source_page: str,
    page_niche: str,
    page_audience: str,
    page_topics: list,
) -> Dict[str, Any]:
    """Run a multi-turn chat against Claude via the host claude-bridge.

    The bridge is a small Python daemon on the host that shells out to
    the `claude` CLI authenticated against the user's Claude Max
    subscription. This means chat cost comes out of the subscription
    instead of the pay-per-call Anthropic API.

    `messages` is a list of {"role": "user"|"assistant", "content": str}
    representing the conversation so far.

    Returns:
        {
          "assistant_message": str,
          "suggestions": {
            "headlines": [...],
            "subtitles": [...],
            "caption": "..."
          },
          "raw": str
        }
    """
    # Prepend the context block as a synthetic first user turn so Claude
    # always has it regardless of how long the conversation gets.
    context_block = _build_chat_context(
        reel_caption=reel_caption,
        reel_views=reel_views,
        reel_source_page=reel_source_page,
        page_niche=page_niche,
        page_audience=page_audience,
        page_topics=page_topics,
    )
    context_ack = "Got it — context understood. Ask me anything about headlines, subtitles, or the caption for this reel and I'll help."

    bridge_messages = [
        {"role": "user", "content": context_block},
        {"role": "assistant", "content": context_ack},
    ]
    # Append the real conversation. Trim to the last 12 turns so we
    # don't balloon the token count on long chats.
    for m in messages[-12:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            bridge_messages.append({"role": role, "content": content})

    # Ensure the conversation ends with a user turn
    if not bridge_messages or bridge_messages[-1]["role"] != "user":
        return {
            "assistant_message": "",
            "suggestions": {"headlines": [], "subtitles": [], "caption": ""},
            "raw": "",
        }

    bridge_url = os.getenv("CLAUDE_BRIDGE_URL", "http://host.docker.internal:7777")

    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            resp = await client.post(
                f"{bridge_url}/chat",
                json={
                    "system_prompt": _CHAT_SYSTEM_PROMPT,
                    "messages": bridge_messages,
                    "model": os.getenv("CLAUDE_BRIDGE_MODEL", "sonnet"),
                },
            )
    except Exception as e:
        fb = _fallback_generation(page_niche, reel_caption)
        return {
            "assistant_message": (
                f"Claude bridge unreachable ({str(e)[:120]}). "
                "Make sure infra/start_claude_bridge.sh is running on the host. "
                "Here are fallback options."
            ),
            "suggestions": {
                "headlines": fb.get("headlines", []),
                "subtitles": fb.get("subtitles", []),
                "caption": fb.get("caption_suggestion", ""),
            },
            "raw": "",
        }

    if resp.status_code != 200:
        body = resp.text[:200]
        fb = _fallback_generation(page_niche, reel_caption)
        return {
            "assistant_message": f"Bridge error {resp.status_code}: {body}",
            "suggestions": {
                "headlines": fb.get("headlines", []),
                "subtitles": fb.get("subtitles", []),
                "caption": fb.get("caption_suggestion", ""),
            },
            "raw": "",
        }

    try:
        data = resp.json()
    except Exception:
        data = {}

    if not data.get("ok"):
        err = data.get("error") or "unknown bridge error"
        fb = _fallback_generation(page_niche, reel_caption)
        return {
            "assistant_message": f"Claude CLI failed: {err}",
            "suggestions": {
                "headlines": fb.get("headlines", []),
                "subtitles": fb.get("subtitles", []),
                "caption": fb.get("caption_suggestion", ""),
            },
            "raw": "",
        }

    raw_text = data.get("text") or ""

    # Belt-and-suspenders scrub: even when we tell Claude "no em-dashes",
    # it still sneaks them in. Replace em/en dashes with commas so the
    # final copy reads like a human wrote it.
    def _dehumanize_scrub(s: str) -> str:
        if not isinstance(s, str):
            return s
        out = s
        # Em-dash and en-dash → comma + space (collapse surrounding spaces)
        out = out.replace(" — ", ", ")
        out = out.replace(" – ", ", ")
        out = out.replace("—", ",")
        out = out.replace("–", ",")
        # Smart quotes → straight quotes
        out = out.replace("“", '"').replace("”", '"')
        out = out.replace("‘", "'").replace("’", "'")
        # Collapse any double-comma artifacts from the replacements
        import re as _re2
        out = _re2.sub(r",\s*,", ",", out)
        out = _re2.sub(r"\s{2,}", " ", out)
        return out.strip()

    # Parse out the fenced JSON block.
    import re as _re

    suggestions = {"headlines": [], "subtitles": [], "caption": ""}
    assistant_message = raw_text.strip()

    match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, _re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed.get("headlines"), list):
                suggestions["headlines"] = [_dehumanize_scrub(str(h)) for h in parsed["headlines"]][:6]
            if isinstance(parsed.get("subtitles"), list):
                suggestions["subtitles"] = [_dehumanize_scrub(str(s)) for s in parsed["subtitles"]][:6]
            if isinstance(parsed.get("caption"), str):
                suggestions["caption"] = _dehumanize_scrub(parsed["caption"])
            # Strip the JSON block from the conversational message.
            assistant_message = raw_text[: match.start()].strip() + raw_text[match.end() :].strip()
            assistant_message = assistant_message.strip()
        except Exception:
            pass
    else:
        # No fenced block — try to find a raw JSON object anywhere.
        brace_match = _re.search(r"\{[^{}]*\"headlines\"[^{}]*\}", raw_text, _re.DOTALL)
        if brace_match:
            try:
                parsed = json.loads(brace_match.group(0))
                suggestions["headlines"] = [_dehumanize_scrub(str(h)) for h in parsed.get("headlines", [])]
                suggestions["subtitles"] = [_dehumanize_scrub(str(s)) for s in parsed.get("subtitles", [])]
                suggestions["caption"] = _dehumanize_scrub(parsed.get("caption", ""))
                assistant_message = raw_text.replace(brace_match.group(0), "").strip()
            except Exception:
                pass

    assistant_message = _dehumanize_scrub(assistant_message)
    if not assistant_message:
        assistant_message = "Here are fresh options."

    return {
        "assistant_message": assistant_message,
        "suggestions": suggestions,
        "raw": raw_text,
    }
