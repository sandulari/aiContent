"""Rotating refresh tokens + reuse detection (Task 2.4).

Exercises the full state machine in
``services/api/services/refresh_tokens.py`` through the HTTP API:

  - login inserts a fresh ``refresh_tokens`` row with a unique
    ``family_id``
  - /refresh rotates: the presented hash is marked revoked, a successor
    in the same family is inserted, response cookies are fresh
  - a replay of an already-rotated (revoked) token returns 401
    ``code: refresh_token_reuse`` AND deletes every row in the family
    (the spec calls for family-wide revocation)
  - unknown hashes return 401 ``code: invalid_refresh_token``
  - expired tokens return 401 ``code: refresh_token_expired`` and the
    row is marked revoked so a future replay still trips REUSE
  - /logout revokes the current row but leaves the family in place

Also asserts the spec's access-token TTL of 15 minutes.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from middleware import auth as auth_middleware
from middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from models.refresh_token import RefreshToken
from models.user import User
from routers import auth as auth_router
from services.refresh_tokens import (
    RotationResult,
    issue_new_family,
    revoke_token,
    rotate_refresh_token,
)


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    """The router's per-IP login/register/forgot limiter is an in-memory
    dict that persists across tests. Clear it so a long suite doesn't
    accidentally trip the 5-register / 8-login cap."""
    auth_router._AUTH_RL.clear()
    yield
    auth_router._AUTH_RL.clear()


# ---------------------------------------------------------------------------
# Access-token TTL — Phase 2.4 spec wants 15 minutes (was 60)
# ---------------------------------------------------------------------------


def test_access_token_default_ttl_is_15_minutes(monkeypatch):
    """The module-level constant should default to 15 when the env var
    is unset. Sanity-check guards against drift back to the old 60."""
    monkeypatch.delenv("ACCESS_TOKEN_MINUTES", raising=False)
    # Re-import the module under a clean env so the constant rebinds.
    import importlib

    importlib.reload(auth_middleware)
    try:
        assert auth_middleware.ACCESS_TOKEN_MINUTES == 15
    finally:
        # Restore — other tests may rely on the module-level state.
        importlib.reload(auth_middleware)


# ---------------------------------------------------------------------------
# Service-layer state machine (drives rotate_refresh_token directly)
# ---------------------------------------------------------------------------


async def test_issue_new_family_creates_row(db_session, authed_user):
    raw, expires, family_id = await issue_new_family(db_session, authed_user.id)
    assert raw  # non-empty
    assert expires > datetime.now(timezone.utc)
    assert isinstance(family_id, UUID)

    rows = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == authed_user.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].family_id == family_id
    assert rows[0].revoked_at is None


async def test_rotate_with_valid_token_marks_old_revoked_and_inserts_successor(
    db_session, authed_user
):
    raw1, _, family_id = await issue_new_family(db_session, authed_user.id)

    outcome = await rotate_refresh_token(db_session, raw1)
    assert outcome.result == RotationResult.ROTATED
    assert outcome.new_raw_token and outcome.new_raw_token != raw1
    assert outcome.family_id == family_id

    rows = (await db_session.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == authed_user.id)
        .order_by(RefreshToken.issued_at)
    )).scalars().all()
    assert len(rows) == 2
    # First row revoked, second row active.
    assert rows[0].revoked_at is not None
    assert rows[1].revoked_at is None
    # Same family.
    assert rows[0].family_id == rows[1].family_id == family_id


async def test_rotate_with_revoked_token_triggers_family_purge(db_session, authed_user):
    raw1, _, family_id = await issue_new_family(db_session, authed_user.id)

    # Rotate once — raw1 is now revoked, raw2 is active.
    out1 = await rotate_refresh_token(db_session, raw1)
    assert out1.result == RotationResult.ROTATED

    # Replay raw1: this is the reuse case.
    out2 = await rotate_refresh_token(db_session, raw1)
    assert out2.result == RotationResult.REUSE
    assert out2.family_id == family_id

    # The entire family is gone.
    rows = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id)
    )).scalars().all()
    assert rows == []


async def test_rotate_with_unknown_token_returns_unknown(db_session):
    outcome = await rotate_refresh_token(db_session, "this-token-was-never-issued")
    assert outcome.result == RotationResult.UNKNOWN
    assert outcome.user_id is None


async def test_rotate_with_expired_token_returns_expired_and_revokes_row(
    db_session, authed_user
):
    raw, _, family_id = await issue_new_family(db_session, authed_user.id)

    # Fast-forward the row's expires_at into the past.
    row = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id)
    )).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    outcome = await rotate_refresh_token(db_session, raw)
    assert outcome.result == RotationResult.EXPIRED

    # Row marked revoked so a future replay still trips REUSE
    # (defense-in-depth — an expired token shouldn't be a free pass to
    # try the chain again).
    await db_session.refresh(row)
    assert row.revoked_at is not None


async def test_revoke_token_marks_row_revoked(db_session, authed_user):
    raw, _, family_id = await issue_new_family(db_session, authed_user.id)
    ok = await revoke_token(db_session, raw)
    assert ok is True

    row = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id)
    )).scalar_one()
    assert row.revoked_at is not None


async def test_revoke_token_returns_false_for_unknown(db_session):
    assert await revoke_token(db_session, "no-such-token") is False


# ---------------------------------------------------------------------------
# HTTP — /refresh + /logout end-to-end
# ---------------------------------------------------------------------------


async def _login(client, email: str, password: str = "testpass123"):
    """Helper: register + login via the API. Returns the response so the
    caller can inspect cookies."""
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Test"},
    )
    return await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )


async def test_login_inserts_refresh_token_row(client, db_session):
    r = await _login(client, f"u-{uuid4().hex[:8]}@example.com")
    assert r.status_code == 200, r.text
    refresh_cookie = r.cookies.get("refresh_token")
    assert refresh_cookie  # set on response

    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None


async def test_refresh_rotates_and_returns_new_cookies(client, db_session):
    r = await _login(client, f"u-{uuid4().hex[:8]}@example.com")
    first_refresh = r.cookies.get("refresh_token")
    assert first_refresh

    # /refresh — should succeed and return a new refresh cookie.
    r2 = await client.post("/api/auth/refresh")
    assert r2.status_code == 200, r2.text
    new_refresh = r2.cookies.get("refresh_token")
    assert new_refresh and new_refresh != first_refresh

    # Two rows now: the original (revoked) + the successor.
    rows = (await db_session.execute(
        select(RefreshToken).order_by(RefreshToken.issued_at)
    )).scalars().all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[1].revoked_at is None
    assert rows[0].family_id == rows[1].family_id


async def test_refresh_replay_returns_reuse_and_wipes_family(client, db_session):
    r = await _login(client, f"u-{uuid4().hex[:8]}@example.com")
    first_refresh = r.cookies.get("refresh_token")

    # Rotate once — first_refresh is now revoked.
    r2 = await client.post("/api/auth/refresh")
    assert r2.status_code == 200
    family_id = (await db_session.execute(select(RefreshToken.family_id))).scalar_one()

    # Replay the original (revoked) cookie. httpx auto-forwards the
    # NEW refresh cookie from r2 — overwrite it back to first_refresh
    # so we replay the old token.
    client.cookies.set("refresh_token", first_refresh)
    r3 = await client.post("/api/auth/refresh")
    assert r3.status_code == 401
    body = r3.json()
    # FastAPI wraps the HTTPException.detail into ``detail``.
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("code") == "refresh_token_reuse"

    # The entire family is gone.
    rows = (await db_session.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id)
    )).scalars().all()
    assert rows == []


async def test_refresh_with_no_cookie_returns_401(client):
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 401


async def test_refresh_with_unknown_cookie_returns_invalid_refresh_token(client):
    client.cookies.set("refresh_token", "not-a-real-token")
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 401
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("code") == "invalid_refresh_token"


async def test_logout_revokes_current_token_keeps_family(client, db_session):
    r = await _login(client, f"u-{uuid4().hex[:8]}@example.com")
    assert r.cookies.get("refresh_token")

    # Logout needs CSRF (mutating + authenticated). Re-use the test
    # client's csrf cookie if present, else mint one.
    csrf = client.cookies.get(CSRF_COOKIE_NAME) or "csrf-logout"
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    r2 = await client.post(
        "/api/auth/logout", headers={CSRF_HEADER_NAME: csrf}
    )
    assert r2.status_code == 200

    # Row still exists, but is revoked. (Family preserved so a future
    # replay still trips REUSE rather than silently being unknown.)
    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 1
    assert rows[0].revoked_at is not None
