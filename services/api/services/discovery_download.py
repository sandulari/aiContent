"""Per-reference-page reel download — RapidAPI resolve + binary fetch + MinIO put.

Owns the slow async work behind ``POST /api/discovery/items/{id}/download``.
The router creates the :class:`models.Download` row, queues this function
via FastAPI's BackgroundTasks, and returns 202 immediately. This function
mutates the row in place as it goes: ``queued`` -> ``downloading`` ->
``done`` | ``failed``.

Retry policy: transient HTTP failures (429, 5xx, network) are retried up
to 3 times with exponential backoff. 4xx (other than 429) is treated as
permanent — no point hammering a "not found".

Dependency injection: the ``transport`` arg accepts an ``httpx.MockTransport``
for tests; ``minio`` accepts any object exposing ``bucket_exists`` /
``make_bucket`` / ``put_object`` so tests can pass a ``MagicMock``.

Scaling notes (parked in FOUND-ISSUES): the full binary lives in memory
during the upload, and the sync MinIO client blocks the event loop for the
duration of the put. Both are fine for 5-30 MB IG reels; if downloads grow
past ~100 MB, stream to disk + use ``asyncio.to_thread`` for the put.
"""
from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.download import (
    STATUS_DONE,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    Download,
)
from models.reference_reel import ReferenceReel
from services.minio_helper import get_minio_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RAPIDAPI_KEY = os.getenv("RAPIDAPI_VIDEO_DL_KEY") or os.getenv("RAPIDAPI_KEY", "")
_RAPIDAPI_HOST = os.getenv(
    "RAPIDAPI_VIDEO_DL_HOST", "social-download-all-in-one.p.rapidapi.com"
)
_RAPIDAPI_PATH = os.getenv("RAPIDAPI_VIDEO_DL_PATH", "/v1/social/autolink")
_RAPIDAPI_URL = f"https://{_RAPIDAPI_HOST}{_RAPIDAPI_PATH}"

# nguyenmanhict's autolink is fast (~5s) for resolution. Binary fetch is
# allowed to take much longer since it's a real MP4 stream.
_RESOLVE_TIMEOUT = httpx.Timeout(30.0)
_FETCH_TIMEOUT = httpx.Timeout(180.0)

_MAX_RETRIES = 3
_VIDEOS_BUCKET = os.getenv("MINIO_BUCKET_VIDEOS", "videos")


class DownloadError(Exception):
    """Recoverable failure during download — caller marks status='failed'."""


# ---------------------------------------------------------------------------
# Helpers — kept module-level so tests can monkeypatch them in isolation.
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    # Read env on every call so tests can monkeypatch RAPIDAPI_VIDEO_DL_KEY.
    key = os.getenv("RAPIDAPI_VIDEO_DL_KEY") or os.getenv("RAPIDAPI_KEY") or _RAPIDAPI_KEY
    return {
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "x-rapidapi-key": key,
        "Content-Type": "application/json",
    }


def _pick_best_media_url(payload: Any) -> Optional[str]:
    """Walk the RapidAPI response shape and pick a downloadable video URL.

    Prefers HD/1080/720 quality hints; falls back to the first non-audio
    media. Returns None if nothing usable.
    """
    if not isinstance(payload, dict):
        return None

    medias = payload.get("medias")
    if not isinstance(medias, list) or not medias:
        # Some providers return ``data: {url}`` or ``download_url`` top-level.
        for top_key in ("download_url", "video_url"):
            v = payload.get(top_key)
            if isinstance(v, str) and v.startswith("http"):
                return v
        return None

    best: Optional[str] = None
    for entry in medias:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url") or entry.get("link")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        if str(entry.get("type", "")).lower() == "audio":
            continue
        quality = " ".join(
            str(entry.get(k, "")).lower() for k in ("quality", "format", "label")
        )
        if any(hint in quality for hint in ("hd", "1080", "720", "no_watermark")):
            return url
        if best is None:
            best = url
    return best


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = _MAX_RETRIES,
    **kwargs: Any,
) -> httpx.Response:
    """Retry on transient failures (429, 5xx, network). Permanent 4xx
    surfaces as the response — caller decides what's recoverable.

    Backoff is exponential: 1s, 2s, 4s. Sleep is asyncio-friendly so the
    loop stays responsive for other requests.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt == max_retries - 1:
                raise DownloadError(f"network failure after {max_retries} attempts: {exc}") from exc
            await asyncio.sleep(2**attempt)
            continue

        if resp.status_code < 500 and resp.status_code != 429:
            return resp

        # 429 or 5xx — retry
        if attempt == max_retries - 1:
            raise DownloadError(
                f"HTTP {resp.status_code} after {max_retries} attempts on {url}"
            )
        await asyncio.sleep(2**attempt)

    # Defensive — loop should have returned or raised already.
    raise DownloadError(f"retries exhausted ({last_exc})")


def _upload_bytes_to_minio(client: Any, *, bucket: str, key: str, data: bytes) -> None:
    """Idempotent: create the bucket if missing, then PUT. Sync call —
    runs inside an async context. Small uploads (typical reel is 5-30 MB)
    don't justify the complexity of streaming through asyncio.to_thread."""
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(
        bucket,
        key,
        BytesIO(data),
        length=len(data),
        content_type="video/mp4",
    )


