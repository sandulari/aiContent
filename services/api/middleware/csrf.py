"""Double-submit cookie CSRF protection.

Standard double-submit pattern:

  - Server issues a ``csrf_token`` cookie. The cookie is NOT HttpOnly —
    JS must read it so the frontend can echo it in the ``X-CSRF-Token``
    header on every mutating request.
  - The cookie itself is SameSite=Lax + Secure (in prod), so cross-site
    code can't read it and a CSRF request from a different origin won't
    carry it. The header echo proves the request originated from same-
    origin JS that successfully read the cookie.
  - On POST/PUT/PATCH/DELETE the middleware compares header == cookie
    via ``hmac.compare_digest``. Mismatch -> 403.

Exemptions (skip the header check):

  - Safe methods: GET, HEAD, OPTIONS.
  - Unauthenticated routes: login, register, refresh, forgot/reset
    password, OAuth callback. The user has no session yet so there's
    nothing to forge against.
  - Requests with no ``access_token`` cookie at all: there's no session
    so the auth dependency will return 401 anyway — letting CSRF run
    first would mask the real failure as 403.

The middleware always sets a fresh ``csrf_token`` cookie on the way out
if the request didn't already have one. Token format: 256 bits of
``secrets.token_urlsafe``, ~43 chars.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Safe HTTP methods that never mutate server state.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Routes that must accept a request without a prior session. Login /
# register / refresh / password reset are the obvious set; OAuth callback
# is a Meta-initiated redirect on a separate origin so a CSRF token from
# *our* origin couldn't possibly accompany it.
_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
})

# Path prefixes that always skip CSRF. OAuth callback is a top-level
# redirect from Meta; the IG OAuth start endpoint already validates a
# signed HMAC state nonce of its own.
_EXEMPT_PREFIXES = ("/api/ig/oauth/",)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None


def _is_exempt(request: Request) -> bool:
    if request.method in _SAFE_METHODS:
        return True
    path = request.url.path
    if path in _EXEMPT_PATHS:
        return True
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return True
    return False


def _has_session(request: Request) -> bool:
    """Best-effort: does this request claim a logged-in user? If not,
    skip CSRF so the auth dependency can return 401 directly. We don't
    decode the token here — presence is enough."""
    return bool(request.cookies.get("access_token"))


def generate_token() -> str:
    """Public so tests / response helpers can issue tokens without
    duplicating the format."""
    return secrets.token_urlsafe(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit cookie on mutating routes. Always issues a
    fresh cookie on the response if the request didn't carry one."""

    async def dispatch(self, request: Request, call_next) -> Response:
        existing_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        if not _is_exempt(request) and _has_session(request):
            header = request.headers.get(CSRF_HEADER_NAME)
            cookie = existing_cookie
            if not header or not cookie:
                return _csrf_failure("Missing CSRF token")
            if not hmac.compare_digest(header, cookie):
                return _csrf_failure("CSRF token mismatch")

        response = await call_next(request)

        # Issue a fresh cookie if the client doesn't have one yet, so
        # JS on the next page load can read + echo it on its mutating
        # calls. We don't rotate on every request — that's noise and
        # creates races with concurrent tabs.
        if not existing_cookie:
            new_token = generate_token()
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=new_token,
                httponly=False,   # MUST be readable by JS for the echo
                secure=COOKIE_SECURE,
                samesite="lax",
                domain=COOKIE_DOMAIN,
                path="/",
            )
        return response


def _csrf_failure(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": detail, "code": "csrf_failure"},
    )
