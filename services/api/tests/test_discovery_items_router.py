"""Discovery items endpoint — listing + refresh + filter-preview wiring."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy import select

import services.rate_limiter as rate_limiter_mod
from models.discovery_filter import DiscoveryFilter
from models.download import Download
from models.reference_page import ReferencePage
from models.reference_reel import ReferenceReel
from routers import discovery_items as items_mod


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis():
    """Swap the rate limiter's client for an in-memory fakeredis for the
    duration of one test, then restore."""
    client = FakeAsyncRedis(decode_responses=True)
    rate_limiter_mod._test_client = client
    try:
        yield client
    finally:
        rate_limiter_mod._test_client = None
        await client.aclose()


@pytest_asyncio.fixture
async def disable_background(monkeypatch):
    """Replace the BackgroundTask target so POST /refresh's queued work
    becomes a no-op. Endpoint tests focus on the response shape +
    rate-limit; do_refresh logic is exercised directly elsewhere."""
    async def _noop(*args, **kwargs):
        return {"refreshed": 0, "failed_handles": []}
    monkeypatch.setattr(items_mod, "refresh_pages_background", _noop)


def _mk_reel(page_id, *, mid: str, code: str, views: int = 1000,
             likes: int = 10, comments: int = 1, permalink: str | None = None):
    return ReferenceReel(
        reference_page_id=page_id,
        ig_media_id=mid,
        ig_code=code,
        permalink=permalink or f"https://www.instagram.com/reel/{code}/",
        view_count=views,
        like_count=likes,
        comment_count=comments,
    )


# ===========================================================================
# GET /api/discovery/items
# ===========================================================================


async def test_items_empty_cache_returns_has_cache_false(authed_client):
    r = await authed_client.get("/api/discovery/items")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_cache"] is False
    # Defaults are returned even with no saved filter.
    assert body["filter"]["min_views"] == 1000
    assert body["filter"]["sort_by"] == "views_desc"


async def test_items_returns_only_this_users_reels(
    authed_client, db_session, authed_user, other_authed_user
):
    page_a = ReferencePage(user_id=authed_user.id, ig_handle="natgeo")
    page_b = ReferencePage(user_id=other_authed_user.id, ig_handle="nasa")
    db_session.add_all([page_a, page_b])
    await db_session.flush()

    db_session.add_all([
        _mk_reel(page_a.id, mid="m1", code="Caa", views=5000),
        _mk_reel(page_b.id, mid="m2", code="Cbb", views=5000),  # other user's
    ])
    await db_session.flush()

    r = await authed_client.get("/api/discovery/items")
    body = r.json()
    assert body["has_cache"] is True
    assert body["total"] == 1
    assert body["items"][0]["source_handle"] == "natgeo"


async def test_items_applies_saved_filter(
    authed_client, db_session, authed_user
):
    # Save a filter that requires min_views=2000.
    db_session.add(DiscoveryFilter(
        user_id=authed_user.id,
        min_views=2000,
        min_likes=0,
        min_comments=0,
        min_engagement_rate=0.0,
        max_age_days=365,
        sort_by="views_desc",
    ))
    page = ReferencePage(user_id=authed_user.id, ig_handle="src")
    db_session.add(page)
    await db_session.flush()
    db_session.add_all([
        _mk_reel(page.id, mid="low", code="Clow", views=1000),
        _mk_reel(page.id, mid="high", code="Chigh", views=5000),
    ])
    await db_session.flush()

    r = await authed_client.get("/api/discovery/items")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["views"] == 5000


async def test_items_ranks_by_sort_by(authed_client, db_session, authed_user):
    db_session.add(DiscoveryFilter(
        user_id=authed_user.id, min_views=0, min_likes=0, min_comments=0,
        min_engagement_rate=0.0, max_age_days=365, sort_by="likes_desc",
    ))
    page = ReferencePage(user_id=authed_user.id, ig_handle="src")
    db_session.add(page)
    await db_session.flush()
    db_session.add_all([
        _mk_reel(page.id, mid="a", code="Ca", views=5000, likes=10),
        _mk_reel(page.id, mid="b", code="Cb", views=1000, likes=500),
    ])
    await db_session.flush()

    r = await authed_client.get("/api/discovery/items")
    body = r.json()
    # likes_desc -> 500 first, even though it has fewer views.
    assert body["items"][0]["likes"] == 500


async def test_items_pagination(authed_client, db_session, authed_user):
    page = ReferencePage(user_id=authed_user.id, ig_handle="src")
    db_session.add(page)
    await db_session.flush()
    for i in range(5):
        db_session.add(_mk_reel(
            page.id, mid=f"m{i}", code=f"C{i}", views=1000 + i * 100,
        ))
    await db_session.flush()

    page1 = await authed_client.get("/api/discovery/items?limit=2&offset=0")
    page2 = await authed_client.get("/api/discovery/items?limit=2&offset=2")
    assert page1.json()["total"] == 5
    assert len(page1.json()["items"]) == 2
    # Page 2 returns different items than page 1 (no overlap).
    p1_ids = {it["permalink"] for it in page1.json()["items"]}
    p2_ids = {it["permalink"] for it in page2.json()["items"]}
    assert p1_ids.isdisjoint(p2_ids)


# ===========================================================================
# POST /api/discovery/refresh (endpoint surface only — do_refresh tested below)
# ===========================================================================


async def test_refresh_with_no_pages_returns_queued_false(
    authed_client, fake_redis, disable_background
):
    r = await authed_client.post("/api/discovery/refresh")
    assert r.status_code == 202
    body = r.json()
    assert body["queued"] is False
    assert body["page_count"] == 0


async def test_refresh_queues_for_each_reference_page(
    authed_client, db_session, authed_user, fake_redis, disable_background
):
    db_session.add_all([
        ReferencePage(user_id=authed_user.id, ig_handle="natgeo"),
        ReferencePage(user_id=authed_user.id, ig_handle="nasa"),
    ])
    await db_session.flush()

    r = await authed_client.post("/api/discovery/refresh")
    assert r.status_code == 202
    body = r.json()
    assert body["queued"] is True
    assert body["page_count"] == 2


async def test_refresh_per_user_rate_limit_returns_429(
    authed_client, db_session, authed_user, fake_redis, disable_background
):
    # One ref page so we don't bail early on "no pages".
    db_session.add(ReferencePage(user_id=authed_user.id, ig_handle="x"))
    await db_session.flush()

    # 5 successful refreshes (= _REFRESH_PER_USER cap), then 429.
    for i in range(5):
        r = await authed_client.post("/api/discovery/refresh")
        assert r.status_code == 202, f"call {i} got {r.status_code}: {r.text}"

    r = await authed_client.post("/api/discovery/refresh")
    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["code"] == "rate_limit"
    assert body["detail"]["retry_after"] > 0


# ===========================================================================
# do_refresh — inner refresh function, no background, no separate session
# ===========================================================================


async def test_do_refresh_upserts_reels(
    db_session, authed_user, monkeypatch
):
    page = ReferencePage(user_id=authed_user.id, ig_handle="natgeo")
    db_session.add(page)
    await db_session.flush()

    async def fake_fetch(handle, **kwargs):
        return [{
            "ig_media_id": "m1",
            "ig_code": "Caa",
            "permalink": "https://www.instagram.com/reel/Caa/",
            "thumbnail_url": "https://cdn/t.jpg",
            "caption": "cap",
            "view_count": 5000,
            "like_count": 100,
            "comment_count": 10,
            "duration_seconds": 30.0,
            "taken_at_unix": 1715000000,
        }]
    monkeypatch.setattr(items_mod, "fetch_handle_reels", fake_fetch)

    result = await items_mod.do_refresh([(page.id, "natgeo")], db_session)
    assert result["refreshed"] == 1
    assert result["failed_handles"] == []

    reels = (await db_session.execute(select(ReferenceReel))).scalars().all()
    assert len(reels) == 1
    assert reels[0].ig_media_id == "m1"
    assert reels[0].view_count == 5000


async def test_do_refresh_is_upsert(db_session, authed_user, monkeypatch):
    """Second refresh with the same ig_media_id must UPDATE, not duplicate."""
    page = ReferencePage(user_id=authed_user.id, ig_handle="src")
    db_session.add(page)
    await db_session.flush()

    base_payload = {
        "ig_media_id": "m1",
        "ig_code": "Caa",
        "permalink": "https://www.instagram.com/reel/Caa/",
        "thumbnail_url": "https://cdn/t.jpg",
        "caption": "old caption",
        "view_count": 1000,
        "like_count": 10,
        "comment_count": 1,
        "duration_seconds": 30.0,
        "taken_at_unix": 1715000000,
    }

    async def fetch_v1(handle, **kwargs):
        return [base_payload]
    monkeypatch.setattr(items_mod, "fetch_handle_reels", fetch_v1)
    await items_mod.do_refresh([(page.id, "src")], db_session)

    async def fetch_v2(handle, **kwargs):
        return [{**base_payload, "view_count": 9999, "caption": "new"}]
    monkeypatch.setattr(items_mod, "fetch_handle_reels", fetch_v2)
    await items_mod.do_refresh([(page.id, "src")], db_session)

    reels = (await db_session.execute(select(ReferenceReel))).scalars().all()
    assert len(reels) == 1  # No duplicate.
    assert reels[0].view_count == 9999
    assert reels[0].caption == "new"


async def test_do_refresh_failure_on_one_handle_doesnt_block_others(
    db_session, authed_user, monkeypatch
):
    from services.reference_discovery import RapidAPIError, RapidAPIErrorKind

    page_good = ReferencePage(user_id=authed_user.id, ig_handle="natgeo")
    page_bad = ReferencePage(user_id=authed_user.id, ig_handle="rate-limited")
    db_session.add_all([page_good, page_bad])
    await db_session.flush()

    async def fake_fetch(handle, **kwargs):
        if handle == "rate-limited":
            raise RapidAPIError(RapidAPIErrorKind.RATE_LIMIT, "429", 429)
        return [{
            "ig_media_id": "m1", "ig_code": "Caa",
            "permalink": "https://x", "view_count": 5000, "like_count": 100,
            "comment_count": 10, "duration_seconds": None, "taken_at_unix": None,
            "thumbnail_url": None, "caption": None,
        }]
    monkeypatch.setattr(items_mod, "fetch_handle_reels", fake_fetch)

    result = await items_mod.do_refresh(
        [(page_good.id, "natgeo"), (page_bad.id, "rate-limited")],
        db_session,
    )
    assert result["refreshed"] == 1
    assert result["failed_handles"] == ["rate-limited"]


# ===========================================================================
# /api/discovery-filter/preview is now wired to the real cache (Task 1.3a)
# ===========================================================================


async def test_filter_preview_counts_matching_cached_reels(
    authed_client, db_session, authed_user
):
    page = ReferencePage(user_id=authed_user.id, ig_handle="src")
    db_session.add(page)
    await db_session.flush()
    db_session.add_all([
        _mk_reel(page.id, mid="a", code="Ca", views=500),
        _mk_reel(page.id, mid="b", code="Cb", views=5000),
        _mk_reel(page.id, mid="c", code="Cc", views=10_000),
    ])
    await db_session.flush()

    # min_views=2000 should match 2 of 3
    r = await authed_client.post(
        "/api/discovery-filter/preview",
        json={"min_views": 2000},
    )
    body = r.json()
    assert body["has_cache"] is True
    assert body["count"] == 2


async def test_filter_preview_empty_cache_keeps_has_cache_false(authed_client):
    r = await authed_client.post(
        "/api/discovery-filter/preview", json={"min_views": 0}
    )
    body = r.json()
    assert body["has_cache"] is False
    assert body["count"] == 0


# ===========================================================================
# POST /api/discovery/items/{id}/download — idempotency + ownership
# GET  /api/discovery/downloads/{id} — status polling
# ===========================================================================


@pytest_asyncio.fixture
async def _stub_download_background(monkeypatch):
    """Replace the BackgroundTask target so POST /download doesn't try to
    hit RapidAPI in tests. Endpoint behavior is what matters here;
    perform_download itself is exercised in test_discovery_download.py."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(items_mod, "_perform_download_background", _noop)


