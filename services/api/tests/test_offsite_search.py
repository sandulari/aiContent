"""Offsite (TikTok) search — projection + query builder + HTTP behaviour."""
from __future__ import annotations

import httpx
import pytest

import services.offsite_search as ot
from services.offsite_search import (
    TikTokErrorKind,
    TikTokSearchError,
    _project_tiktok_item,
    build_query_from_caption,
    search_similar_tiktok,
)


# ---------------------------------------------------------------------------
# build_query_from_caption
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_hashtags_win_over_words(self):
        q = build_query_from_caption(
            "Check out my #explore #travel post in Lisbon", fallback="zzz"
        )
        assert q == "explore travel"

    def test_caps_at_three_hashtags(self):
        q = build_query_from_caption("#a #b #c #d #e", fallback="")
        assert q.split() == ["a", "b", "c"]

    def test_word_fallback_when_no_hashtags(self):
        q = build_query_from_caption(
            "Sunset over the bay was incredible", fallback="zz"
        )
        assert q == "Sunset over the bay was"

    def test_skips_mentions_and_short_tokens(self):
        q = build_query_from_caption("@friend a b ok view here please", fallback="zz")
        # `a` and `b` are 1-char tokens — skipped per the length filter.
        assert q == "ok view here please"

    def test_falls_back_when_caption_empty(self):
        assert build_query_from_caption("", fallback="ig_code_abc") == "ig_code_abc"

    def test_falls_back_when_caption_only_punctuation(self):
        # Only one >1-char word ("...") which fails the alnum filter.
        assert build_query_from_caption(",,, !! ?", fallback="zzz") == ",,, !!"


# ---------------------------------------------------------------------------
# _project_tiktok_item — provider shape variants
# ---------------------------------------------------------------------------


class TestProjectTikTokItem:
    def test_aweme_id_with_share_url_and_author_unique_id(self):
        out = _project_tiktok_item({
            "aweme_id": "7123",
            "share_url": "https://www.tiktok.com/@charli/video/7123",
            "author": {"unique_id": "charli"},
            "play_count": 9_000_000,
            "digg_count": 500_000,
            "comment_count": 1234,
            "desc": "epic dance",
            "video": {"duration": 15},
            "cover": {"url_list": ["https://cdn/x.jpg"]},
            "create_time": 1715000000,
        })
        assert out["tiktok_id"] == "7123"
        assert out["source_handle"] == "charli"
        assert out["permalink"] == "https://www.tiktok.com/@charli/video/7123"
        assert out["view_count"] == 9_000_000
        assert out["like_count"] == 500_000
        assert out["comment_count"] == 1234
        assert out["thumbnail_url"] == "https://cdn/x.jpg"
        assert out["duration_seconds"] == 15
        assert out["taken_at_unix"] == 1715000000

    def test_alt_keys_id_username_like_count(self):
        out = _project_tiktok_item({
            "id": "abc",
            "author": {"username": "User"},
            "stats": {"play_count": 100, "like_count": 10, "comment_count": 1},
            "title": "headline",
        })
        assert out["tiktok_id"] == "abc"
        assert out["source_handle"] == "user"  # lowercase
        assert out["view_count"] == 100
        assert out["like_count"] == 10
        assert out["caption"] == "headline"

    def test_permalink_falls_back_to_handle_video_format(self):
        out = _project_tiktok_item({
            "video_id": "999",
            "author": {"unique_id": "nasa"},
        })
        assert out["permalink"] == "https://www.tiktok.com/@nasa/video/999"

    def test_returns_none_without_id(self):
        assert _project_tiktok_item({"desc": "no id here"}) is None

    def test_returns_none_for_non_dict(self):
        assert _project_tiktok_item("garbage") is None

    def test_handle_strips_at_and_lowercases(self):
        out = _project_tiktok_item({
            "id": "1",
            "author": {"unique_id": "@MixedCase"},
        })
        assert out["source_handle"] == "mixedcase"


# ---------------------------------------------------------------------------
# search_similar_tiktok — HTTP-level via httpx.MockTransport
# ---------------------------------------------------------------------------


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _stub_rapidapi_key(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_TIKTOK_KEY", "test-key")


def _ok_response_with_videos(videos):
    return httpx.Response(200, json={"data": {"videos": videos}})


class TestSearchSimilarTikTok:
    async def test_happy_path_returns_projections(self):
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["host"] = request.url.host
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            return _ok_response_with_videos([
                {
                    "aweme_id": "7000",
                    "author": {"unique_id": "tiktoker"},
                    "share_url": "https://tiktok/x",
                    "play_count": 1234,
                    "digg_count": 100,
                    "comment_count": 5,
                }
            ])

        items = await search_similar_tiktok(
            "dance routine", max_results=5, transport=_mock_transport(handler)
        )
        assert len(items) == 1
        assert items[0]["tiktok_id"] == "7000"
        assert items[0]["source_handle"] == "tiktoker"
        # Source isolation: request goes to TikTok host, NOT IG.
        assert "tiktok" in captured["host"]
        assert "instagram" not in captured["host"]
        # Query was forwarded as a search param.
        assert captured["query"]["keywords"] == "dance routine"

    async def test_passes_max_results_as_count(self):
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = dict(request.url.params)
            return _ok_response_with_videos([])

        await search_similar_tiktok(
            "x", max_results=7, transport=_mock_transport(handler)
        )
        assert captured["query"]["count"] == "7"

    async def test_429_raises_rate_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.RATE_LIMIT
        assert exc.value.status_code == 429

    @pytest.mark.parametrize("status_code", [500, 502, 503, 418, 404])
    async def test_non_2xx_raises_upstream(self, status_code):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code)

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.UPSTREAM_ERROR

    async def test_timeout_raises_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated")

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.TIMEOUT

    async def test_malformed_json_raises_malformed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not-json")

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.MALFORMED

    async def test_missing_items_list_raises_malformed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": "not-a-list-or-dict"})

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.MALFORMED

    async def test_missing_rapidapi_key_raises_not_configured(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_TIKTOK_KEY", raising=False)
        monkeypatch.delenv("RAPIDAPI_KEY", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("should not call HTTP without a key")

        with pytest.raises(TikTokSearchError) as exc:
            await search_similar_tiktok("x", transport=_mock_transport(handler))
        assert exc.value.kind is TikTokErrorKind.NOT_CONFIGURED

    async def test_drops_unparseable_items_keeps_rest(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_response_with_videos([
                {"no_id": True},  # dropped
                {"aweme_id": "1", "author": {"unique_id": "a"}},  # kept
                "garbage",  # dropped (not a dict)
                {"aweme_id": "2", "author": {"unique_id": "b"}},  # kept
            ])

        items = await search_similar_tiktok(
            "x", transport=_mock_transport(handler)
        )
        assert [it["tiktok_id"] for it in items] == ["1", "2"]
