"""External conversation lock contract tests."""

import asyncio
import datetime
from typing import Any, cast

import pytest

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLockOwnershipLost,
    ExternalChannelConversationLockTimeout,
    ExternalChannelConversationLockUnavailable,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.conversation_lock import (
    InMemoryExternalChannelConversationLock,
    RedisExternalChannelConversationLock,
)


def _scope() -> ExternalChannelConversationScope:
    return ExternalChannelConversationScope(
        connection_id="connection",
        kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel",
        provider_thread_key="thread",
    )


def _deadline(seconds: float = 1.0) -> ExternalChannelOperationDeadline:
    return ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    )


@pytest.mark.asyncio
async def test_memory_lock_serializes_same_digest() -> None:
    lock = InMemoryExternalChannelConversationLock()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first() -> None:
        async with lock.acquire(scope=_scope(), deadline=_deadline()):
            entered.set()
            await release.wait()

    task = asyncio.create_task(first())
    await entered.wait()
    with pytest.raises(ExternalChannelConversationLockTimeout):
        async with lock.acquire(scope=_scope(), deadline=_deadline(0.01)):
            pass
    release.set()
    await task


@pytest.mark.asyncio
async def test_memory_lease_asserts_after_release() -> None:
    lock = InMemoryExternalChannelConversationLock()
    lease = cast(Any, None)
    async with lock.acquire(scope=_scope(), deadline=_deadline()) as owned:
        lease = owned
        await owned.assert_owned()
    with pytest.raises(ExternalChannelConversationLockOwnershipLost):
        await lease.assert_owned()


class _FakeRedis:
    """Minimal owner-token Redis command surface for lock contract tests."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, int]] = {}
        self.unavailable = False

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool,
        px: int,
    ) -> bool:
        if self.unavailable:
            raise OSError("redis unavailable")
        if nx and key in self.values:
            return False
        self.values[key] = (value, px)
        return True

    async def eval(self, script: str, _numkeys: int, key: str, *args: object) -> int:
        if self.unavailable:
            raise OSError("redis unavailable")
        current = self.values.get(key)
        owner = str(args[0])
        if "PEXPIRE" in script:
            if current is None or current[0] != owner:
                return 0
            lease_ttl = args[1]
            assert isinstance(lease_ttl, int)
            self.values[key] = (owner, lease_ttl)
            return 1
        if "DEL" in script:
            if current is None or current[0] != owner:
                return 0
            del self.values[key]
            return 1
        return int(current is not None and current[0] == owner)


@pytest.mark.asyncio
async def test_redis_lock_uses_owner_fencing_without_memory_fallback() -> None:
    redis = _FakeRedis()
    lock = RedisExternalChannelConversationLock(
        cast(Any, redis),
        lease_ttl_seconds=1.0,
        renewal_interval_seconds=0.2,
    )
    async with lock.acquire(scope=_scope(), deadline=_deadline()) as owned:
        await owned.assert_owned()
        redis.unavailable = True
        with pytest.raises(ExternalChannelConversationLockUnavailable):
            await owned.assert_owned()
        redis.unavailable = False
