"""Instagram Reels scheduled publishing tasks.

Flow (per scheduled_reels row):

    queued -> processing -> published    (happy path)
                         -> failed       (token bad, container error, or
                                          attempt_count exceeded 3)
                         -> queued       (retry w/ 10-min backoff, or
                                          rate-limit 1-hr reschedule)

Orchestration pieces:

* ``tick_scheduled_reels`` — celery-beat every 60s. Picks up to 50 rows
  whose ``scheduled_at <= NOW()`` with ``FOR UPDATE SKIP LOCKED`` so
  multiple beat instances can't double-dispatch. Fans out individual
  ``publish_scheduled_reel`` tasks.
* ``publish_scheduled_reel(id)`` — the actual work: flip row to
  processing, load user's IG creds, presign the MP4 from MinIO so Meta
  can fetch it, create the container, poll status, publish.
* ``cleanup_stuck_processing`` — every 15m. Anything stuck in
  ``processing`` for >30m gets reconciled against Meta or marked failed.

Notes on isolation from the API service:

* The worker is a separate service with its own Python path, so we don't
  import ``services.api.services.crypto``. Instead we do a minimal
  inline Fernet decrypt here using ``IG_TOKEN_ENC_KEY`` which is shared
  across services (same key material; see docker-compose).
* Meta Graph hostnames are in ``graph.instagram.com`` (Instagram Login
  flavor of the Graph API) and expect ``access_token`` as a param.

Rate limit (verified April 2026): **100 API-published media per IG
account per rolling 24h**. We check this before creating a container
so we don't burn a token on a request that would 400.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from celery_app import app
from lib.db import get_session
from lib.minio_client import get_minio_client

logger = logging.getLogger(__name__)

META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")
GRAPH_BASE = "https://graph.instagram.com"

# Meta caption hard limit.
CAPTION_MAX = 2200

# Rolling 24h publish cap per IG account (Meta, April 2026).
RATE_LIMIT_24H = 100

# Max total time we'll spend polling container status before giving up.
POLL_TOTAL_CAP_SECONDS = 15 * 60

# Backoff schedule for container status polling, then repeats the last
# value until POLL_TOTAL_CAP_SECONDS elapses.
POLL_BACKOFF = [5, 10, 15, 30, 60, 60, 60]

# Manual retry policy — we don't use Celery's retry machinery because we
# want the retry to happen on a wall-clock schedule (10 min) via the
# scheduled_at column, not immediately.
MAX_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Token / redaction helpers
# ---------------------------------------------------------------------------


def _redact(token: Optional[str]) -> str:
    """Safe log representation — first 6 + last 4 chars only."""
    if not token:
        return "<none>"
    if len(token) < 16:
        return "<redacted>"
    return f"{token[:6]}...{token[-4:]}"


_fernet_cached: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Return a process-cached Fernet keyed on IG_TOKEN_ENC_KEY."""
    global _fernet_cached
    if _fernet_cached is None:
        key = os.environ.get("IG_TOKEN_ENC_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "IG_TOKEN_ENC_KEY is not set in the worker environment."
            )
        _fernet_cached = Fernet(key.encode())
    return _fernet_cached


