"""Backend-neutral Runtime Web capacity conformance tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from azents_runtime_control.runtime_web_capacity import (
    ActiveCapacityStream,
    BufferGrant,
    CapacityDirection,
    CapacityProfile,
    CapacityProtocol,
    CapacitySnapshot,
    CapacityState,
    InMemoryRuntimeWebCapacityCoordinator,
    RedisRuntimeWebCapacityCoordinator,
    RuntimeWebCapacityCoordinator,
    TokenBucketState,
)


class RedisStoreUnavailable(Exception):
    """Expected test Redis availability failure."""


class Clock:
    """Deterministic monotonic millisecond test clock."""

    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value


class MemoryRedisStore:
    """Content-free deterministic Redis storage double."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail_get = False
        self.fail_set = False

    async def get(self, name: str) -> bytes | None:
        if self.fail_get:
            raise RedisStoreUnavailable
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> object:
        if self.fail_set:
            raise RedisStoreUnavailable
        if ex <= 0:
            raise ValueError("Redis test TTL must be positive")
        self.values[name] = value.encode()
        return True


class BlockingRedisStore(MemoryRedisStore):
    """Redis double that exposes concurrent SET ordering deterministically."""

    def __init__(self) -> None:
        super().__init__()
        self.block_next_set = False
        self.set_started = asyncio.Event()
        self.release_set = asyncio.Event()
        self.active_sets = 0
        self.maximum_active_sets = 0

    async def set(self, name: str, value: str, *, ex: int) -> object:
        self.active_sets += 1
        self.maximum_active_sets = max(self.maximum_active_sets, self.active_sets)
        try:
            if self.block_next_set:
                self.block_next_set = False
                self.set_started.set()
                await self.release_set.wait()
            return await super().set(name, value, ex=ex)
        finally:
            self.active_sets -= 1


CoordinatorFactory = Callable[
    [Clock, CapacityProfile],
    Awaitable[RuntimeWebCapacityCoordinator],
]


async def _memory_factory(
    clock: Clock, profile: CapacityProfile
) -> RuntimeWebCapacityCoordinator:
    return InMemoryRuntimeWebCapacityCoordinator(
        epoch="epoch-1",
        profile=profile,
        monotonic_clock_milliseconds=clock,
    )


async def _redis_factory(
    clock: Clock, profile: CapacityProfile
) -> RuntimeWebCapacityCoordinator:
    return await RedisRuntimeWebCapacityCoordinator.create(
        redis=MemoryRedisStore(),
        key="runtime-web:capacity:test",
        epoch="epoch-1",
        profile=profile,
        monotonic_clock_milliseconds=clock,
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )


FACTORIES: tuple[CoordinatorFactory, ...] = (_memory_factory, _redis_factory)


def _profile() -> CapacityProfile:
    return CapacityProfile(
        maximum_active_streams=2,
        maximum_sse_streams=1,
        maximum_websocket_streams=1,
        maximum_pending_opens=2,
        maximum_buffer_bytes=1024,
        inbound_bytes_per_second=100,
        outbound_bytes_per_second=100,
        burst_bytes=100,
    )


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_open_and_protocol_limits(
    factory: CoordinatorFactory,
) -> None:
    coordinator = await factory(Clock(), _profile())
    assert await coordinator.begin_open(1)
    assert await coordinator.accept_open(ActiveCapacityStream(1, CapacityProtocol.SSE))
    assert await coordinator.begin_open(2)
    assert not await coordinator.accept_open(
        ActiveCapacityStream(2, CapacityProtocol.SSE)
    )
    await coordinator.reject_open(2)
    assert await coordinator.begin_open(3)
    assert await coordinator.accept_open(
        ActiveCapacityStream(3, CapacityProtocol.WEBSOCKET)
    )
    assert await coordinator.begin_open(4)
    assert not await coordinator.accept_open(
        ActiveCapacityStream(4, CapacityProtocol.HTTP)
    )


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_buffer_grants_are_idempotent_and_bounded(
    factory: CoordinatorFactory,
) -> None:
    coordinator = await factory(Clock(), _profile())
    assert await coordinator.reserve_buffer(BufferGrant("gateway", 800))
    assert await coordinator.reserve_buffer(BufferGrant("gateway", 800))
    assert not await coordinator.reserve_buffer(BufferGrant("runner", 225))
    with pytest.raises(ValueError, match="changed size"):
        await coordinator.reserve_buffer(BufferGrant("gateway", 801))
    await coordinator.release_buffer("gateway")
    assert await coordinator.reserve_buffer(BufferGrant("runner", 225))


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_reclassifies_http_as_sse(
    factory: CoordinatorFactory,
) -> None:
    coordinator = await factory(Clock(), _profile())
    assert await coordinator.begin_open(1)
    assert await coordinator.accept_open(ActiveCapacityStream(1, CapacityProtocol.HTTP))
    assert await coordinator.classify_stream(1, CapacityProtocol.SSE)
    snapshot = await coordinator.snapshot()
    assert snapshot.active_sse_streams == 1


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_bandwidth_refills_from_injected_clock(
    factory: CoordinatorFactory,
) -> None:
    clock = Clock()
    coordinator = await factory(clock, _profile())
    assert await coordinator.acquire_bandwidth(CapacityDirection.OUTBOUND, 100)
    assert not await coordinator.acquire_bandwidth(CapacityDirection.OUTBOUND, 1)
    clock.value = 500
    assert await coordinator.acquire_bandwidth(CapacityDirection.OUTBOUND, 50)


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_reconciles_complete_live_owner_usage(
    factory: CoordinatorFactory,
) -> None:
    coordinator = await factory(Clock(), _profile())
    state = CapacityState(
        epoch="epoch-2",
        pending_stream_ids=(),
        active_streams=(
            ActiveCapacityStream(7, CapacityProtocol.HTTP),
            ActiveCapacityStream(8, CapacityProtocol.WEBSOCKET),
        ),
        buffer_grants=(BufferGrant("owner", 512),),
        inbound=TokenBucketState(
            tokens_milli_bytes=75_000,
            updated_at_milliseconds=500,
        ),
        outbound=TokenBucketState(
            tokens_milli_bytes=25_000,
            updated_at_milliseconds=500,
        ),
        degraded=False,
    )
    await coordinator.reconcile(state)
    assert await coordinator.export_state() == state
    assert await coordinator.snapshot() == CapacitySnapshot(
        epoch="epoch-2",
        pending_opens=0,
        active_streams=2,
        active_sse_streams=0,
        active_websocket_streams=1,
        buffer_bytes=512,
        degraded=False,
    )


