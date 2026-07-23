"""Runtime Provider enrollment rate limit tests."""

from typing import Any, cast

import pytest
from redis.asyncio import Redis

from azents.services.runtime_provider_control.rate_limit import (
    RedisRuntimeProviderEnrollmentRateLimiter,
    RuntimeProviderEnrollmentRateLimited,
)


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
    limiter = RedisRuntimeProviderEnrollmentRateLimiter(cast(Redis, cast(Any, redis)))

    await limiter.acquire(grant_id="grant-1", source_address="192.0.2.10")

    key = redis.calls[0][2]
    assert isinstance(key, str)
    assert key.startswith("azents:runtime-provider-enrollment-rate-limit:")
    assert "grant-1" not in key
    assert "192.0.2.10" not in key


@pytest.mark.asyncio
async def test_rate_limiter_rejects_excess_attempt_with_ttl() -> None:
    """Excess attempts expose only the remaining retry interval."""
    limiter = RedisRuntimeProviderEnrollmentRateLimiter(
        cast(Redis, cast(Any, FakeRedis([11, 17])))
    )

    with pytest.raises(RuntimeProviderEnrollmentRateLimited) as error:
        await limiter.acquire(grant_id="grant-1", source_address="192.0.2.10")

    assert error.value.retry_after_seconds == 17
