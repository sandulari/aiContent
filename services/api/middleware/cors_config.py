"""Strict CORS configuration (Task 2.5).

Replaces ``allow_origins=[...] / allow_methods=["*"] / allow_headers=["*"]``
with an explicit allow-list driven by ``ALLOWED_ORIGINS`` env. Three
hard rules enforced here:

  1. **No ``*`` origin when ``allow_credentials=True``.** Per the CORS
     spec, browsers refuse to send credentials to a wildcard origin,
     and FastAPI's CORSMiddleware "fixes" that by echoing the request
     origin — which is functionally an open allowlist (any site can
     read responses). We fail fast at startup if anyone tries it.

  2. **Methods are explicit.** ``GET, POST, PUT, PATCH, DELETE, OPTIONS``
     only. No ``*``. If a route ever needs a different method
     (e.g. WebSocket), the spec change goes through this list.

  3. **Headers are explicit.** Only the ones our frontend actually
     sends: ``Content-Type``, ``Authorization``, ``X-CSRF-Token``
     (Task 2.1), ``Idempotency-Key`` (Task 2.2). New headers are
     added here, not silently allowed by ``*``.

We also ``expose_headers`` for things the JS reads off the response —
``Idempotent-Replay`` so a client can tell a cached replay from a fresh
execution, and ``Retry-After`` so the 429 retry UI works.

Production defaults: read ``ALLOWED_ORIGINS`` (comma-separated). Falls
back to the legacy ``CORS_ORIGINS`` env var so an in-place deploy
doesn't break. Final fallback for dev: localhost.
"""
from __future__ import annotations

import os
from typing import Iterable

# Headers the frontend is allowed to SEND on a cross-origin request.
ALLOWED_REQUEST_HEADERS: list[str] = [
    "Content-Type",
    "Authorization",
    "X-CSRF-Token",
    "Idempotency-Key",
]

# Headers the JS is allowed to READ off the response. ``Set-Cookie`` is
# special — the browser handles it regardless and JS never reads it.
EXPOSED_RESPONSE_HEADERS: list[str] = [
    "Idempotent-Replay",  # Task 2.2 — cache replay marker
    "Retry-After",        # 429 responses include this
]

ALLOWED_METHODS: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

_DEV_DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:8080"


class InsecureCORSConfig(ValueError):
    """Raised at startup if the allowlist would expand to ``*`` while
    credentials are enabled — that combo is silently insecure."""


def parse_allowed_origins(
    raw: str | None, *, allow_credentials: bool
) -> list[str]:
    """Parse a comma-separated origin list.

    Empty entries are dropped, whitespace is stripped. If any entry is
    ``*`` and ``allow_credentials`` is True we raise — callers MUST
    fix the config before the app comes up.
    """
    raw = (raw or _DEV_DEFAULT_ORIGINS).strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    if not parts:
        # Defensive: an env var set to a single comma would otherwise
        # leave us with an empty allowlist and silently deny everything.
        parts = [p for p in _DEV_DEFAULT_ORIGINS.split(",")]

    if allow_credentials and "*" in parts:
        raise InsecureCORSConfig(
            "ALLOWED_ORIGINS contains '*' but allow_credentials=True. "
            "Browsers ignore wildcard origins on credentialed requests; "
            "use an explicit comma-separated origin list instead."
        )
    return parts


def cors_kwargs(
    *,
    allow_credentials: bool = True,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return the kwargs to pass to ``app.add_middleware(CORSMiddleware, **k)``.

    Reads ``ALLOWED_ORIGINS`` (preferred) or legacy ``CORS_ORIGINS``
    from ``env`` (defaults to ``os.environ``) and applies the explicit
    method / header / expose-header allowlists above.
    """
    env = env if env is not None else dict(os.environ)
    raw = env.get("ALLOWED_ORIGINS") or env.get("CORS_ORIGINS")
    origins = parse_allowed_origins(raw, allow_credentials=allow_credentials)

    return {
        "allow_origins": origins,
        "allow_credentials": allow_credentials,
        "allow_methods": ALLOWED_METHODS,
        "allow_headers": ALLOWED_REQUEST_HEADERS,
        "expose_headers": EXPOSED_RESPONSE_HEADERS,
        "max_age": 600,  # cache preflight for 10 minutes
    }