@pytest.mark.parametrize("factory", FACTORIES)
async def test_capacity_backend_duplicate_stream_identity_is_rejected(
    factory: CoordinatorFactory,
) -> None:
    coordinator = await factory(Clock(), _profile())
    assert await coordinator.begin_open(1)
    with pytest.raises(ValueError, match="already registered"):
        await coordinator.begin_open(1)


async def test_redis_backend_restores_only_the_same_epoch() -> None:
    redis = MemoryRedisStore()
    clock = Clock()
    first = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:restore",
        epoch="epoch-1",
        profile=_profile(),
        monotonic_clock_milliseconds=clock,
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    assert await first.begin_open(1)
    restored = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:restore",
        epoch="epoch-1",
        profile=_profile(),
        monotonic_clock_milliseconds=clock,
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    assert (await restored.export_state()).pending_stream_ids == (1,)

    reset = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:restore",
        epoch="epoch-2",
        profile=_profile(),
        monotonic_clock_milliseconds=clock,
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    assert await reset.export_state() == CapacityState(
        epoch="epoch-2",
        pending_stream_ids=(),
        active_streams=(),
        buffer_grants=(),
        inbound=TokenBucketState(
            tokens_milli_bytes=100_000,
            updated_at_milliseconds=0,
        ),
        outbound=TokenBucketState(
            tokens_milli_bytes=100_000,
            updated_at_milliseconds=0,
        ),
        degraded=False,
    )


async def test_redis_backend_continues_in_memory_across_get_and_set_failures() -> None:
    redis = MemoryRedisStore()
    redis.fail_get = True
    coordinator = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:failure",
        epoch="epoch-1",
        profile=_profile(),
        monotonic_clock_milliseconds=Clock(),
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    assert (await coordinator.snapshot()).degraded

    redis.fail_get = False
    redis.fail_set = True
    assert await coordinator.begin_open(1)
    failed_state = await coordinator.export_state()
    assert failed_state.pending_stream_ids == (1,)
    assert failed_state.degraded

    redis.fail_set = False
    assert await coordinator.begin_open(2)
    recovered_state = await coordinator.export_state()
    assert recovered_state.pending_stream_ids == (1, 2)
    assert not recovered_state.degraded


async def test_redis_backend_serializes_mutation_snapshot_and_set() -> None:
    redis = BlockingRedisStore()
    coordinator = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:ordering",
        epoch="epoch-1",
        profile=_profile(),
        monotonic_clock_milliseconds=Clock(),
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    redis.block_next_set = True
    first = asyncio.create_task(coordinator.begin_open(1))
    await redis.set_started.wait()
    second = asyncio.create_task(coordinator.begin_open(2))
    redis.release_set.set()
    assert await first
    assert await second
    assert redis.maximum_active_sets == 1

    restored = await RedisRuntimeWebCapacityCoordinator.create(
        redis=redis,
        key="runtime-web:capacity:ordering",
        epoch="epoch-1",
        profile=_profile(),
        monotonic_clock_milliseconds=Clock(),
        ttl_seconds=60,
        recoverable_errors=(RedisStoreUnavailable,),
    )
    assert (await restored.export_state()).pending_stream_ids == (1, 2)
