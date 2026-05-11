"""CSRF middleware (Task 2.1) — double-submit cookie enforcement.

Covers the spec's required cases — missing token rejected, wrong token
rejected, valid token accepted — plus the exemption rules (safe methods,
unauthenticated requests, exempt auth + OAuth paths). The middleware also
issues a fresh ``csrf_token`` cookie on the way out when the request didn't
carry one, which the last test asserts.
"""
from __future__ import annotations

import pytest

from middleware.auth import create_access_token
from middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


# ---------------------------------------------------------------------------
# Spec cases (authenticated mutating route)
# ---------------------------------------------------------------------------


async def test_post_missing_csrf_token_rejected(client, authed_user):
    """No ``X-CSRF-Token`` header on a session-bearing POST -> 403."""
    token = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", token)
    # No csrf cookie, no header.
    r = await client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "csrf_failure"


async def test_post_mismatched_csrf_token_rejected(client, authed_user):
    """Cookie token and header token differ -> 403."""
    token = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", token)
    client.cookies.set(CSRF_COOKIE_NAME, "cookie-value")
    r = await client.post(
        "/api/reference-pages",
        json={"ig_handle": "natgeo"},
        headers={CSRF_HEADER_NAME: "different-value"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failure"


async def test_post_matching_csrf_token_accepted(authed_client):
    """``authed_client`` already carries matching cookie + header; the
    request should reach the router and create a row."""
    r = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# Exemptions
# ---------------------------------------------------------------------------


async def test_get_is_safe_method_no_csrf_required(client, authed_user):
    """GET is in ``_SAFE_METHODS`` so should pass without any CSRF token."""
    token = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", token)
    r = await client.get("/api/reference-pages")
    assert r.status_code == 200


async def test_unauthenticated_post_skips_csrf(client):
    """No ``access_token`` cookie -> CSRF middleware steps aside so the auth
    dependency returns the real 401 (not a misleading 403)."""
    r = await client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 401


async def test_login_endpoint_exempt_from_csrf(client):
    """``/api/auth/login`` is in ``_EXEMPT_PATHS`` — request lands on the
    router (which will return 401 for bogus creds, NOT a CSRF 403)."""
    r = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    # Real auth response, not the CSRF middleware's 403.
    assert r.status_code in (401, 422)
    if r.headers.get("content-type", "").startswith("application/json"):
        assert r.json().get("code") != "csrf_failure"


# ---------------------------------------------------------------------------
# Cookie issuance
# ---------------------------------------------------------------------------


async def test_response_sets_csrf_cookie_when_missing(client):
    """A request without ``csrf_token`` should get one set on the response
    so the next page-load's JS can read + echo it."""
    r = await client.get("/api/health")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert CSRF_COOKIE_NAME in set_cookie, set_cookie
    # MUST be readable by JS — no HttpOnly flag.
    assert "httponly" not in set_cookie.lower()
