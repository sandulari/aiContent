"""Discovery download service — RapidAPI resolve + retry + MinIO upload.

HTTP-level interactions use ``httpx.MockTransport`` so we exercise the real
retry/parse code paths without a network. MinIO is a ``MagicMock`` with
just the three methods the uploader touches (``bucket_exists``,
``make_bucket``, ``put_object``) — no need for a real S3 mock here.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

import services.discovery_download as dl_mod
from models.download import (
    STATUS_DONE,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    Download,
)
from models.reference_page import ReferencePage
from models.reference_reel import ReferenceReel
from services.discovery_download import (
    DownloadError,
    _pick_best_media_url,
    _request_with_retries,
    perform_download,
)


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_rapidapi_key(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_VIDEO_DL_KEY", "test-key")


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Cut asyncio.sleep to a no-op so retry tests run fast."""
    async def _noop(_):
        return None
    monkeypatch.setattr(dl_mod.asyncio, "sleep", _noop)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


async def _seed_reel_and_download(db_session, user):
    page = ReferencePage(user_id=user.id, ig_handle="natgeo")
    db_session.add(page)
    await db_session.flush()
    reel = ReferenceReel(
        reference_page_id=page.id,
        ig_media_id="m1",
        ig_code="Caa",
        permalink="https://www.instagram.com/reel/Caa/",
        view_count=5000,
        like_count=100,
        comment_count=10,
    )
    db_session.add(reel)
    await db_session.flush()
    download = Download(user_id=user.id, reference_reel_id=reel.id, status="queued")
    db_session.add(download)
    await db_session.flush()
    return reel, download


# ===========================================================================
# _pick_best_media_url
# ===========================================================================


class TestPickBestMediaUrl:
    def test_prefers_hd(self):
        url = _pick_best_media_url({
            "medias": [
                {"url": "https://cdn/sd.mp4", "quality": "sd"},
                {"url": "https://cdn/hd.mp4", "quality": "hd"},
            ],
        })
        assert url == "https://cdn/hd.mp4"

    def test_prefers_1080(self):
        url = _pick_best_media_url({
            "medias": [
                {"url": "https://cdn/360.mp4", "quality": "360p"},
                {"url": "https://cdn/1080.mp4", "quality": "1080p"},
            ],
        })
        assert url == "https://cdn/1080.mp4"

    def test_skips_audio(self):
        url = _pick_best_media_url({
            "medias": [
                {"url": "https://cdn/audio.mp3", "type": "audio", "quality": "hd"},
                {"url": "https://cdn/video.mp4", "type": "video"},
            ],
        })
        assert url == "https://cdn/video.mp4"

    def test_falls_back_to_top_level_download_url(self):
        url = _pick_best_media_url({"download_url": "https://cdn/d.mp4"})
        assert url == "https://cdn/d.mp4"

    def test_returns_none_for_empty_medias(self):
        assert _pick_best_media_url({"medias": []}) is None

    def test_returns_none_for_non_dict(self):
        assert _pick_best_media_url("garbage") is None

    def test_returns_first_non_audio_when_no_quality_hint(self):
        url = _pick_best_media_url({
            "medias": [
                {"url": "https://cdn/a.mp4"},
                {"url": "https://cdn/b.mp4"},
            ],
        })
        assert url == "https://cdn/a.mp4"


# ===========================================================================
# _request_with_retries
# ===========================================================================


