"""Runtime Provider enrollment rate limit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis

from azents.services.runtime_provider_control.rate_limit import (
    RedisRuntimeProviderEnrollmentRateLimiter,
    RuntimeProviderEnrollmentRateLimited,
)
from azents.testing.types import require_instance


class FakeRedis:
    """Return one configured Lua admission result."""

    def __init__(self, result: list[int]) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> list[int]:
        self.calls.append(args)
        return self.result


@pytest.mark.asyncio
async def test_rate_limiter_allows_attempt_within_window() -> None:
    """Attempts through the configured maximum are admitted."""
    redis = FakeRedis([10, 23])
    client = MagicMock(spec=Redis)
    client.eval = AsyncMock(side_effect=redis.eval)
    limiter = RedisRuntimeProviderEnrollmentRateLimiter(require_instance(client, Redis))

    await limiter.acquire(grant_id="grant-1", source_address="192.0.2.10")

    key = redis.calls[0][2]
    assert isinstance(key, str)
    assert key.startswith("azents:runtime-provider-enrollment-rate-limit:")
    assert "grant-1" not in key
    assert "192.0.2.10" not in key


@pytest.mark.asyncio
async def test_rate_limiter_rejects_excess_attempt_with_ttl() -> None:
    """Excess attempts expose only the remaining retry interval."""
    client = MagicMock(spec=Redis)
    client.eval = AsyncMock(side_effect=FakeRedis([11, 17]).eval)
    limiter = RedisRuntimeProviderEnrollmentRateLimiter(require_instance(client, Redis))

    with pytest.raises(RuntimeProviderEnrollmentRateLimited) as error:
        await limiter.acquire(grant_id="grant-1", source_address="192.0.2.10")

    assert error.value.retry_after_seconds == 17


@pytest.mark.asyncio
async def test_rate_limiter_reset_opens_fresh_best_effort_window(
    redis_url: str,
) -> None:
    """An empty Redis store resets abuse counting without retaining authority."""
    redis = Redis.from_url(redis_url)
    await redis.flushall()
    limiter = RedisRuntimeProviderEnrollmentRateLimiter(
        redis,
        max_attempts=1,
    )
    try:
        await limiter.acquire(
            grant_id="grant-reset",
            source_address="192.0.2.20",
        )
        with pytest.raises(RuntimeProviderEnrollmentRateLimited):
            await limiter.acquire(
                grant_id="grant-reset",
                source_address="192.0.2.20",
            )

        await redis.flushall()

        await limiter.acquire(
            grant_id="grant-reset",
            source_address="192.0.2.20",
        )
    finally:
        await redis.aclose()
