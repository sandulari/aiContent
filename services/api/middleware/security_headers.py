"""Security response headers (Task 2.6).

A single Starlette middleware that adds the OWASP-recommended security
headers to every response from the API. These are all *response*
headers — the browser enforces them once a response arrives.

Headers set:

  - ``Content-Security-Policy`` — for the API, the strictest policy
    possible: ``default-src 'none'; frame-ancestors 'none'``. The API
    serves JSON; nothing it returns should ever execute scripts or be
    embedded as a frame. If a route ever serves HTML (e.g. an error
    page) the browser refuses to load any subresources, which is
    exactly what we want for a wrong-content-type leak.

  - ``Strict-Transport-Security`` — only emitted when the request was
    served over HTTPS (or when an upstream proxy signalled it via
    ``X-Forwarded-Proto: https``). Browsers ignore HSTS on plain HTTP
    by spec, but emitting it on plain HTTP from a misconfigured
    reverse proxy can pin clients to the wrong scheme — better to be
    explicit. ``max-age=31536000; includeSubDomains`` (one year).

  - ``X-Content-Type-Options: nosniff`` — kills MIME sniffing so a
    text/plain response with HTML in it can't be re-interpreted by
    the browser as HTML.

  - ``X-Frame-Options: DENY`` — even with CSP frame-ancestors, the
    older header still helps for clients that don't speak modern CSP.

  - ``Referrer-Policy: strict-origin-when-cross-origin`` — the
    browser default since 2020 but we set it explicitly so the
    behaviour doesn't drift if a future browser changes it.

  - ``Permissions-Policy`` — disable camera, mic, geolocation,
    payment, USB. Nothing in the app needs those.

The Next.js frontend sets its own copy of most of these in
``apps/web/next.config.js`` (the frontend's CSP has to be broader
because Next inlines scripts). This middleware covers everything the
API serves directly.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Locked down for an API: nothing should be loaded from a JSON response.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_HSTS = "max-age=31536000; includeSubDomains"
_PERMISSIONS = (
    "camera=(), microphone=(), geolocation=(), "
    "payment=(), usb=(), magnetometer=(), gyroscope=()"
)
_REFERRER = "strict-origin-when-cross-origin"


def _is_https(request: Request) -> bool:
    """Detect HTTPS even when behind a reverse proxy that terminates
    TLS upstream. nginx sends ``X-Forwarded-Proto: https`` for us in
    prod; uvicorn's ``--proxy-headers`` flag promotes it to
    ``request.url.scheme``."""
    if request.url.scheme == "https":
        return True
    fwd = request.headers.get("x-forwarded-proto", "").lower()
    return fwd == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # ``setdefault`` so a route that wants a different CSP (e.g. /docs
        # serving Swagger UI in dev) can override.
        h = response.headers
        h.setdefault("Content-Security-Policy", _API_CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", _REFERRER)
        h.setdefault("Permissions-Policy", _PERMISSIONS)
        if _is_https(request):
            h.setdefault("Strict-Transport-Security", _HSTS)
        return response
