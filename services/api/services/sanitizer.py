"""HTML / text sanitization helpers (Task 2.3 — XSS hardening).

We currently store two classes of user-provided strings:

  - **Plain-text identifiers / display strings** — ``users.display_name``,
    template names, and similar fields that the frontend renders as
    text. React's default escaping already prevents script-injection on
    render, but those same strings ALSO land in HTML email templates
    (welcome + password reset) where `f"... {display_name} ..."` is a
    real injection sink. Sanitizing on the way in means the stored value
    is safe no matter which output context picks it up later.

  - **Third-party content** — ``reference_reels.caption`` fetched from
    RapidAPI. We don't trust the source, but we also never interpolate
    these into HTML — only into text contexts. The frontend should
    treat them as opaque text and the backend leaves them untouched.

For the first class, we use :mod:`bleach` with ``tags=[]`` so every HTML
tag is stripped to its text content. Plain ``html.escape`` would only
encode the characters; bleach strips the structure entirely, which is
what we want for fields advertised as "plain text".

For email templates we additionally rely on :func:`html.escape` at the
interpolation point as defense-in-depth — bleach normalizes on input,
``escape`` covers any code path that bypassed the Pydantic layer (e.g.
admin-set fields, legacy rows from before this commit).
"""
from __future__ import annotations

import html

import bleach


def clean_text(value: str | None) -> str | None:
    """Strip ALL HTML tags from ``value`` and return the plain text.

    Returns ``None`` unchanged so optional fields keep their semantics.
    Whitespace is normalised (leading/trailing trim) but inner spaces
    are preserved. Used in Pydantic field validators for any user-
    supplied string that's meant to be plain text.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    # ``strip=True`` -> tags are removed, their text content is kept.
    cleaned = bleach.clean(value, tags=[], attributes={}, strip=True)
    return cleaned.strip()


def escape_for_html(value: str | None) -> str:
    """HTML-escape a string for safe interpolation into an HTML email.

    Defense-in-depth around :func:`clean_text` — if a row somehow
    contains raw HTML (legacy data, admin override, etc.), this still
    renders it as visible text instead of executing it. Returns the
    empty string for ``None`` so f-strings stay tidy.
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)
