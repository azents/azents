"""Persistent Runtime Web Gateway, relay, and Runner gRPC data plane."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import enum
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from typing import NoReturn, Protocol, TypeVar

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
    StreamDirection,
    StreamProtocol,
)
from azents_runtime_control.system_metrics import RunnerRuntimeWebMetrics
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
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_MAX_MISSED_HEARTBEATS = 2
_LOGGER = logging.getLogger(__name__)
_TaskResult = TypeVar("_TaskResult")


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


@dataclasses.dataclass(frozen=True)
class RuntimeWebControlHardLimits:
    """Independent process ceilings for the Runtime Web Control data plane."""

    maximum_sessions: int
    maximum_active_streams: int
    maximum_application_buffer_bytes: int
    maximum_control_buffer_bytes: int
    maximum_queued_envelopes: int
    maximum_pending_tasks: int
    maximum_event_loop_lag_milliseconds: int
    maximum_resident_memory_bytes: int

    def __post_init__(self) -> None:
        for name, value in dataclasses.asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclasses.dataclass(frozen=True)
class RuntimeWebControlResourceSnapshot:
    """Current content-free Control hard-limit usage."""

    active_sessions: int
    active_streams: int
    application_buffer_bytes: int
    control_buffer_bytes: int
    queued_envelopes: int
    pending_tasks: int
    event_loop_lag_milliseconds: float
    resident_memory_bytes: int


class RuntimeWebControlResourceTracker:
    """Reserve exact process resources independently from Runtime soft capacity."""

    def __init__(
        self,
        *,
        limits: RuntimeWebControlHardLimits,
        resident_memory_bytes: Callable[[], int],
    ) -> None:
        self.limits = limits
        self.resident_memory_bytes = resident_memory_bytes()
        self.active_sessions = 0
        self.active_streams = 0
        self.application_buffer_bytes = 0
        self.control_buffer_bytes = 0
        self.queued_envelopes = 0
        self.pending_tasks = 0
        self.event_loop_lag_milliseconds = 0.0

    def pressure_acceptable(self) -> bool:
        """Return whether sampled process pressure remains below hard ceilings."""
        return (
            self.event_loop_lag_milliseconds
            < self.limits.maximum_event_loop_lag_milliseconds
            and self.resident_memory_bytes < self.limits.maximum_resident_memory_bytes
        )

    def update_process_pressure(
        self,
        *,
        lag_milliseconds: float,
        resident_memory_bytes: int,
    ) -> None:
        """Replace cached event-loop and resident-memory pressure samples."""
        if lag_milliseconds < 0 or resident_memory_bytes < 0:
            raise ValueError("Runtime Web Control pressure must not be negative")
        self.event_loop_lag_milliseconds = lag_milliseconds
        self.resident_memory_bytes = resident_memory_bytes

    def try_open_session(self) -> bool:
        """Reserve one peer session under the process RSS and session ceilings."""
        if (
            self.active_sessions >= self.limits.maximum_sessions
            or not self.pressure_acceptable()
        ):
            return False
        self.active_sessions += 1
        return True

    def close_session(self) -> None:
        """Release one exact peer-session reservation."""
        if self.active_sessions <= 0:
            raise ValueError("Runtime Web Control session reservation is absent")
        self.active_sessions -= 1

    def try_open_stream(self) -> bool:
        """Reserve one logical stream under the process stream and RSS ceilings."""
        if (
            self.active_streams >= self.limits.maximum_active_streams
            or not self.pressure_acceptable()
        ):
            return False
        self.active_streams += 1
        return True

    def close_stream(self) -> None:
        """Release one exact logical-stream reservation."""
        if self.active_streams <= 0:
            raise ValueError("Runtime Web Control stream reservation is absent")
        self.active_streams -= 1

    def try_begin_task(self) -> bool:
        """Reserve one bounded queue or open task."""
        if (
            self.pending_tasks >= self.limits.maximum_pending_tasks
            or not self.pressure_acceptable()
        ):
            return False
        self.pending_tasks += 1
        return True

    def end_task(self) -> None:
        """Release one exact pending-task reservation."""
        if self.pending_tasks <= 0:
            raise ValueError("Runtime Web Control task reservation is absent")
        self.pending_tasks -= 1

    def try_reserve_envelope(
        self,
        *,
        application_bytes: int,
        control_bytes: int,
    ) -> bool:
        """Reserve one queued envelope and its application/control bytes."""
        if application_bytes < 0 or control_bytes < 0:
            raise ValueError("Runtime Web Control buffer sizes must not be negative")
        if (
            self.queued_envelopes >= self.limits.maximum_queued_envelopes
            or self.application_buffer_bytes + application_bytes
            > self.limits.maximum_application_buffer_bytes
            or self.control_buffer_bytes + control_bytes
            > self.limits.maximum_control_buffer_bytes
            or not self.pressure_acceptable()
        ):
            return False
        self.queued_envelopes += 1
        self.application_buffer_bytes += application_bytes
        self.control_buffer_bytes += control_bytes
        return True

    def release_envelope(
        self,
        *,
        application_bytes: int,
        control_bytes: int,
    ) -> None:
        """Release one exact queued envelope reservation."""
        if (
            self.queued_envelopes <= 0
            or application_bytes < 0
            or control_bytes < 0
            or application_bytes > self.application_buffer_bytes
            or control_bytes > self.control_buffer_bytes
        ):
            raise ValueError("Runtime Web Control envelope release is invalid")
        self.queued_envelopes -= 1
        self.application_buffer_bytes -= application_bytes
        self.control_buffer_bytes -= control_bytes

    def snapshot(self) -> RuntimeWebControlResourceSnapshot:
        """Return exact process usage for metrics and readiness."""
        return RuntimeWebControlResourceSnapshot(
            active_sessions=self.active_sessions,
            active_streams=self.active_streams,
            application_buffer_bytes=self.application_buffer_bytes,
            control_buffer_bytes=self.control_buffer_bytes,
            queued_envelopes=self.queued_envelopes,
            pending_tasks=self.pending_tasks,
            event_loop_lag_milliseconds=self.event_loop_lag_milliseconds,
            resident_memory_bytes=self.resident_memory_bytes,
        )


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


def _runner_runtime_web_metrics_lines(
    snapshots: tuple[RunnerRuntimeWebMetrics, ...],
) -> list[str]:
    """Render one identity-free aggregate across active Runner snapshots."""
    active_streams_by_protocol = {protocol: 0 for protocol in StreamProtocol}
    opens_accepted_by_protocol = {protocol: 0 for protocol in StreamProtocol}
    opens_rejected_by_reason = {reason: 0 for reason in CloseReason}
    resets_by_reason = {reason: 0 for reason in CloseReason}
    closes_by_reason = {reason: 0 for reason in CloseReason}
    traffic = {
        (protocol, direction): [0, 0]
        for protocol in StreamProtocol
        for direction in StreamDirection
    }
    for snapshot in snapshots:
        for item in snapshot.active_streams_by_protocol:
            active_streams_by_protocol[item.protocol] += item.value
        for item in snapshot.opens_accepted_by_protocol:
            opens_accepted_by_protocol[item.protocol] += item.value
        for item in snapshot.opens_rejected_by_reason:
            opens_rejected_by_reason[item.reason] += item.value
        for item in snapshot.resets_by_reason:
            resets_by_reason[item.reason] += item.value
        for item in snapshot.closes_by_reason:
            closes_by_reason[item.reason] += item.value
        for item in snapshot.traffic:
            aggregate = traffic[(item.protocol, item.direction)]
            aggregate[0] += item.frames
            aggregate[1] += item.bytes

    duration_seconds_sum = sum(snapshot.duration_seconds_sum for snapshot in snapshots)
    goodput_bytes = sum(snapshot.goodput_bytes for snapshot in snapshots)
    response_sent_bytes = sum(snapshot.response_sent_bytes for snapshot in snapshots)
    response_consumed_bytes = sum(
        snapshot.response_consumed_bytes for snapshot in snapshots
    )
    worst_lag_snapshot = max(
        snapshots,
        key=lambda snapshot: (
            snapshot.event_loop_lag_milliseconds
            / snapshot.event_loop_lag_limit_milliseconds
        ),
        default=None,
    )
    worst_lag_milliseconds = (
        worst_lag_snapshot.event_loop_lag_milliseconds
        if worst_lag_snapshot is not None
        else 0.0
    )
    worst_lag_limit_milliseconds = (
        worst_lag_snapshot.event_loop_lag_limit_milliseconds
        if worst_lag_snapshot is not None
        else 0
    )
    worst_lag_pressure = (
        worst_lag_milliseconds / worst_lag_limit_milliseconds
        if worst_lag_limit_milliseconds > 0
        else 0.0
    )
    goodput_bytes_per_second = (
        goodput_bytes / duration_seconds_sum if duration_seconds_sum > 0 else 0.0
    )
    lines = [
        "# TYPE runtime_web_runner_sessions gauge",
        (
            "runtime_web_runner_sessions "
            f"{sum(snapshot.active_sessions for snapshot in snapshots)}"
        ),
        "# TYPE runtime_web_runner_session_limit gauge",
        (
            "runtime_web_runner_session_limit "
            f"{sum(snapshot.maximum_sessions for snapshot in snapshots)}"
        ),
        "# TYPE runtime_web_runner_active_streams gauge",
        (
            "runtime_web_runner_active_streams "
            f"{sum(snapshot.active_streams for snapshot in snapshots)}"
        ),
        "# TYPE runtime_web_runner_active_stream_limit gauge",
        (
            "runtime_web_runner_active_stream_limit "
            f"{sum(snapshot.maximum_active_streams for snapshot in snapshots)}"
        ),
        "# TYPE runtime_web_runner_active_streams_by_protocol gauge",
        "# TYPE runtime_web_runner_open_total counter",
    ]
    for protocol in StreamProtocol:
        label = f'protocol="{protocol.value}"'
        lines.extend(
            (
                (
                    "runtime_web_runner_active_streams_by_protocol"
                    f"{{{label}}} {active_streams_by_protocol[protocol]}"
                ),
                (
                    f'runtime_web_runner_open_total{{{label},outcome="accepted"}} '
                    f"{opens_accepted_by_protocol[protocol]}"
                ),
            )
        )
    lines.extend(
        (
            "# TYPE runtime_web_runner_open_rejected_total counter",
            "# TYPE runtime_web_runner_reset_total counter",
            "# TYPE runtime_web_runner_close_total counter",
        )
    )
    for reason in CloseReason:
        label = f'reason="{reason.value}"'
        lines.extend(
            (
                (
                    f"runtime_web_runner_open_rejected_total{{{label}}} "
                    f"{opens_rejected_by_reason[reason]}"
                ),
                (
                    f"runtime_web_runner_reset_total{{{label}}} "
                    f"{resets_by_reason[reason]}"
                ),
                (
                    f"runtime_web_runner_close_total{{{label}}} "
                    f"{closes_by_reason[reason]}"
                ),
            )
        )
    lines.extend(
        (
            "# TYPE runtime_web_runner_setup_seconds summary",
            (
                "runtime_web_runner_setup_seconds_sum "
                f"{sum(snapshot.setup_seconds_sum for snapshot in snapshots)}"
            ),
            (
                "runtime_web_runner_setup_seconds_count "
                f"{sum(snapshot.setup_count for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_ttfb_seconds summary",
            (
                "runtime_web_runner_ttfb_seconds_sum "
                f"{sum(snapshot.ttfb_seconds_sum for snapshot in snapshots)}"
            ),
            (
                "runtime_web_runner_ttfb_seconds_count "
                f"{sum(snapshot.ttfb_count for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_duration_seconds summary",
            f"runtime_web_runner_duration_seconds_sum {duration_seconds_sum}",
            (
                "runtime_web_runner_duration_seconds_count "
                f"{sum(snapshot.duration_count for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_goodput_bytes counter",
            f"runtime_web_runner_goodput_bytes {goodput_bytes}",
            "# TYPE runtime_web_runner_goodput_bytes_per_second gauge",
            (f"runtime_web_runner_goodput_bytes_per_second {goodput_bytes_per_second}"),
            "# TYPE runtime_web_runner_frames_total counter",
            "# TYPE runtime_web_runner_bytes_total counter",
        )
    )
    for protocol in StreamProtocol:
        for direction in StreamDirection:
            labels = f'protocol="{protocol.value}",direction="{direction.value}"'
            frames, byte_count = traffic[(protocol, direction)]
            lines.extend(
                (
                    f"runtime_web_runner_frames_total{{{labels}}} {frames}",
                    f"runtime_web_runner_bytes_total{{{labels}}} {byte_count}",
                )
            )
    lines.extend(
        (
            "# TYPE runtime_web_runner_credit_stalls_total counter",
            (
                "runtime_web_runner_credit_stalls_total "
                f"{sum(snapshot.credit_stalls_total for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_credit_stall_seconds_total counter",
            (
                "runtime_web_runner_credit_stall_seconds_total "
                f"{sum(snapshot.credit_stall_seconds for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_request_consumed_bytes counter",
            (
                "runtime_web_runner_request_consumed_bytes "
                f"{sum(snapshot.request_consumed_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_response_sent_bytes counter",
            f"runtime_web_runner_response_sent_bytes {response_sent_bytes}",
            "# TYPE runtime_web_runner_response_consumed_bytes counter",
            f"runtime_web_runner_response_consumed_bytes {response_consumed_bytes}",
            "# TYPE runtime_web_runner_response_credit_outstanding_bytes gauge",
            (
                "runtime_web_runner_response_credit_outstanding_bytes "
                f"{response_sent_bytes - response_consumed_bytes}"
            ),
            "# TYPE runtime_web_runner_heartbeat_total counter",
            (
                "runtime_web_runner_heartbeat_total "
                f"{sum(snapshot.heartbeats_total for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_go_away_total counter",
            (
                "runtime_web_runner_go_away_total "
                f"{sum(snapshot.go_aways_total for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_epoch_transition_total counter",
            (
                "runtime_web_runner_epoch_transition_total "
                f"{sum(snapshot.epoch_transitions_total for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_application_buffer_bytes gauge",
            (
                "runtime_web_runner_application_buffer_bytes "
                f"{sum(snapshot.application_buffer_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_application_buffer_limit_bytes gauge",
            (
                "runtime_web_runner_application_buffer_limit_bytes "
                f"{
                    sum(
                        snapshot.application_buffer_limit_bytes
                        for snapshot in snapshots
                    )
                }"
            ),
            "# TYPE runtime_web_runner_control_buffer_bytes gauge",
            (
                "runtime_web_runner_control_buffer_bytes "
                f"{sum(snapshot.control_buffer_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_control_buffer_limit_bytes gauge",
            (
                "runtime_web_runner_control_buffer_limit_bytes "
                f"{sum(snapshot.control_buffer_limit_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_queued_envelopes gauge",
            (
                "runtime_web_runner_queued_envelopes "
                f"{sum(snapshot.queued_envelopes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_queued_envelope_limit gauge",
            (
                "runtime_web_runner_queued_envelope_limit "
                f"{sum(snapshot.queued_envelope_limit for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_pending_tasks gauge",
            (
                "runtime_web_runner_pending_tasks "
                f"{sum(snapshot.pending_tasks for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_pending_task_limit gauge",
            (
                "runtime_web_runner_pending_task_limit "
                f"{sum(snapshot.pending_task_limit for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_event_loop_lag_milliseconds gauge",
            (
                "runtime_web_runner_event_loop_lag_milliseconds "
                f"{worst_lag_milliseconds}"
            ),
            "# TYPE runtime_web_runner_event_loop_lag_limit_milliseconds gauge",
            (
                "runtime_web_runner_event_loop_lag_limit_milliseconds "
                f"{worst_lag_limit_milliseconds}"
            ),
            "# TYPE runtime_web_runner_event_loop_lag_pressure gauge",
            f"runtime_web_runner_event_loop_lag_pressure {worst_lag_pressure}",
            "# TYPE runtime_web_runner_resident_memory_bytes gauge",
            (
                "runtime_web_runner_resident_memory_bytes "
                f"{sum(snapshot.resident_memory_bytes for snapshot in snapshots)}"
            ),
            "# TYPE runtime_web_runner_resident_memory_limit_bytes gauge",
            (
                "runtime_web_runner_resident_memory_limit_bytes "
                f"{sum(snapshot.resident_memory_limit_bytes for snapshot in snapshots)}"
            ),
        )
    )
    return lines


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
    def __init__(
        self,
        resources: RuntimeWebControlResourceTracker | None = None,
    ) -> None:
        self.items: deque[_QueuedEnvelope] = deque()
        self.bytes = 0
        self.stalls = 0
        self.closed = False
        self.condition = asyncio.Condition()
        self.resources = resources

    async def put(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        on_dequeued: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        size = envelope.ByteSize()
        if not 1 <= size <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web session envelope size is invalid")
        application_bytes = _application_payload_size(envelope)
        control_bytes = size - application_bytes
        resources = self.resources
        if resources is not None:
            if not resources.try_begin_task():
                raise _RuntimeWebControlResourceExhausted
        reserved = False
        try:
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
                if resources is not None:
                    if not resources.try_reserve_envelope(
                        application_bytes=application_bytes,
                        control_bytes=control_bytes,
                    ):
                        raise _RuntimeWebControlResourceExhausted
                    reserved = True
                copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
                copied.CopyFrom(envelope)
                self.items.append(
                    _QueuedEnvelope(
                        copied,
                        on_dequeued,
                        application_bytes,
                        control_bytes,
                    )
                )
                self.bytes += size
                self.condition.notify_all()
        except BaseException:
            if resources is not None and reserved:
                resources.release_envelope(
                    application_bytes=application_bytes,
                    control_bytes=control_bytes,
                )
            raise
        finally:
            if resources is not None:
                resources.end_task()

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
            if self.resources is not None:
                self.resources.release_envelope(
                    application_bytes=queued.application_bytes,
                    control_bytes=queued.control_bytes,
                )
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
        if self.resources is not None:
            for item in queued:
                self.resources.release_envelope(
                    application_bytes=item.application_bytes,
                    control_bytes=item.control_bytes,
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
    application_bytes: int
    control_bytes: int


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


class _RuntimeWebControlResourceExhausted(RuntimeError):
    """One process-local Control hard-limit rejection."""


class _RuntimeWebControlDraining(RuntimeError):
    """Reject one session registered after Control drain begins."""


def _create_control_task(
    resources: RuntimeWebControlResourceTracker | None,
    task: Callable[[], Awaitable[_TaskResult]],
    *,
    name: str | None = None,
) -> asyncio.Task[_TaskResult]:
    """Create one task with an exactly paired process-budget reservation."""
    if resources is not None and not resources.try_begin_task():
        raise _RuntimeWebControlResourceExhausted
    released = False

    def release() -> None:
        nonlocal released
        if resources is not None and not released:
            resources.end_task()
            released = True

    async def run() -> _TaskResult:
        try:
            return await task()
        finally:
            release()

    managed = run()
    try:
        created = asyncio.create_task(managed, name=name)
    except BaseException:
        managed.close()
        release()
        raise
    created.add_done_callback(lambda _completed: release())
    return created


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
        resources: RuntimeWebControlResourceTracker | None = None,
    ) -> None:
        self.accepted = accepted
        self.control_boot_id = control_boot_id
        self.queue = _BoundedEnvelopeQueue(resources)
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
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.heartbeat_sequence = 0
        self.heartbeat_acknowledged_sequence = 0
        self.heartbeats_sent = 0
        self.heartbeat_acknowledgements = 0
        self.missed_heartbeats = 0

    def start_heartbeats(self) -> None:
        """Start one application-independent Owner-session heartbeat loop."""
        if self.heartbeat_task is not None:
            raise RuntimeError("Runtime Web Runner heartbeat is already active")
        self.heartbeat_task = _create_control_task(
            self.queue.resources,
            self._heartbeat_loop,
            name=(
                "runtime-web-control-runner-heartbeat:"
                f"{self.accepted.owner.session_lease_id}"
            ),
        )

    async def acknowledge_heartbeat(self, sequence: int) -> None:
        """Apply one exact monotonic Runner heartbeat acknowledgement."""
        async with self.lock:
            if (
                sequence <= self.heartbeat_acknowledged_sequence
                or sequence > self.heartbeat_sequence
            ):
                raise ValueError(
                    "Runtime Web Runner heartbeat acknowledgement is invalid"
                )
            self.heartbeat_acknowledged_sequence = sequence
            self.heartbeat_acknowledgements += 1

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            async with self.lock:
                missed = self.heartbeat_sequence - self.heartbeat_acknowledged_sequence
                if missed >= _MAX_MISSED_HEARTBEATS:
                    self.missed_heartbeats += 1
                    exhausted = True
                else:
                    exhausted = False
                    self.heartbeat_sequence += 1
                    sequence = self.heartbeat_sequence
                    self.heartbeats_sent += 1
            if exhausted:
                await self.queue.close()
                return
            owner = self.accepted.owner
            heartbeat = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
                protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
                session_id=owner.session_lease_id,
                peer_boot_id=self.control_boot_id,
                owner_boot_id=owner.owner_boot_id,
                session_lease_id=owner.session_lease_id,
                lease_generation=owner.lease_generation,
            )
            heartbeat.heartbeat.monotonic_sequence = sequence
            try:
                await self.queue.put(heartbeat)
            except RuntimeError:
                return

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
        heartbeat_task = self.heartbeat_task
        self.heartbeat_task = None
        if heartbeat_task is not None and heartbeat_task is not asyncio.current_task():
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
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
        hard_limits: RuntimeWebControlHardLimits,
        resident_memory_bytes: Callable[[], int],
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
        self.resources = RuntimeWebControlResourceTracker(
            limits=hard_limits,
            resident_memory_bytes=resident_memory_bytes,
        )
        self.relay_pool.bind_resources(self.resources)
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
        self.heartbeats_received = 0
        self.runner_heartbeats_sent = 0
        self.runner_heartbeat_acknowledgements = 0
        self.runner_missed_heartbeats = 0
        self.owner_epoch_transitions = 0
        self.draining = False
        self.binding_changed = asyncio.Condition()
        self.lock = asyncio.Lock()

    def update_process_pressure(
        self,
        *,
        lag_milliseconds: float,
        resident_memory_bytes: int,
    ) -> None:
        """Update process progress evidence used by metrics and probes."""
        self.resources.update_process_pressure(
            lag_milliseconds=lag_milliseconds,
            resident_memory_bytes=resident_memory_bytes,
        )

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
            queue=_BoundedEnvelopeQueue(self.resources),
        )
        async with self.lock:
            if self.draining:
                raise _RuntimeWebControlDraining("Runtime Web Control is draining")
            if not self.resources.try_open_session():
                raise _RuntimeWebControlResourceExhausted
            if source.source_key in self.sources:
                self.resources.close_session()
                raise ValueError("Runtime Web source session ID is already active")
            self.sources[source.source_key] = source
        return source

    async def unregister_source(self, source: _SourceSession) -> None:
        async with self.lock:
            if self.sources.get(source.source_key) is source:
                self.sources.pop(source.source_key)
                self.resources.close_session()
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
            resources=self.resources,
        )
        async with self.lock:
            if not self.resources.try_open_session():
                raise _RuntimeWebControlResourceExhausted
            if accepted.owner in self.runners:
                self.resources.close_session()
                raise ValueError("Runtime Web Owner Runner session is already active")
            self.runners[accepted.owner] = connection
            self.owner_epoch_transitions += 1
        return connection

    async def unregister_runner(
        self,
        accepted: RuntimeWebAcceptedRunnerSession,
    ) -> None:
        async with self.lock:
            connection = self.runners.pop(accepted.owner, None)
            keys = tuple(
                key
                for key, binding in self.bindings.items()
                if binding.target.owner == accepted.owner
            )
        if connection is not None:
            self.runner_heartbeats_sent += connection.heartbeats_sent
            self.runner_heartbeat_acknowledgements += (
                connection.heartbeat_acknowledgements
            )
            self.runner_missed_heartbeats += connection.missed_heartbeats
            self.resources.close_session()
            await connection.close()
        for key in keys:
            await self._release(key)
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
            async with self.lock:
                self.heartbeats_received += 1
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
            if not self.resources.try_begin_task():
                await source.queue.put(
                    _rejection(
                        source,
                        self.control_boot_id,
                        envelope.stream_id,
                        CloseReason.RESOURCE_EXHAUSTED,
                    )
                )
                return
            try:
                await self._open(source, key, envelope)
            finally:
                self.resources.end_task()
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
        if envelope.WhichOneof("payload") == "heartbeat_ack":
            if envelope.stream_id != 0:
                raise ValueError(
                    "Runtime Web Runner heartbeat acknowledgement must be "
                    "session-scoped"
                )
            await connection.acknowledge_heartbeat(
                envelope.heartbeat_ack.monotonic_sequence
            )
            return
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
        resources = self.resources.snapshot()
        limits = self.resources.limits
        async with self.lock:
            gateway_sessions = sum(
                source.owner is None for source in self.sources.values()
            )
            relay_sessions = sum(
                source.owner is not None for source in self.sources.values()
            )
            runner_sessions = len(self.runners)
            active_streams = len(self.bindings)
            runner_owners = tuple(self.runners)
            queues = tuple(source.queue for source in self.sources.values()) + tuple(
                connection.queue for connection in self.runners.values()
            )
            window_updates = self.window_updates
            resets = self.resets
            drains = self.drains
            heartbeats_received = self.heartbeats_received
            owner_epoch_transitions = self.owner_epoch_transitions
            heartbeats_sent = (
                sum(connection.heartbeats_sent for connection in self.runners.values())
                + self.runner_heartbeats_sent
            )
            heartbeat_acknowledgements = (
                sum(
                    connection.heartbeat_acknowledgements
                    for connection in self.runners.values()
                )
                + self.runner_heartbeat_acknowledgements
            )
            missed_heartbeats = (
                sum(
                    connection.missed_heartbeats for connection in self.runners.values()
                )
                + self.runner_missed_heartbeats
            )
        current_time = self.clock()
        runner_snapshots: list[RunnerRuntimeWebMetrics] = []
        for owner in runner_owners:
            try:
                samples = await self.runner_metrics.read_runner_system_metrics(
                    runtime_id=owner.runtime_id,
                    generation=owner.runner_generation,
                    current_time=current_time,
                )
            except self.metrics_recoverable_errors:
                continue
            if not samples:
                continue
            runner_snapshots.append(samples[-1].runtime_web)
        lines = [
            "# TYPE runtime_web_control_sessions gauge",
            (f'runtime_web_control_sessions{{role="gateway"}} {gateway_sessions}'),
            (f'runtime_web_control_sessions{{role="relay"}} {relay_sessions}'),
            (f'runtime_web_control_sessions{{role="runner"}} {runner_sessions}'),
            "# TYPE runtime_web_control_active_streams gauge",
            f"runtime_web_control_active_streams {active_streams}",
            "# TYPE runtime_web_control_hard_sessions gauge",
            f"runtime_web_control_hard_sessions {resources.active_sessions}",
            "# TYPE runtime_web_control_hard_session_limit gauge",
            f"runtime_web_control_hard_session_limit {limits.maximum_sessions}",
            "# TYPE runtime_web_control_hard_stream_limit gauge",
            f"runtime_web_control_hard_stream_limit {limits.maximum_active_streams}",
            "# TYPE runtime_web_control_application_buffer_bytes gauge",
            (
                "runtime_web_control_application_buffer_bytes "
                f"{resources.application_buffer_bytes}"
            ),
            "# TYPE runtime_web_control_application_buffer_limit_bytes gauge",
            (
                "runtime_web_control_application_buffer_limit_bytes "
                f"{limits.maximum_application_buffer_bytes}"
            ),
            "# TYPE runtime_web_control_control_buffer_bytes gauge",
            (
                "runtime_web_control_control_buffer_bytes "
                f"{resources.control_buffer_bytes}"
            ),
            "# TYPE runtime_web_control_control_buffer_limit_bytes gauge",
            (
                "runtime_web_control_control_buffer_limit_bytes "
                f"{limits.maximum_control_buffer_bytes}"
            ),
            "# TYPE runtime_web_control_queued_envelopes gauge",
            f"runtime_web_control_queued_envelopes {resources.queued_envelopes}",
            "# TYPE runtime_web_control_queued_envelope_limit gauge",
            (
                "runtime_web_control_queued_envelope_limit "
                f"{limits.maximum_queued_envelopes}"
            ),
            "# TYPE runtime_web_control_pending_tasks gauge",
            f"runtime_web_control_pending_tasks {resources.pending_tasks}",
            "# TYPE runtime_web_control_pending_task_limit gauge",
            f"runtime_web_control_pending_task_limit {limits.maximum_pending_tasks}",
            "# TYPE runtime_web_control_event_loop_lag_milliseconds gauge",
            (
                "runtime_web_control_event_loop_lag_milliseconds "
                f"{resources.event_loop_lag_milliseconds}"
            ),
            "# TYPE runtime_web_control_event_loop_lag_limit_milliseconds gauge",
            (
                "runtime_web_control_event_loop_lag_limit_milliseconds "
                f"{limits.maximum_event_loop_lag_milliseconds}"
            ),
            "# TYPE runtime_web_control_resident_memory_bytes gauge",
            (
                "runtime_web_control_resident_memory_bytes "
                f"{resources.resident_memory_bytes}"
            ),
            "# TYPE runtime_web_control_resident_memory_limit_bytes gauge",
            (
                "runtime_web_control_resident_memory_limit_bytes "
                f"{limits.maximum_resident_memory_bytes}"
            ),
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
            "# TYPE runtime_web_control_heartbeats_received_total counter",
            (f"runtime_web_control_heartbeats_received_total {heartbeats_received}"),
            "# TYPE runtime_web_control_runner_heartbeats_sent_total counter",
            (f"runtime_web_control_runner_heartbeats_sent_total {heartbeats_sent}"),
            (
                "# TYPE runtime_web_control_runner_heartbeat_acknowledgements_total "
                "counter"
            ),
            (
                "runtime_web_control_runner_heartbeat_acknowledgements_total "
                f"{heartbeat_acknowledgements}"
            ),
            "# TYPE runtime_web_control_runner_missed_heartbeats_total counter",
            (f"runtime_web_control_runner_missed_heartbeats_total {missed_heartbeats}"),
            "# TYPE runtime_web_control_owner_epoch_transition_total counter",
            (
                "runtime_web_control_owner_epoch_transition_total "
                f"{owner_epoch_transitions}"
            ),
        ]
        lines.extend(_runner_runtime_web_metrics_lines(tuple(runner_snapshots)))
        lines.append("# EOF")
        return "\n".join(lines) + "\n"

    async def subready(self) -> bool:
        """Return replacement sub-readiness without coupling general liveness."""
        async with self.lock:
            return (
                bool(self.runners)
                and not self.draining
                and self.resources.pressure_acceptable()
            )

    def live(self) -> bool:
        """Return process liveness based only on event-loop progress."""
        return (
            self.resources.event_loop_lag_milliseconds
            < self.resources.limits.maximum_event_loop_lag_milliseconds
        )

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
            session_count = len(runners) + len(sources)
            stream_count = len(self.bindings)
            self.runners.clear()
            self.sources.clear()
            self.draining_sources.clear()
            self.bindings.clear()
            self.brokers.clear()
            self.source_tombstones.clear()
            self.source_tombstone_set.clear()
            for _ in range(session_count):
                self.resources.close_session()
            for _ in range(stream_count):
                self.resources.close_stream()
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
            admitted = False if draining else self.resources.try_open_stream()
            if admitted:
                self.bindings[key] = binding
        if not admitted:
            if broker is not None:
                await broker.release(key)
            await source.queue.put(
                _rejection(
                    source,
                    self.control_boot_id,
                    envelope.stream_id,
                    (
                        CloseReason.SERVICE_DRAIN
                        if draining
                        else CloseReason.RESOURCE_EXHAUSTED
                    ),
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
        self.resources.close_stream()
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
        except _RuntimeWebControlResourceExhausted:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard session limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        try:
            await source.queue.put(
                _acceptance(first, self.data_plane.control_boot_id, self.clock)
            )
        except _RuntimeWebControlResourceExhausted:
            await self.data_plane.unregister_source(source)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard queue limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        try:
            reader = _create_control_task(
                self.data_plane.resources,
                lambda: _read_source(self.data_plane, source, request_iterator),
                name=f"runtime-web-gateway-reader:{source.session_id}",
            )
        except _RuntimeWebControlResourceExhausted:
            await self.data_plane.unregister_source(source)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard task limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        except Exception:
            await self.data_plane.unregister_source(source)
            raise
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
        except _RuntimeWebControlResourceExhausted:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard session limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        try:
            await source.queue.put(_acceptance(first, owner.owner_boot_id, self.clock))
        except _RuntimeWebControlResourceExhausted:
            await self.data_plane.unregister_source(source)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard queue limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        try:
            reader = _create_control_task(
                self.data_plane.resources,
                lambda: _read_source(self.data_plane, source, request_iterator),
                name=f"runtime-web-relay-reader:{source.session_id}",
            )
        except _RuntimeWebControlResourceExhausted:
            await self.data_plane.unregister_source(source)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard task limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        except Exception:
            await self.data_plane.unregister_source(source)
            raise
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
        try:
            connection = await self.data_plane.register_runner(accepted)
        except _RuntimeWebControlResourceExhausted:
            await self.registry.release(accepted)
            await self.offer_provider.release_owner(owner)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard session limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        try:
            await connection.queue.put(
                _acceptance(first, owner.owner_boot_id, self.clock)
            )
        except _RuntimeWebControlResourceExhausted:
            await self.data_plane.unregister_runner(accepted)
            await self.registry.release(accepted)
            await self.offer_provider.release_owner(owner)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard queue limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        renewal: asyncio.Task[None] | None = None
        reader: asyncio.Task[None] | None = None

        async def cleanup() -> None:
            for task in (renewal, reader):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (renewal, reader) if task is not None),
                return_exceptions=True,
            )
            await self.data_plane.unregister_runner(accepted)
            await self.registry.release(accepted)
            await self.offer_provider.release_owner(owner)

        try:
            connection.start_heartbeats()
            renewal = _create_control_task(
                self.data_plane.resources,
                lambda: _renew_owner_session(
                    provider=self.offer_provider,
                    owner=owner,
                    connection=connection,
                    interval_seconds=self.renew_interval_seconds,
                ),
                name=f"runtime-web-owner-renewal:{owner.session_lease_id}",
            )
            reader = _create_control_task(
                self.data_plane.resources,
                lambda: _read_runner(
                    self.data_plane,
                    connection,
                    request_iterator,
                ),
                name=f"runtime-web-runner-reader:{owner.session_lease_id}",
            )
        except _RuntimeWebControlResourceExhausted:
            await cleanup()
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web Control hard task limit is exhausted",
            )
            raise AssertionError("unreachable") from None
        except asyncio.CancelledError:
            await cleanup()
            raise
        except Exception:
            await cleanup()
            raise
        try:
            async for response in connection.queue:
                yield response
        finally:
            await cleanup()


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
    live = request.app[_OPERATIONS_DATA_PLANE].live()
    return web.Response(
        status=200 if live else 503,
        text="live\n" if live else "not live\n",
    )


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
