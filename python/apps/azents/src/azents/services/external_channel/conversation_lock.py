"""Ephemeral external-conversation coordination lock implementations."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from azents.services.external_channel.conversation import (
    ExternalChannelConversationLock,
    ExternalChannelConversationLockLease,
    ExternalChannelConversationLockOwnershipLost,
    ExternalChannelConversationLockTimeout,
    ExternalChannelConversationLockUnavailable,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)

_DEFAULT_KEY_PREFIX = "azents:external-channel:conversation"
_MIN_SLEEP_SECONDS = 0.001

_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

_ASSERT_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return 1
end
return 0
"""


def _remaining_seconds(deadline: ExternalChannelOperationDeadline) -> float:
    return deadline.remaining_seconds()


async def _await_with_deadline(
    awaitable: Awaitable[object],
    *,
    deadline: ExternalChannelOperationDeadline,
) -> object:
    remaining = _remaining_seconds(deadline)
    if remaining <= 0:
        raise ExternalChannelConversationLockTimeout(
            "External Channel conversation lock deadline expired."
        )
    try:
        async with asyncio.timeout(remaining):
            return await awaitable
    except TimeoutError as error:
        raise ExternalChannelConversationLockTimeout(
            "External Channel conversation lock deadline expired."
        ) from error


@dataclass
class _MemoryLease:
    lock: asyncio.Lock
    owner: str
    released: bool = False

    async def assert_owned(self) -> None:
        if self.released or not self.lock.locked():
            raise ExternalChannelConversationLockOwnershipLost(
                "External Channel conversation lock ownership was lost."
            )

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self.lock.locked():
            self.lock.release()


class InMemoryExternalChannelConversationLock(ExternalChannelConversationLock):
    """Process-local keyed conversation lock."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _lock_for(self, digest: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(digest)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[digest] = lock
            return lock

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        return self._acquire(scope=scope, deadline=deadline)

    @asynccontextmanager
    async def _acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AsyncIterator[ExternalChannelConversationLockLease]:
        lock = await self._lock_for(scope.lock_digest)
        remaining = _remaining_seconds(deadline)
        if remaining <= 0:
            raise ExternalChannelConversationLockTimeout(
                "External Channel conversation lock deadline expired."
            )
        try:
            async with asyncio.timeout(remaining):
                await lock.acquire()
        except TimeoutError as error:
            raise ExternalChannelConversationLockTimeout(
                "External Channel conversation lock acquisition timed out."
            ) from error
        lease = _MemoryLease(lock=lock, owner=secrets.token_hex(16))
        try:
            yield lease
        finally:
            await lease.release()


@dataclass
class _RedisLease:
    redis: Redis
    key: str
    owner: str
    ttl_milliseconds: int
    renewal_interval_seconds: float
    deadline: ExternalChannelOperationDeadline
    released: bool = False
    renewal_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.renewal_task = asyncio.create_task(self._renew_loop())

    async def assert_owned(self) -> None:
        if self.released:
            raise ExternalChannelConversationLockOwnershipLost(
                "External Channel conversation lock ownership was lost."
            )
        try:
            result = await _await_with_deadline(
                cast(Any, self.redis).eval(
                    _ASSERT_SCRIPT,
                    1,
                    self.key,
                    self.owner,
                ),
                deadline=self.deadline,
            )
        except ExternalChannelConversationLockTimeout:
            raise
        except (RedisError, OSError) as error:
            raise ExternalChannelConversationLockUnavailable(
                "External Channel conversation lock backend is unavailable."
            ) from error
        if not bool(result):
            raise ExternalChannelConversationLockOwnershipLost(
                "External Channel conversation lock ownership was lost."
            )

    async def _renew_loop(self) -> None:
        try:
            while not self.released:
                await asyncio.sleep(self.renewal_interval_seconds)
                if self.released:
                    return
                try:
                    result = await cast(Any, self.redis).eval(
                        _RENEW_SCRIPT,
                        1,
                        self.key,
                        self.owner,
                        self.ttl_milliseconds,
                    )
                except RedisError, OSError:
                    return
                if not bool(result):
                    return
        except asyncio.CancelledError:
            raise

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self.renewal_task is not None:
            self.renewal_task.cancel()
            await asyncio.gather(self.renewal_task, return_exceptions=True)
        try:
            result = await cast(Any, self.redis).eval(
                _RELEASE_SCRIPT,
                1,
                self.key,
                self.owner,
            )
        except (RedisError, OSError) as error:
            raise ExternalChannelConversationLockUnavailable(
                "External Channel conversation lock backend is unavailable."
            ) from error
        if not bool(result):
            raise ExternalChannelConversationLockOwnershipLost(
                "External Channel conversation lock ownership was lost."
            )


class RedisExternalChannelConversationLock(ExternalChannelConversationLock):
    """Redis-backed owner-token-fenced conversation lock."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = _DEFAULT_KEY_PREFIX,
        lease_ttl_seconds: float = 30.0,
        renewal_interval_seconds: float = 10.0,
        retry_interval_seconds: float = 0.01,
    ) -> None:
        if not key_prefix or key_prefix.endswith(":"):
            raise ValueError("External Channel lock key prefix is invalid.")
        if lease_ttl_seconds <= 0:
            raise ValueError("External Channel lock lease TTL must be positive.")
        if (
            renewal_interval_seconds <= 0
            or renewal_interval_seconds >= lease_ttl_seconds
        ):
            raise ValueError(
                "External Channel lock renewal interval must be shorter than TTL."
            )
        self.redis = redis
        self.key_prefix = key_prefix
        self.lease_ttl_seconds = lease_ttl_seconds
        self.renewal_interval_seconds = renewal_interval_seconds
        self.retry_interval_seconds = retry_interval_seconds

    def _key(self, scope: ExternalChannelConversationScope) -> str:
        return f"{self.key_prefix}:{scope.lock_digest}"

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        return self._acquire(scope=scope, deadline=deadline)

    @asynccontextmanager
    async def _acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AsyncIterator[ExternalChannelConversationLockLease]:
        owner = secrets.token_hex(16)
        key = self._key(scope)
        ttl_milliseconds = max(1, int(self.lease_ttl_seconds * 1000))
        while True:
            remaining = _remaining_seconds(deadline)
            if remaining <= 0:
                raise ExternalChannelConversationLockTimeout(
                    "External Channel conversation lock acquisition timed out."
                )
            try:
                acquired = await _await_with_deadline(
                    self.redis.set(
                        key,
                        owner,
                        nx=True,
                        px=ttl_milliseconds,
                    ),
                    deadline=deadline,
                )
            except ExternalChannelConversationLockTimeout:
                raise
            except (RedisError, OSError) as error:
                raise ExternalChannelConversationLockUnavailable(
                    "External Channel conversation lock backend is unavailable."
                ) from error
            if acquired:
                lease = _RedisLease(
                    redis=self.redis,
                    key=key,
                    owner=owner,
                    ttl_milliseconds=ttl_milliseconds,
                    renewal_interval_seconds=self.renewal_interval_seconds,
                    deadline=deadline,
                )
                await lease.start()
                try:
                    yield lease
                finally:
                    await lease.release()
                return
            await asyncio.sleep(min(self.retry_interval_seconds, remaining))