def _decrypt_ig_token(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("ig_token_undecryptable") from exc


# ---------------------------------------------------------------------------
# MinIO presign
# ---------------------------------------------------------------------------


def _split_export_key(export_minio_key: str) -> Tuple[str, str]:
    """``exports/uid/foo.mp4`` -> (``exports``, ``uid/foo.mp4``)."""
    if not export_minio_key or "/" not in export_minio_key:
        raise ValueError(f"invalid export_minio_key: {export_minio_key!r}")
    bucket, key = export_minio_key.split("/", 1)
    return bucket, key


def _presign_for_meta(export_minio_key: str, expires_seconds: int = 3600) -> str:
    """Return a publicly-reachable presigned GET URL for Meta to fetch.

    The MinIO SDK signs URLs against ``MINIO_ENDPOINT`` — inside our
    docker network that's something like ``minio:9000`` which Meta's
    servers on the open internet cannot reach. If ``MINIO_EXTERNAL_ENDPOINT``
    is set we rewrite the URL host/scheme to the public endpoint. The
    signature itself is computed over path + query only (SigV4), not the
    hostname, so swapping the netloc is safe.
    """
    from datetime import timedelta

    bucket, key = _split_export_key(export_minio_key)
    client = get_minio_client()
    presigned = client.presigned_get_object(
        bucket, key, expires=timedelta(seconds=expires_seconds)
    )

    external = os.environ.get("MINIO_EXTERNAL_ENDPOINT", "").strip()
    if external:
        parsed = urlparse(presigned)
        # Parse external as either "host:port" or a full URL.
        if "://" in external:
            ext_parsed = urlparse(external)
            new_scheme = ext_parsed.scheme or parsed.scheme
            new_netloc = ext_parsed.netloc or ext_parsed.path
        else:
            # Default to https when the internal endpoint is http but a
            # bare host:port is provided externally (prod reverse proxy).
            secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
            new_scheme = "https" if secure else "http"
            new_netloc = external
        presigned = urlunparse(parsed._replace(scheme=new_scheme, netloc=new_netloc))
    return presigned


# ---------------------------------------------------------------------------
# Graph API helpers
# ---------------------------------------------------------------------------


def _graph_url(path: str) -> str:
    return f"{GRAPH_BASE}/{META_GRAPH_VERSION}/{path.lstrip('/')}"


def _extract_error_subcode(resp: requests.Response) -> Tuple[Optional[int], str]:
    """Pull ``(error_subcode, human message)`` out of a Graph response."""
    try:
        body = resp.json()
    except ValueError:
        return None, resp.text[:500]
    err = body.get("error") or {}
    sub = err.get("error_subcode")
    msg = err.get("message") or body.get("error_description") or resp.text[:500]
    if err.get("type"):
        msg = f"{err.get('type')}: {msg}"
    return sub, msg


def _is_token_error_subcode(subcode: Optional[int]) -> bool:
    # 463 = expired, 467 = invalid (Meta docs).
    return subcode in (463, 467)


def _normalize_user_tags(user_tags: Any) -> List[Dict[str, Any]]:
    """Graph rejects bare strings in user_tags — only {username, x?, y?}.

    x/y are optional (tag-in-video without position is legal). We keep
    them only when both coordinates are present to avoid partial tags.
    """
    if not user_tags:
        return []
    if isinstance(user_tags, str):
        try:
            user_tags = json.loads(user_tags)
        except json.JSONDecodeError:
            return []
    if not isinstance(user_tags, list):
        return []
    out: List[Dict[str, Any]] = []
    for t in user_tags:
        if not isinstance(t, dict):
            continue
        username = t.get("username")
        if not username or not isinstance(username, str):
            continue
        tag: Dict[str, Any] = {"username": username.lstrip("@")}
        x, y = t.get("x"), t.get("y")
        if x is not None and y is not None:
            try:
                tag["x"] = float(x)
                tag["y"] = float(y)
            except (TypeError, ValueError):
                pass
        out.append(tag)
    return out


# ---------------------------------------------------------------------------
# DB helpers for state transitions
# ---------------------------------------------------------------------------


def _mark_failed(reel_id: str, reason: str) -> None:
    # Guard against clobbering terminal states. cleanup_stuck_processing
    # can race a still-running publish task (e.g., worker stuck >30m on a
    # Meta call); without this guard the loser's 4xx-already-published
    # response would flip a successful row from published -> failed.
    with get_session() as session:
        session.execute(
            text(
                """
                UPDATE scheduled_reels
                SET status = 'failed',
                    last_error = :err,
                    celery_task_id = NULL,
                    updated_at = NOW()
                WHERE id = :id
                  AND status NOT IN ('published', 'cancelled')
                """
            ),
            {"id": reel_id, "err": reason[:1000]},
        )
    logger.warning("scheduled_reel %s -> failed (%s)", reel_id, reason)


def _requeue(reel_id: str, delay_minutes: int, reason: str) -> None:
    # Same terminal-state guard as _mark_failed.
    with get_session() as session:
        session.execute(
            text(
                """
                UPDATE scheduled_reels
                SET status = 'queued',
                    scheduled_at = NOW() + (:mins || ' minutes')::interval,
                    last_error = :err,
                    celery_task_id = NULL,
                    processing_started_at = NULL,
                    updated_at = NOW()
                WHERE id = :id
                  AND status NOT IN ('published', 'cancelled')
                """
            ),
            {"id": reel_id, "mins": str(delay_minutes), "err": reason[:1000]},
        )
    logger.info(
        "scheduled_reel %s re-queued in %d min (%s)", reel_id, delay_minutes, reason
    )


# ---------------------------------------------------------------------------
# Tick: beat task that fans work out to individual publish tasks
# ---------------------------------------------------------------------------


@app.task(name="tasks.publish_scheduled_reel.tick_scheduled_reels")
def tick_scheduled_reels():
    """Select due scheduled reels and dispatch publish tasks.

    ``FOR UPDATE SKIP LOCKED`` guards against two beat instances picking
    the same row. We only use the lock to read the ids — the actual
    ``processing`` flip happens inside the per-row task with a separate
    transaction that also status-gates on ``status='queued'``.
    """
    try:
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id FROM scheduled_reels
                    WHERE status = 'queued' AND scheduled_at <= NOW()
                    ORDER BY scheduled_at ASC
                    LIMIT 50
                    FOR UPDATE SKIP LOCKED
                    """
                )
            ).fetchall()
            due_ids = [str(r.id) for r in rows]
    except Exception as exc:
        logger.error("tick_scheduled_reels DB query failed: %s", exc, exc_info=True)
        return {"dispatched": 0, "error": str(exc)[:200]}

    for rid in due_ids:
        try:
            publish_scheduled_reel.delay(rid)
        except Exception as exc:
            logger.error(
                "tick_scheduled_reels: dispatch failed for %s: %s",
                rid,
                exc,
                exc_info=True,
            )
    logger.info("tick_scheduled_reels dispatched=%d", len(due_ids))
    return {"dispatched": len(due_ids)}


# ---------------------------------------------------------------------------
# Main publish task
# ---------------------------------------------------------------------------


@app.task(
    name="tasks.publish_scheduled_reel.publish_scheduled_reel",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def publish_scheduled_reel(self, reel_id: str):
    """Publish a single scheduled_reels row to Instagram via Graph API.

    All error handling is manual — we never rely on Celery's built-in
    retry because we need to push the next attempt out in wall-clock
    time (scheduled_at) rather than Celery's ETA so the tick loop keeps
    owning dispatch.
    """
    task_id = self.request.id or "unknown"
    logger.info("publish_scheduled_reel start id=%s task=%s", reel_id, task_id)

    # ---- Step 1: atomically flip queued -> processing ---------------------
    with get_session() as session:
        locked = session.execute(
            text(
                """
                UPDATE scheduled_reels
                SET status = 'processing',
                    processing_started_at = NOW(),
                    celery_task_id = :task_id,
                    updated_at = NOW()
                WHERE id = :id AND status = 'queued'
                RETURNING id
                """
            ),
            {"id": reel_id, "task_id": task_id},
        ).fetchone()
    if not locked:
        logger.info(
            "publish_scheduled_reel %s: row no longer queued, skipping", reel_id
        )
        return {"skipped": True, "reason": "not_queued"}

    try:
        return _do_publish(reel_id)
    except _PermanentFailure as exc:
        # Already marked failed inside helper — just log.
        logger.error(
            "publish_scheduled_reel %s permanent failure: %s",
            reel_id,
            exc,
            exc_info=True,
        )
        return {"status": "failed", "reason": str(exc)}
    except Exception as exc:
        # Unexpected: bump attempt_count and requeue or fail.
        logger.error(
            "publish_scheduled_reel %s unexpected error: %s",
            reel_id,
            exc,
            exc_info=True,
        )
        _handle_transient_failure(reel_id, str(exc))
        return {"status": "error", "reason": str(exc)[:500]}


class _PermanentFailure(Exception):
    """Sentinel: row has already been flipped to ``failed``."""


def _handle_transient_failure(reel_id: str, reason: str) -> None:
    """Bump attempt_count; requeue if < MAX_ATTEMPTS, else mark failed."""
    with get_session() as session:
        row = session.execute(
            text(
                """
                UPDATE scheduled_reels
                SET attempt_count = attempt_count + 1,
                    updated_at = NOW()
                WHERE id = :id
                RETURNING attempt_count
                """
            ),
            {"id": reel_id},
        ).fetchone()
    attempts = row.attempt_count if row else MAX_ATTEMPTS
    if attempts < MAX_ATTEMPTS:
        _requeue(reel_id, delay_minutes=10, reason=f"retry_{attempts}: {reason}"[:900])
    else:
        _mark_failed(reel_id, f"max_attempts: {reason}")


def _do_publish(reel_id: str) -> Dict[str, Any]:
    """Inner pipeline, called after row is already in ``processing``."""

    # ---- Step 2: join-load row + user + export ---------------------------
    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT
                    sr.id, sr.user_id, sr.user_export_id, sr.caption,
                    sr.user_tags, sr.share_to_feed, sr.ig_container_id,
                    sr.attempt_count,
                    u.ig_user_id, u.ig_access_token, u.ig_token_expires_at,
                    u.ig_account_type,
                    ue.export_minio_key
                FROM scheduled_reels sr
                JOIN users u ON u.id = sr.user_id
                JOIN user_exports ue ON ue.id = sr.user_export_id
                WHERE sr.id = :id
                """
            ),
            {"id": reel_id},
        ).fetchone()

    if not row:
        raise _PermanentFailure(f"scheduled_reel {reel_id} vanished")

    # ---- Step 3: guard IG credentials ------------------------------------
    if not row.ig_access_token or not row.ig_user_id:
        _mark_failed(reel_id, "ig_token_expired_or_missing")
        raise _PermanentFailure("ig_token_expired_or_missing")

    if row.ig_token_expires_at is not None:
        # Compare in DB so we don't have to worry about aware/naive.
        with get_session() as session:
            expired = session.execute(
                text("SELECT (:ts < NOW()) AS expired"),
                {"ts": row.ig_token_expires_at},
            ).scalar()
        if expired:
            _mark_failed(reel_id, "ig_token_expired_or_missing")
            raise _PermanentFailure("ig_token_expired_or_missing")

    if not row.export_minio_key:
        _mark_failed(reel_id, "export_minio_key_missing")
        raise _PermanentFailure("export_minio_key_missing")

    # ---- Step 4: decrypt token -------------------------------------------
    try:
        access_token = _decrypt_ig_token(row.ig_access_token)
    except Exception as exc:
        logger.error(
            "publish_scheduled_reel %s: token decrypt failed: %s",
            reel_id,
            exc,
            exc_info=True,
        )
        _mark_failed(reel_id, "ig_token_undecryptable")
        raise _PermanentFailure("ig_token_undecryptable") from exc

    logger.info(
        "publish_scheduled_reel %s ig_user=%s token=%s",
        reel_id,
        row.ig_user_id,
        _redact(access_token),
    )

    # ---- Step 5: rolling-24h rate limit check ----------------------------
    with get_session() as session:
        count_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM scheduled_reels
                WHERE user_id = :uid
                  AND status IN ('processing', 'published')
                  AND (
                        published_at > NOW() - INTERVAL '24 hours'
                        OR (status = 'processing'
                            AND processing_started_at > NOW() - INTERVAL '24 hours'
                            AND id <> :self_id)
                      )
                """
            ),
            {"uid": str(row.user_id), "self_id": reel_id},
        ).fetchone()
    used = count_row.cnt if count_row else 0
    if used >= RATE_LIMIT_24H:
        logger.warning(
            "publish_scheduled_reel %s hit 24h rate limit (%d), rescheduling",
            reel_id,
            used,
        )
        _requeue(reel_id, delay_minutes=60, reason="rate_limit_24h")
        raise _PermanentFailure("rate_limit_24h")

    # ---- Step 6: presign MinIO object for Meta ---------------------------
    try:
        video_url = _presign_for_meta(row.export_minio_key)
    except Exception as exc:
        logger.error(
            "publish_scheduled_reel %s presign failed: %s", reel_id, exc, exc_info=True
        )
        raise  # bubble -> transient handler

    # ---- Step 7: create container ----------------------------------------
    container_id = row.ig_container_id
    if not container_id:
        container_id = _create_container(
            reel_id=reel_id,
            ig_user_id=row.ig_user_id,
            access_token=access_token,
            video_url=video_url,
            caption=row.caption,
            share_to_feed=bool(row.share_to_feed),
            user_tags=row.user_tags,
        )
        # Persist container id immediately so a crash doesn't lose it.
        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE scheduled_reels
                    SET ig_container_id = :cid, updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"cid": container_id, "id": reel_id},
            )
    else:
        logger.info(
            "publish_scheduled_reel %s reusing existing container %s",
            reel_id,
            container_id,
        )

    # ---- Step 8: poll container status -----------------------------------
    final_status = _poll_container_status(
        reel_id=reel_id,
        container_id=container_id,
        access_token=access_token,
    )

    if final_status == "PUBLISHED":
        # Container already published — rare, but tolerate it.
        logger.warning(
            "publish_scheduled_reel %s: container already PUBLISHED on poll",
            reel_id,
        )
        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE scheduled_reels
                    SET status = 'published',
                        published_at = NOW(),
                        last_error = NULL,
                        celery_task_id = NULL,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": reel_id},
            )
        return {"status": "published", "already": True}

    # ---- Step 9: publish --------------------------------------------------
    media_id = _publish_container(
        reel_id=reel_id,
        ig_user_id=row.ig_user_id,
        container_id=container_id,
        access_token=access_token,
    )

    with get_session() as session:
        session.execute(
            text(
                """
                UPDATE scheduled_reels
                SET status = 'published',
                    ig_media_id = :mid,
                    published_at = NOW(),
                    last_error = NULL,
                    celery_task_id = NULL,
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": reel_id, "mid": media_id},
        )
    logger.info(
        "publish_scheduled_reel %s PUBLISHED media_id=%s container=%s",
        reel_id,
        media_id,
        container_id,
    )
    return {"status": "published", "media_id": media_id, "container_id": container_id}


