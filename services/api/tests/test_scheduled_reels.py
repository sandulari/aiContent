"""Scheduled reels — timezone handling, double-publish prevention, retry
cap, status transitions, ownership scoping.

The existing scheduler (services/api/routers/scheduled_reels.py +
services/worker/tasks/publish_scheduled_reel.py) was built without any
test coverage in this repo. These cases pin its current behaviour so
future changes notice when they shift the contract.

The worker's actual Graph API call to publish a reel isn't exercised
here — that's a publish_scheduled_reel.py concern that lives in the
sync worker package and would need its own conftest. The router-level
state-machine + validation surface is what Task 1.7 calls out and what
we lock down here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from middleware.auth import create_access_token
from models.scheduled_reel import ScheduledReel
from models.user_export import UserExport
from models.user_template import UserTemplate
from models.viral_reel import ViralReel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _future_iso(minutes_ahead: int = 30) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    ).isoformat()


async def _connect_ig_for_publish(user, db_session):
    """Set the IG OAuth fields the scheduler router requires to allow a
    POST. The encrypted token doesn't need to be decryptable here — only
    /scheduled-reels/{id}/insights touches decrypt_token, and we don't
    test that path."""
    user.ig_user_id = "1234567890"
    user.ig_account_type = "BUSINESS"
    user.ig_access_token = "fake-encrypted-token"
    user.ig_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    user.ig_auth_method = "oauth"
    await db_session.flush()


async def _seed_export(db_session, user):
    """Seed a UserExport in 'done' state — minimum viable for the
    scheduler's `export.export_status == "done"` precondition. Backs onto
    a synthetic ViralReel + master-style template so we don't require
    the lifespan seed to have run before this fixture executes."""
    template = UserTemplate(
        user_id=user.id,
        template_name="test-template",
        is_master=False,
        lock_layout=False,
    )
    db_session.add(template)
    viral_reel = ViralReel(
        ig_video_id=f"vr-{uuid4().hex[:8]}",
        ig_url="https://www.instagram.com/reel/Cxx/",
        view_count=1000,
        like_count=100,
        comment_count=10,
    )
    db_session.add(viral_reel)
    await db_session.flush()

    export = UserExport(
        user_id=user.id,
        viral_reel_id=viral_reel.id,
        template_id=template.id,
        headline_text="head",
        subtitle_text="sub",
        export_status="done",
        export_minio_key=f"exports/{user.id}/x.mp4",
    )
    db_session.add(export)
    await db_session.flush()
    return export


# ---------------------------------------------------------------------------
# Timezone handling — the spec's first test bullet
# ---------------------------------------------------------------------------


async def test_create_rejects_naive_datetime(authed_client, db_session, authed_user):
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)

    naive = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": naive},
    )
    # Pydantic field_validator rejects naive datetimes with 422 before
    # the handler runs.
    assert r.status_code == 422


async def test_create_accepts_tz_aware_datetime(authed_client, db_session, authed_user):
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": _future_iso()},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued"
    # The router returns scheduled_at as ISO 8601 in UTC.
    assert body["scheduled_at"].endswith("+00:00") or body["scheduled_at"].endswith("Z")


async def test_create_rejects_too_close_lead_time(authed_client, db_session, authed_user):
    """_MIN_SCHEDULE_LEAD is 2 minutes; anything within is 400."""
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)
    too_soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": too_soon},
    )
    assert r.status_code == 400


async def test_create_rejects_too_far_future(authed_client, db_session, authed_user):
    """_MAX_SCHEDULE_DAYS is 60; anything past is 400."""
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)
    too_far = (datetime.now(timezone.utc) + timedelta(days=61)).isoformat()

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": too_far},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# IG-connection preconditions
# ---------------------------------------------------------------------------


async def test_create_requires_ig_connected(authed_client, db_session, authed_user):
    """User without ig_user_id / ig_access_token can't schedule."""
    export = await _seed_export(db_session, authed_user)
    # NOTE: skipping _connect_ig_for_publish — user has no IG state.
    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": _future_iso()},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ig_not_connected"


async def test_create_rejects_expired_ig_token(authed_client, db_session, authed_user):
    authed_user.ig_user_id = "1"
    authed_user.ig_access_token = "x"
    authed_user.ig_account_type = "BUSINESS"
    authed_user.ig_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.flush()
    export = await _seed_export(db_session, authed_user)

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": _future_iso()},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ig_token_expired"


async def test_create_rejects_personal_account(authed_client, db_session, authed_user):
    authed_user.ig_user_id = "1"
    authed_user.ig_access_token = "x"
    authed_user.ig_account_type = "PERSONAL"
    authed_user.ig_token_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    await db_session.flush()
    export = await _seed_export(db_session, authed_user)

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": _future_iso()},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ig_account_type_personal"


# ---------------------------------------------------------------------------
# Export-readiness check
# ---------------------------------------------------------------------------


async def test_create_requires_export_done(authed_client, db_session, authed_user):
    """Export must be export_status='done' with an export_minio_key."""
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)
    export.export_status = "editing"
    export.export_minio_key = None
    await db_session.flush()

    r = await authed_client.post(
        "/api/scheduled-reels",
        json={"user_export_id": str(export.id), "scheduled_at": _future_iso()},
    )
    assert r.status_code == 404  # router treats it as "not ready or not found"


# ---------------------------------------------------------------------------
# Double-publish prevention — only 'queued' rows are mutable
# ---------------------------------------------------------------------------


