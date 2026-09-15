"""Backend-neutral ephemeral Runtime Web soft-capacity coordination."""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import json
from collections.abc import Callable
from typing import Protocol, Self


class CapacityRedisStore(Protocol):
    """Minimal supported Redis client surface used by capacity coordination."""

    async def get(self, name: str) -> bytes | str | None: ...

    async def set(self, name: str, value: str, *, ex: int) -> object: ...


class CapacityProtocol(enum.StrEnum):
    """Logical stream class used by Runtime-scoped capacity."""

    HTTP = "http"
    SSE = "sse"
    WEBSOCKET = "websocket"


class CapacityDirection(enum.StrEnum):
    """Bandwidth direction at the Runtime boundary."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclasses.dataclass(frozen=True)
class CapacityProfile:
    """Validated Runtime soft limits and hard burst bound."""

    maximum_active_streams: int
    maximum_sse_streams: int
    maximum_websocket_streams: int
    maximum_pending_opens: int
    maximum_buffer_bytes: int
    inbound_bytes_per_second: int
    outbound_bytes_per_second: int
    burst_bytes: int

    def __post_init__(self) -> None:
        """Reject non-positive or internally inconsistent capacity."""
        for value in dataclasses.astuple(self):
            if value <= 0:
                raise ValueError("Runtime Web capacity values must be positive")
        if self.maximum_sse_streams > self.maximum_active_streams:
            raise ValueError("SSE capacity exceeds total stream capacity")
        if self.maximum_websocket_streams > self.maximum_active_streams:
            raise ValueError("WebSocket capacity exceeds total stream capacity")


@dataclasses.dataclass(frozen=True)
class ActiveCapacityStream:
    """One content-free active logical stream."""

    stream_id: int
    protocol: CapacityProtocol

    def __post_init__(self) -> None:
        """Reject invalid stream identity."""
        if self.stream_id <= 0:
            raise ValueError("Runtime Web capacity stream ID must be positive")


@dataclasses.dataclass(frozen=True)
class BufferGrant:
    """One process-local buffer grant charged to the Runtime."""

    grant_id: str
    size_bytes: int

    def __post_init__(self) -> None:
        """Reject invalid grant identity or size."""
        if not self.grant_id:
            raise ValueError("Runtime Web buffer grant ID is required")
        if self.size_bytes <= 0:
            raise ValueError("Runtime Web buffer grant size must be positive")


@dataclasses.dataclass(frozen=True)
class TokenBucketState:
    """Deterministic integer token state shared by both backends."""

    tokens_milli_bytes: int
    updated_at_milliseconds: int

    def __post_init__(self) -> None:
        """Reject negative token state."""
        if self.tokens_milli_bytes < 0 or self.updated_at_milliseconds < 0:
            raise ValueError("Runtime Web token state must not be negative")


@dataclasses.dataclass(frozen=True)
class CapacityState:
    """Complete ephemeral state used for backend parity and recovery."""

    epoch: str
    pending_stream_ids: tuple[int, ...]
    active_streams: tuple[ActiveCapacityStream, ...]
    buffer_grants: tuple[BufferGrant, ...]
    inbound: TokenBucketState
    outbound: TokenBucketState
    degraded: bool

    def __post_init__(self) -> None:
        """Reject incomplete epoch identity."""
        if not self.epoch:
            raise ValueError("Runtime Web capacity epoch is required")


@dataclasses.dataclass(frozen=True)
class CapacitySnapshot:
    """Content-free current capacity usage."""

    epoch: str
    pending_opens: int
    active_streams: int
    active_sse_streams: int
    active_websocket_streams: int
    buffer_bytes: int
    degraded: bool


class RuntimeWebCapacityCoordinator(Protocol):
    """Equivalent contract implemented by in-memory and Redis backends."""

    async def begin_open(self, stream_id: int) -> bool: ...

    async def accept_open(self, stream: ActiveCapacityStream) -> bool: ...

    async def classify_stream(
        self, stream_id: int, protocol: CapacityProtocol
    ) -> bool: ...

    async def reject_open(self, stream_id: int) -> None: ...

    async def release_stream(self, stream_id: int) -> None: ...

    async def reserve_buffer(self, grant: BufferGrant) -> bool: ...

    async def release_buffer(self, grant_id: str) -> None: ...

    async def acquire_bandwidth(
        self, direction: CapacityDirection, size_bytes: int
    ) -> bool: ...

    async def reconcile(self, state: CapacityState) -> None: ...

    async def export_state(self) -> CapacityState: ...

    async def snapshot(self) -> CapacitySnapshot: ...


@dataclasses.dataclass
class _TokenBucket:
    rate: int
    capacity_milli_bytes: int
    tokens_milli_bytes: int
    updated_at_milliseconds: int

    def acquire(self, size_bytes: int, now_milliseconds: int) -> bool:
        if now_milliseconds < self.updated_at_milliseconds:
            raise ValueError("Runtime Web monotonic clock moved backwards")
        elapsed = now_milliseconds - self.updated_at_milliseconds
        self.tokens_milli_bytes = min(
            self.capacity_milli_bytes,
            self.tokens_milli_bytes + elapsed * self.rate,
        )
        self.updated_at_milliseconds = now_milliseconds
        required = size_bytes * 1000
        if required > self.tokens_milli_bytes:
            return False
        self.tokens_milli_bytes -= required
        return True

    def state(self) -> TokenBucketState:
        return TokenBucketState(
            tokens_milli_bytes=self.tokens_milli_bytes,
            updated_at_milliseconds=self.updated_at_milliseconds,
        )


class InMemoryRuntimeWebCapacityCoordinator:
    """Complete Owner-local ephemeral capacity implementation."""

    def __init__(
        self,
        *,
        epoch: str,
        profile: CapacityProfile,
        monotonic_clock_milliseconds: Callable[[], int],
    ) -> None:
        if not epoch:
            raise ValueError("Runtime Web capacity epoch is required")
        self.epoch = epoch
        self.profile = profile
        self.monotonic_clock_milliseconds = monotonic_clock_milliseconds
        now = monotonic_clock_milliseconds()
        if now < 0:
            raise ValueError("Runtime Web monotonic clock must not be negative")
        capacity = profile.burst_bytes * 1000
        self.inbound = _TokenBucket(
            rate=profile.inbound_bytes_per_second,
            capacity_milli_bytes=capacity,
            tokens_milli_bytes=capacity,
            updated_at_milliseconds=now,
        )
        self.outbound = _TokenBucket(
            rate=profile.outbound_bytes_per_second,
            capacity_milli_bytes=capacity,
            tokens_milli_bytes=capacity,
            updated_at_milliseconds=now,
        )
        self.pending: set[int] = set()
        self.active: dict[int, CapacityProtocol] = {}
        self.buffer_grants: dict[str, int] = {}
        self.degraded = False
        self.lock = asyncio.Lock()

    async def begin_open(self, stream_id: int) -> bool:
        """Reserve one pending-open slot."""
        if stream_id <= 0:
            raise ValueError("Runtime Web capacity stream ID must be positive")
        async with self.lock:
            if stream_id in self.pending or stream_id in self.active:
                raise ValueError("Runtime Web capacity stream ID is already registered")
            if len(self.pending) >= self.profile.maximum_pending_opens:
                return False
            self.pending.add(stream_id)
            return True

    async def accept_open(self, stream: ActiveCapacityStream) -> bool:
        """Move one pending stream into active capacity."""
        async with self.lock:
            if stream.stream_id not in self.pending:
                raise ValueError("Runtime Web open was not pending")
            if not self._allows_protocol(stream.protocol):
                return False
            self.pending.remove(stream.stream_id)
            self.active[stream.stream_id] = stream.protocol
            return True

    async def classify_stream(self, stream_id: int, protocol: CapacityProtocol) -> bool:
        """Reclassify an accepted HTTP stream after response inspection."""
        async with self.lock:
            existing = self.active.get(stream_id)
            if existing is None:
                raise ValueError("Runtime Web capacity stream is not active")
            if existing is protocol:
                return True
            if existing is not CapacityProtocol.HTTP:
                raise ValueError("Runtime Web capacity stream was already classified")
            if not self._allows_protocol(protocol, include_total=False):
                return False
            self.active[stream_id] = protocol
            return True

    async def reject_open(self, stream_id: int) -> None:
        """Release one pending open."""
        async with self.lock:
            self.pending.discard(stream_id)

    async def release_stream(self, stream_id: int) -> None:
        """Release pending or active stream usage."""
        async with self.lock:
            self.pending.discard(stream_id)
            self.active.pop(stream_id, None)

    async def reserve_buffer(self, grant: BufferGrant) -> bool:
        """Reserve one exact process-local buffer grant."""
        async with self.lock:
            existing = self.buffer_grants.get(grant.grant_id)
            if existing is not None:
                if existing != grant.size_bytes:
                    raise ValueError("Runtime Web buffer grant changed size")
                return True
            if sum(self.buffer_grants.values()) + grant.size_bytes > (
                self.profile.maximum_buffer_bytes
            ):
                return False
            self.buffer_grants[grant.grant_id] = grant.size_bytes
            return True

    async def release_buffer(self, grant_id: str) -> None:
        """Release one buffer grant idempotently."""
        if not grant_id:
            raise ValueError("Runtime Web buffer grant ID is required")
        async with self.lock:
            self.buffer_grants.pop(grant_id, None)

    async def acquire_bandwidth(
        self, direction: CapacityDirection, size_bytes: int
    ) -> bool:
        """Consume one bounded bandwidth grant."""
        if size_bytes <= 0:
            raise ValueError("Runtime Web bandwidth size must be positive")
        async with self.lock:
            bucket = (
                self.inbound
                if direction is CapacityDirection.INBOUND
                else self.outbound
            )
            return bucket.acquire(size_bytes, self.monotonic_clock_milliseconds())

    async def reconcile(self, state: CapacityState) -> None:
        """Replace state from a complete live Owner snapshot."""
        pending = set(state.pending_stream_ids)
        active = {stream.stream_id: stream.protocol for stream in state.active_streams}
        grants = {grant.grant_id: grant.size_bytes for grant in state.buffer_grants}
        if len(pending) != len(state.pending_stream_ids):
            raise ValueError("Runtime Web pending stream IDs must be unique")
        if len(active) != len(state.active_streams):
            raise ValueError("Runtime Web active stream IDs must be unique")
        if pending & active.keys():
            raise ValueError("Runtime Web pending and active streams overlap")
        if len(pending) > self.profile.maximum_pending_opens:
            raise ValueError("Runtime Web reconciled pending usage exceeds hard limit")
        self._validate_active(active)
        if len(grants) != len(state.buffer_grants):
            raise ValueError("Runtime Web buffer grant IDs must be unique")
        if sum(grants.values()) > self.profile.maximum_buffer_bytes:
            raise ValueError("Runtime Web reconciled buffer usage exceeds hard limit")
        capacity = self.profile.burst_bytes * 1000
        for bucket in (state.inbound, state.outbound):
            if bucket.tokens_milli_bytes > capacity:
                raise ValueError("Runtime Web reconciled bandwidth exceeds burst limit")
        async with self.lock:
            self.epoch = state.epoch
            self.pending = pending
            self.active = active
            self.buffer_grants = grants
            self.inbound.tokens_milli_bytes = state.inbound.tokens_milli_bytes
            self.inbound.updated_at_milliseconds = state.inbound.updated_at_milliseconds
            self.outbound.tokens_milli_bytes = state.outbound.tokens_milli_bytes
            self.outbound.updated_at_milliseconds = (
                state.outbound.updated_at_milliseconds
            )
            self.degraded = state.degraded

    async def export_state(self) -> CapacityState:
        """Export complete deterministic backend state."""
        async with self.lock:
            return CapacityState(
                epoch=self.epoch,
                pending_stream_ids=tuple(sorted(self.pending)),
                active_streams=tuple(
                    ActiveCapacityStream(stream_id, protocol)
                    for stream_id, protocol in sorted(self.active.items())
                ),
                buffer_grants=tuple(
                    BufferGrant(grant_id, size)
                    for grant_id, size in sorted(self.buffer_grants.items())
                ),
                inbound=self.inbound.state(),
                outbound=self.outbound.state(),
                degraded=self.degraded,
            )

    async def snapshot(self) -> CapacitySnapshot:
        """Return current content-free capacity usage."""
        async with self.lock:
            return CapacitySnapshot(
                epoch=self.epoch,
                pending_opens=len(self.pending),
                active_streams=len(self.active),
                active_sse_streams=self._protocol_count(CapacityProtocol.SSE),
                active_websocket_streams=self._protocol_count(
                    CapacityProtocol.WEBSOCKET
                ),
                buffer_bytes=sum(self.buffer_grants.values()),
                degraded=self.degraded,
            )

    async def set_degraded(self, degraded: bool) -> None:
        """Set the observable backend degradation state."""
        async with self.lock:
            self.degraded = degraded

    def _allows_protocol(
        self, protocol: CapacityProtocol, *, include_total: bool = True
    ) -> bool:
        if include_total and len(self.active) >= self.profile.maximum_active_streams:
            return False
        if protocol is CapacityProtocol.SSE:
            return self._protocol_count(protocol) < self.profile.maximum_sse_streams
        if protocol is CapacityProtocol.WEBSOCKET:
            return (
                self._protocol_count(protocol) < self.profile.maximum_websocket_streams
            )
        return True

    def _validate_active(self, active: dict[int, CapacityProtocol]) -> None:
        if len(active) > self.profile.maximum_active_streams:
            raise ValueError("Runtime Web reconciled active usage exceeds hard limit")
        for protocol, maximum in (
            (CapacityProtocol.SSE, self.profile.maximum_sse_streams),
            (CapacityProtocol.WEBSOCKET, self.profile.maximum_websocket_streams),
        ):
            if sum(value is protocol for value in active.values()) > maximum:
                raise ValueError(
                    f"Runtime Web reconciled {protocol.value} usage exceeds hard limit"
                )

    def _protocol_count(self, protocol: CapacityProtocol) -> int:
        return sum(value is protocol for value in self.active.values())


class RedisRuntimeWebCapacityCoordinator:
    """Availability-safe Redis projection over exact in-memory semantics."""

    def __init__(
        self,
        *,
        redis: CapacityRedisStore,
        key: str,
        memory: InMemoryRuntimeWebCapacityCoordinator,
        ttl_seconds: int,
        recoverable_errors: tuple[type[Exception], ...],
    ) -> None:
        if not key or ttl_seconds <= 0 or not recoverable_errors:
            raise ValueError("Runtime Web Redis capacity settings are invalid")
        self.redis = redis
        self.key = key
        self.memory = memory
        self.ttl_seconds = ttl_seconds
        self.recoverable_errors = recoverable_errors
        self.lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        *,
        redis: CapacityRedisStore,
        key: str,
        epoch: str,
        profile: CapacityProfile,
        monotonic_clock_milliseconds: Callable[[], int],
        ttl_seconds: int,
        recoverable_errors: tuple[type[Exception], ...],
    ) -> Self:
        """Create the Redis backend and restore complete ephemeral state if present."""
        memory = InMemoryRuntimeWebCapacityCoordinator(
            epoch=epoch,
            profile=profile,
            monotonic_clock_milliseconds=monotonic_clock_milliseconds,
        )
        coordinator = cls(
            redis=redis,
            key=key,
            memory=memory,
            ttl_seconds=ttl_seconds,
            recoverable_errors=recoverable_errors,
        )
        try:
            raw = await redis.get(key)
        except recoverable_errors:
            await memory.set_degraded(True)
            return coordinator
        if raw is not None:
            restored = _decode_state(raw)
            if restored.epoch == epoch:
                await memory.reconcile(restored)
        await coordinator._persist_or_degrade()
        return coordinator

    async def begin_open(self, stream_id: int) -> bool:
        async with self.lock:
            result = await self.memory.begin_open(stream_id)
            await self._persist_or_degrade()
            return result

    async def accept_open(self, stream: ActiveCapacityStream) -> bool:
        async with self.lock:
            result = await self.memory.accept_open(stream)
            await self._persist_or_degrade()
            return result

    async def classify_stream(self, stream_id: int, protocol: CapacityProtocol) -> bool:
        async with self.lock:
            result = await self.memory.classify_stream(stream_id, protocol)
            await self._persist_or_degrade()
            return result

    async def reject_open(self, stream_id: int) -> None:
        async with self.lock:
            await self.memory.reject_open(stream_id)
            await self._persist_or_degrade()

    async def release_stream(self, stream_id: int) -> None:
        async with self.lock:
            await self.memory.release_stream(stream_id)
            await self._persist_or_degrade()

    async def reserve_buffer(self, grant: BufferGrant) -> bool:
        async with self.lock:
            result = await self.memory.reserve_buffer(grant)
            await self._persist_or_degrade()
            return result

    async def release_buffer(self, grant_id: str) -> None:
        async with self.lock:
            await self.memory.release_buffer(grant_id)
            await self._persist_or_degrade()

    async def acquire_bandwidth(
        self, direction: CapacityDirection, size_bytes: int
    ) -> bool:
        async with self.lock:
            result = await self.memory.acquire_bandwidth(direction, size_bytes)
            await self._persist_or_degrade()
            return result

    async def reconcile(self, state: CapacityState) -> None:
        async with self.lock:
            await self.memory.reconcile(state)
            await self._persist_or_degrade()

    async def export_state(self) -> CapacityState:
        async with self.lock:
            return await self.memory.export_state()

    async def snapshot(self) -> CapacitySnapshot:
        async with self.lock:
            return await self.memory.snapshot()

    async def _persist_or_degrade(self) -> None:
        state = dataclasses.replace(
            await self.memory.export_state(),
            degraded=False,
        )
        try:
            await self.redis.set(
                self.key,
                json.dumps(
                    _encode_state(state),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                ex=self.ttl_seconds,
            )
        except self.recoverable_errors:
            await self.memory.set_degraded(True)
            return
        await self.memory.set_degraded(False)


def _encode_state(state: CapacityState) -> dict[str, object]:
    return {
        "active_streams": [
            {"protocol": stream.protocol.value, "stream_id": stream.stream_id}
            for stream in state.active_streams
        ],
        "buffer_grants": [dataclasses.asdict(grant) for grant in state.buffer_grants],
        "degraded": state.degraded,
        "epoch": state.epoch,
        "inbound": dataclasses.asdict(state.inbound),
        "outbound": dataclasses.asdict(state.outbound),
        "pending_stream_ids": list(state.pending_stream_ids),
    }


def _decode_state(raw: bytes | str) -> CapacityState:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Runtime Web Redis capacity state must be an object")
    return CapacityState(
        epoch=str(data["epoch"]),
        pending_stream_ids=tuple(int(value) for value in data["pending_stream_ids"]),
        active_streams=tuple(
            ActiveCapacityStream(
                stream_id=int(value["stream_id"]),
                protocol=CapacityProtocol(str(value["protocol"])),
            )
            for value in data["active_streams"]
        ),
        buffer_grants=tuple(
            BufferGrant(
                grant_id=str(value["grant_id"]), size_bytes=int(value["size_bytes"])
            )
            for value in data["buffer_grants"]
        ),
        inbound=TokenBucketState(**data["inbound"]),
        outbound=TokenBucketState(**data["outbound"]),
        degraded=bool(data["degraded"]),
    )
