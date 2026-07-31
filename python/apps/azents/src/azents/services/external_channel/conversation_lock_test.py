"""External conversation lock contract tests."""

import asyncio
import datetime
from collections.abc import Iterator
from typing import Any, cast

import pytest
from testcontainers.redis import RedisContainer

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.core.redis import create_redis_client
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


async def _record_durable_acceptance(
    durable_guard: asyncio.Lock,
    durable_positions: list[str],
    outcomes: list[str],
) -> None:
    """Simulate the fenced PostgreSQL position compare-and-set."""
    async with durable_guard:
        if not durable_positions:
            durable_positions.append("trigger")
            outcomes.append("accepted")
        else:
            outcomes.append("duplicate")


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


@pytest.mark.asyncio
async def test_expired_deadline_does_not_create_redis_operation() -> None:
    created = False

    class _NeverCalledRedis:
        def set(
            self,
            _key: str,
            _value: str,
            *,
            nx: bool,
            px: int,
        ) -> asyncio.Future[object]:
            del nx, px
            nonlocal created
            created = True
            return asyncio.get_running_loop().create_future()

    lock = RedisExternalChannelConversationLock(cast(Any, _NeverCalledRedis()))
    with pytest.raises(ExternalChannelConversationLockTimeout):
        async with lock.acquire(scope=_scope(), deadline=_deadline(-1)):
            pass

    assert created is False


@pytest.mark.asyncio
async def test_memory_lock_replicas_overlap_but_durable_acceptance_converges() -> None:
    locks = (
        InMemoryExternalChannelConversationLock(),
        InMemoryExternalChannelConversationLock(),
    )
    start = asyncio.Event()
    both_acquired = asyncio.Event()
    active_guard = asyncio.Lock()
    durable_guard = asyncio.Lock()
    active = 0
    maximum_active = 0
    durable_positions: list[str] = []
    outcomes: list[str] = []

    async def ingest(lock: InMemoryExternalChannelConversationLock) -> None:
        nonlocal active, maximum_active
        await start.wait()
        async with lock.acquire(scope=_scope(), deadline=_deadline(5.0)) as lease:
            await lease.assert_owned()
            async with active_guard:
                active += 1
                maximum_active = max(maximum_active, active)
                if active == len(locks):
                    both_acquired.set()
            await both_acquired.wait()
            await _record_durable_acceptance(
                durable_guard,
                durable_positions,
                outcomes,
            )
            async with active_guard:
                active -= 1

    tasks = [asyncio.create_task(ingest(lock)) for lock in locks]
    start.set()
    async with asyncio.timeout(5.0):
        await asyncio.gather(*tasks)

    assert maximum_active == 2
    assert sorted(outcomes) == ["accepted", "duplicate"]
    assert durable_positions == ["trigger"]


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


@pytest.fixture(scope="module")
def redis_container(
    check_docker_availability: None,
) -> Iterator[RedisContainer]:
    del check_docker_availability
    with RedisContainer("redis:7.4-alpine") as container:
        yield container


@pytest.mark.asyncio
async def test_real_redis_lock_replicas_serialize_and_accept_once(
    redis_container: RedisContainer,
) -> None:
    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(redis_container.port))
    clients = (
        create_redis_client(f"redis://{host}:{port}"),
        create_redis_client(f"redis://{host}:{port}"),
    )
    locks = (
        RedisExternalChannelConversationLock(
            clients[0],
            key_prefix="azents:test:external-channel:conversation",
            lease_ttl_seconds=2.0,
            renewal_interval_seconds=0.2,
        ),
        RedisExternalChannelConversationLock(
            clients[1],
            key_prefix="azents:test:external-channel:conversation",
            lease_ttl_seconds=2.0,
            renewal_interval_seconds=0.2,
        ),
    )
    first_acquired = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    second_acquired = asyncio.Event()
    durable_guard = asyncio.Lock()
    durable_positions: list[str] = []
    outcomes: list[str] = []

    async def first() -> None:
        async with locks[0].acquire(
            scope=_scope(),
            deadline=_deadline(5.0),
        ) as lease:
            await lease.assert_owned()
            first_acquired.set()
            await release_first.wait()
            await _record_durable_acceptance(
                durable_guard,
                durable_positions,
                outcomes,
            )

    async def second() -> None:
        second_started.set()
        async with locks[1].acquire(
            scope=_scope(),
            deadline=_deadline(5.0),
        ) as lease:
            await lease.assert_owned()
            second_acquired.set()
            await _record_durable_acceptance(
                durable_guard,
                durable_positions,
                outcomes,
            )

    first_task = asyncio.create_task(first())
    second_task: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5.0):
            await first_acquired.wait()
        second_task = asyncio.create_task(second())
        async with asyncio.timeout(5.0):
            await second_started.wait()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await second_acquired.wait()
        release_first.set()
        async with asyncio.timeout(5.0):
            await asyncio.gather(first_task, second_task)

        assert second_acquired.is_set()
        assert outcomes == ["accepted", "duplicate"]
        assert durable_positions == ["trigger"]
    finally:
        release_first.set()
        tasks = [first_task]
        if second_task is not None:
            tasks.append(second_task)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(client.aclose() for client in clients))
