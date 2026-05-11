"""Reference pages — CRUD + cap + duplicate + ownership.

These exercise both the service-layer guard (friendly 409) and the
BEFORE-INSERT trigger backstop. Cross-tenant tests confirm User A
cannot see, list, or delete User B's reference pages.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from middleware.auth import create_access_token
from models.reference_page import ReferencePage


# ---------------------------------------------------------------------------
# List + add + idempotency
# ---------------------------------------------------------------------------


async def test_list_empty(authed_client):
    r = await authed_client.get("/api/reference-pages")
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0, "max": 5}


async def test_add_creates_row(authed_client):
    r = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ig_handle"] == "natgeo"
    assert body["ig_user_id"] is None
    assert body["added_at"] is not None

    r2 = await authed_client.get("/api/reference-pages")
    assert r2.json()["count"] == 1
    assert r2.json()["items"][0]["id"] == body["id"]


async def test_add_is_idempotent_per_handle(authed_client):
    r1 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r1.status_code == 201

    r2 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    # Re-adding the same handle is a no-op — same row, 200 instead of 201.
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]

    r3 = await authed_client.get("/api/reference-pages")
    assert r3.json()["count"] == 1


async def test_add_normalizes_input(authed_client):
    """`@NATGEO`, `https://www.instagram.com/natgeo/?hl=en`, `natgeo` all collapse to one row."""
    r1 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "@NATGEO"}
    )
    assert r1.status_code == 201
    assert r1.json()["ig_handle"] == "natgeo"

    r2 = await authed_client.post(
        "/api/reference-pages",
        json={"ig_handle": "https://www.instagram.com/natgeo/?hl=en"},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]


@pytest.mark.parametrize(
    "bad_handle",
    [
        "with space",
        "exclaim!",
        "a" * 31,
        "",
        "comma,bad",
    ],
)
async def test_add_rejects_invalid_handles(authed_client, bad_handle):
    r = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": bad_handle}
    )
    # Pydantic validation surfaces as 422.
    assert r.status_code == 422, (
        f"expected 422 for handle {bad_handle!r}, got {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# Cap enforcement — service layer + DB trigger
# ---------------------------------------------------------------------------


async def test_max_5_enforced_at_service_layer(authed_client):
    for i in range(5):
        r = await authed_client.post(
            "/api/reference-pages", json={"ig_handle": f"ref{i}"}
        )
        assert r.status_code == 201, f"failed to add ref{i}: {r.text}"

    r6 = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "ref5"}
    )
    assert r6.status_code == 409
    body = r6.json()
    assert body["detail"]["code"] == "max_reference_pages"


async def test_max_5_enforced_at_db_trigger(db_session, authed_user):
    """Bypass the router and INSERT directly — exercises the trigger that
    guards against concurrent inserts both passing the count check.
    """
    for i in range(5):
        db_session.add(
            ReferencePage(user_id=authed_user.id, ig_handle=f"ref{i}")
        )
    await db_session.flush()

    db_session.add(ReferencePage(user_id=authed_user.id, ig_handle="ref5"))
    with pytest.raises(Exception) as exc:
        await db_session.flush()
    assert "max 5 reference pages" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Delete + ownership
# ---------------------------------------------------------------------------


async def test_delete_removes_own_page(authed_client):
    created = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    ref_id = created.json()["id"]

    r = await authed_client.delete(f"/api/reference-pages/{ref_id}")
    assert r.status_code == 204

    listing = await authed_client.get("/api/reference-pages")
    assert listing.json()["count"] == 0


async def test_delete_nonexistent_returns_404(authed_client):
    r = await authed_client.delete(f"/api/reference-pages/{uuid4()}")
    assert r.status_code == 404


async def test_cannot_see_another_users_pages(
    authed_client, db_session, other_authed_user
):
    db_session.add(
        ReferencePage(user_id=other_authed_user.id, ig_handle="otheruser")
    )
    await db_session.flush()

    r = await authed_client.get("/api/reference-pages")
    assert r.status_code == 200
    assert r.json()["count"] == 0


async def test_cannot_delete_another_users_page(
    authed_client, db_session, other_authed_user
):
    row = ReferencePage(user_id=other_authed_user.id, ig_handle="otheruser")
    db_session.add(row)
    await db_session.flush()
    other_id = row.id

    r = await authed_client.delete(f"/api/reference-pages/{other_id}")
    # 404 — we don't acknowledge the row exists at all to the wrong owner.
    assert r.status_code == 404

    # Row still there for the real owner.
    still = await db_session.get(ReferencePage, other_id)
    assert still is not None


async def test_other_user_can_have_same_handle(
    authed_client, db_session, other_authed_user
):
    """The UNIQUE constraint is on (user_id, ig_handle) — different users
    are allowed to track the same inspiration page independently."""
    db_session.add(
        ReferencePage(user_id=other_authed_user.id, ig_handle="natgeo")
    )
    await db_session.flush()

    r = await authed_client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Auth boundary
# ---------------------------------------------------------------------------


async def test_unauthenticated_list_rejected(client):
    # `client` has no auth cookie; only `authed_client` does.
    r = await client.get("/api/reference-pages")
    assert r.status_code == 401


async def test_unauthenticated_add_rejected(client):
    r = await client.post(
        "/api/reference-pages", json={"ig_handle": "natgeo"}
    )
    assert r.status_code == 401


async def test_unauthenticated_delete_rejected(client):
    r = await client.delete(f"/api/reference-pages/{uuid4()}")
    assert r.status_code == 401
