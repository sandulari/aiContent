"""Per-user "last discovery refresh" state, persisted to Redis.

The refresh endpoint is fire-and-forget (BackgroundTasks). Without a way
for the UI to see *what happened* the user is left guessing why their
feed is still empty. This module is the durable surface: each refresh
writes its lifecycle (queued -> running -> done|failed) plus per-handle
outcome into a single Redis key the UI can poll.

Design notes:
  - One key per user. New refresh overwrites the previous one — the UI
    only cares about the latest attempt.
  - 24h TTL. Plenty for the polling window; gone before it can confuse
    future debug sessions.
  - Status uses a small vocabulary the frontend literals match:
    ``queued`` (accepted, BackgroundTask not yet started), ``running``
    (fetch in progress), ``done`` (every handle succeeded or returned
    empty), ``partial`` (some handles failed), ``failed`` (every handle
    failed — usually subscription / global rate limit).
  - ``error_kind`` carries a single dominant failure kind so the UI can
    show a specific message ("RapidAPI subscription needs renewal").
    When mixed, picks the worst signal in priority order.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_TTL_SECONDS = 24 * 3600

# Tests inject a fakeredis instance here. Production never touches it.
_test_client: Redis | None = None


def _client() -> Redis:
    if _test_client is not None:
        return _test_client
    return Redis.from_url(REDIS_URL, decode_responses=True)


def _key(user_id: UUID | str) -> str:
    return f"discovery:run:{user_id}:latest"


@dataclass
class DiscoveryRun:
    run_id: str
    status: str  # queued | running | done | partial | failed
    started_at: str
    finished_at: str | None = None
    page_count: int = 0
    refreshed: int = 0
    failed_handles: list[str] = field(default_factory=list)
    error_kind: str | None = None  # subscription | rate_limit | upstream | timeout | None
    error_detail: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "DiscoveryRun":
        data = json.loads(raw)
        return cls(**data)


def new_run_id() -> str:
    return str(uuid4())


async def write_queued(
    user_id: UUID | str,
    *,
    run_id: str,
    page_count: int,
    redis: Redis | None = None,
) -> DiscoveryRun:
    """Initial state when ``POST /refresh`` returns 202."""
    run = DiscoveryRun(
        run_id=run_id,
        status="queued",
        started_at=datetime.now(timezone.utc).isoformat(),
        page_count=page_count,
    )
    await _write(user_id, run, redis=redis)
    return run


async def write_running(
    user_id: UUID | str,
    *,
    run_id: str,
    redis: Redis | None = None,
) -> DiscoveryRun | None:
    """Transition queued -> running when the BackgroundTask picks up.

    No-op if the stored run_id is different (a newer refresh raced this
    one); whatever the newer state shows is more accurate.
    """
    existing = await read(user_id, redis=redis)
    if existing is None or existing.run_id != run_id:
        return existing
    existing.status = "running"
    await _write(user_id, existing, redis=redis)
    return existing


async def write_finished(
    user_id: UUID | str,
    *,
    run_id: str,
    refreshed: int,
    failed_handles: Iterable[str],
    error_kind: str | None,
    error_detail: str | None = None,
    redis: Redis | None = None,
) -> DiscoveryRun | None:
    """Terminal state with the outcome split. Status is derived:

      - all handles succeeded -> ``done``
      - some failed -> ``partial``
      - every handle failed -> ``failed``
    """
    existing = await read(user_id, redis=redis)
    # If the stored run was overwritten by a newer one, don't clobber it.
    if existing is None or existing.run_id != run_id:
        return existing

    failed_list = list(failed_handles)
    page_count = existing.page_count
    if failed_list and refreshed == 0:
        status = "failed"
    elif failed_list:
        status = "partial"
    else:
        status = "done"

    existing.status = status
    existing.finished_at = datetime.now(timezone.utc).isoformat()
    existing.refreshed = refreshed
    existing.failed_handles = failed_list
    existing.error_kind = error_kind
    existing.error_detail = error_detail
    await _write(user_id, existing, redis=redis)
    return existing


async def read(
    user_id: UUID | str,
    *,
    redis: Redis | None = None,
) -> DiscoveryRun | None:
    """Return the latest run state, or None if never refreshed."""
    client = redis or _client()
    owns = redis is None and _test_client is None
    try:
        raw = await client.get(_key(user_id))
        if not raw:
            return None
        try:
            return DiscoveryRun.from_json(raw)
        except (json.JSONDecodeError, TypeError):
            # Defensive — a corrupted key shouldn't take down the endpoint.
            return None
    finally:
        if owns:
            await client.aclose()


async def _write(
    user_id: UUID | str,
    run: DiscoveryRun,
    *,
    redis: Redis | None = None,
) -> None:
    client = redis or _client()
    owns = redis is None and _test_client is None
    try:
        await client.set(_key(user_id), run.to_json(), ex=_TTL_SECONDS)
    finally:
        if owns:
            await client.aclose()
