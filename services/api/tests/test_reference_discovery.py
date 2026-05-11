"""Reference discovery service — pure logic + RapidAPI client error mapping.

The HTTP-level tests use ``httpx.MockTransport`` so we exercise the actual
``fetch_handle_reels`` code path (status mapping, JSON parsing, paging
short-circuit) without making real network calls or pulling a new
``respx``-style mocking dep.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from services.reference_discovery import (
    DiscoveryItem,
    RapidAPIError,
    RapidAPIErrorKind,
    SORT_COMMENTS_DESC,
    SORT_ENGAGEMENT_DESC,
    SORT_LIKES_DESC,
    SORT_POSTED_AT_DESC,
    SORT_VIEWS_DESC,
    apply_filter,
    compute_score,
    engagement_rate,
    fetch_handle_reels,
    rank_items,
    to_discovery_item,
)


# ---------------------------------------------------------------------------
# Test helpers — DiscoveryItem factory
# ---------------------------------------------------------------------------


def _mk(
    permalink: str,
    *,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    posted_at: datetime | None = None,
    handle: str = "src",
    score: float = 0.0,
) -> DiscoveryItem:
    return DiscoveryItem(
        source_handle=handle,
        permalink=permalink,
        media_url=None,
        thumbnail=None,
        caption=None,
        views=views,
        likes=likes,
        comments=comments,
        posted_at=posted_at,
        duration_seconds=None,
        score=score,
    )


# ===========================================================================
# Pure logic — engagement / score / filter / rank
# ===========================================================================


class TestEngagementRate:
    def test_zero_views_returns_zero(self):
        assert engagement_rate(0, 100, 100) == 0.0

    def test_negative_views_returns_zero(self):
        # Defensive: a buggy upstream sending a negative shouldn't crash.
        assert engagement_rate(-1, 10, 10) == 0.0

    def test_normal(self):
        # 100 + 50 = 150 over 1000 views
        assert engagement_rate(1000, 100, 50) == pytest.approx(0.15)


class TestComputeScore:
    @pytest.mark.parametrize(
        "sort_by,views,likes,comments,posted_at,expected",
        [
            (SORT_VIEWS_DESC, 5000, 100, 50, None, 5000.0),
            (SORT_LIKES_DESC, 5000, 100, 50, None, 100.0),
            (SORT_COMMENTS_DESC, 5000, 100, 50, None, 50.0),
            (SORT_ENGAGEMENT_DESC, 1000, 100, 50, None, pytest.approx(0.15)),
            (SORT_ENGAGEMENT_DESC, 0, 100, 50, None, 0.0),
        ],
    )
    def test_known_keys(self, sort_by, views, likes, comments, posted_at, expected):
        assert compute_score(sort_by, views, likes, comments, posted_at) == expected

    def test_posted_at_uses_unix_timestamp(self):
        ts = datetime(2026, 5, 1, tzinfo=timezone.utc)
        score = compute_score(SORT_POSTED_AT_DESC, 0, 0, 0, ts)
        assert score == ts.timestamp()

    def test_posted_at_none_is_zero(self):
        assert compute_score(SORT_POSTED_AT_DESC, 100, 0, 0, None) == 0.0

    def test_unknown_sort_falls_back_to_views(self):
        assert compute_score("garbage_key", 5000, 0, 0, None) == 5000.0


class TestApplyFilter:
    def test_min_views_excludes_below_threshold(self):
        items = [_mk("a", views=100), _mk("b", views=999), _mk("c", views=1000)]
        kept = apply_filter(
            items,
            min_views=1000,
            min_likes=0,
            min_comments=0,
            min_engagement_rate=0.0,
            max_age_days=365,
        )
        assert {i.permalink for i in kept} == {"c"}

    def test_min_engagement_rate_strict(self):
        # 100/2000 = 0.05 — below 0.10 threshold
        low = _mk("low", views=2000, likes=80, comments=20)
        # 200/1000 = 0.20 — above
        high = _mk("high", views=1000, likes=180, comments=20)
        kept = apply_filter(
            [low, high],
            min_views=0,
            min_likes=0,
            min_comments=0,
            min_engagement_rate=0.10,
            max_age_days=365,
        )
        assert [i.permalink for i in kept] == ["high"]

    def test_max_age_in_seconds_not_just_days(self):
        """An item posted 60 days + 1 hour ago should fail max_age_days=60."""
        now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)
        old = _mk("old", views=10, posted_at=now - timedelta(days=60, hours=1))
        fresh = _mk("fresh", views=10, posted_at=now - timedelta(days=59))
        kept = apply_filter(
            [old, fresh],
            min_views=0,
            min_likes=0,
            min_comments=0,
            min_engagement_rate=0.0,
            max_age_days=60,
            now=now,
        )
        assert {i.permalink for i in kept} == {"fresh"}

    def test_unknown_posted_at_passes_age_check(self):
        """Items with no posted_at should pass — refresh will populate later."""
        item = _mk("a", views=10, posted_at=None)
        kept = apply_filter(
            [item],
            min_views=0,
            min_likes=0,
            min_comments=0,
            min_engagement_rate=0.0,
            max_age_days=1,
        )
        assert len(kept) == 1

    def test_all_thresholds_must_pass(self):
        items = [_mk("a", views=10_000, likes=0, comments=0)]
        kept = apply_filter(
            items,
            min_views=0,
            min_likes=1,  # 0 likes -> fails
            min_comments=0,
            min_engagement_rate=0.0,
            max_age_days=365,
        )
        assert kept == []

    def test_naive_posted_at_treated_as_utc(self):
        """Legacy rows may have naive datetimes; don't crash on the
        aware-vs-naive comparison."""
        now = datetime(2026, 5, 12, tzinfo=timezone.utc)
        naive_old = (now - timedelta(days=10)).replace(tzinfo=None)
        item = _mk("a", views=10, posted_at=naive_old)
        kept = apply_filter(
            [item],
            min_views=0,
            min_likes=0,
            min_comments=0,
            min_engagement_rate=0.0,
            max_age_days=30,
            now=now,
        )
        assert len(kept) == 1


class TestRankItems:
    def test_views_desc_sorts_high_to_low(self):
        a = _mk("a", views=100)
        b = _mk("b", views=300)
        c = _mk("c", views=200)
        out = rank_items([a, b, c], SORT_VIEWS_DESC)
        assert [i.permalink for i in out] == ["b", "c", "a"]

    def test_likes_desc(self):
        a = _mk("a", likes=10)
        b = _mk("b", likes=30)
        out = rank_items([a, b], SORT_LIKES_DESC)
        assert out[0].permalink == "b"

    def test_engagement_desc(self):
        # 0.10 vs 0.20 — higher should come first
        low = _mk("low", views=1000, likes=100, comments=0)
        high = _mk("high", views=1000, likes=180, comments=20)
        out = rank_items([low, high], SORT_ENGAGEMENT_DESC)
        assert out[0].permalink == "high"

    def test_posted_at_desc(self):
        now = datetime(2026, 5, 12, tzinfo=timezone.utc)
        older = _mk("old", posted_at=now - timedelta(days=10))
        newer = _mk("new", posted_at=now - timedelta(days=2))
        out = rank_items([older, newer], SORT_POSTED_AT_DESC)
        assert [i.permalink for i in out] == ["new", "old"]

    def test_tiebreaker_is_permalink_asc(self):
        """Two items with identical scores must always sort the same way."""
        a = _mk("z_perm", views=100)
        b = _mk("a_perm", views=100)
        out1 = rank_items([a, b], SORT_VIEWS_DESC)
        out2 = rank_items([b, a], SORT_VIEWS_DESC)
        assert [i.permalink for i in out1] == [i.permalink for i in out2]
        assert out1[0].permalink == "a_perm"  # alphabetically first

    def test_empty_input(self):
        assert rank_items([], SORT_VIEWS_DESC) == []


# ===========================================================================
# Mapper: to_discovery_item
# ===========================================================================


class TestToDiscoveryItem:
    def test_rapidapi_projection_dict(self):
        row = {
            "ig_code": "Cabc",
            "permalink": "https://www.instagram.com/reel/Cabc/",
            "thumbnail_url": "https://cdn/x.jpg",
            "caption": "test caption",
            "view_count": 5000,
            "like_count": 200,
            "comment_count": 10,
            "duration_seconds": 30.5,
            "taken_at_unix": 1715000000,
        }
        item = to_discovery_item("natgeo", row, sort_by=SORT_VIEWS_DESC)
        assert item.source_handle == "natgeo"
        assert item.permalink == "https://www.instagram.com/reel/Cabc/"
        assert item.thumbnail == "https://cdn/x.jpg"
        assert item.views == 5000
        assert item.likes == 200
        assert item.comments == 10
        assert item.duration_seconds == 30.5
        assert item.score == 5000.0
        assert item.posted_at == datetime.fromtimestamp(
            1715000000, tz=timezone.utc
        )

    def test_orm_like_object(self):
        row = SimpleNamespace(
            ig_code="Cabc",
            permalink="https://www.instagram.com/reel/Cabc/",
            thumbnail_url=None,
            caption=None,
            view_count=100,
            like_count=10,
            comment_count=2,
            duration_seconds=None,
            posted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            media_url=None,
        )
        item = to_discovery_item("nasa", row, sort_by=SORT_ENGAGEMENT_DESC)
        assert item.source_handle == "nasa"
        assert item.views == 100
        # (10 + 2) / 100 = 0.12
        assert item.score == pytest.approx(0.12)

    def test_handles_missing_optionals(self):
        # Bare minimum dict — nothing optional set.
        item = to_discovery_item("foo", {"permalink": "x"})
        assert item.views == 0
        assert item.likes == 0
        assert item.comments == 0
        assert item.posted_at is None
        assert item.caption is None
        assert item.thumbnail is None


# ===========================================================================
# fetch_handle_reels — HTTP-level via httpx.MockTransport
# ===========================================================================


def _mock_transport(handler):
    """Build an httpx.MockTransport from a synchronous handler. Each call
    receives the request and returns an httpx.Response."""
    return httpx.MockTransport(handler)


def _reels_payload(items: list[dict]) -> dict:
    return {"data": {"items": items, "paging_info": {"max_id": ""}}}


@pytest.fixture(autouse=True)
def _stub_rapidapi_key(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")


class TestFetchHandleReels:
    async def test_happy_path_returns_projected_dicts(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "42", "username": "natgeo"})
            if "/reels" in request.url.path:
                return httpx.Response(
                    200,
                    json=_reels_payload([
                        {
                            "media": {
                                "pk": "media-1",
                                "code": "Cabc",
                                "play_count": 5000,
                                "like_count": 200,
                                "comment_count": 10,
                                "video_duration": 30.0,
                                "taken_at": 1715000000,
                                "caption": {"text": "hello world"},
                                "image_versions2": {
                                    "candidates": [{"url": "https://cdn/x.jpg"}]
                                },
                            }
                        }
                    ]),
                )
            return httpx.Response(404)

        items = await fetch_handle_reels("natgeo", transport=_mock_transport(handler))
        assert len(items) == 1
        it = items[0]
        assert it["ig_code"] == "Cabc"
        assert it["permalink"] == "https://www.instagram.com/reel/Cabc/"
        assert it["thumbnail_url"] == "https://cdn/x.jpg"
        assert it["view_count"] == 5000
        assert it["caption"] == "hello world"
        assert it["taken_at_unix"] == 1715000000

    async def test_drops_items_without_shortcode(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            return httpx.Response(
                200, json=_reels_payload([{"media": {"code": ""}}])
            )

        items = await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert items == []

    @pytest.mark.parametrize(
        "status,expected_kind",
        [
            (404, RapidAPIErrorKind.NOT_FOUND),
            (429, RapidAPIErrorKind.RATE_LIMIT),
            (500, RapidAPIErrorKind.UPSTREAM_ERROR),
            (502, RapidAPIErrorKind.UPSTREAM_ERROR),
            (503, RapidAPIErrorKind.UPSTREAM_ERROR),
            (418, RapidAPIErrorKind.UPSTREAM_ERROR),
        ],
    )
    async def test_profile_status_mapping(self, status, expected_kind):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status)

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is expected_kind
        assert exc.value.status_code == status

    async def test_profile_timeout_maps_to_timeout_kind(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated timeout")

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is RapidAPIErrorKind.TIMEOUT

    async def test_profile_malformed_body_maps_to_malformed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not-json-at-all")

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is RapidAPIErrorKind.MALFORMED

    async def test_profile_missing_user_id_maps_to_malformed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"username": "x"})  # no pk/id

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is RapidAPIErrorKind.MALFORMED

    async def test_reels_429_propagates(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            return httpx.Response(429)

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is RapidAPIErrorKind.RATE_LIMIT

    async def test_reels_404_returns_empty_not_error(self):
        """A handle with no reels at all should yield [] without raising."""
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            return httpx.Response(404)

        items = await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert items == []

    async def test_missing_rapidapi_key_raises_upstream(self, monkeypatch):
        monkeypatch.setenv("RAPIDAPI_KEY", "")
        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x")
        assert exc.value.kind is RapidAPIErrorKind.UPSTREAM_ERROR

    async def test_paginates_until_no_max_id(self):
        call_count = {"reels": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            call_count["reels"] += 1
            # Page 1: one item, next page token; Page 2: one item, no token.
            if call_count["reels"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "items": [{"media": {"pk": "m1", "code": "Caa"}}],
                            "paging_info": {"max_id": "TOKEN"},
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [{"media": {"pk": "m2", "code": "Cbb"}}],
                        "paging_info": {"max_id": ""},
                    }
                },
            )

        items = await fetch_handle_reels(
            "x", max_pages=5, transport=_mock_transport(handler)
        )
        assert {it["ig_code"] for it in items} == {"Caa", "Cbb"}
        assert call_count["reels"] == 2  # Stopped after empty max_id.

    async def test_paginates_stops_at_max_pages(self):
        """Even if the upstream keeps returning max_id, we respect max_pages."""
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [{"media": {"pk": "m", "code": "C" + request.url.params.get("max_id", "0")}}],
                        "paging_info": {"max_id": "next-page-forever"},
                    }
                },
            )

        items = await fetch_handle_reels(
            "x", max_pages=2, transport=_mock_transport(handler)
        )
        assert len(items) == 2  # exactly max_pages

    async def test_reels_missing_data_blob_maps_to_malformed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/profile" in request.url.path:
                return httpx.Response(200, json={"pk": "1"})
            return httpx.Response(200, json={"items": []})  # missing 'data' wrapper

        with pytest.raises(RapidAPIError) as exc:
            await fetch_handle_reels("x", transport=_mock_transport(handler))
        assert exc.value.kind is RapidAPIErrorKind.MALFORMED
