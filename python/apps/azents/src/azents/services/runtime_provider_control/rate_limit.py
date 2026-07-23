"""Redis admission limit for public Runtime Provider enrollment exchange."""

import dataclasses
import hashlib
from typing import Protocol

from redis.asyncio import Redis

_WINDOW_SECONDS = 60
_MAX_ATTEMPTS = 10
_ACQUIRE_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {count, ttl}
"""


@dataclasses.dataclass
class RuntimeProviderEnrollmentRateLimited(Exception):
    """Enrollment exchange admission limit was exceeded."""

    retry_after_seconds: int


class RuntimeProviderEnrollmentRateLimiter(Protocol):
    """Admission contract for public Provider enrollment exchange."""

    async def acquire(self, *, grant_id: str, source_address: str) -> None:
        """Consume one admission attempt."""
        ...


@dataclasses.dataclass(frozen=True)
class RedisRuntimeProviderEnrollmentRateLimiter:
    """Atomic fixed-window enrollment exchange rate limiter."""

    redis: Redis
    max_attempts: int = _MAX_ATTEMPTS
    window_seconds: int = _WINDOW_SECONDS

    async def acquire(self, *, grant_id: str, source_address: str) -> None:
        """Consume one admission attempt or raise with a retry interval."""
        key = _rate_limit_key(grant_id, source_address)
        result = await self.redis.eval(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py stubs omit dynamic commands.
            _ACQUIRE_SCRIPT,
            1,
            key,
            self.window_seconds,
        )
        if not isinstance(result, list) or len(result) != 2:
            raise RuntimeError("Enrollment rate limiter returned an invalid result")
        count = int(result[0])
        ttl = max(int(result[1]), 1)
        if count > self.max_attempts:
            raise RuntimeProviderEnrollmentRateLimited(ttl)


def _rate_limit_key(grant_id: str, source_address: str) -> str:
    digest = hashlib.sha256(f"{grant_id}\0{source_address}".encode()).hexdigest()
    return f"azents:runtime-provider-enrollment-rate-limit:{digest}"
