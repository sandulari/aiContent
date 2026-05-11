"""Discovery filter — GET defaults, PUT upsert, /preview, validation, isolation."""
from __future__ import annotations

import pytest

from middleware.auth import create_access_token


# ---------------------------------------------------------------------------
# GET defaults / GET after PUT
# ---------------------------------------------------------------------------


async def test_get_returns_defaults_when_no_row(authed_client):
    r = await authed_client.get("/api/discovery-filter")
    assert r.status_code == 200
    body = r.json()
    assert body["min_views"] == 1000
    assert body["min_likes"] == 10
    assert body["min_comments"] == 0
    assert body["min_engagement_rate"] == 0.0
    assert body["max_age_days"] == 60
    assert body["sort_by"] == "views_desc"
    assert body["is_default"] is True
    assert body["updated_at"] is None


async def test_put_creates_row_then_get_reflects(authed_client):
    payload = {
        "min_views": 5000,
        "min_likes": 50,
        "min_comments": 5,
        "min_engagement_rate": 0.03,
        "max_age_days": 14,
        "sort_by": "engagement_desc",
    }
    r = await authed_client.put("/api/discovery-filter", json=payload)
    assert r.status_code == 200, r.text
    saved = r.json()
    for k, v in payload.items():
        assert saved[k] == v, k
    assert saved["is_default"] is False
    assert saved["updated_at"] is not None

    r2 = await authed_client.get("/api/discovery-filter")
    assert r2.status_code == 200
    fresh = r2.json()
    assert fresh["is_default"] is False
    for k, v in payload.items():
        assert fresh[k] == v, k


async def test_put_is_upsert_no_duplicate_row(authed_client, db_session, authed_user):
    from sqlalchemy import select, func
    from models.discovery_filter import DiscoveryFilter

    # First PUT — INSERT path.
    r1 = await authed_client.put(
        "/api/discovery-filter", json={"min_views": 100}
    )
    assert r1.status_code == 200
    # Second PUT — UPDATE path. Same user, different values.
    r2 = await authed_client.put(
        "/api/discovery-filter", json={"min_views": 200}
    )
    assert r2.status_code == 200
    assert r2.json()["min_views"] == 200

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(DiscoveryFilter)
            .where(DiscoveryFilter.user_id == authed_user.id)
        )
    ).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Validation — Pydantic + DB CHECKs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"min_views": -1},
        {"min_likes": -10},
        {"min_comments": -5},
        {"min_engagement_rate": -0.1},
        {"min_engagement_rate": 1.5},  # spec is 0-1 (fraction, not %)
        {"max_age_days": 0},
        {"max_age_days": 366},
        {"sort_by": "random_garbage"},
        {"sort_by": ""},
        {"unknown_field": 42},  # extra="forbid"
    ],
)
async def test_put_rejects_invalid_payload(authed_client, bad_payload):
    r = await authed_client.put("/api/discovery-filter", json=bad_payload)
    assert r.status_code == 422, (
        f"expected 422 for {bad_payload!r}, got {r.status_code}: {r.text}"
    )


async def test_put_with_empty_body_uses_all_defaults(authed_client):
    """PUT with no fields = "save the defaults" — explicit lock-in action."""
    r = await authed_client.put("/api/discovery-filter", json={})
    assert r.status_code == 200
    saved = r.json()
    assert saved["min_views"] == 1000
    assert saved["sort_by"] == "views_desc"
    assert saved["is_default"] is False  # row now exists


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------


async def test_preview_returns_zero_until_cache_exists(authed_client):
    r = await authed_client.post(
        "/api/discovery-filter/preview",
        json={"min_views": 100, "max_age_days": 30},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["has_cache"] is False


async def test_preview_validates_payload(authed_client):
    r = await authed_client.post(
        "/api/discovery-filter/preview",
        json={"max_age_days": 9999},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


async def test_users_have_independent_filters(client, authed_user, other_authed_user):
    """User A's PUT must never appear in user B's GET."""
    tok_a = create_access_token(authed_user.id, role=authed_user.role)
    tok_b = create_access_token(other_authed_user.id, role=other_authed_user.role)

    client.cookies.set("access_token", tok_a)
    r = await client.put("/api/discovery-filter", json={"min_views": 999})
    assert r.status_code == 200

    client.cookies.set("access_token", tok_b)
    r2 = await client.get("/api/discovery-filter")
    assert r2.status_code == 200
    body = r2.json()
    # User B sees defaults because they never PUT — A's 999 is invisible.
    assert body["is_default"] is True
    assert body["min_views"] == 1000


# ---------------------------------------------------------------------------
# Auth boundary
# ---------------------------------------------------------------------------


async def test_unauthenticated_get_rejected(client):
    r = await client.get("/api/discovery-filter")
    assert r.status_code == 401


async def test_unauthenticated_put_rejected(client):
    r = await client.put(
        "/api/discovery-filter", json={"min_views": 100}
    )
    assert r.status_code == 401


async def test_unauthenticated_preview_rejected(client):
    r = await client.post("/api/discovery-filter/preview", json={})
    assert r.status_code == 401
