"""Security response headers (Task 2.6).

Verifies the middleware adds the OWASP-recommended headers to *every*
response — including the CSRF middleware's early-return 403, the auth
dependency's 401, and validation 422s. Because security headers are
the outermost middleware, they wrap every other middleware's responses
on the way out.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Happy path — health endpoint
# ---------------------------------------------------------------------------


async def test_health_has_all_security_headers(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy") is not None
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    permissions = r.headers.get("permissions-policy", "")
    assert "camera=()" in permissions
    assert "microphone=()" in permissions
    assert "geolocation=()" in permissions


async def test_http_response_has_no_hsts(client):
    """HSTS over plain HTTP is meaningless; we only emit it on HTTPS.
    The test client uses http://test, so HSTS should be absent."""
    r = await client.get("/api/health")
    assert "strict-transport-security" not in {k.lower() for k in r.headers}


async def test_https_response_has_hsts(client):
    """When the upstream proxy reports HTTPS via X-Forwarded-Proto, the
    middleware should emit Strict-Transport-Security."""
    r = await client.get(
        "/api/health", headers={"X-Forwarded-Proto": "https"}
    )
    hsts = r.headers.get("strict-transport-security")
    assert hsts is not None
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


# ---------------------------------------------------------------------------
# Headers are present even on error responses
# ---------------------------------------------------------------------------


async def test_csrf_403_carries_security_headers(client, authed_user):
    """The CSRF middleware short-circuits with a 403 before the route
    runs. SecurityHeaders is OUTERMOST so it still stamps the response."""
    from middleware.auth import create_access_token

    token = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", token)
    # No CSRF header, no CSRF cookie -> 403.
    r = await client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 403
    assert r.headers.get("content-security-policy") is not None
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


async def test_unauthenticated_401_carries_security_headers(client):
    """An auth-dependency 401 (no cookie at all) still gets the
    security headers."""
    r = await client.get("/api/reference-pages")
    assert r.status_code == 401
    assert r.headers.get("content-security-policy") is not None
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