# ---------------------------------------------------------------------------
# Graph API wrappers
# ---------------------------------------------------------------------------


def _create_container(
    *,
    reel_id: str,
    ig_user_id: str,
    access_token: str,
    video_url: str,
    caption: Optional[str],
    share_to_feed: bool,
    user_tags: Any,
) -> str:
    """POST /{ig_user_id}/media — returns container id. Raises on failure."""
    params: Dict[str, str] = {
        "media_type": "REELS",
        "video_url": video_url,
        "access_token": access_token,
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if caption:
        params["caption"] = caption[:CAPTION_MAX]

    normalized_tags = _normalize_user_tags(user_tags)
    if normalized_tags:
        params["user_tags"] = json.dumps(normalized_tags)

    url = _graph_url(f"{ig_user_id}/media")
    try:
        resp = requests.post(url, params=params, timeout=30)
    except requests.RequestException as exc:
        logger.error(
            "publish_scheduled_reel %s container POST transport error: %s",
            reel_id,
            exc,
            exc_info=True,
        )
        raise

    if resp.status_code >= 400:
        subcode, msg = _extract_error_subcode(resp)
        logger.error(
            "publish_scheduled_reel %s container create failed http=%d sub=%s msg=%s",
            reel_id,
            resp.status_code,
            subcode,
            msg,
        )
        if _is_token_error_subcode(subcode):
            _mark_failed(reel_id, "ig_token_invalid")
            raise _PermanentFailure("ig_token_invalid")
        # Non-token 4xx from Meta is usually a permanent bad-request
        # (caption too long, video format, etc.). Only retry 5xx.
        if 400 <= resp.status_code < 500:
            _mark_failed(reel_id, f"container_create_4xx: {msg}"[:1000])
            raise _PermanentFailure("container_create_4xx")
        raise RuntimeError(f"container_create_5xx: http={resp.status_code} {msg}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"container_create_bad_json: {resp.text[:200]}") from exc
    container_id = body.get("id")
    if not container_id:
        raise RuntimeError(f"container_create_no_id: {body!r}")
    logger.info(
        "publish_scheduled_reel %s container created id=%s", reel_id, container_id
    )
    return str(container_id)


def _poll_container_status(
    *, reel_id: str, container_id: str, access_token: str
) -> str:
    """Poll until FINISHED/PUBLISHED or permanent/timeout.

    Returns ``"FINISHED"`` or ``"PUBLISHED"`` on success. Raises
    ``_PermanentFailure`` on ERROR/EXPIRED (row already marked failed)
    or a plain ``RuntimeError`` on timeout so the outer handler can
    requeue.
    """
    url = _graph_url(container_id)
    params = {"fields": "status_code,status", "access_token": access_token}

    waited = 0
    for i in range(10_000):  # sane upper bound; cap is POLL_TOTAL_CAP_SECONDS
        sleep_for = POLL_BACKOFF[i] if i < len(POLL_BACKOFF) else POLL_BACKOFF[-1]
        if waited + sleep_for > POLL_TOTAL_CAP_SECONDS:
            sleep_for = max(1, POLL_TOTAL_CAP_SECONDS - waited)
        time.sleep(sleep_for)
        waited += sleep_for

        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            logger.warning(
                "publish_scheduled_reel %s poll transport error (will retry): %s",
                reel_id,
                exc,
            )
            if waited >= POLL_TOTAL_CAP_SECONDS:
                raise RuntimeError("poll_transport_timeout") from exc
            continue

        if resp.status_code >= 400:
            subcode, msg = _extract_error_subcode(resp)
            if _is_token_error_subcode(subcode):
                _mark_failed(reel_id, "ig_token_invalid")
                raise _PermanentFailure("ig_token_invalid")
            logger.warning(
                "publish_scheduled_reel %s poll http=%d sub=%s msg=%s",
                reel_id,
                resp.status_code,
                subcode,
                msg,
            )
            if waited >= POLL_TOTAL_CAP_SECONDS:
                raise RuntimeError(f"poll_http_{resp.status_code}: {msg}")
            continue

        try:
            body = resp.json()
        except ValueError:
            if waited >= POLL_TOTAL_CAP_SECONDS:
                raise RuntimeError(f"poll_bad_json: {resp.text[:200]}")
            continue

        status_code = (body.get("status_code") or "").upper()
        status_text = body.get("status") or ""
        logger.info(
            "publish_scheduled_reel %s poll %ds status_code=%s",
            reel_id,
            waited,
            status_code,
        )

        if status_code == "FINISHED":
            return "FINISHED"
        if status_code == "PUBLISHED":
            return "PUBLISHED"
        if status_code in ("ERROR", "EXPIRED"):
            _mark_failed(reel_id, f"container_{status_code}: {status_text}"[:1000])
            raise _PermanentFailure(f"container_{status_code}")
        if status_code == "IN_PROGRESS":
            if waited >= POLL_TOTAL_CAP_SECONDS:
                raise RuntimeError("poll_in_progress_timeout")
            continue
        # Unknown / missing status — treat as in progress until cap.
        if waited >= POLL_TOTAL_CAP_SECONDS:
            raise RuntimeError(f"poll_unknown_status_timeout: {status_code}")

    raise RuntimeError("poll_loop_exhausted")


def _publish_container(
    *,
    reel_id: str,
    ig_user_id: str,
    container_id: str,
    access_token: str,
) -> str:
    """POST /{ig_user_id}/media_publish — returns media id."""
    url = _graph_url(f"{ig_user_id}/media_publish")
    params = {"creation_id": container_id, "access_token": access_token}
    try:
        resp = requests.post(url, params=params, timeout=30)
    except requests.RequestException as exc:
        logger.error(
            "publish_scheduled_reel %s publish transport error: %s",
            reel_id,
            exc,
            exc_info=True,
        )
        raise

    if resp.status_code >= 400:
        subcode, msg = _extract_error_subcode(resp)
        logger.error(
            "publish_scheduled_reel %s publish failed http=%d sub=%s msg=%s",
            reel_id,
            resp.status_code,
            subcode,
            msg,
        )
        if _is_token_error_subcode(subcode):
            _mark_failed(reel_id, "ig_token_invalid")
            raise _PermanentFailure("ig_token_invalid")
        if 400 <= resp.status_code < 500:
            _mark_failed(reel_id, f"publish_4xx: {msg}"[:1000])
            raise _PermanentFailure("publish_4xx")
        raise RuntimeError(f"publish_5xx: http={resp.status_code} {msg}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"publish_bad_json: {resp.text[:200]}") from exc
    media_id = body.get("id")
    if not media_id:
        raise RuntimeError(f"publish_no_id: {body!r}")
    return str(media_id)


# ---------------------------------------------------------------------------
# Stuck-row reconciliation
# ---------------------------------------------------------------------------


@app.task(name="tasks.publish_scheduled_reel.cleanup_stuck_processing")
def cleanup_stuck_processing():
    """Reconcile rows stuck in ``processing`` for >30m.

    Possible causes: worker OOM mid-poll, Meta returned FINISHED but we
    crashed before /media_publish, etc. Query Meta for the container's
    state using the owning user's token:

    * FINISHED        -> call /media_publish and mark published.
    * PUBLISHED       -> already published on Meta's side, mark published
                         (ig_media_id unknown unless Graph returns it).
    * ERROR/EXPIRED   -> mark failed.
    * Anything else   -> mark failed with stuck_processing_timeout.
    """
    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT sr.id, sr.ig_container_id,
                       u.ig_user_id, u.ig_access_token
                FROM scheduled_reels sr
                JOIN users u ON u.id = sr.user_id
                WHERE sr.status = 'processing'
                  AND sr.processing_started_at < NOW() - INTERVAL '30 minutes'
                LIMIT 100
                """
            )
        ).fetchall()

    reconciled = 0
    for r in rows:
        reel_id = str(r.id)
        try:
            if not r.ig_container_id or not r.ig_access_token or not r.ig_user_id:
                _mark_failed(reel_id, "stuck_processing_timeout")
                reconciled += 1
                continue

            try:
                token = _decrypt_ig_token(r.ig_access_token)
            except Exception:
                _mark_failed(reel_id, "stuck_processing_timeout")
                reconciled += 1
                continue

            url = _graph_url(r.ig_container_id)
            try:
                resp = requests.get(
                    url,
                    params={
                        "fields": "status_code,status",
                        "access_token": token,
                    },
                    timeout=20,
                )
            except requests.RequestException as exc:
                # Meta unreachable — leave the row in processing so the
                # next 15-min tick can retry. Failing here would burn
                # otherwise-recoverable rows during a Graph outage.
                logger.warning(
                    "cleanup_stuck_processing %s unreachable, skipping: %s",
                    reel_id, exc,
                )
                continue

            if resp.status_code >= 400:
                subcode, msg = _extract_error_subcode(resp)
                logger.warning(
                    "cleanup_stuck_processing %s http=%d sub=%s msg=%s",
                    reel_id,
                    resp.status_code,
                    subcode,
                    msg,
                )
                # Token revoked is permanent — but a generic 4xx/5xx
                # could be transient (rate limit, temporary 5xx, eventual
                # consistency on the container id). Only fail on definite
                # signals; leave the rest for the next tick.
                if _is_token_error_subcode(subcode):
                    _mark_failed(reel_id, "ig_token_invalid")
                    reconciled += 1
                continue

            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                logger.warning(
                    "cleanup_stuck_processing %s non-JSON response, skipping",
                    reel_id,
                )
                continue
            status_code = (body.get("status_code") or "").upper()

            if status_code == "FINISHED":
                try:
                    media_id = _publish_container(
                        reel_id=reel_id,
                        ig_user_id=r.ig_user_id,
                        container_id=r.ig_container_id,
                        access_token=token,
                    )
                except _PermanentFailure:
                    reconciled += 1
                    continue
                except Exception as exc:
                    logger.error(
                        "cleanup_stuck_processing %s publish failed: %s",
                        reel_id,
                        exc,
                        exc_info=True,
                    )
                    _mark_failed(reel_id, "stuck_processing_timeout")
                    reconciled += 1
                    continue
                with get_session() as session:
                    session.execute(
                        text(
                            """
                            UPDATE scheduled_reels
                            SET status = 'published',
                                ig_media_id = :mid,
                                published_at = NOW(),
                                last_error = NULL,
                                celery_task_id = NULL,
                                updated_at = NOW()
                            WHERE id = :id
                            """
                        ),
                        {"id": reel_id, "mid": media_id},
                    )
                logger.info(
                    "cleanup_stuck_processing %s reconciled -> published", reel_id
                )
            elif status_code == "PUBLISHED":
                with get_session() as session:
                    session.execute(
                        text(
                            """
                            UPDATE scheduled_reels
                            SET status = 'published',
                                published_at = NOW(),
                                last_error = NULL,
                                celery_task_id = NULL,
                                updated_at = NOW()
                            WHERE id = :id
                            """
                        ),
                        {"id": reel_id},
                    )
            elif status_code in ("ERROR", "EXPIRED"):
                _mark_failed(reel_id, f"container_{status_code}")
            else:
                _mark_failed(reel_id, "stuck_processing_timeout")

            reconciled += 1
        except Exception as exc:
            logger.error(
                "cleanup_stuck_processing %s unexpected: %s",
                reel_id,
                exc,
                exc_info=True,
            )
            try:
                _mark_failed(reel_id, "stuck_processing_timeout")
                reconciled += 1
            except Exception:
                pass

    logger.info("cleanup_stuck_processing reconciled=%d", reconciled)
    return {"reconciled": reconciled}