async def _seed_owned_reel(db_session, user, handle="natgeo"):
    page = ReferencePage(user_id=user.id, ig_handle=handle)
    db_session.add(page)
    await db_session.flush()
    reel = _mk_reel(page.id, mid="m1", code="Caa")
    db_session.add(reel)
    await db_session.flush()
    return reel


async def test_download_post_creates_row_202(
    authed_client, db_session, authed_user, _stub_download_background
):
    reel = await _seed_owned_reel(db_session, authed_user)

    r = await authed_client.post(f"/api/discovery/items/{reel.id}/download")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["reference_reel_id"] == str(reel.id)
    assert body["minio_key"] is None


async def test_download_post_is_idempotent_returns_existing(
    authed_client, db_session, authed_user, _stub_download_background
):
    reel = await _seed_owned_reel(db_session, authed_user)

    r1 = await authed_client.post(f"/api/discovery/items/{reel.id}/download")
    assert r1.status_code == 202
    first_id = r1.json()["id"]

    r2 = await authed_client.post(f"/api/discovery/items/{reel.id}/download")
    # Second call: same row, 200 (not 202) to signal "already exists".
    assert r2.status_code == 200
    assert r2.json()["id"] == first_id

    # Only one row in DB.
    from sqlalchemy import select as sa_select, func
    count = (
        await db_session.execute(
            sa_select(func.count()).select_from(Download).where(
                Download.user_id == authed_user.id,
                Download.reference_reel_id == reel.id,
            )
        )
    ).scalar()
    assert count == 1


