"""Persistent Runtime Web Gateway, relay, and Runner gRPC data plane."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import enum
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from typing import NoReturn, Protocol

import grpc
from aiohttp import web
from azents_runtime_control.proto import (
    runtime_web_session_pb2,
    runtime_web_session_pb2_grpc,
)
from azents_runtime_control.runtime_web_capacity import (
    BufferGrant,
    CapacityDirection,
    CapacityProfile,
    CapacityProtocol,
    CapacityRedisStore,
    CapacitySnapshot,
    InMemoryRuntimeWebCapacityCoordinator,
    RedisRuntimeWebCapacityCoordinator,
    RuntimeWebCapacityCoordinator,
)
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MAX_ENVELOPE_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    Header,
    OwnerSessionEpoch,
    RequestHead,
    StreamAuthority,
    StreamProtocol,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session import SessionManager
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeRunnerCredentialAuthenticator,
    RuntimeRunnerCredentialGrpcAuth,
)
from azents.runtime.coordination.data import RuntimeSystemMetricsSample
from azents.runtime.web_session_broker import (
    BrokerStreamKey,
    BrokerTarget,
    RuntimeWebSessionBroker,
)
from azents.runtime.web_session_owner import (
    RuntimeWebAcceptedRunnerSession,
    RuntimeWebAuthenticatedRunnerConnection,
    RuntimeWebOwnedSession,
    RuntimeWebOwnerSessionRegistry,
)
from azents.runtime.web_session_relay import (
    RelaySessionKey,
    RuntimeWebRelayPool,
)

_MAX_QUEUED_ENVELOPES = 32
_MAX_QUEUED_BYTES = 16 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


class RuntimeWebCapacityBackend(enum.StrEnum):
    """Configured soft-capacity projection backend."""

    MEMORY = "memory"
    REDIS = "redis"


@dataclasses.dataclass(frozen=True)
class RuntimeWebCapacityConfig:
    """Validated Owner-scoped soft-capacity configuration."""

    backend: RuntimeWebCapacityBackend
    profile: CapacityProfile
    redis_namespace: str
    redis_ttl_seconds: int

    def __post_init__(self) -> None:
        if not self.redis_namespace or self.redis_ttl_seconds <= 0:
            raise ValueError("Runtime Web capacity Redis settings are invalid")


class RuntimeWebCapacityRegistry:
    """Create one equivalent capacity coordinator per Owner epoch."""

    def __init__(
        self,
        *,
        config: RuntimeWebCapacityConfig,
        redis: CapacityRedisStore,
        monotonic_clock_milliseconds: Callable[[], int],
        recoverable_errors: tuple[type[Exception], ...],
    ) -> None:
        self.config = config
        self.redis = redis
        self.monotonic_clock_milliseconds = monotonic_clock_milliseconds
        self.recoverable_errors = recoverable_errors
        self.coordinators: dict[OwnerSessionEpoch, RuntimeWebCapacityCoordinator] = {}
        self.lock = asyncio.Lock()

    async def get(
        self,
        owner: OwnerSessionEpoch,
    ) -> RuntimeWebCapacityCoordinator:
        """Return the exact Owner-epoch coordinator without durable capacity state."""
        async with self.lock:
            existing = self.coordinators.get(owner)
            if existing is not None:
                return existing
            epoch = (
                f"{owner.owner_boot_id}:{owner.session_lease_id}:"
                f"{owner.lease_generation}"
            )
            if self.config.backend is RuntimeWebCapacityBackend.MEMORY:
                coordinator: RuntimeWebCapacityCoordinator = (
                    InMemoryRuntimeWebCapacityCoordinator(
                        epoch=epoch,
                        profile=self.config.profile,
                        monotonic_clock_milliseconds=(
                            self.monotonic_clock_milliseconds
                        ),
                    )
                )
            else:
                coordinator = await RedisRuntimeWebCapacityCoordinator.create(
                    redis=self.redis,
                    key=(
                        f"{self.config.redis_namespace}:"
                        f"{owner.runtime_id}:{owner.desired_generation}:"
                        f"{owner.runner_generation}"
                    ),
                    epoch=epoch,
                    profile=self.config.profile,
                    monotonic_clock_milliseconds=self.monotonic_clock_milliseconds,
                    ttl_seconds=self.config.redis_ttl_seconds,
                    recoverable_errors=self.recoverable_errors,
                )
            self.coordinators[owner] = coordinator
            return coordinator

    async def snapshots(self) -> tuple[CapacitySnapshot, ...]:
        """Return content-free snapshots for active Owner epochs."""
        async with self.lock:
            coordinators = tuple(self.coordinators.values())
        return tuple([await coordinator.snapshot() for coordinator in coordinators])

    async def release(self, owner: OwnerSessionEpoch) -> None:
        """Drop one ephemeral coordinator when its Owner epoch terminates."""
        async with self.lock:
            self.coordinators.pop(owner, None)


class RuntimeWebOwnedSessionProvider(Protocol):
    """Resolve the exact one-time Owner offer issued on the operation channel."""

    async def owned_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RuntimeWebOwnedSession | None: ...

    async def renew_owner(self, owner: OwnerSessionEpoch) -> bool: ...

    async def mark_owner_draining(self, owner: OwnerSessionEpoch) -> bool: ...

    async def release_owner(self, owner: OwnerSessionEpoch) -> bool: ...


class RuntimeWebRunnerMetricsReader(Protocol):
    """Read bounded ordinary Runner metrics already accepted by Control."""

    async def read_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        current_time: datetime.datetime,
    ) -> list[RuntimeSystemMetricsSample]: ...


class RuntimeWebTrustedPeerContext(Protocol):
    """Transport identity methods required from a trusted gRPC context."""

    def auth_context(self) -> Mapping[str, Iterable[bytes]]: ...

    async def abort(self, code: grpc.StatusCode, details: str) -> NoReturn: ...


class RuntimeWebTrustedPeerAuthenticator:
    """Require one configured role-specific mTLS identity outside local mode."""

    def __init__(
        self,
        *,
        allow_insecure: bool,
        gateway_identities: frozenset[str],
        control_identities: frozenset[str],
    ) -> None:
        if not allow_insecure and (not gateway_identities or not control_identities):
            raise ValueError("Runtime Web trusted peer identities are required")
        self.allow_insecure = allow_insecure
        self.gateway_identities = gateway_identities
        self.control_identities = control_identities

    async def gateway(self, context: RuntimeWebTrustedPeerContext) -> str:
        """Authenticate one Gateway-only peer identity."""
        return await self._authenticate(
            context,
            allowed=self.gateway_identities,
            role="Gateway",
        )

    async def control(self, context: RuntimeWebTrustedPeerContext) -> str:
        """Authenticate one Control-only peer identity."""
        return await self._authenticate(
            context,
            allowed=self.control_identities,
            role="Control",
        )

    async def _authenticate(
        self,
        context: RuntimeWebTrustedPeerContext,
        *,
        allowed: frozenset[str],
        role: str,
    ) -> str:
        if self.allow_insecure:
            return f"insecure-{role.lower()}"
        raw = context.auth_context().get("x509_common_name")
        values = tuple(raw) if isinstance(raw, (tuple, list)) else ()
        identities = tuple(
            value.decode("utf-8") if isinstance(value, bytes) else str(value)
            for value in values
        )
        if len(identities) != 1 or identities[0] not in allowed:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                f"Runtime Web {role} peer identity is not authorized",
            )
            raise AssertionError("unreachable")
        return identities[0]


class _BoundedEnvelopeQueue:
    def __init__(self) -> None:
        self.items: deque[_QueuedEnvelope] = deque()
        self.bytes = 0
        self.stalls = 0
        self.closed = False
        self.condition = asyncio.Condition()

    async def put(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        on_dequeued: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        size = envelope.ByteSize()
        if not 1 <= size <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web session envelope size is invalid")
        async with self.condition:
            if (
                len(self.items) >= _MAX_QUEUED_ENVELOPES
                or self.bytes + size > _MAX_QUEUED_BYTES
            ):
                self.stalls += 1
            await self.condition.wait_for(
                lambda: (
                    (
                        len(self.items) < _MAX_QUEUED_ENVELOPES
                        and self.bytes + size <= _MAX_QUEUED_BYTES
                    )
                    or self.closed
                )
            )
            if self.closed:
                raise RuntimeError("Runtime Web session response queue is closed")
            copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            copied.CopyFrom(envelope)
            self.items.append(_QueuedEnvelope(copied, on_dequeued))
            self.bytes += size
            self.condition.notify_all()

    async def __aiter__(
        self,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        while True:
            async with self.condition:
                await self.condition.wait_for(lambda: bool(self.items) or self.closed)
                if not self.items:
                    return
                queued = self.items.popleft()
                self.bytes -= queued.envelope.ByteSize()
                self.condition.notify_all()
            if queued.on_dequeued is not None:
                await queued.on_dequeued()
            yield queued.envelope

    async def close(self) -> None:
        async with self.condition:
            self.closed = True
            queued = tuple(self.items)
            self.items.clear()
            self.bytes = 0
            self.condition.notify_all()
        results = await asyncio.gather(
            *(item.on_dequeued() for item in queued if item.on_dequeued is not None),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup(
                "Runtime Web queue release failed",
                errors,
            )


@dataclasses.dataclass(frozen=True)
class _SourceSession:
    source_key: str
    session_id: str
    peer_boot_id: str
    owner: OwnerSessionEpoch | None
    queue: _BoundedEnvelopeQueue


@dataclasses.dataclass(frozen=True)
class _QueuedEnvelope:
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    on_dequeued: Callable[[], Awaitable[None]] | None


@dataclasses.dataclass(frozen=True)
class _StreamBinding:
    source: _SourceSession
    key: BrokerStreamKey
    target: BrokerTarget
    broker: RuntimeWebSessionBroker | None
    capacity_stream_id: int | None
    runner_stream_id: int | None
    protocol: CapacityProtocol


@dataclasses.dataclass(frozen=True)
class _RunnerSourceBinding:
    source: _SourceSession
    source_stream_id: int


class _RuntimeWebCapacityRejected(RuntimeError):
    """One exact Owner-capacity rejection before queue admission."""


class _RuntimeWebControlDraining(RuntimeError):
    """Reject one session registered after Control drain begins."""


class _FixedRouter:
    def __init__(self, target: BrokerTarget) -> None:
        self.target = target

    async def resolve(self, authority: StreamAuthority) -> BrokerTarget | None:
        if (
            authority.runtime_id,
            authority.desired_generation,
            authority.runner_generation,
        ) != (
            self.target.owner.runtime_id,
            self.target.owner.desired_generation,
            self.target.owner.runner_generation,
        ):
            return None
        return self.target


class _RunnerConnection:
    def __init__(
        self,
        *,
        accepted: RuntimeWebAcceptedRunnerSession,
        control_boot_id: str,
    ) -> None:
        self.accepted = accepted
        self.control_boot_id = control_boot_id
        self.queue = _BoundedEnvelopeQueue()
        self.next_stream_id = 1
        self.sources: dict[int, _RunnerSourceBinding] = {}
        self.source_ids: dict[tuple[str, int], int] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()
        self.source_response_session_consumed: dict[str, int] = {}
        self.runner_response_session_consumed = 0
        self.runner_request_stream_consumed: dict[int, int] = {}
        self.runner_request_session_consumed = 0
        self.source_request_session_consumed: dict[str, int] = {}
        self.lock = asyncio.Lock()

    async def send(
        self,
        source: _SourceSession,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        on_dequeued: Callable[[], Awaitable[None]] | None = None,
    ) -> int:
        """Remap one source stream into the Runner session namespace."""
        source_key = (source.source_key, envelope.stream_id)
        async with self.lock:
            runner_stream_id = self.source_ids.get(source_key)
            if runner_stream_id is None:
                if envelope.WhichOneof("payload") != "open":
                    raise ValueError("Runtime Web Runner source stream is unknown")
                runner_stream_id = self.next_stream_id
                self.next_stream_id += 1
                self.source_ids[source_key] = runner_stream_id
                self.sources[runner_stream_id] = _RunnerSourceBinding(
                    source=source,
                    source_stream_id=envelope.stream_id,
                )
            forwarded = _owner_envelope(
                envelope,
                owner=self.accepted.owner,
                peer_boot_id=self.control_boot_id,
                stream_id=runner_stream_id,
            )
            if envelope.WhichOneof("payload") == "window_update":
                if (
                    envelope.window_update.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
                ):
                    raise ValueError(
                        "Runtime Web source response credit direction is invalid"
                    )
                previous = self.source_response_session_consumed.get(
                    source.source_key,
                    0,
                )
                current = envelope.window_update.session_consumed_total
                if current < previous:
                    raise ValueError(
                        "Runtime Web source response consumed total decreased"
                    )
                self.source_response_session_consumed[source.source_key] = current
                self.runner_response_session_consumed += current - previous
                forwarded.window_update.session_consumed_total = (
                    self.runner_response_session_consumed
                )
            await self.queue.put(forwarded, on_dequeued=on_dequeued)
            return runner_stream_id

    async def source_binding(
        self,
        runner_stream_id: int,
    ) -> _RunnerSourceBinding | None:
        async with self.lock:
            return self.sources.get(runner_stream_id)

    async def terminal(self, runner_stream_id: int) -> bool:
        async with self.lock:
            return runner_stream_id in self.tombstone_set

    async def receive(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        on_dequeued: Callable[[], Awaitable[None]] | None = None,
    ) -> BrokerStreamKey:
        """Return one Runner response to the exact source session."""
        if not _matches_owner(envelope, self.accepted.owner):
            raise ValueError("Runtime Web Runner response Owner epoch is stale")
        if envelope.peer_boot_id != self.accepted.runner_boot_id:
            raise ValueError("Runtime Web Runner response peer identity changed")
        async with self.lock:
            binding = self.sources.get(envelope.stream_id)
            if binding is None:
                raise ValueError("Runtime Web Runner response stream is unknown")
            source = binding.source
            translated = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            translated.CopyFrom(envelope)
            translated.session_id = source.session_id
            translated.peer_boot_id = (
                self.accepted.owner.owner_boot_id
                if source.owner is not None
                else self.control_boot_id
            )
            translated.stream_id = binding.source_stream_id
            payload = envelope.WhichOneof("payload")
            if payload == "open_accepted":
                translated.open_accepted.route_path = (
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL
                )
            elif payload == "window_update":
                if (
                    envelope.window_update.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                ):
                    raise ValueError(
                        "Runtime Web Runner request credit direction is invalid"
                    )
                runner_session_total = envelope.window_update.session_consumed_total
                if runner_session_total < self.runner_request_session_consumed:
                    raise ValueError(
                        "Runtime Web Runner request consumed total decreased"
                    )
                previous_stream_total = self.runner_request_stream_consumed.get(
                    envelope.stream_id,
                    0,
                )
                current_stream_total = envelope.window_update.stream_consumed_total
                if current_stream_total < previous_stream_total:
                    raise ValueError(
                        "Runtime Web Runner request stream consumed total decreased"
                    )
                self.runner_request_session_consumed = runner_session_total
                self.runner_request_stream_consumed[envelope.stream_id] = (
                    current_stream_total
                )
                source_total = self.source_request_session_consumed.get(
                    source.source_key,
                    0,
                ) + (current_stream_total - previous_stream_total)
                self.source_request_session_consumed[source.source_key] = source_total
                translated.window_update.session_consumed_total = source_total
        await source.queue.put(translated, on_dequeued=on_dequeued)
        return BrokerStreamKey(source.source_key, binding.source_stream_id)

    async def release(
        self,
        *,
        source_session_id: str,
        source_stream_id: int,
    ) -> None:
        async with self.lock:
            runner_stream_id = self.source_ids.pop(
                (source_session_id, source_stream_id),
                None,
            )
            if runner_stream_id is not None:
                self.sources.pop(runner_stream_id, None)
                self.runner_request_stream_consumed.pop(runner_stream_id, None)
                if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
                    expired = self.tombstones.popleft()
                    self.tombstone_set.remove(expired)
                self.tombstones.append(runner_stream_id)
                self.tombstone_set.add(runner_stream_id)

    async def release_source(self, source_key: str) -> None:
        """Release hop-local credit totals for one closed source session."""
        async with self.lock:
            self.source_response_session_consumed.pop(source_key, None)
            self.source_request_session_consumed.pop(source_key, None)

    async def close(self) -> None:
        async with self.lock:
            sources = tuple(self.sources.items())
            self.sources.clear()
            self.source_ids.clear()
            self.tombstones.clear()
            self.tombstone_set.clear()
            self.source_response_session_consumed.clear()
            self.runner_response_session_consumed = 0
            self.runner_request_stream_consumed.clear()
            self.runner_request_session_consumed = 0
            self.source_request_session_consumed.clear()
        for _runner_stream_id, binding in sources:
            source = binding.source
            reset = _base_response(source, self.control_boot_id)
            reset.stream_id = binding.source_stream_id
            reset.reset.reason = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_OWNER_LOST
            )
            await source.queue.put(reset)
        await self.queue.close()


class RuntimeWebControlDataPlane:
    """Route Gateway and one-hop relay streams to exact Owner Runner sessions."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        route_repository: RuntimeWebSessionRouteRepository,
        owner_replica_id: str,
        control_boot_id: str,
        capacity_registry: RuntimeWebCapacityRegistry,
        relay_pool: RuntimeWebRelayPool,
        runner_metrics: RuntimeWebRunnerMetricsReader,
        clock: Callable[[], datetime.datetime],
        metrics_recoverable_errors: tuple[type[Exception], ...],
        owner_lifecycle: RuntimeWebOwnedSessionProvider,
        long_lived_grace_seconds: float,
        finite_grace_seconds: float,
    ) -> None:
        if (
            not metrics_recoverable_errors
            or long_lived_grace_seconds <= 0
            or finite_grace_seconds <= long_lived_grace_seconds
        ):
            raise ValueError("Runtime Web Control lifecycle settings are invalid")
        self.session_manager = session_manager
        self.route_repository = route_repository
        self.owner_replica_id = owner_replica_id
        self.control_boot_id = control_boot_id
        self.capacity_registry = capacity_registry
        self.relay_pool = relay_pool
        self.runner_metrics = runner_metrics
        self.clock = clock
        self.metrics_recoverable_errors = metrics_recoverable_errors
        self.owner_lifecycle = owner_lifecycle
        self.long_lived_grace_seconds = long_lived_grace_seconds
        self.finite_grace_seconds = finite_grace_seconds
        self.runners: dict[OwnerSessionEpoch, _RunnerConnection] = {}
        self.brokers: dict[OwnerSessionEpoch, RuntimeWebSessionBroker] = {}
        self.bindings: dict[BrokerStreamKey, _StreamBinding] = {}
        self.source_tombstones: deque[BrokerStreamKey] = deque(
            maxlen=MAX_STREAM_TOMBSTONES
        )
        self.source_tombstone_set: set[BrokerStreamKey] = set()
        self.owner_addresses: dict[OwnerSessionEpoch, str] = {}
        self.sources: dict[str, _SourceSession] = {}
        self.draining_sources: set[str] = set()
        self.window_updates = 0
        self.resets = 0
        self.drains = 0
        self.draining = False
        self.binding_changed = asyncio.Condition()
        self.lock = asyncio.Lock()

    async def register_source(
        self,
        *,
        session_id: str,
        peer_boot_id: str,
        owner: OwnerSessionEpoch | None,
    ) -> _SourceSession:
        source = _SourceSession(
            source_key=(
                session_id if owner is None else f"{session_id}:{peer_boot_id}"
            ),
            session_id=session_id,
            peer_boot_id=peer_boot_id,
            owner=owner,
            queue=_BoundedEnvelopeQueue(),
        )
        async with self.lock:
            if self.draining:
                raise _RuntimeWebControlDraining("Runtime Web Control is draining")
            if source.source_key in self.sources:
                raise ValueError("Runtime Web source session ID is already active")
            self.sources[source.source_key] = source
        return source

    async def unregister_source(self, source: _SourceSession) -> None:
        async with self.lock:
            if self.sources.get(source.source_key) is source:
                self.sources.pop(source.source_key)
            self.draining_sources.discard(source.source_key)
            keys = tuple(
                key
                for key, binding in self.bindings.items()
                if binding.source is source
            )
        for key in keys:
            await self._release(key)
        async with self.lock:
            runners = tuple(self.runners.values())
        await asyncio.gather(
            *(runner.release_source(source.source_key) for runner in runners),
        )
        await source.queue.close()

    async def register_runner(
        self,
        accepted: RuntimeWebAcceptedRunnerSession,
    ) -> _RunnerConnection:
        connection = _RunnerConnection(
            accepted=accepted,
            control_boot_id=self.control_boot_id,
        )
        async with self.lock:
            if accepted.owner in self.runners:
                raise ValueError("Runtime Web Owner Runner session is already active")
            self.runners[accepted.owner] = connection
        return connection

    async def unregister_runner(
        self,
        accepted: RuntimeWebAcceptedRunnerSession,
    ) -> None:
        async with self.lock:
            connection = self.runners.pop(accepted.owner, None)
        if connection is not None:
            await connection.close()
        await self.capacity_registry.release(accepted.owner)

    async def handle(
        self,
        source: _SourceSession,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        """Route one exact source envelope without retry or replay."""
        if (
            envelope.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT
            or envelope.session_id != source.session_id
            or envelope.peer_boot_id != source.peer_boot_id
            or not 1 <= envelope.ByteSize() <= MAX_ENVELOPE_BYTES
        ):
            raise ValueError("Runtime Web source envelope identity is stale")
        payload = envelope.WhichOneof("payload")
        if payload == "go_away":
            async with self.lock:
                self.draining_sources.add(source.source_key)
                self.drains += 1
            return
        if payload == "heartbeat":
            response = _base_response(source, self.control_boot_id)
            response.heartbeat_ack.monotonic_sequence = (
                envelope.heartbeat.monotonic_sequence
            )
            await source.queue.put(response)
            return
        key = BrokerStreamKey(source.source_key, envelope.stream_id)
        if payload == "open":
            async with self.lock:
                draining = self.draining or source.source_key in self.draining_sources
            if draining:
                await source.queue.put(
                    _rejection(
                        source,
                        self.control_boot_id,
                        envelope.stream_id,
                        CloseReason.SERVICE_DRAIN,
                    )
                )
                return
            await self._open(source, key, envelope)
            return
        if payload == "window_update":
            async with self.lock:
                self.window_updates += 1
        elif payload in {"cancel", "reset"}:
            async with self.lock:
                self.resets += 1
        async with self.lock:
            binding = self.bindings.get(key)
        if binding is None:
            async with self.lock:
                terminal = key in self.source_tombstone_set
            if terminal:
                return
            raise ValueError("Runtime Web source stream is unknown")
        await self._forward(binding, envelope)

    async def runner_response(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        """Dispatch one Runner response through its exact active connection."""
        async with self.lock:
            connection = next(
                (
                    candidate
                    for owner, candidate in self.runners.items()
                    if owner.session_lease_id == envelope.session_id
                ),
                None,
            )
        if connection is None:
            raise ValueError("Runtime Web Runner Owner session is not active")
        runner_source = await connection.source_binding(envelope.stream_id)
        if runner_source is None:
            if await connection.terminal(envelope.stream_id):
                return
            raise ValueError("Runtime Web Runner response stream is unknown")
        source_key = BrokerStreamKey(
            runner_source.source.source_key,
            runner_source.source_stream_id,
        )
        async with self.lock:
            binding = self.bindings.get(source_key)
        if binding is None:
            raise ValueError("Runtime Web Runner response binding is unknown")
        if envelope.WhichOneof("payload") == "response_head" and _is_sse(
            envelope.response_head
        ):
            if binding.broker is None or binding.capacity_stream_id is None:
                raise ValueError("Runtime Web SSE capacity Owner is absent")
            classified = await binding.broker.capacity.classify_stream(
                binding.capacity_stream_id,
                CapacityProtocol.SSE,
            )
            if not classified:
                await self._send_runner_reset(
                    binding,
                    CloseReason.RESOURCE_EXHAUSTED,
                )
                await runner_source.source.queue.put(
                    _reset(
                        runner_source.source,
                        self.control_boot_id,
                        runner_source.source_stream_id,
                        CloseReason.RESOURCE_EXHAUSTED,
                    )
                )
                await self._release(source_key)
                return
            binding = dataclasses.replace(binding, protocol=CapacityProtocol.SSE)
            async with self.lock:
                if source_key in self.bindings:
                    self.bindings[source_key] = binding
        try:
            on_dequeued = await self._capacity_release_on_dequeue(
                binding,
                envelope,
                direction=CapacityDirection.OUTBOUND,
            )
        except _RuntimeWebCapacityRejected:
            await self._send_runner_reset(
                binding,
                CloseReason.RESOURCE_EXHAUSTED,
            )
            await runner_source.source.queue.put(
                _reset(
                    runner_source.source,
                    self.control_boot_id,
                    runner_source.source_stream_id,
                    CloseReason.RESOURCE_EXHAUSTED,
                )
            )
            await self._release(source_key)
            return
        try:
            await connection.receive(envelope, on_dequeued=on_dequeued)
        except RuntimeError:
            if on_dequeued is not None:
                await on_dequeued()
            if runner_source.source.queue.closed:
                await self._release(source_key)
                return
            raise
        except BaseException:
            if on_dequeued is not None:
                await on_dequeued()
            raise
        if envelope.WhichOneof("payload") in {
            "open_rejected",
            "reset",
            "stream_end",
        }:
            await self._release(source_key)

    async def relay_response(
        self,
        key: RelaySessionKey,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        """Translate one remote Owner response to its source Gateway session."""
        translated = await self.relay_pool.route_response(key=key, envelope=envelope)
        if translated is None:
            return
        async with self.lock:
            source = self.sources.get(translated.session_id)
        if source is None:
            return
        source_key = BrokerStreamKey(source.source_key, translated.stream_id)
        try:
            await source.queue.put(translated)
        except RuntimeError:
            if not source.queue.closed:
                raise
            await self._release(source_key)
            return
        if translated.WhichOneof("payload") in {
            "open_rejected",
            "reset",
            "stream_end",
        }:
            await self._release(source_key)

    async def resolve_local_owner(
        self,
        owner: OwnerSessionEpoch,
    ) -> bool:
        """Verify that an inbound relay targets this exact live Owner epoch."""
        route = await self._resolve_route(
            runtime_id=owner.runtime_id,
            desired_generation=owner.desired_generation,
            runner_generation=owner.runner_generation,
        )
        return (
            route is not None
            and route.owner_replica_id == self.owner_replica_id
            and _route_owner(route) == owner
        )

    async def owner_address(self, owner: OwnerSessionEpoch) -> str:
        """Return the exact trusted address for one resolved Owner epoch."""
        async with self.lock:
            address = self.owner_addresses.get(owner)
        if address is not None:
            return address
        route = await self._resolve_route(
            runtime_id=owner.runtime_id,
            desired_generation=owner.desired_generation,
            runner_generation=owner.runner_generation,
        )
        if route is None or _route_owner(route) != owner:
            raise ValueError("Runtime Web relay Owner route is stale")
        return route.owner_address

    async def metrics(self) -> str:
        """Render bounded content-free Control and capacity metrics."""
        snapshots = await self.capacity_registry.snapshots()
        async with self.lock:
            gateway_sessions = sum(
                source.owner is None for source in self.sources.values()
            )
            relay_sessions = sum(
                source.owner is not None for source in self.sources.values()
            )
            runner_sessions = len(self.runners)
            active_streams = len(self.bindings)
            runner_items = tuple(self.runners.items())
            queues = tuple(source.queue for source in self.sources.values()) + tuple(
                connection.queue for connection in self.runners.values()
            )
            runner_active_streams = sum(
                binding.target.local for binding in self.bindings.values()
            )
            window_updates = self.window_updates
            resets = self.resets
            drains = self.drains
        runner_memory_bytes = 0
        runner_memory_limit_bytes = 0
        for owner, _connection in runner_items:
            try:
                samples = await self.runner_metrics.read_runner_system_metrics(
                    runtime_id=owner.runtime_id,
                    generation=owner.runner_generation,
                    current_time=self.clock(),
                )
            except self.metrics_recoverable_errors:
                continue
            if not samples:
                continue
            memory = samples[-1].memory
            if memory.used is not None:
                runner_memory_bytes += memory.used
            if memory.total is not None:
                runner_memory_limit_bytes += memory.total
        lines = [
            "# TYPE runtime_web_control_sessions gauge",
            (f'runtime_web_control_sessions{{role="gateway"}} {gateway_sessions}'),
            (f'runtime_web_control_sessions{{role="relay"}} {relay_sessions}'),
            (f'runtime_web_control_sessions{{role="runner"}} {runner_sessions}'),
            "# TYPE runtime_web_control_active_streams gauge",
            f"runtime_web_control_active_streams {active_streams}",
            "# TYPE runtime_web_control_capacity_active_streams gauge",
            (
                "runtime_web_control_capacity_active_streams "
                f"{sum(snapshot.active_streams for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_control_capacity_buffer_bytes gauge",
            (
                "runtime_web_control_capacity_buffer_bytes "
                f"{sum(snapshot.buffer_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_control_capacity_degraded gauge",
            (
                "runtime_web_control_capacity_degraded "
                f"{int(any(snapshot.degraded for snapshot in snapshots))}"
            ),
            "# TYPE runtime_web_control_capacity_backend_info gauge",
            (
                "runtime_web_control_capacity_backend_info"
                f'{{backend="{self.capacity_registry.config.backend.value}"}} 1'
            ),
            "# TYPE runtime_web_control_queue_bytes gauge",
            f"runtime_web_control_queue_bytes {sum(queue.bytes for queue in queues)}",
            "# TYPE runtime_web_control_queue_envelopes gauge",
            (
                "runtime_web_control_queue_envelopes "
                f"{sum(len(queue.items) for queue in queues)}"
            ),
            "# TYPE runtime_web_control_credit_stalls_total counter",
            (
                "runtime_web_control_credit_stalls_total "
                f"{sum(queue.stalls for queue in queues)}"
            ),
            "# TYPE runtime_web_control_window_updates_total counter",
            f"runtime_web_control_window_updates_total {window_updates}",
            "# TYPE runtime_web_control_resets_total counter",
            f"runtime_web_control_resets_total {resets}",
            "# TYPE runtime_web_control_drains_total counter",
            f"runtime_web_control_drains_total {drains}",
            "# TYPE runtime_web_runner_active_streams gauge",
            f"runtime_web_runner_active_streams {runner_active_streams}",
            "# TYPE runtime_web_runner_memory_bytes gauge",
            f"runtime_web_runner_memory_bytes {runner_memory_bytes}",
            "# TYPE runtime_web_runner_memory_limit_bytes gauge",
            f"runtime_web_runner_memory_limit_bytes {runner_memory_limit_bytes}",
            "# EOF",
        ]
        return "\n".join(lines) + "\n"

    async def subready(self) -> bool:
        """Return replacement sub-readiness without coupling general liveness."""
        async with self.lock:
            return bool(self.runners) and not self.draining

    async def begin_drain(self) -> None:
        """Withdraw readiness, fence Owner leases, and drain without replay."""
        async with self.lock:
            if self.draining:
                return
            self.draining = True
            self.drains += 1
            self.draining_sources.update(self.sources)
            sources = tuple(self.sources.values())
            runners = tuple(self.runners.items())
        await asyncio.gather(
            *(
                self.owner_lifecycle.mark_owner_draining(owner)
                for owner, _connection in runners
            )
        )
        long_deadline = self.clock() + datetime.timedelta(
            seconds=self.long_lived_grace_seconds
        )
        finite_deadline = self.clock() + datetime.timedelta(
            seconds=self.finite_grace_seconds
        )
        for source in sources:
            await source.queue.put(
                _go_away(
                    source,
                    self.control_boot_id,
                    deadline=finite_deadline,
                )
            )
        for owner, connection in runners:
            await connection.queue.put(
                _runner_go_away(
                    owner,
                    self.control_boot_id,
                    deadline=finite_deadline,
                )
            )
        await self._wait_for_protocols(
            {CapacityProtocol.SSE, CapacityProtocol.WEBSOCKET},
            timeout_seconds=max(
                0.0,
                (long_deadline - self.clock()).total_seconds(),
            ),
        )
        await self._reset_protocols({CapacityProtocol.SSE, CapacityProtocol.WEBSOCKET})
        await self._wait_for_protocols(
            {CapacityProtocol.HTTP},
            timeout_seconds=max(
                0.0,
                (finite_deadline - self.clock()).total_seconds(),
            ),
        )
        await self._reset_protocols({CapacityProtocol.HTTP})

    async def close(self) -> None:
        """Close relay and Runner state without replay."""
        await self.relay_pool.close()
        async with self.lock:
            runners = tuple(self.runners.values())
            sources = tuple(self.sources.values())
            self.runners.clear()
            self.sources.clear()
            self.draining_sources.clear()
            self.bindings.clear()
            self.brokers.clear()
            self.source_tombstones.clear()
            self.source_tombstone_set.clear()
        await asyncio.gather(
            *(runner.close() for runner in runners),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(source.queue.close() for source in sources),
            return_exceptions=True,
        )

    async def _wait_for_protocols(
        self,
        protocols: set[CapacityProtocol],
        *,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            return
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.binding_changed:
                    await self.binding_changed.wait_for(
                        lambda: (
                            not any(
                                binding.protocol in protocols
                                for binding in self.bindings.values()
                            )
                        )
                    )
        except TimeoutError:
            return

    async def _reset_protocols(
        self,
        protocols: set[CapacityProtocol],
    ) -> None:
        async with self.lock:
            bindings = tuple(
                binding
                for binding in self.bindings.values()
                if binding.protocol in protocols
            )
        for binding in bindings:
            await self._send_runner_reset(
                binding,
                CloseReason.SERVICE_DRAIN,
            )
            await binding.source.queue.put(
                _reset(
                    binding.source,
                    self.control_boot_id,
                    binding.key.stream_id,
                    CloseReason.SERVICE_DRAIN,
                )
            )
            await self._release(binding.key)

    async def _open(
        self,
        source: _SourceSession,
        key: BrokerStreamKey,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        authority = _authority(envelope.open.authority)
        head = _request_head(envelope.open.request_head)
        if source.owner is None:
            route = await self._resolve_route(
                runtime_id=authority.runtime_id,
                desired_generation=authority.desired_generation,
                runner_generation=authority.runner_generation,
            )
            target = None if route is None else _target(route, self.owner_replica_id)
        else:
            target = (
                BrokerTarget(owner=source.owner, local=True, relay_count=0)
                if await self.resolve_local_owner(source.owner)
                else None
            )
        if target is None:
            await source.queue.put(
                _rejection(
                    source,
                    self.control_boot_id,
                    envelope.stream_id,
                    CloseReason.OWNER_LOST,
                )
            )
            return
        protocol = (
            CapacityProtocol.WEBSOCKET
            if head.protocol is StreamProtocol.WEBSOCKET
            else CapacityProtocol.HTTP
        )
        broker: RuntimeWebSessionBroker | None = None
        capacity_stream_id: int | None = None
        if target.local:
            capacity = await self.capacity_registry.get(target.owner)
            async with self.lock:
                broker = self.brokers.get(target.owner)
                if broker is None:
                    broker = RuntimeWebSessionBroker(
                        router=_FixedRouter(target),
                        capacity=capacity,
                    )
                    self.brokers[target.owner] = broker
            admission = await broker.admit(
                key=key,
                authority=authority,
                protocol=head.protocol,
            )
            if admission is None:
                await source.queue.put(
                    _rejection(
                        source,
                        self.control_boot_id,
                        envelope.stream_id,
                        CloseReason.RESOURCE_EXHAUSTED,
                    )
                )
                return
            capacity_stream_id = admission.capacity_stream_id
        binding = _StreamBinding(
            source=source,
            key=key,
            target=target,
            broker=broker,
            capacity_stream_id=capacity_stream_id,
            runner_stream_id=None,
            protocol=protocol,
        )
        async with self.lock:
            draining = self.draining or source.source_key in self.draining_sources
            if not draining:
                self.bindings[key] = binding
        if draining:
            if broker is not None:
                await broker.release(key)
            await source.queue.put(
                _rejection(
                    source,
                    self.control_boot_id,
                    envelope.stream_id,
                    CloseReason.SERVICE_DRAIN,
                )
            )
            return
        async with self.binding_changed:
            self.binding_changed.notify_all()
        try:
            await self._forward(binding, envelope)
        except BaseException:
            await self._release(key)
            raise

    async def _forward(
        self,
        binding: _StreamBinding,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        target = binding.target
        if target.local:
            async with self.lock:
                runner = self.runners.get(target.owner)
            if runner is None:
                await binding.source.queue.put(
                    _rejection(
                        binding.source,
                        self.control_boot_id,
                        envelope.stream_id,
                        CloseReason.OWNER_LOST,
                    )
                )
                await self._release(binding.key)
                return
            try:
                on_dequeued = await self._capacity_release_on_dequeue(
                    binding,
                    envelope,
                    direction=CapacityDirection.INBOUND,
                )
            except _RuntimeWebCapacityRejected:
                await self._send_runner_reset(
                    binding,
                    CloseReason.RESOURCE_EXHAUSTED,
                )
                await binding.source.queue.put(
                    _reset(
                        binding.source,
                        self.control_boot_id,
                        envelope.stream_id,
                        CloseReason.RESOURCE_EXHAUSTED,
                    )
                )
                await self._release(binding.key)
                return
            try:
                runner_stream_id = await runner.send(
                    binding.source,
                    envelope,
                    on_dequeued=on_dequeued,
                )
            except BaseException:
                if on_dequeued is not None:
                    await on_dequeued()
                raise
            if binding.runner_stream_id is None:
                async with self.lock:
                    current = self.bindings.get(binding.key)
                    if current is binding:
                        self.bindings[binding.key] = dataclasses.replace(
                            binding,
                            runner_stream_id=runner_stream_id,
                        )
            return
        await self.relay_pool.forward(target=target, envelope=envelope)

    async def _send_runner_reset(
        self,
        binding: _StreamBinding,
        reason: CloseReason,
    ) -> None:
        if not binding.target.local or binding.runner_stream_id is None:
            return
        async with self.lock:
            runner = self.runners.get(binding.target.owner)
        if runner is None:
            return
        reset = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id=binding.target.owner.session_lease_id,
            peer_boot_id=self.control_boot_id,
            owner_boot_id=binding.target.owner.owner_boot_id,
            session_lease_id=binding.target.owner.session_lease_id,
            lease_generation=binding.target.owner.lease_generation,
            stream_id=binding.runner_stream_id,
        )
        reset.reset.reason = _close_reason(reason)
        await runner.queue.put(reset)

    async def _capacity_release_on_dequeue(
        self,
        binding: _StreamBinding,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        direction: CapacityDirection,
    ) -> Callable[[], Awaitable[None]] | None:
        size = _application_payload_size(envelope)
        if size == 0 or binding.broker is None:
            return None
        capacity = binding.broker.capacity
        grant_id = (
            f"{binding.key.source_session_id}:{binding.key.stream_id}:"
            f"{direction.value}:{envelope.frame_sequence}:"
            f"{envelope.WhichOneof('payload')}"
        )
        grant = BufferGrant(grant_id=grant_id, size_bytes=size)
        if not await capacity.reserve_buffer(grant):
            raise _RuntimeWebCapacityRejected
        if not await capacity.acquire_bandwidth(direction, size):
            await capacity.release_buffer(grant_id)
            raise _RuntimeWebCapacityRejected
        released = False

        async def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            await capacity.release_buffer(grant_id)

        return release

    async def _release(self, key: BrokerStreamKey) -> None:
        async with self.lock:
            binding = self.bindings.pop(key, None)
            broker = None if binding is None else binding.broker
            runner = None if binding is None else self.runners.get(binding.target.owner)
        if binding is None:
            return
        async with self.lock:
            if key not in self.source_tombstone_set:
                if len(self.source_tombstones) == MAX_STREAM_TOMBSTONES:
                    expired = self.source_tombstones.popleft()
                    self.source_tombstone_set.remove(expired)
                self.source_tombstones.append(key)
                self.source_tombstone_set.add(key)
        if runner is not None:
            await runner.release(
                source_session_id=key.source_session_id,
                source_stream_id=key.stream_id,
            )
        if broker is not None:
            await broker.release(key)
        async with self.binding_changed:
            self.binding_changed.notify_all()

    async def _resolve_route(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
    ) -> RuntimeWebSessionRoute | None:
        async with self.session_manager() as session:
            route = await self.route_repository.resolve(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
                protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            )
        if route is not None:
            async with self.lock:
                self.owner_addresses[_route_owner(route)] = route.owner_address
        return route


class RuntimeWebGatewaySessionGrpcServicer(
    runtime_web_session_pb2_grpc.RuntimeWebGatewaySessionServicer
):
    """Authenticate and serve one persistent Gateway session."""

    def __init__(
        self,
        *,
        data_plane: RuntimeWebControlDataPlane,
        peers: RuntimeWebTrustedPeerAuthenticator,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self.data_plane = data_plane
        self.peers = peers
        self.clock = clock

    async def Connect(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        await self.peers.gateway(context)
        first = await _first(request_iterator, context)
        _validate_hello(
            first,
            role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY,
            clock=self.clock,
            owner=None,
        )
        try:
            source = await self.data_plane.register_source(
                session_id=first.session_id,
                peer_boot_id=first.peer_boot_id,
                owner=None,
            )
        except _RuntimeWebControlDraining:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Runtime Web Control is draining",
            )
            raise AssertionError("unreachable") from None
        await source.queue.put(
            _acceptance(first, self.data_plane.control_boot_id, self.clock)
        )
        reader = asyncio.create_task(
            _read_source(self.data_plane, source, request_iterator)
        )
        try:
            async for response in source.queue:
                yield response
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            await self.data_plane.unregister_source(source)


class RuntimeWebControlSessionGrpcServicer(
    runtime_web_session_pb2_grpc.RuntimeWebControlSessionServicer
):
    """Authenticate and serve one exact incoming Owner relay."""

    def __init__(
        self,
        *,
        data_plane: RuntimeWebControlDataPlane,
        peers: RuntimeWebTrustedPeerAuthenticator,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self.data_plane = data_plane
        self.peers = peers
        self.clock = clock

    async def Relay(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        await self.peers.control(context)
        first = await _first(request_iterator, context)
        owner = _owner_from_envelope(first)
        _validate_hello(
            first,
            role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_CONTROL,
            clock=self.clock,
            owner=owner,
        )
        if not await self.data_plane.resolve_local_owner(owner):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Runtime Web relay Owner epoch is stale",
            )
            raise AssertionError("unreachable")
        try:
            source = await self.data_plane.register_source(
                session_id=first.session_id,
                peer_boot_id=first.peer_boot_id,
                owner=owner,
            )
        except _RuntimeWebControlDraining:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Runtime Web Control is draining",
            )
            raise AssertionError("unreachable") from None
        await source.queue.put(_acceptance(first, owner.owner_boot_id, self.clock))
        reader = asyncio.create_task(
            _read_source(self.data_plane, source, request_iterator)
        )
        try:
            async for response in source.queue:
                yield response
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            await self.data_plane.unregister_source(source)


class RuntimeRunnerWebSessionGrpcServicer(
    runtime_web_session_pb2_grpc.RuntimeRunnerWebSessionServicer
):
    """Authenticate and attach one Runner to its exact Owner epoch."""

    def __init__(
        self,
        *,
        data_plane: RuntimeWebControlDataPlane,
        offer_provider: RuntimeWebOwnedSessionProvider,
        registry: RuntimeWebOwnerSessionRegistry,
        runner_authenticator: RuntimeRunnerCredentialAuthenticator,
        clock: Callable[[], datetime.datetime],
        renew_interval_seconds: float,
    ) -> None:
        if renew_interval_seconds <= 0:
            raise ValueError("Runtime Web Owner renewal interval must be positive")
        self.data_plane = data_plane
        self.offer_provider = offer_provider
        self.registry = registry
        self.auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)
        self.clock = clock
        self.renew_interval_seconds = renew_interval_seconds

    async def Connect(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        credential = await self.auth.authenticate(context)
        first = await _first(request_iterator, context)
        owner = _owner_from_envelope(first)
        _validate_runner_hello(
            first, owner=owner, credential=credential, clock=self.clock
        )
        owned = await self.offer_provider.owned_for_runner(
            runtime_id=owner.runtime_id,
            runner_generation=owner.runner_generation,
        )
        if owned is None:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Runtime Web Runner session offer is unavailable",
            )
            raise AssertionError("unreachable")
        accepted = await self.registry.accept(
            owned,
            first,
            RuntimeWebAuthenticatedRunnerConnection(
                runtime_id=credential.runtime_id,
                runner_boot_id=first.peer_boot_id,
                desired_generation=credential.desired_generation,
                runner_generation=owner.runner_generation,
            ),
        )
        connection = await self.data_plane.register_runner(accepted)
        await connection.queue.put(_acceptance(first, owner.owner_boot_id, self.clock))
        renewal = asyncio.create_task(
            _renew_owner_session(
                provider=self.offer_provider,
                owner=owner,
                connection=connection,
                interval_seconds=self.renew_interval_seconds,
            ),
            name=f"runtime-web-owner-renewal:{owner.session_lease_id}",
        )
        reader = asyncio.create_task(
            _read_runner(self.data_plane, connection, request_iterator)
        )
        try:
            async for response in connection.queue:
                yield response
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            await self.data_plane.unregister_runner(accepted)
            await self.registry.release(accepted)
            await self.offer_provider.release_owner(owner)


def add_runtime_web_session_servicers(
    *,
    trusted_server: grpc.aio.Server,
    runner_server: grpc.aio.Server,
    data_plane: RuntimeWebControlDataPlane,
    offer_provider: RuntimeWebOwnedSessionProvider,
    owner_registry: RuntimeWebOwnerSessionRegistry,
    runner_authenticator: RuntimeRunnerCredentialAuthenticator,
    peer_authenticator: RuntimeWebTrustedPeerAuthenticator,
    clock: Callable[[], datetime.datetime],
    owner_renew_interval_seconds: float,
) -> None:
    """Register the three replacement persistent session services."""
    runtime_web_session_pb2_grpc.add_RuntimeWebGatewaySessionServicer_to_server(
        RuntimeWebGatewaySessionGrpcServicer(
            data_plane=data_plane,
            peers=peer_authenticator,
            clock=clock,
        ),
        trusted_server,
    )
    runtime_web_session_pb2_grpc.add_RuntimeWebControlSessionServicer_to_server(
        RuntimeWebControlSessionGrpcServicer(
            data_plane=data_plane,
            peers=peer_authenticator,
            clock=clock,
        ),
        trusted_server,
    )
    runtime_web_session_pb2_grpc.add_RuntimeRunnerWebSessionServicer_to_server(
        RuntimeRunnerWebSessionGrpcServicer(
            data_plane=data_plane,
            offer_provider=offer_provider,
            registry=owner_registry,
            runner_authenticator=runner_authenticator,
            clock=clock,
            renew_interval_seconds=owner_renew_interval_seconds,
        ),
        runner_server,
    )


_OPERATIONS_DATA_PLANE = web.AppKey(
    "runtime-web-control-data-plane",
    RuntimeWebControlDataPlane,
)


def create_runtime_web_control_operations_application(
    data_plane: RuntimeWebControlDataPlane,
) -> web.Application:
    """Create an internal-only Runtime Web Control operations application."""
    application = web.Application(client_max_size=1024)
    application[_OPERATIONS_DATA_PLANE] = data_plane
    application.router.add_get("/__azents/runtime-web/ready", _operations_ready)
    application.router.add_get("/__azents/runtime-web/live", _operations_live)
    application.router.add_get("/__azents/runtime-web/metrics", _operations_metrics)
    application.router.add_post("/__azents/runtime-web/drain", _operations_drain)
    return application


async def _operations_ready(request: web.Request) -> web.Response:
    ready = await request.app[_OPERATIONS_DATA_PLANE].subready()
    return web.Response(
        status=200 if ready else 503,
        text="ready\n" if ready else "not ready\n",
    )


async def _operations_live(request: web.Request) -> web.Response:
    del request
    return web.Response(text="live\n")


async def _operations_metrics(request: web.Request) -> web.Response:
    return web.Response(
        text=await request.app[_OPERATIONS_DATA_PLANE].metrics(),
        content_type="text/plain",
    )


async def _operations_drain(request: web.Request) -> web.Response:
    await request.app[_OPERATIONS_DATA_PLANE].begin_drain()
    return web.Response(text="drained\n")


async def _read_source(
    data_plane: RuntimeWebControlDataPlane,
    source: _SourceSession,
    messages: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
) -> None:
    try:
        async for envelope in messages:
            await data_plane.handle(source, envelope)
    finally:
        await source.queue.close()


async def _read_runner(
    data_plane: RuntimeWebControlDataPlane,
    connection: _RunnerConnection,
    messages: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
) -> None:
    try:
        async for envelope in messages:
            await data_plane.runner_response(envelope)
    except asyncio.CancelledError:
        raise
    except Exception:
        _LOGGER.exception("Runtime Web Runner session reader failed")
        raise
    finally:
        await connection.queue.close()


async def _renew_owner_session(
    *,
    provider: RuntimeWebOwnedSessionProvider,
    owner: OwnerSessionEpoch,
    connection: _RunnerConnection,
    interval_seconds: float,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            renewed = await provider.renew_owner(owner)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Runtime Web Owner renewal failed")
            await connection.close()
            return
        if not renewed:
            _LOGGER.warning("Runtime Web Owner renewal lost its exact epoch")
            await connection.close()
            return


async def _first(
    messages: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
    context: grpc.aio.ServicerContext,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    try:
        return await anext(messages)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web session hello is required",
        )
        raise AssertionError("unreachable") from None


def _validate_hello(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    *,
    role: int,
    clock: Callable[[], datetime.datetime],
    owner: OwnerSessionEpoch | None,
) -> None:
    hello = envelope.hello
    deadline = hello.deadline_at.ToDatetime(tzinfo=datetime.UTC)
    if (
        envelope.WhichOneof("payload") != "hello"
        or envelope.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT
        or not envelope.session_id
        or not envelope.peer_boot_id
        or hello.role != role
        or deadline <= clock()
        or hello.maximum_data_frame_bytes < APPROVED_SESSION_PROFILE.data_frame_bytes
        or hello.request_stream_window_bytes
        != APPROVED_SESSION_PROFILE.request_stream_window_bytes
        or hello.response_stream_window_bytes
        != APPROVED_SESSION_PROFILE.response_stream_window_bytes
        or hello.request_session_window_bytes
        != APPROVED_SESSION_PROFILE.request_session_window_bytes
        or hello.response_session_window_bytes
        != APPROVED_SESSION_PROFILE.response_session_window_bytes
        or (owner is not None and not _matches_owner(envelope, owner))
    ):
        raise ValueError("Runtime Web session hello is incompatible")


def _validate_runner_hello(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    *,
    owner: OwnerSessionEpoch,
    credential: RuntimeRunnerCredential,
    clock: Callable[[], datetime.datetime],
) -> None:
    _validate_hello(
        envelope,
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_RUNNER,
        clock=clock,
        owner=owner,
    )
    if (
        owner.runtime_id != credential.runtime_id
        or owner.desired_generation != credential.desired_generation
    ):
        raise ValueError("Runtime Web Runner credential Owner epoch is stale")


def _acceptance(
    request: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    peer_boot_id: str,
    clock: Callable[[], datetime.datetime],
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    accepted = runtime_web_session_pb2.RuntimeWebSessionAccepted(
        data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
        request_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        ),
        response_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        ),
        request_session_window_bytes=(
            APPROVED_SESSION_PROFILE.request_session_window_bytes
        ),
        response_session_window_bytes=(
            APPROVED_SESSION_PROFILE.response_session_window_bytes
        ),
    )
    accepted.accepted_at.FromDatetime(clock())
    response = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=request.session_id,
        peer_boot_id=peer_boot_id,
        stream_id=0,
        session_accepted=accepted,
    )
    if request.HasField("owner_boot_id"):
        response.owner_boot_id = request.owner_boot_id
    if request.HasField("session_lease_id"):
        response.session_lease_id = request.session_lease_id
    if request.HasField("lease_generation"):
        response.lease_generation = request.lease_generation
    return response


def _base_response(
    source: _SourceSession,
    control_boot_id: str,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    response = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=source.session_id,
        peer_boot_id=(
            source.owner.owner_boot_id if source.owner is not None else control_boot_id
        ),
    )
    if source.owner is not None:
        response.owner_boot_id = source.owner.owner_boot_id
        response.session_lease_id = source.owner.session_lease_id
        response.lease_generation = source.owner.lease_generation
    return response


def _rejection(
    source: _SourceSession,
    control_boot_id: str,
    stream_id: int,
    reason: CloseReason,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    response = _base_response(source, control_boot_id)
    response.stream_id = stream_id
    response.open_rejected.reason = _close_reason(reason)
    return response


def _reset(
    source: _SourceSession,
    control_boot_id: str,
    stream_id: int,
    reason: CloseReason,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    response = _base_response(source, control_boot_id)
    response.stream_id = stream_id
    response.reset.reason = _close_reason(reason)
    return response


def _go_away(
    source: _SourceSession,
    control_boot_id: str,
    *,
    deadline: datetime.datetime,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    response = _base_response(source, control_boot_id)
    response.go_away.last_accepted_stream_id = 2**64 - 1
    response.go_away.reason = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    response.go_away.drain_deadline_at.FromDatetime(deadline)
    return response


def _runner_go_away(
    owner: OwnerSessionEpoch,
    control_boot_id: str,
    *,
    deadline: datetime.datetime,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    response = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id=control_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
    )
    response.go_away.last_accepted_stream_id = 2**64 - 1
    response.go_away.reason = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    response.go_away.drain_deadline_at.FromDatetime(deadline)
    return response


def _application_payload_size(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> int:
    payload = envelope.WhichOneof("payload")
    if payload == "data":
        return len(envelope.data.data)
    if payload == "websocket":
        return len(envelope.websocket.data)
    return 0


def _is_sse(
    response: runtime_web_session_pb2.RuntimeWebSessionResponseHead,
) -> bool:
    return any(
        header.name.lower() == b"content-type"
        and header.value.split(b";", maxsplit=1)[0].strip().lower()
        == b"text/event-stream"
        for header in response.headers
    )


def _owner_envelope(
    source: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    *,
    owner: OwnerSessionEpoch,
    peer_boot_id: str,
    stream_id: int,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
    envelope.CopyFrom(source)
    envelope.protocol_fingerprint = RUNTIME_WEB_PROTOCOL_FINGERPRINT
    envelope.session_id = owner.session_lease_id
    envelope.peer_boot_id = peer_boot_id
    envelope.owner_boot_id = owner.owner_boot_id
    envelope.session_lease_id = owner.session_lease_id
    envelope.lease_generation = owner.lease_generation
    envelope.stream_id = stream_id
    return envelope


def _authority(
    message: runtime_web_session_pb2.RuntimeWebSessionAuthority,
) -> StreamAuthority:
    return StreamAuthority(
        correlation_id=message.correlation_id,
        endpoint_id=message.endpoint_id,
        cycle_id=message.cycle_id,
        endpoint_authority_revision=message.endpoint_authority_revision,
        close_barrier=message.close_barrier,
        identity_id=message.identity_id,
        authentication_session_id=message.authentication_session_id,
        user_id=message.user_id,
        agent_session_id=message.agent_session_id,
        runtime_id=message.runtime_id,
        desired_generation=message.desired_generation,
        runner_generation=message.runner_generation,
        port=message.port,
        open_deadline_at=message.open_deadline_at.ToDatetime(tzinfo=datetime.UTC),
        approval_deadline_at=message.approval_deadline_at.ToDatetime(
            tzinfo=datetime.UTC
        ),
        transport_deadline_at=message.transport_deadline_at.ToDatetime(
            tzinfo=datetime.UTC
        ),
    )


def _request_head(
    message: runtime_web_session_pb2.RuntimeWebSessionRequestHead,
) -> RequestHead:
    if message.protocol == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_HTTP:
        protocol = StreamProtocol.HTTP
    elif (
        message.protocol
        == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_WEBSOCKET
    ):
        protocol = StreamProtocol.WEBSOCKET
    else:
        raise ValueError("Runtime Web session protocol is invalid")
    return RequestHead(
        protocol=protocol,
        method=bytes(message.method),
        target=bytes(message.target),
        headers=tuple(
            Header(name=bytes(header.name), value=bytes(header.value))
            for header in message.headers
        ),
    )


def _target(
    route: RuntimeWebSessionRoute,
    owner_replica_id: str,
) -> BrokerTarget:
    local = route.owner_replica_id == owner_replica_id
    return BrokerTarget(
        owner=_route_owner(route),
        local=local,
        relay_count=0 if local else 1,
    )


def _route_owner(route: RuntimeWebSessionRoute) -> OwnerSessionEpoch:
    return OwnerSessionEpoch(
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
        runtime_id=route.runtime_id,
        desired_generation=route.desired_generation,
        runner_generation=route.runner_generation,
    )


def _owner_from_envelope(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> OwnerSessionEpoch:
    if (
        not envelope.HasField("owner_boot_id")
        or not envelope.HasField("session_lease_id")
        or not envelope.HasField("lease_generation")
        or envelope.WhichOneof("payload") == "hello"
        and (
            not envelope.hello.HasField("runtime_id")
            or not envelope.hello.HasField("desired_generation")
            or not envelope.hello.HasField("runner_generation")
        )
    ):
        raise ValueError("Runtime Web Owner epoch is incomplete")
    hello = envelope.hello
    return OwnerSessionEpoch(
        owner_boot_id=envelope.owner_boot_id,
        session_lease_id=envelope.session_lease_id,
        lease_generation=envelope.lease_generation,
        runtime_id=hello.runtime_id,
        desired_generation=hello.desired_generation,
        runner_generation=hello.runner_generation,
    )


def _matches_owner(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    owner: OwnerSessionEpoch,
) -> bool:
    return (
        envelope.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
        and envelope.session_id == owner.session_lease_id
        and envelope.HasField("owner_boot_id")
        and envelope.owner_boot_id == owner.owner_boot_id
        and envelope.HasField("session_lease_id")
        and envelope.session_lease_id == owner.session_lease_id
        and envelope.HasField("lease_generation")
        and envelope.lease_generation == owner.lease_generation
    )


def _close_reason(
    reason: CloseReason,
) -> runtime_web_session_pb2.RuntimeWebSessionCloseReason.ValueType:
    return {
        CloseReason.CALLER: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        ),
        CloseReason.APPROVAL_EXPIRED: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPROVAL_EXPIRED
        ),
        CloseReason.AUTHORITY_REVOKED: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_AUTHORITY_REVOKED
        ),
        CloseReason.GENERATION_REPLACED: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_GENERATION_REPLACED
        ),
        CloseReason.DEADLINE: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_DEADLINE
        ),
        CloseReason.SERVICE_DRAIN: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
        ),
        CloseReason.OWNER_LOST: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_OWNER_LOST
        ),
        CloseReason.PROTOCOL_VIOLATION: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
        ),
        CloseReason.RESOURCE_EXHAUSTED: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_RESOURCE_EXHAUSTED
        ),
        CloseReason.APPLICATION_UNAVAILABLE: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE
        ),
        CloseReason.TRANSPORT_UNAVAILABLE: (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
        ),
    }[reason]