# ---------------------------------------------------------------------------
# Orchestrator — invoked by BackgroundTasks (and the test suite)
# ---------------------------------------------------------------------------


async def perform_download(
    download_id: UUID,
    db: AsyncSession,
    *,
    minio: Any | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Download:
    """Fetch the linked reference_reel's media + upload to MinIO. Mutates
    the ``Download`` row in place and returns it. Does NOT commit — the
    caller (production wrapper or test) owns transaction lifecycle.

    On success: status=done, minio_key + file_size_bytes set.
    On failure: status=failed, error_message set (no exception bubbles).
    """
    download = (
        await db.execute(select(Download).where(Download.id == download_id))
    ).scalar_one()
    reel = (
        await db.execute(
            select(ReferenceReel).where(ReferenceReel.id == download.reference_reel_id)
        )
    ).scalar_one()

    download.status = STATUS_DOWNLOADING
    download.error_message = None
    await db.flush()

    if not _headers().get("x-rapidapi-key"):
        download.status = STATUS_FAILED
        download.error_message = "RAPIDAPI_VIDEO_DL_KEY not configured"
        await db.flush()
        return download

    try:
        async with httpx.AsyncClient(
            timeout=_RESOLVE_TIMEOUT, transport=transport, headers=_headers()
        ) as client:
            # Step 1: resolve a downloadable URL.
            resolve = await _request_with_retries(
                client,
                "POST",
                _RAPIDAPI_URL,
                json={"url": reel.permalink},
            )
            if resolve.status_code != 200:
                raise DownloadError(
                    f"resolve returned HTTP {resolve.status_code} for {reel.permalink}"
                )
            try:
                payload = resolve.json()
            except ValueError as exc:
                raise DownloadError("resolve body is not JSON") from exc

            media_url = _pick_best_media_url(payload)
            if not media_url:
                raise DownloadError(f"no playable media for {reel.permalink}")

        # Step 2: fetch the binary. New client with a longer timeout —
        # the resolve client closed at the `async with` exit above.
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT, transport=transport
        ) as bin_client:
            bin_resp = await _request_with_retries(bin_client, "GET", media_url)
            if bin_resp.status_code != 200:
                raise DownloadError(
                    f"binary fetch HTTP {bin_resp.status_code} for {media_url}"
                )
            data = bin_resp.content
            if not data:
                raise DownloadError("binary fetch returned empty body")

        # Step 3: upload.
        minio_client = minio or get_minio_client()
        # Keys are scoped per-user + per-download id so two users
        # downloading the same reel don't collide and we can purge by
        # user_id on account deletion.
        key = f"discovery/{download.user_id}/{download.id}.mp4"
        _upload_bytes_to_minio(
            minio_client, bucket=_VIDEOS_BUCKET, key=key, data=data
        )

        download.status = STATUS_DONE
        download.minio_key = key
        download.file_size_bytes = len(data)
        download.error_message = None
    except DownloadError as exc:
        logger.warning("Download %s failed: %s", download_id, exc)
        download.status = STATUS_FAILED
        download.error_message = str(exc)[:500]
    except Exception as exc:  # noqa: BLE001 — never crash BackgroundTask
        logger.exception("Download %s failed unexpectedly", download_id)
        download.status = STATUS_FAILED
        download.error_message = f"unexpected {exc.__class__.__name__}: {exc}"[:500]

    await db.flush()
    return download