class TestRequestRetries:
    async def test_returns_immediately_on_2xx(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            r = await _request_with_retries(client, "GET", "https://example/")
        assert r.status_code == 200
        assert calls["n"] == 1

    async def test_retries_429_until_success(self):
        seq = [429, 429, 200]

        def handler(request):
            return httpx.Response(seq.pop(0))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            r = await _request_with_retries(
                client, "GET", "https://example/", max_retries=3
            )
        assert r.status_code == 200

    async def test_retries_5xx_until_success(self):
        seq = [503, 200]

        def handler(request):
            return httpx.Response(seq.pop(0))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            r = await _request_with_retries(client, "GET", "https://example/")
        assert r.status_code == 200

    async def test_raises_after_all_retries_exhausted(self):
        def handler(request):
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            with pytest.raises(DownloadError) as exc:
                await _request_with_retries(
                    client, "GET", "https://example/", max_retries=3
                )
        assert "HTTP 503" in str(exc.value)

    async def test_returns_4xx_without_retry(self):
        """4xx (other than 429) is permanent — don't burn retries."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            r = await _request_with_retries(client, "GET", "https://example/")
        assert r.status_code == 404
        assert calls["n"] == 1

    async def test_retries_on_network_error(self):
        seq = [
            httpx.ReadTimeout("simulated"),
            httpx.Response(200),
        ]

        def handler(request):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            r = await _request_with_retries(
                client, "GET", "https://example/", max_retries=3
            )
        assert r.status_code == 200


# ===========================================================================
# perform_download — full orchestrator
# ===========================================================================


@pytest.fixture
def fake_minio():
    """MagicMock with the three methods _upload_bytes_to_minio touches."""
    m = MagicMock()
    m.bucket_exists.return_value = False  # forces make_bucket call (test it)
    m.make_bucket.return_value = None
    m.put_object.return_value = None
    return m


def _success_transport(media_url: str = "https://cdn/video.mp4"):
    def handler(request: httpx.Request) -> httpx.Response:
        if "social-download-all-in-one" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "medias": [
                        {"url": media_url, "quality": "hd", "type": "video"}
                    ]
                },
            )
        # The binary fetch.
        return httpx.Response(200, content=b"VIDEO_BYTES_FAKE")
    return _mock_transport(handler)


async def test_happy_path_marks_done_and_uploads(
    db_session, authed_user, fake_minio
):
    _, download = await _seed_reel_and_download(db_session, authed_user)

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_success_transport()
    )

    assert result.status == STATUS_DONE
    assert result.file_size_bytes == len(b"VIDEO_BYTES_FAKE")
    assert result.minio_key is not None
    assert result.error_message is None
    # MinIO touched.
    fake_minio.bucket_exists.assert_called()
    fake_minio.make_bucket.assert_called()  # bucket didn't exist in fixture
    fake_minio.put_object.assert_called_once()


async def test_resolve_no_playable_media_marks_failed(
    db_session, authed_user, fake_minio
):
    """Provider returned 200 but the medias array has nothing usable."""
    _, download = await _seed_reel_and_download(db_session, authed_user)

    def handler(request: httpx.Request) -> httpx.Response:
        if "social-download-all-in-one" in str(request.url):
            return httpx.Response(200, json={"medias": []})
        return httpx.Response(200, content=b"never reached")

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_FAILED
    assert "no playable media" in result.error_message
    fake_minio.put_object.assert_not_called()


async def test_resolve_retries_429_then_succeeds(
    db_session, authed_user, fake_minio
):
    _, download = await _seed_reel_and_download(db_session, authed_user)
    seq = [429, 429, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        if "social-download-all-in-one" in str(request.url):
            status_code = seq.pop(0)
            if status_code == 200:
                return httpx.Response(
                    200,
                    json={"medias": [{"url": "https://cdn/v.mp4", "type": "video"}]},
                )
            return httpx.Response(status_code)
        return httpx.Response(200, content=b"BYTES")

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_DONE
    assert result.minio_key is not None


async def test_resolve_5xx_until_exhausted_marks_failed(
    db_session, authed_user, fake_minio
):
    _, download = await _seed_reel_and_download(db_session, authed_user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_FAILED
    assert "503" in result.error_message
    fake_minio.put_object.assert_not_called()


async def test_resolve_404_marks_failed_without_retry(
    db_session, authed_user, fake_minio
):
    """Permanent 4xx (other than 429) shouldn't burn retries."""
    _, download = await _seed_reel_and_download(db_session, authed_user)
    calls = {"resolve": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "social-download-all-in-one" in str(request.url):
            calls["resolve"] += 1
            return httpx.Response(404)
        return httpx.Response(200, content=b"never")

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_FAILED
    assert calls["resolve"] == 1  # No retries.
    assert "HTTP 404" in result.error_message


async def test_binary_fetch_failure_marks_failed(
    db_session, authed_user, fake_minio
):
    _, download = await _seed_reel_and_download(db_session, authed_user)

    def handler(request: httpx.Request) -> httpx.Response:
        if "social-download-all-in-one" in str(request.url):
            return httpx.Response(
                200,
                json={"medias": [{"url": "https://cdn/v.mp4", "type": "video"}]},
            )
        return httpx.Response(503)

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_FAILED
    fake_minio.put_object.assert_not_called()


async def test_missing_rapidapi_key_marks_failed_immediately(
    db_session, authed_user, fake_minio, monkeypatch
):
    monkeypatch.delenv("RAPIDAPI_VIDEO_DL_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    _, download = await _seed_reel_and_download(db_session, authed_user)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("HTTP should never be called when key is missing")

    result = await perform_download(
        download.id, db_session, minio=fake_minio, transport=_mock_transport(handler)
    )
    assert result.status == STATUS_FAILED
    assert "not configured" in result.error_message


async def test_minio_key_is_scoped_per_user_and_download(
    db_session, authed_user, fake_minio
):
    _, download = await _seed_reel_and_download(db_session, authed_user)
    await perform_download(
        download.id, db_session, minio=fake_minio, transport=_success_transport()
    )
    assert download.minio_key.startswith(f"discovery/{authed_user.id}/")
    assert download.minio_key.endswith(".mp4")