async def _seed_schedule_at_status(
    db_session, user, *, status: str, export=None
) -> ScheduledReel:
    if export is None:
        await _connect_ig_for_publish(user, db_session)
        export = await _seed_export(db_session, user)
    row = ScheduledReel(
        user_id=user.id,
        user_export_id=export.id,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        timezone="UTC",
        status=status,
        share_to_feed=True,
        attempt_count=0,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_cancel_blocks_processing_to_prevent_double_publish(
    authed_client, db_session, authed_user
):
    """Once the worker has flipped a row to 'processing' it owns it. The
    router refuses to mutate state so two callers can't both observe
    'queued' and trigger a parallel publish."""
    row = await _seed_schedule_at_status(db_session, authed_user, status="processing")
    r = await authed_client.delete(f"/api/scheduled-reels/{row.id}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "not_cancellable"


async def test_cancel_blocks_published(authed_client, db_session, authed_user):
    row = await _seed_schedule_at_status(db_session, authed_user, status="published")
    r = await authed_client.delete(f"/api/scheduled-reels/{row.id}")
    assert r.status_code == 409


async def test_patch_blocks_non_queued_status(authed_client, db_session, authed_user):
    """Editing the schedule of a row the worker is processing would race
    the Graph API call — router refuses."""
    row = await _seed_schedule_at_status(db_session, authed_user, status="processing")
    r = await authed_client.patch(
        f"/api/scheduled-reels/{row.id}",
        json={"caption": "should not apply"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "not_editable"


async def test_cancel_allowed_for_queued(authed_client, db_session, authed_user):
    row = await _seed_schedule_at_status(db_session, authed_user, status="queued")
    r = await authed_client.delete(f"/api/scheduled-reels/{row.id}")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Retry semantics
# ---------------------------------------------------------------------------


async def test_retry_failed_row_returns_to_queued(
    authed_client, db_session, authed_user
):
    """Retry resets attempt_count + error + container id, kicks
    scheduled_at forward, status back to 'queued'."""
    row = await _seed_schedule_at_status(db_session, authed_user, status="failed")
    row.attempt_count = 3
    row.last_error = "graph api 500"
    row.ig_container_id = "stale-container-id"
    await db_session.flush()

    r = await authed_client.post(f"/api/scheduled-reels/{row.id}/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["attempt_count"] == 0
    assert body["last_error"] is None
    assert body["ig_container_id"] is None


async def test_retry_rejects_non_failed_status(authed_client, db_session, authed_user):
    for state in ("queued", "processing", "published", "cancelled"):
        row = await _seed_schedule_at_status(db_session, authed_user, status=state)
        r = await authed_client.post(f"/api/scheduled-reels/{row.id}/retry")
        assert r.status_code == 409, f"retry on {state} should 409, got {r.status_code}"
        assert r.json()["detail"]["code"] == "not_retryable"


# ---------------------------------------------------------------------------
# Status transitions surface — list endpoint counts
# ---------------------------------------------------------------------------


async def test_list_returns_counts_per_status(authed_client, db_session, authed_user):
    """The counts dict is the UI's source of truth for status badges —
    it must reflect every row regardless of any filter applied to the
    items list."""
    await _connect_ig_for_publish(authed_user, db_session)
    export = await _seed_export(db_session, authed_user)
    # Two queued, one failed, one cancelled.
    for status_val in ("queued", "queued", "failed", "cancelled"):
        await _seed_schedule_at_status(
            db_session, authed_user, status=status_val, export=export
        )

    # Filter the list to queued only — counts should still reflect ALL.
    r = await authed_client.get("/api/scheduled-reels?status=queued")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2  # filter applied
    assert body["counts"] == {
        "queued": 2,
        "processing": 0,
        "published": 0,
        "failed": 1,
        "cancelled": 1,
    }


# ---------------------------------------------------------------------------
# Cross-tenant ownership
# ---------------------------------------------------------------------------


async def test_cross_tenant_cannot_see(client, authed_user, other_authed_user, db_session):
    await _connect_ig_for_publish(other_authed_user, db_session)
    export = await _seed_export(db_session, other_authed_user)
    row = ScheduledReel(
        user_id=other_authed_user.id,
        user_export_id=export.id,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        timezone="UTC",
        status="queued",
        share_to_feed=True,
    )
    db_session.add(row)
    await db_session.flush()

    tok = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", tok)

    r = await client.get(f"/api/scheduled-reels/{row.id}")
    assert r.status_code == 404

    r = await client.delete(f"/api/scheduled-reels/{row.id}")
    assert r.status_code == 404

    r = await client.post(f"/api/scheduled-reels/{row.id}/retry")
    assert r.status_code == 404


async def test_unauthenticated_endpoints_401(client):
    """Sanity: the standard endpoints don't leak when no cookie is set."""
    fake = uuid4()
    for method, path in [
        ("get", "/api/scheduled-reels"),
        ("get", f"/api/scheduled-reels/{fake}"),
        ("post", "/api/scheduled-reels"),
        ("patch", f"/api/scheduled-reels/{fake}"),
        ("delete", f"/api/scheduled-reels/{fake}"),
        ("post", f"/api/scheduled-reels/{fake}/retry"),
        ("get", f"/api/scheduled-reels/{fake}/insights"),
    ]:
        if method == "post" and not path.endswith("retry"):
            r = await client.post(path, json={})
        elif method == "patch":
            r = await client.patch(path, json={})
        else:
            r = await getattr(client, method)(path)
        assert r.status_code == 401, f"{method.upper()} {path} -> {r.status_code}"
