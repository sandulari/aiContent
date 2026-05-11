"""Redis rate limiter — pipeline atomicity, TTL behaviour, key isolation.

Uses ``fakeredis`` so the suite doesn't need a real Redis server. All
behaviour we care about (INCR + EXPIRE nx pipeline, TTL queries on hit)
is implemented in fakeredis 2.x with the same semantics as real Redis.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from services.rate_limiter import RateLimitExceeded, check_and_bump


@pytest_asyncio.fixture
async def fake_redis():
    client = FakeAsyncRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def test_first_call_returns_count_one_and_sets_ttl(fake_redis):
    count = await check_and_bump(
        "k", max_per_window=5, window_seconds=60, redis=fake_redis
    )
    assert count == 1
    ttl = await fake_redis.ttl("k")
    assert 0 < ttl <= 60


async def test_increments_until_cap(fake_redis):
    for i in range(1, 6):
        count = await check_and_bump(
            "k", max_per_window=5, window_seconds=60, redis=fake_redis
        )
        assert count == i


async def test_raises_when_cap_exceeded(fake_redis):
    for _ in range(5):
        await check_and_bump(
            "k", max_per_window=5, window_seconds=60, redis=fake_redis
        )
    with pytest.raises(RateLimitExceeded) as exc:
        await check_and_bump(
            "k", max_per_window=5, window_seconds=60, redis=fake_redis
        )
    assert exc.value.retry_after > 0
    assert exc.value.retry_after <= 60


async def test_ttl_is_not_reset_on_subsequent_increments(fake_redis):
    """EXPIRE nx=True means the TTL is only set on the first increment;
    later increments must NOT extend the window (otherwise the counter
    would never expire under sustained load)."""
    await check_and_bump(
        "k", max_per_window=10, window_seconds=60, redis=fake_redis
    )
    ttl_first = await fake_redis.ttl("k")

    # Second call passes a different window_seconds — irrelevant, the
    # original TTL should hold.
    await check_and_bump(
        "k", max_per_window=10, window_seconds=999, redis=fake_redis
    )
    ttl_second = await fake_redis.ttl("k")
    # ttl_second <= ttl_first (it may have decreased by clock skew, but
    # never increased to the 999 the second call passed).
    assert ttl_second <= ttl_first


async def test_different_keys_have_independent_counters(fake_redis):
    await check_and_bump(
        "a", max_per_window=2, window_seconds=60, redis=fake_redis
    )
    await check_and_bump(
        "a", max_per_window=2, window_seconds=60, redis=fake_redis
    )
    # 'a' is at cap; 'b' is untouched.
    with pytest.raises(RateLimitExceeded):
        await check_and_bump(
            "a", max_per_window=2, window_seconds=60, redis=fake_redis
        )
    count_b = await check_and_bump(
        "b", max_per_window=2, window_seconds=60, redis=fake_redis
    )
    assert count_b == 1


async def test_retry_after_reflects_remaining_ttl(fake_redis):
    for _ in range(3):
        await check_and_bump(
            "k", max_per_window=3, window_seconds=60, redis=fake_redis
        )
    with pytest.raises(RateLimitExceeded) as exc:
        await check_and_bump(
            "k", max_per_window=3, window_seconds=60, redis=fake_redis
        )
    # Retry-After should match the actual TTL on the key.
    current_ttl = await fake_redis.ttl("k")
    # Allow 1s slack for the time between the raise and our TTL read.
    assert abs(exc.value.retry_after - current_ttl) <= 1
