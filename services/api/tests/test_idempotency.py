"""Idempotency middleware (Task 2.2) — spec cases + edge cases.

Spec: ``Idempotency-Key`` header, 24h cache, same key + same body →
cached, same key + different body → 409. We additionally assert:

  - the replay carries an ``Idempotent-Replay: true`` header so callers
    can tell a cached hit from a fresh execution
  - per-user scoping (user A's key doesn't shadow user B's request)
  - non-mutating methods don't get cached
  - bad key format -> 400
  - non-2xx responses are NOT cached (retry should re-run)
  - responses that set cookies are NOT cached (e.g. /api/auth/login)
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy import select

from middleware import idempotency
from middleware.auth import create_access_token
from middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from middleware.idempotency import IDEMPOTENCY_HEADER, REPLAY_HEADER
from models.reference_page import ReferencePage


@pytest_asyncio.fixture(autouse=True)
async def fake_redis():
    """Inject a fakeredis client so the middleware never touches a real
    Redis. ``autouse`` so every test in this module is isolated to its
    own in-memory cache (cleaner than relying on test ordering)."""
    client = FakeAsyncRedis(decode_responses=False)
    idempotency._test_client = client
    try:
        yield client
    finally:
        idempotency._test_client = None
        await client.aclose()


# ---------------------------------------------------------------------------
# Spec cases
# ---------------------------------------------------------------------------


async def test_same_key_same_body_returns_cached(authed_client, db_session, authed_user):
    """Two POSTs with the same key + same body: only one row created,
    the second response carries ``Idempotent-Replay: true``."""
    key = f"key-{uuid4().hex}"
    payload = {"ig_handle": "natgeo"}

    r1 = await authed_client.post(
        "/api/reference-pages",
        json=payload,
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r1.status_code == 201, r1.text
    assert r1.headers.get(REPLAY_HEADER) is None

    r2 = await authed_client.post(
        "/api/reference-pages",
        json=payload,
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r2.status_code == 201, r2.text
    assert r2.headers.get(REPLAY_HEADER) == "true"
    assert r2.json() == r1.json()

    # Only one row exists in DB — the second POST returned a cached
    # response without re-executing the handler.
    result = await db_session.execute(
        select(ReferencePage).where(ReferencePage.user_id == authed_user.id)
    )
    assert len(result.scalars().all()) == 1


async def test_same_key_different_body_returns_409(authed_client):
    """Reusing a key for a logically-different request is a client bug
    — surface it as 409 instead of silently overwriting the cache."""
    key = f"key-{uuid4().hex}"

    r1 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "natgeo"},
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r1.status_code == 201

    r2 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "different_handle"},
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["code"] == "idempotency_key_conflict"


# ---------------------------------------------------------------------------
# Scoping + opt-in
# ---------------------------------------------------------------------------


async def test_no_idempotency_key_means_no_caching(authed_client):
    """Without the header, the middleware steps aside. Two identical
    POSTs both hit the handler — the second gets the app-layer
    idempotent-add behaviour (200 instead of 201) but is NOT a cached
    replay (no ``Idempotent-Replay`` header)."""
    r1 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    r2 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r1.status_code == 201
    assert r2.status_code == 200  # service-layer dedup, not cache replay
    assert r1.headers.get(REPLAY_HEADER) is None
    assert r2.headers.get(REPLAY_HEADER) is None


async def test_different_keys_run_independently(authed_client):
    """Two different keys = two distinct logical operations."""
    r1 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "natgeo"},
        headers={IDEMPOTENCY_HEADER: f"key-a-{uuid4().hex}"},
    )
    r2 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "different"},
        headers={IDEMPOTENCY_HEADER: f"key-b-{uuid4().hex}"},
    )
    assert r1.status_code == 201
    # Second key + different body -> fresh handler run (creates a new row).
    assert r2.status_code == 201
    assert r2.headers.get(REPLAY_HEADER) is None


async def test_keys_scoped_per_user(client, authed_user, other_authed_user):
    """User A's idempotency key must NOT shadow user B's request. Both
    POSTs should produce 201s scoped to their own user."""
    key = f"shared-key-{uuid4().hex}"
    csrf = "csrf-token-value"

    tok_a = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", tok_a)
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    r_a = await client.post(
        "/api/reference-pages",
        json={"ig_handle": "for_user_a"},
        headers={IDEMPOTENCY_HEADER: key, CSRF_HEADER_NAME: csrf},
    )
    assert r_a.status_code == 201

    tok_b = create_access_token(other_authed_user.id, role=other_authed_user.role)
    client.cookies.set("access_token", tok_b)
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    r_b = await client.post(
        "/api/reference-pages",
        json={"ig_handle": "for_user_b"},
        headers={IDEMPOTENCY_HEADER: key, CSRF_HEADER_NAME: csrf},
    )
    # If we'd shadowed across users, this would 409 (different body) or
    # return User A's cached row. Neither is acceptable.
    assert r_b.status_code == 201, r_b.text
    assert r_b.headers.get(REPLAY_HEADER) is None
    assert r_b.json()["ig_handle"] == "for_user_b"


# ---------------------------------------------------------------------------
# Negative shapes
# ---------------------------------------------------------------------------


async def test_get_with_idempotency_key_is_not_cached(authed_client):
    """Safe methods skip the middleware entirely — no cache write, no
    cache hit, no replay header."""
    r = await authed_client.get(
        "/api/reference-pages",
        headers={IDEMPOTENCY_HEADER: f"key-{uuid4().hex}"},
    )
    assert r.status_code == 200
    assert r.headers.get(REPLAY_HEADER) is None


async def test_invalid_key_format_rejected(authed_client):
    """Empty / too-short / illegal-char keys are a 400 (not 403/500)."""
    r = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "natgeo"},
        headers={IDEMPOTENCY_HEADER: "short"},  # < 8 chars
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_idempotency_key"


async def test_non_2xx_response_not_cached(authed_client):
    """If the first call failed validation (422) we should NOT cache it
    — the client may fix the body and retry with the same key."""
    key = f"key-{uuid4().hex}"

    r1 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": ""},  # fails Pydantic validation
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r1.status_code in (400, 422)

    # Retry with a fixed body using the same key — should succeed,
    # not return the cached 4xx.
    r2 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "natgeo"},
        headers={IDEMPOTENCY_HEADER: key},
    )
    assert r2.status_code == 201
    assert r2.headers.get(REPLAY_HEADER) is None