async def test_download_post_404_when_reel_does_not_exist(
    authed_client, _stub_download_background
):
    from uuid import uuid4
    r = await authed_client.post(f"/api/discovery/items/{uuid4()}/download")
    assert r.status_code == 404


async def test_download_post_404_when_reel_belongs_to_another_user(
    authed_client, db_session, authed_user, other_authed_user, _stub_download_background
):
    # Reel owned by other_authed_user.
    page = ReferencePage(user_id=other_authed_user.id, ig_handle="nasa")
    db_session.add(page)
    await db_session.flush()
    reel = _mk_reel(page.id, mid="m1", code="Caa")
    db_session.add(reel)
    await db_session.flush()

    r = await authed_client.post(f"/api/discovery/items/{reel.id}/download")
    assert r.status_code == 404


async def test_get_download_status(
    authed_client, db_session, authed_user, _stub_download_background
):
    reel = await _seed_owned_reel(db_session, authed_user)
    create = await authed_client.post(f"/api/discovery/items/{reel.id}/download")
    download_id = create.json()["id"]

    r = await authed_client.get(f"/api/discovery/downloads/{download_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == download_id
    assert body["status"] == "queued"


async def test_get_download_404_when_not_owner(
    authed_client, db_session, authed_user, other_authed_user
):
    page = ReferencePage(user_id=other_authed_user.id, ig_handle="nasa")
    db_session.add(page)
    await db_session.flush()
    reel = _mk_reel(page.id, mid="m1", code="Caa")
    db_session.add(reel)
    await db_session.flush()
    other_dl = Download(
        user_id=other_authed_user.id,
        reference_reel_id=reel.id,
        status="done",
        minio_key="discovery/x.mp4",
    )
    db_session.add(other_dl)
    await db_session.flush()

    r = await authed_client.get(f"/api/discovery/downloads/{other_dl.id}")
    assert r.status_code == 404


async def test_get_download_unauthenticated_401(client):
    from uuid import uuid4
    r = await client.get(f"/api/discovery/downloads/{uuid4()}")
    assert r.status_code == 401


# ===========================================================================
# GET /api/discovery/items/{id}/similar  (Task 1.6)
# ===========================================================================


async def _seed_reel_with_caption(db_session, user, *, caption: str, code: str = "Caa"):
    page = ReferencePage(user_id=user.id, ig_handle="natgeo")
    db_session.add(page)
    await db_session.flush()
    reel = ReferenceReel(
        reference_page_id=page.id,
        ig_media_id=f"m_{code}",
        ig_code=code,
        permalink=f"https://www.instagram.com/reel/{code}/",
        caption=caption,
        view_count=5000,
        like_count=100,
        comment_count=10,
    )
    db_session.add(reel)
    await db_session.flush()
    return reel


async def test_similar_happy_path_returns_items(
    authed_client, db_session, authed_user, fake_redis, monkeypatch
):
    reel = await _seed_reel_with_caption(
        db_session, authed_user, caption="amazing #dance #viral"
    )

    captured_query: list[str] = []

    async def fake_search(query, **kwargs):
        captured_query.append(query)
        return [
            {
                "tiktok_id": "7000",
                "source_handle": "tiktoker",
                "permalink": "https://www.tiktok.com/@tiktoker/video/7000",
                "thumbnail_url": "https://cdn/x.jpg",
                "caption": "tiktok caption",
                "view_count": 9_000_000,
                "like_count": 100_000,
                "comment_count": 500,
                "duration_seconds": 15,
                "taken_at_unix": 1715000000,
            }
        ]

    monkeypatch.setattr(items_mod, "search_similar_tiktok", fake_search)

    r = await authed_client.get(f"/api/discovery/items/{reel.id}/similar")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["query"] == "dance viral"
    assert body["source"]["handle"] == "natgeo"
    assert body["source"]["permalink"] == reel.permalink
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["source_handle"] == "tiktoker"
    assert it["permalink"].startswith("https://www.tiktok.com/")
    assert it["views"] == 9_000_000

    # Query was built from the reel's hashtags, not its ig_code.
    assert captured_query == ["dance viral"]


async def test_similar_error_fallback_returns_200_with_error(
    authed_client, db_session, authed_user, fake_redis, monkeypatch
):
    from services.offsite_search import TikTokErrorKind, TikTokSearchError

    reel = await _seed_reel_with_caption(
        db_session, authed_user, caption="post #travel"
    )

    async def fake_search(query, **kwargs):
        raise TikTokSearchError(TikTokErrorKind.RATE_LIMIT, "429", 429)

    monkeypatch.setattr(items_mod, "search_similar_tiktok", fake_search)

    r = await authed_client.get(f"/api/discovery/items/{reel.id}/similar")
    # Spec: "error fallback" — surfaces as 200 with items=[] and an
    # error flag so the UI can render an explainer rather than crash.
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["error"] == "rate_limit"


async def test_similar_404_when_reel_not_found(
    authed_client, fake_redis
):
    from uuid import uuid4
    r = await authed_client.get(f"/api/discovery/items/{uuid4()}/similar")
    assert r.status_code == 404


async def test_similar_404_when_reel_belongs_to_another_user(
    authed_client, db_session, other_authed_user, fake_redis
):
    page = ReferencePage(user_id=other_authed_user.id, ig_handle="nasa")
    db_session.add(page)
    await db_session.flush()
    reel = _mk_reel(page.id, mid="m", code="Cother")
    db_session.add(reel)
    await db_session.flush()

    r = await authed_client.get(f"/api/discovery/items/{reel.id}/similar")
    assert r.status_code == 404


async def test_similar_rate_limit_429(
    authed_client, db_session, authed_user, fake_redis, monkeypatch
):
    """Exhaust the per-user cap then expect a 429 with retry_after."""
    reel = await _seed_reel_with_caption(
        db_session, authed_user, caption="#viral"
    )

    async def fake_search(query, **kwargs):
        return []

    monkeypatch.setattr(items_mod, "search_similar_tiktok", fake_search)

    # The cap is 20 — exhaust then try one more.
    for i in range(20):
        r = await authed_client.get(f"/api/discovery/items/{reel.id}/similar")
        assert r.status_code == 200, f"call {i} got {r.status_code}: {r.text}"

    r = await authed_client.get(f"/api/discovery/items/{reel.id}/similar")
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "rate_limit"
    assert r.json()["detail"]["retry_after"] > 0


async def test_similar_unauthenticated_401(client):
    from uuid import uuid4
    r = await client.get(f"/api/discovery/items/{uuid4()}/similar")
    assert r.status_code == 401
