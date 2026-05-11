"""Sliding-window rate limiter backed by Redis.

Single-purpose helper used by the discovery endpoints (per-user + global
RapidAPI call caps). Production callers pass the shared ``REDIS_URL`` —
tests monkeypatch ``_test_client`` to a ``fakeredis`` instance so we
don't need a real Redis to assert rate-limit logic.
"""
from __future__ import annotations

import os
from typing import Optional

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Tests inject a fakeredis instance here. Production code never touches this.
_test_client: Optional[Redis] = None


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        super().__init__(f"rate limited; retry after {retry_after_seconds}s")
        self.retry_after = retry_after_seconds


def _client() -> Redis:
    if _test_client is not None:
        return _test_client
    return Redis.from_url(REDIS_URL, decode_responses=True)


async def check_and_bump(
    key: str,
    *,
    max_per_window: int,
    window_seconds: int,
    redis: Redis | None = None,
) -> int:
    """Atomically increment ``key`` and enforce the per-window cap.

    Raises :class:`RateLimitExceeded` with ``retry_after`` set to the
    current key TTL when the cap is hit. Returns the current count on
    success so callers can log it.

    The increment + first-time-only EXPIRE happens in a single pipeline
    so two concurrent INCRs can't both miss the EXPIRE call and leave a
    counter with no TTL (would silently keep rate-limiting forever).
    """
    client = redis or _client()
    owns_client = redis is None and _test_client is None

    try:
        pipe = client.pipeline()
        pipe.incr(key)
        # nx=True sets the TTL only if the key has no TTL yet — i.e. on
        # the INCR that created the counter. Subsequent calls within the
        # window are no-ops for EXPIRE, which is what we want.
        pipe.expire(key, window_seconds, nx=True)
        result = await pipe.execute()
        count = int(result[0])

        if count > max_per_window:
            ttl = await client.ttl(key)
            # If TTL is -1 (no expiry — shouldn't happen but be defensive)
            # or -2 (key missing — even weirder), report the full window.
            retry_after = ttl if ttl > 0 else window_seconds
            raise RateLimitExceeded(retry_after)
        return count
    finally:
        if owns_client:
            await client.aclose()
