"""Replacement Runtime Web logical-stream dispatch for the Runtime Runner."""

# Protobuf generated enum names are intentionally explicit at the wire boundary.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
from collections import deque
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import h11
import httpcore
from azents_runtime_control.grpc_runner_web_session_client import (
    GrpcRunnerWebSessionClient,
    RunnerWebResourceExhausted,
)
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import (
    AbsoluteCreditWindow,
    HierarchicalCredit,
)
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_ENVELOPE_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    Header,
    RequestHead,
    RunnerSessionOffer,
    StreamAuthority,
    StreamDirection,
    StreamProtocol,
    WebSocketOpcode,
)
from azents_runtime_control.system_metrics import (
    RunnerRuntimeWebMetrics,
    RunnerRuntimeWebProtocolCount,
    RunnerRuntimeWebReasonCount,
    RunnerRuntimeWebTrafficCount,
)
from wsproto.events import (
    BytesMessage,
    CloseConnection,
    Event,
    Ping,
    Pong,
    TextMessage,
)
from wsproto.utilities import LocalProtocolError as WsprotoLocalProtocolError
from wsproto.utilities import RemoteProtocolError as WsprotoRemoteProtocolError

from azents_runtime_runner.web_session import (
    RunnerWebLoopbackProtocolError,
    RunnerWebSessionManager,
    RunnerWebSocket,
)

_LOGGER = logging.getLogger(__name__)
_MAX_UINT64 = (1 << 64) - 1
_IGNORED_TOMBSTONE_PAYLOADS = frozenset(
    {
        "window_update",
        "direction_end",
        "cancel",
        "reset",
        "stream_end",
    }
)


@dataclasses.dataclass(frozen=True)
class RunnerWebHardLimits:
    """Independent process ceilings for the Runtime Web Runner data plane."""

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
class RunnerWebResourceSnapshot:
    """Current content-free Runner hard-limit usage."""

    active_sessions: int
    active_streams: int
    application_buffer_bytes: int
    control_buffer_bytes: int
    queued_envelopes: int
    pending_tasks: int
    event_loop_lag_milliseconds: float
    resident_memory_bytes: int


class RunnerWebResourceTracker:
    """Enforce process limits and retain bounded aggregate transport evidence."""

    def __init__(
        self,
        *,
        limits: RunnerWebHardLimits,
        resident_memory_bytes: Callable[[], int],
    ) -> None:
        self.limits = limits
        self.resident_memory_bytes = resident_memory_bytes()
        self.active_sessions = 0
        self.active_streams = 0
        self.active_streams_by_protocol = {protocol: 0 for protocol in StreamProtocol}
        self.application_buffer_bytes = 0
        self.control_buffer_bytes = 0
        self.queued_envelopes = 0
        self.pending_tasks = 0
        self.event_loop_lag_milliseconds = 0.0
        self.opens_accepted = {protocol: 0 for protocol in StreamProtocol}
        self.opens_rejected = {reason: 0 for reason in CloseReason}
        self.resets = {reason: 0 for reason in CloseReason}
        self.closes = {reason: 0 for reason in CloseReason}
        self.frames = {
            (protocol, direction): 0
            for protocol in StreamProtocol
            for direction in ("request", "response")
        }
        self.bytes = {
            (protocol, direction): 0
            for protocol in StreamProtocol
            for direction in ("request", "response")
        }
        self.setup_seconds_sum = 0.0
        self.setup_count = 0
        self.ttfb_seconds_sum = 0.0
        self.ttfb_count = 0
        self.duration_seconds_sum = 0.0
        self.duration_count = 0
        self.goodput_bytes = 0
        self.credit_stalls = 0
        self.credit_stall_seconds = 0.0
        self.request_consumed_bytes = 0
        self.response_sent_bytes = 0
        self.response_consumed_bytes = 0
        self.heartbeats = 0
        self.go_aways = 0
        self.epoch_transitions = 0

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
            raise ValueError("Runner Web process pressure must not be negative")
        self.event_loop_lag_milliseconds = lag_milliseconds
        self.resident_memory_bytes = resident_memory_bytes

    def try_open_session(self) -> bool:
        """Reserve one persistent Owner session under process pressure."""
        if (
            self.active_sessions >= self.limits.maximum_sessions
            or not self.pressure_acceptable()
        ):
            return False
        self.active_sessions += 1
        return True

    def close_session(self) -> None:
        """Release one exact Owner-session reservation."""
        if self.active_sessions <= 0:
            raise ValueError("Runner Web session reservation is absent")
        self.active_sessions -= 1

    def try_open_stream(self, protocol: StreamProtocol) -> bool:
        """Reserve one logical stream under process limits."""
        if (
            self.active_streams >= self.limits.maximum_active_streams
            or not self.pressure_acceptable()
        ):
            return False
        self.active_streams += 1
        self.active_streams_by_protocol[protocol] += 1
        return True

    def close_stream(self, protocol: StreamProtocol) -> None:
        """Release one exact logical-stream reservation."""
        if self.active_streams <= 0 or self.active_streams_by_protocol[protocol] <= 0:
            raise ValueError("Runner Web stream reservation is absent")
        self.active_streams -= 1
        self.active_streams_by_protocol[protocol] -= 1

    def try_begin_tasks(self, count: int = 1) -> bool:
        """Reserve bounded asynchronous work before task creation."""
        if count <= 0:
            raise ValueError("Runner Web task reservation must be positive")
        if (
            self.pending_tasks + count > self.limits.maximum_pending_tasks
            or not self.pressure_acceptable()
        ):
            return False
        self.pending_tasks += count
        return True

    def end_tasks(self, count: int = 1) -> None:
        """Release exact task reservations."""
        if count <= 0 or count > self.pending_tasks:
            raise ValueError("Runner Web task release is invalid")
        self.pending_tasks -= count

    def try_reserve_envelope(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> bool:
        """Reserve one queued envelope and its application/control bytes."""
        size = envelope.ByteSize()
        if not 1 <= size <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runner Web envelope size is invalid")
        application_bytes = _application_payload_size(envelope)
        control_bytes = size - application_bytes
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
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        """Release one exact queued-envelope reservation."""
        application_bytes = _application_payload_size(envelope)
        control_bytes = envelope.ByteSize() - application_bytes
        if (
            self.queued_envelopes <= 0
            or application_bytes > self.application_buffer_bytes
            or control_bytes > self.control_buffer_bytes
        ):
            raise ValueError("Runner Web envelope release is invalid")
        self.queued_envelopes -= 1
        self.application_buffer_bytes -= application_bytes
        self.control_buffer_bytes -= control_bytes

    def record_open_accepted(
        self,
        protocol: StreamProtocol,
        setup_seconds: float,
    ) -> None:
        """Record one bounded accepted-open setup observation."""
        self.opens_accepted[protocol] += 1
        self.setup_seconds_sum += _finite_non_negative(setup_seconds)
        self.setup_count += 1

    def record_open_rejected(self, reason: CloseReason) -> None:
        """Record one bounded local open rejection."""
        self.opens_rejected[reason] += 1

    def record_reset(self, reason: CloseReason) -> None:
        """Record one bounded reset reason."""
        self.resets[reason] += 1

    def record_close(
        self,
        reason: CloseReason,
        *,
        duration_seconds: float,
        application_bytes: int,
    ) -> None:
        """Record one terminal stream without content or identity dimensions."""
        if application_bytes < 0:
            raise ValueError("Runner Web stream bytes must not be negative")
        self.closes[reason] += 1
        self.duration_seconds_sum += _finite_non_negative(duration_seconds)
        self.duration_count += 1
        self.goodput_bytes += application_bytes

    def record_ttfb(self, seconds: float) -> None:
        """Record one first-response-byte observation."""
        self.ttfb_seconds_sum += _finite_non_negative(seconds)
        self.ttfb_count += 1

    def record_frame(
        self,
        protocol: StreamProtocol,
        direction: str,
        size_bytes: int,
    ) -> None:
        """Record one typed application frame using bounded dimensions."""
        if direction not in {"request", "response"} or size_bytes < 0:
            raise ValueError("Runner Web frame metric is invalid")
        self.frames[(protocol, direction)] += 1
        self.bytes[(protocol, direction)] += size_bytes

    def snapshot(self) -> RunnerWebResourceSnapshot:
        """Return exact current process usage."""
        return RunnerWebResourceSnapshot(
            active_sessions=self.active_sessions,
            active_streams=self.active_streams,
            application_buffer_bytes=self.application_buffer_bytes,
            control_buffer_bytes=self.control_buffer_bytes,
            queued_envelopes=self.queued_envelopes,
            pending_tasks=self.pending_tasks,
            event_loop_lag_milliseconds=self.event_loop_lag_milliseconds,
            resident_memory_bytes=self.resident_memory_bytes,
        )

    def system_metrics_snapshot(self) -> RunnerRuntimeWebMetrics:
        """Return the complete bounded aggregate for Runner Control reporting."""
        snapshot = self.snapshot()
        limits = self.limits
        return RunnerRuntimeWebMetrics(
            active_sessions=snapshot.active_sessions,
            active_streams=snapshot.active_streams,
            maximum_sessions=limits.maximum_sessions,
            maximum_active_streams=limits.maximum_active_streams,
            application_buffer_bytes=snapshot.application_buffer_bytes,
            application_buffer_limit_bytes=limits.maximum_application_buffer_bytes,
            control_buffer_bytes=snapshot.control_buffer_bytes,
            control_buffer_limit_bytes=limits.maximum_control_buffer_bytes,
            queued_envelopes=snapshot.queued_envelopes,
            queued_envelope_limit=limits.maximum_queued_envelopes,
            pending_tasks=snapshot.pending_tasks,
            pending_task_limit=limits.maximum_pending_tasks,
            event_loop_lag_milliseconds=snapshot.event_loop_lag_milliseconds,
            event_loop_lag_limit_milliseconds=(
                limits.maximum_event_loop_lag_milliseconds
            ),
            resident_memory_bytes=snapshot.resident_memory_bytes,
            resident_memory_limit_bytes=limits.maximum_resident_memory_bytes,
            credit_stalls_total=self.credit_stalls,
            credit_stall_seconds=self.credit_stall_seconds,
            request_consumed_bytes=self.request_consumed_bytes,
            response_sent_bytes=self.response_sent_bytes,
            response_consumed_bytes=self.response_consumed_bytes,
            heartbeats_total=self.heartbeats,
            go_aways_total=self.go_aways,
            epoch_transitions_total=self.epoch_transitions,
            setup_seconds_sum=self.setup_seconds_sum,
            setup_count=self.setup_count,
            ttfb_seconds_sum=self.ttfb_seconds_sum,
            ttfb_count=self.ttfb_count,
            duration_seconds_sum=self.duration_seconds_sum,
            duration_count=self.duration_count,
            goodput_bytes=self.goodput_bytes,
            active_streams_by_protocol=tuple(
                RunnerRuntimeWebProtocolCount(
                    protocol=protocol,
                    value=self.active_streams_by_protocol[protocol],
                )
                for protocol in StreamProtocol
            ),
            opens_accepted_by_protocol=tuple(
                RunnerRuntimeWebProtocolCount(
                    protocol=protocol,
                    value=self.opens_accepted[protocol],
                )
                for protocol in StreamProtocol
            ),
            opens_rejected_by_reason=tuple(
                RunnerRuntimeWebReasonCount(
                    reason=reason,
                    value=self.opens_rejected[reason],
                )
                for reason in CloseReason
            ),
            resets_by_reason=tuple(
                RunnerRuntimeWebReasonCount(
                    reason=reason,
                    value=self.resets[reason],
                )
                for reason in CloseReason
            ),
            closes_by_reason=tuple(
                RunnerRuntimeWebReasonCount(
                    reason=reason,
                    value=self.closes[reason],
                )
                for reason in CloseReason
            ),
            traffic=tuple(
                RunnerRuntimeWebTrafficCount(
                    protocol=protocol,
                    direction=direction,
                    frames=self.frames[(protocol, direction.value)],
                    bytes=self.bytes[(protocol, direction.value)],
                )
                for protocol in StreamProtocol
                for direction in StreamDirection
            ),
        )

    def render_openmetrics(self) -> str:
        """Render bounded content-free Runner transport telemetry."""
        snapshot = self.snapshot()
        limits = self.limits
        goodput = (
            self.goodput_bytes / self.duration_seconds_sum
            if self.duration_seconds_sum > 0
            else 0.0
        )
        lines = [
            "# TYPE runtime_web_runner_sessions gauge",
            f"runtime_web_runner_sessions {snapshot.active_sessions}",
            "# TYPE runtime_web_runner_active_streams gauge",
            f"runtime_web_runner_active_streams {snapshot.active_streams}",
        ]
        for protocol in StreamProtocol:
            label = f'protocol="{protocol.value}"'
            lines.extend(
                (
                    (
                        "runtime_web_runner_active_streams_by_protocol"
                        f"{{{label}}} {self.active_streams_by_protocol[protocol]}"
                    ),
                    (
                        f'runtime_web_runner_open_total{{{label},outcome="accepted"}} '
                        f"{self.opens_accepted[protocol]}"
                    ),
                )
            )
        for reason in CloseReason:
            reason_label = f'reason="{reason.value}"'
            lines.extend(
                (
                    (
                        "runtime_web_runner_open_rejected_total"
                        f"{{{reason_label}}} {self.opens_rejected[reason]}"
                    ),
                    (
                        f"runtime_web_runner_reset_total{{{reason_label}}} "
                        f"{self.resets[reason]}"
                    ),
                    (
                        f"runtime_web_runner_close_total{{{reason_label}}} "
                        f"{self.closes[reason]}"
                    ),
                )
            )
        lines.extend(
            (
                "# TYPE runtime_web_runner_setup_seconds summary",
                f"runtime_web_runner_setup_seconds_sum {self.setup_seconds_sum}",
                f"runtime_web_runner_setup_seconds_count {self.setup_count}",
                "# TYPE runtime_web_runner_ttfb_seconds summary",
                f"runtime_web_runner_ttfb_seconds_sum {self.ttfb_seconds_sum}",
                f"runtime_web_runner_ttfb_seconds_count {self.ttfb_count}",
                "# TYPE runtime_web_runner_duration_seconds summary",
                (
                    "runtime_web_runner_duration_seconds_sum "
                    f"{self.duration_seconds_sum}"
                ),
                f"runtime_web_runner_duration_seconds_count {self.duration_count}",
                "# TYPE runtime_web_runner_goodput_bytes_per_second gauge",
                f"runtime_web_runner_goodput_bytes_per_second {goodput}",
            )
        )
        for protocol in StreamProtocol:
            for direction in ("request", "response"):
                labels = (
                    f'protocol="{protocol.value}",direction="{direction}",path="local"'
                )
                lines.extend(
                    (
                        (
                            f"runtime_web_runner_frames_total{{{labels}}} "
                            f"{self.frames[(protocol, direction)]}"
                        ),
                        (
                            f"runtime_web_runner_bytes_total{{{labels}}} "
                            f"{self.bytes[(protocol, direction)]}"
                        ),
                    )
                )
        lines.extend(
            (
                "# TYPE runtime_web_runner_credit_stalls_total counter",
                f"runtime_web_runner_credit_stalls_total {self.credit_stalls}",
                "# TYPE runtime_web_runner_credit_stall_seconds_total counter",
                (
                    "runtime_web_runner_credit_stall_seconds_total "
                    f"{self.credit_stall_seconds}"
                ),
                "# TYPE runtime_web_runner_request_consumed_bytes counter",
                (
                    "runtime_web_runner_request_consumed_bytes "
                    f"{self.request_consumed_bytes}"
                ),
                "# TYPE runtime_web_runner_response_credit_outstanding_bytes gauge",
                (
                    "runtime_web_runner_response_credit_outstanding_bytes "
                    f"{self.response_sent_bytes - self.response_consumed_bytes}"
                ),
                "# TYPE runtime_web_runner_heartbeat_total counter",
                f"runtime_web_runner_heartbeat_total {self.heartbeats}",
                "# TYPE runtime_web_runner_go_away_total counter",
                f"runtime_web_runner_go_away_total {self.go_aways}",
                "# TYPE runtime_web_runner_epoch_transition_total counter",
                (f"runtime_web_runner_epoch_transition_total {self.epoch_transitions}"),
                "# TYPE runtime_web_runner_application_buffer_bytes gauge",
                (
                    "runtime_web_runner_application_buffer_bytes "
                    f"{snapshot.application_buffer_bytes}"
                ),
                "# TYPE runtime_web_runner_application_buffer_limit_bytes gauge",
                (
                    "runtime_web_runner_application_buffer_limit_bytes "
                    f"{limits.maximum_application_buffer_bytes}"
                ),
                "# TYPE runtime_web_runner_control_buffer_bytes gauge",
                (
                    "runtime_web_runner_control_buffer_bytes "
                    f"{snapshot.control_buffer_bytes}"
                ),
                "# TYPE runtime_web_runner_control_buffer_limit_bytes gauge",
                (
                    "runtime_web_runner_control_buffer_limit_bytes "
                    f"{limits.maximum_control_buffer_bytes}"
                ),
                "# TYPE runtime_web_runner_queued_envelopes gauge",
                f"runtime_web_runner_queued_envelopes {snapshot.queued_envelopes}",
                "# TYPE runtime_web_runner_queued_envelope_limit gauge",
                (
                    "runtime_web_runner_queued_envelope_limit "
                    f"{limits.maximum_queued_envelopes}"
                ),
                "# TYPE runtime_web_runner_pending_tasks gauge",
                f"runtime_web_runner_pending_tasks {snapshot.pending_tasks}",
                "# TYPE runtime_web_runner_pending_task_limit gauge",
                (
                    "runtime_web_runner_pending_task_limit "
                    f"{limits.maximum_pending_tasks}"
                ),
                "# TYPE runtime_web_runner_event_loop_lag_milliseconds gauge",
                (
                    "runtime_web_runner_event_loop_lag_milliseconds "
                    f"{snapshot.event_loop_lag_milliseconds}"
                ),
                "# TYPE runtime_web_runner_event_loop_lag_limit_milliseconds gauge",
                (
                    "runtime_web_runner_event_loop_lag_limit_milliseconds "
                    f"{limits.maximum_event_loop_lag_milliseconds}"
                ),
                "# TYPE runtime_web_runner_resident_memory_bytes gauge",
                (
                    "runtime_web_runner_resident_memory_bytes "
                    f"{snapshot.resident_memory_bytes}"
                ),
                "# TYPE runtime_web_runner_resident_memory_limit_bytes gauge",
                (
                    "runtime_web_runner_resident_memory_limit_bytes "
                    f"{limits.maximum_resident_memory_bytes}"
                ),
                "# EOF",
            )
        )
        return "\n".join(lines) + "\n"


class _RunnerInboundQueue:
    """One per-stream queue with process-wide byte and envelope accounting."""

    def __init__(self, resources: RunnerWebResourceTracker) -> None:
        self.resources = resources
        self.items: deque[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = deque()
        self.condition = asyncio.Condition()
        self.closed = False

    async def put(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> bool:
        """Queue a copy or reject this stream without blocking peer multiplexing."""
        async with self.condition:
            if (
                self.closed
                or len(self.items) >= 8
                or not self.resources.try_reserve_envelope(envelope)
            ):
                return False
            copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            copied.CopyFrom(envelope)
            self.items.append(copied)
            self.condition.notify_all()
            return True

    async def get(self) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        """Pop one queued envelope and release its exact reservation."""
        async with self.condition:
            await self.condition.wait_for(lambda: bool(self.items) or self.closed)
            if not self.items:
                raise RuntimeError("Runner Web inbound queue is closed")
            envelope = self.items.popleft()
            self.resources.release_envelope(envelope)
            return envelope

    async def close(self) -> None:
        """Release all queued envelopes and wake the stream consumer."""
        async with self.condition:
            self.closed = True
            queued = tuple(self.items)
            self.items.clear()
            self.condition.notify_all()
        for envelope in queued:
            self.resources.release_envelope(envelope)


@dataclasses.dataclass
class _Stream:
    offer: RunnerSessionOffer
    client: GrpcRunnerWebSessionClient
    authority: StreamAuthority
    head: RequestHead
    inbound: _RunnerInboundQueue
    response_credit: HierarchicalCredit
    credit_changed: asyncio.Condition
    task: asyncio.Task[None] | None = None
    request_sequence: int = 0
    request_consumed_total: int = 0
    close_reason: CloseReason = CloseReason.CALLER
    started_at: float = 0.0
    application_bytes: int = 0
    resources_reserved: bool = False


class RunnerWebSessionDispatcher:
    """Translate one persistent Runner session into bounded loopback exchanges."""

    def __init__(
        self,
        manager: RunnerWebSessionManager,
        *,
        resources: RunnerWebResourceTracker,
        monotonic_clock: Callable[[], float],
    ) -> None:
        self.manager = manager
        self.resources = resources
        self.monotonic_clock = monotonic_clock
        self.streams: dict[int, _Stream] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()
        self.last_stream_id = 0
        self.request_session_consumed_total = 0
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
            maximum_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        )
        self.response_credit_changed = asyncio.Condition()
        self.offer_lock = asyncio.Lock()
        self.accepting_envelopes = False
        self.accepting_streams = False
        self.session_reserved = False
        self.session_task_reserved = False
        self.drain_task: asyncio.Task[None] | None = None

    async def handle_offer(self, offer: RunnerSessionOffer) -> None:
        """Activate the sole exact offer with this dispatcher."""
        async with self.offer_lock:
            if not self.manager.offer_is_current(offer):
                return
            previous_accepting_envelopes = self.accepting_envelopes
            previous_accepting_streams = self.accepting_streams
            self.accepting_envelopes = False
            try:
                current = self.manager.offer
                if current is None or current.owner != offer.owner:
                    if current is not None:
                        await self.close(reason=CloseReason.GENERATION_REPLACED)
                    self._reset_session_flow()
                accepted = await self.manager.accept_offer(
                    offer,
                    self,
                    self.fail_transport,
                )
                if accepted:
                    if not self.resources.try_open_session():
                        await self.manager.close()
                        raise RunnerWebResourceExhausted(
                            "Runner Web session hard limit is exhausted"
                        )
                    if not self.resources.try_begin_tasks():
                        self.resources.close_session()
                        await self.manager.close()
                        raise RunnerWebResourceExhausted(
                            "Runner Web session task limit is exhausted"
                        )
                    self.session_reserved = True
                    self.session_task_reserved = True
                    self.accepting_envelopes = True
                    self.accepting_streams = True
                    self.resources.epoch_transitions += 1
                else:
                    self.accepting_envelopes = previous_accepting_envelopes
                    self.accepting_streams = previous_accepting_streams
            except asyncio.CancelledError:
                raise
            except Exception:
                self.accepting_envelopes = False
                raise

    async def __call__(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        offer = self.manager.offer
        client = self.manager.client
        if (
            not self.accepting_envelopes
            or offer is None
            or client is None
            or not _matches_offer(envelope, offer)
        ):
            raise ValueError("Runner Web envelope authority is stale")
        payload = envelope.WhichOneof("payload")
        if payload == "heartbeat":
            self.resources.heartbeats += 1
            response = self._envelope(offer=offer)
            response.heartbeat_ack.monotonic_sequence = (
                envelope.heartbeat.monotonic_sequence
            )
            await self._send(response, client=client)
            return
        if payload == "go_away":
            self.resources.go_aways += 1
            self.accepting_streams = False
            deadline = envelope.go_away.drain_deadline_at.ToDatetime(tzinfo=UTC)
            if self.drain_task is None or self.drain_task.done():
                if self.resources.try_begin_tasks():
                    self.drain_task = asyncio.create_task(
                        self._run_drain(deadline),
                        name="runtime-web-runner-drain",
                    )
                else:
                    await self._drain(deadline)
            return
        if payload == "open":
            if not self.accepting_streams:
                await self._reset(
                    envelope.stream_id,
                    CloseReason.SERVICE_DRAIN,
                )
                return
            await self._open(envelope)
            return
        stream = self.streams.get(envelope.stream_id)
        if stream is None:
            if envelope.stream_id in self.tombstone_set:
                if payload in _IGNORED_TOMBSTONE_PAYLOADS:
                    return
                raise ValueError("Runner Web tombstoned stream received new data")
            raise ValueError("Runner Web stream is unknown")
        if payload == "window_update":
            if (
                envelope.window_update.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            ):
                raise ValueError("Runner Web response credit direction is invalid")
            async with self.response_credit_changed:
                stream.response_credit.update_consumed(
                    stream_consumed_total=envelope.window_update.stream_consumed_total,
                    session_consumed_total=envelope.window_update.session_consumed_total,
                )
                self.resources.response_consumed_bytes = (
                    envelope.window_update.session_consumed_total
                )
                self.response_credit_changed.notify_all()
            return
        if payload in {"cancel", "reset"}:
            if stream.task is not None:
                stream.task.cancel()
            return
        if payload not in {"data", "direction_end", "websocket"}:
            raise ValueError("Runner Web stream frame is invalid")
        if not await stream.inbound.put(envelope):
            stream.close_reason = CloseReason.RESOURCE_EXHAUSTED
            if stream.task is not None:
                stream.task.cancel()
            return
        if payload in {"data", "websocket"}:
            size = _application_payload_size(envelope)
            self.resources.record_frame(stream.head.protocol, "request", size)
            stream.application_bytes += size

    async def close(
        self,
        *,
        reason: CloseReason = CloseReason.SERVICE_DRAIN,
    ) -> None:
        """Cancel every stream without preserving application outcomes."""
        self.accepting_envelopes = False
        self.accepting_streams = False
        drain_task = self.drain_task
        self.drain_task = None
        if (
            drain_task is not None
            and drain_task is not asyncio.current_task()
            and not drain_task.done()
        ):
            drain_task.cancel()
        if drain_task is not None and drain_task is not asyncio.current_task():
            await asyncio.gather(drain_task, return_exceptions=True)
        active = tuple(self.streams.values())
        tasks = tuple(stream.task for stream in active if stream.task is not None)
        for stream in active:
            stream.close_reason = reason
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.streams.clear()
        self.tombstones.clear()
        self.tombstone_set.clear()
        self.last_stream_id = 0
        if self.session_reserved:
            self.resources.close_session()
            self.session_reserved = False
        if self.session_task_reserved:
            self.resources.end_tasks()
            self.session_task_reserved = False

    async def fail_transport(self) -> None:
        """Fail all old-epoch work when the independent gRPC receiver ends."""
        await self.close(reason=CloseReason.TRANSPORT_UNAVAILABLE)

    async def _run_drain(self, deadline: datetime) -> None:
        """Run one reserved drain task and release its process slot."""
        try:
            await self._drain(deadline)
        finally:
            self.resources.end_tasks()

    async def _drain(self, deadline: datetime) -> None:
        """Wait for active work until the peer deadline, then reset the remainder."""
        tasks = tuple(
            stream.task for stream in self.streams.values() if stream.task is not None
        )
        remaining = max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        if tasks and remaining > 0:
            _, pending = await asyncio.wait(tasks, timeout=remaining)
        else:
            pending = set(tasks)
        for task in pending:
            stream = next(
                (
                    candidate
                    for candidate in self.streams.values()
                    if candidate.task is task
                ),
                None,
            )
            if stream is not None:
                stream.close_reason = CloseReason.SERVICE_DRAIN
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _open(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        started_at = self.monotonic_clock()
        stream_id = envelope.stream_id
        self._claim_stream_id(stream_id)
        authority = _authority(envelope.open.authority)
        head = _head(envelope.open.request_head)
        offer = self.manager.offer
        client = self.manager.client
        if offer is None or client is None:
            raise RuntimeError("Runner Web session epoch is absent")
        if (
            authority.runtime_id != self.manager.runtime_id
            or authority.desired_generation
            != self.manager.accepted_desired_generation()
            or authority.runner_generation != self.manager.accepted_generation()
        ):
            self.resources.record_open_rejected(CloseReason.GENERATION_REPLACED)
            await self._reset(stream_id, CloseReason.GENERATION_REPLACED)
            self._retire(stream_id)
            return
        if not self.resources.try_open_stream(head.protocol):
            self.resources.record_open_rejected(CloseReason.RESOURCE_EXHAUSTED)
            await self._reset(stream_id, CloseReason.RESOURCE_EXHAUSTED)
            self._retire(stream_id)
            return
        if not self.resources.try_begin_tasks():
            self.resources.close_stream(head.protocol)
            self.resources.record_open_rejected(CloseReason.RESOURCE_EXHAUSTED)
            await self._reset(stream_id, CloseReason.RESOURCE_EXHAUSTED)
            self._retire(stream_id)
            return
        stream = _Stream(
            offer=offer,
            client=client,
            authority=authority,
            head=head,
            inbound=_RunnerInboundQueue(self.resources),
            response_credit=HierarchicalCredit(
                stream=AbsoluteCreditWindow(
                    initial_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                    maximum_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                ),
                session=self.response_session_credit,
            ),
            credit_changed=self.response_credit_changed,
            started_at=started_at,
            resources_reserved=True,
        )
        self.streams[stream_id] = stream
        accepted = self._envelope(stream_id=stream_id, offer=offer)
        accepted.open_accepted.data_frame_bytes = (
            APPROVED_SESSION_PROFILE.data_frame_bytes
        )
        accepted.open_accepted.request_credit_bytes = (
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        )
        accepted.open_accepted.response_credit_bytes = (
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        )
        accepted.open_accepted.route_path = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL
        )
        try:
            await self._send(accepted, client=client)
            self.resources.record_open_accepted(
                head.protocol,
                self.monotonic_clock() - started_at,
            )
            stream.task = asyncio.create_task(
                self._run(stream_id, stream),
                name=f"runtime-web-runner-stream:{stream_id}",
            )
        except BaseException:
            if self.streams.pop(stream_id, None) is stream:
                await stream.inbound.close()
                self.resources.end_tasks()
                self.resources.close_stream(head.protocol)
                self._retire(stream_id)
            raise

    async def _run(self, stream_id: int, stream: _Stream) -> None:
        try:
            if stream.head.protocol is StreamProtocol.HTTP:
                await self._http(stream_id, stream)
            else:
                await self._websocket(stream_id, stream)
        except asyncio.CancelledError:
            _LOGGER.info(
                "Runtime Web Runner stream cancelled",
                extra={"close_reason": stream.close_reason.value},
            )
            await self._reset(stream_id, stream.close_reason, stream=stream)
            raise
        except TimeoutError:
            stream.close_reason = CloseReason.DEADLINE
            _LOGGER.info("Runtime Web Runner stream deadline reached")
            await self._reset(stream_id, CloseReason.DEADLINE, stream=stream)
        except OSError, httpcore.NetworkError, httpcore.ProtocolError:
            stream.close_reason = CloseReason.APPLICATION_UNAVAILABLE
            _LOGGER.exception("Runtime Web Runner loopback stream failed")
            await self._reset(
                stream_id,
                CloseReason.APPLICATION_UNAVAILABLE,
                stream=stream,
            )
        except (
            RunnerWebLoopbackProtocolError,
            h11.LocalProtocolError,
            WsprotoLocalProtocolError,
            WsprotoRemoteProtocolError,
        ):
            stream.close_reason = CloseReason.PROTOCOL_VIOLATION
            _LOGGER.warning("Runtime Web Runner WebSocket protocol failed")
            await self._reset(
                stream_id,
                CloseReason.PROTOCOL_VIOLATION,
                stream=stream,
            )
        except RunnerWebResourceExhausted:
            stream.close_reason = CloseReason.RESOURCE_EXHAUSTED
            _LOGGER.warning("Runtime Web Runner hard process limit was exhausted")
            await self._reset(
                stream_id,
                CloseReason.RESOURCE_EXHAUSTED,
                stream=stream,
            )
        except (
            RuntimeError,
            ValueError,
            UnicodeError,
        ):
            stream.close_reason = CloseReason.PROTOCOL_VIOLATION
            _LOGGER.exception("Runtime Web Runner stream protocol failed")
            await self._reset(
                stream_id,
                CloseReason.PROTOCOL_VIOLATION,
                stream=stream,
            )
        else:
            stream.close_reason = CloseReason.CALLER
            _LOGGER.info("Runtime Web Runner stream completed")
        finally:
            if self.streams.pop(stream_id, None) is stream:
                self._retire(stream_id)
            stream.response_credit.close()
            await stream.inbound.close()
            if stream.resources_reserved:
                self.resources.end_tasks()
                self.resources.close_stream(stream.head.protocol)
                self.resources.record_close(
                    stream.close_reason,
                    duration_seconds=self.monotonic_clock() - stream.started_at,
                    application_bytes=stream.application_bytes,
                )

    async def _http(self, stream_id: int, stream: _Stream) -> None:
        remaining = _remaining(stream.authority.transport_deadline_at)
        async with self.manager.loopback.request(
            method=stream.head.method,
            target=stream.head.target,
            headers=tuple(
                (header.name, header.value) for header in stream.head.headers
            ),
            port=stream.authority.port,
            body=self._body(stream_id, stream),
            timeout_seconds=remaining,
        ) as response:
            head = self._envelope(stream_id=stream_id, offer=stream.offer)
            head.response_head.status = response.status
            head.response_head.headers.extend(
                runtime_web_session_pb2.RuntimeWebSessionHeader(name=name, value=value)
                for name, value in response.headers
            )
            await self._send(head, client=stream.client)
            self.resources.record_ttfb(self.monotonic_clock() - stream.started_at)
            sequence = 0
            async for chunk in response.body:
                for data in _chunks(chunk):
                    sequence += 1
                    await self._response_data(stream_id, stream, sequence, data)
            end = self._envelope(stream_id=stream_id, offer=stream.offer)
            end.direction_end.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            )
            end.direction_end.final_sequence = sequence
            await self._send(end, client=stream.client)
            await self._stream_end(stream_id, stream)

    async def _body(self, stream_id: int, stream: _Stream) -> AsyncIterator[bytes]:
        while True:
            envelope = await stream.inbound.get()
            payload = envelope.WhichOneof("payload")
            if payload == "direction_end":
                if (
                    envelope.direction_end.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                    or envelope.direction_end.final_sequence != stream.request_sequence
                ):
                    raise ValueError("Runner Web request end sequence is invalid")
                return
            if (
                payload != "data"
                or envelope.data.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                or envelope.frame_sequence != stream.request_sequence + 1
            ):
                raise ValueError("Runner Web request body sequence is invalid")
            stream.request_sequence = envelope.frame_sequence
            data = bytes(envelope.data.data)
            yield data
            stream.request_consumed_total += len(data)
            self.request_session_consumed_total += len(data)
            self.resources.request_consumed_bytes += len(data)
            update = self._envelope(stream_id=stream_id, offer=stream.offer)
            update.window_update.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
            )
            update.window_update.stream_consumed_total = stream.request_consumed_total
            update.window_update.session_consumed_total = (
                self.request_session_consumed_total
            )
            await self._send(update, client=stream.client)

    async def _websocket(self, stream_id: int, stream: _Stream) -> None:
        websocket = await self.manager.loopback.websocket(
            target=stream.head.target,
            headers=tuple(
                (header.name, header.value) for header in stream.head.headers
            ),
            port=stream.authority.port,
            timeout_seconds=_remaining(stream.authority.transport_deadline_at),
        )
        try:
            head = self._envelope(stream_id=stream_id, offer=stream.offer)
            head.response_head.status = 101
            head.response_head.headers.extend(
                runtime_web_session_pb2.RuntimeWebSessionHeader(name=name, value=value)
                for name, value in websocket.response_headers
            )
            await self._send(head, client=stream.client)
            self.resources.record_ttfb(self.monotonic_clock() - stream.started_at)
            if not self.resources.try_begin_tasks(2):
                raise RunnerWebResourceExhausted(
                    "Runner WebSocket task hard limit is exhausted"
                )
            try:
                browser = asyncio.create_task(self._ws_from_browser(stream, websocket))
                application = asyncio.create_task(
                    self._ws_from_application(stream_id, stream, websocket)
                )
                done, pending = await asyncio.wait(
                    (browser, application),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    await task
            finally:
                self.resources.end_tasks(2)
            await self._stream_end(stream_id, stream)
        finally:
            await websocket.close()

    async def _ws_from_browser(
        self,
        stream: _Stream,
        websocket: RunnerWebSocket,
    ) -> None:
        current: WebSocketOpcode | None = None
        while True:
            envelope = await stream.inbound.get()
            if envelope.WhichOneof("payload") == "direction_end":
                if (
                    envelope.direction_end.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                    or envelope.direction_end.final_sequence != stream.request_sequence
                ):
                    raise ValueError("Runner WebSocket request end is invalid")
                return
            if (
                envelope.WhichOneof("payload") != "websocket"
                or envelope.websocket.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                or envelope.frame_sequence != stream.request_sequence + 1
            ):
                raise ValueError("Runner WebSocket request frame is invalid")
            stream.request_sequence = envelope.frame_sequence
            opcode = _opcode(envelope.websocket.opcode)
            effective = current if opcode is WebSocketOpcode.CONTINUATION else opcode
            if effective is None:
                raise ValueError("Runner WebSocket continuation is invalid")
            data = bytes(envelope.websocket.data)
            await websocket.send(
                _ws_event(
                    effective,
                    data,
                    final=envelope.websocket.final,
                )
            )
            if data and opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                stream.request_consumed_total += len(data)
                self.request_session_consumed_total += len(data)
                self.resources.request_consumed_bytes += len(data)
                update = self._envelope(
                    stream_id=envelope.stream_id,
                    offer=stream.offer,
                )
                update.window_update.direction = (
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                )
                update.window_update.stream_consumed_total = (
                    stream.request_consumed_total
                )
                update.window_update.session_consumed_total = (
                    self.request_session_consumed_total
                )
                await self._send(update, client=stream.client)
            current = None if envelope.websocket.final else effective
            if effective is WebSocketOpcode.CLOSE:
                return

    async def _ws_from_application(
        self,
        stream_id: int,
        stream: _Stream,
        websocket: RunnerWebSocket,
    ) -> None:
        sequence = 0
        fragmented_opcode: WebSocketOpcode | None = None
        async for event in websocket.receive():
            converted = _from_ws_event(event)
            if converted is None:
                continue
            opcode, final, data = converted
            wire_opcode = opcode
            if opcode in {WebSocketOpcode.TEXT, WebSocketOpcode.BINARY}:
                if fragmented_opcode is not None:
                    if opcode is not fragmented_opcode:
                        raise ValueError(
                            "Runner WebSocket response message type changed"
                        )
                    wire_opcode = WebSocketOpcode.CONTINUATION
                if final:
                    fragmented_opcode = None
                else:
                    fragmented_opcode = opcode
            sequence += 1
            if data and wire_opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                await self._reserve(stream, len(data))
            envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
            envelope.frame_sequence = sequence
            envelope.websocket.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            )
            envelope.websocket.opcode = _opcode_proto(wire_opcode)
            envelope.websocket.final = final
            envelope.websocket.data = data
            await self._send(envelope, client=stream.client)
            self.resources.record_frame(stream.head.protocol, "response", len(data))
            stream.application_bytes += len(data)
            if opcode is WebSocketOpcode.CLOSE:
                return

    async def _response_data(
        self,
        stream_id: int,
        stream: _Stream,
        sequence: int,
        data: bytes,
    ) -> None:
        await self._reserve(stream, len(data))
        envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
        envelope.frame_sequence = sequence
        envelope.data.direction = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
        )
        envelope.data.data = data
        await self._send(envelope, client=stream.client)
        self.resources.record_frame(stream.head.protocol, "response", len(data))
        stream.application_bytes += len(data)

    async def _reserve(self, stream: _Stream, size: int) -> None:
        stalled_at: float | None = None
        async with stream.credit_changed:
            if stream.response_credit.available_bytes < size:
                stalled_at = self.monotonic_clock()
                self.resources.credit_stalls += 1
            await stream.credit_changed.wait_for(
                lambda: stream.response_credit.available_bytes >= size
            )
            stream.response_credit.reserve(size)
            self.resources.response_sent_bytes += size
        if stalled_at is not None:
            self.resources.credit_stall_seconds += self.monotonic_clock() - stalled_at

    def _reset_session_flow(self) -> None:
        """Start each Owner epoch with independent absolute session totals."""
        self.request_session_consumed_total = 0
        self.resources.response_sent_bytes = 0
        self.resources.response_consumed_bytes = 0
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
            maximum_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        )
        self.response_credit_changed = asyncio.Condition()
        self.tombstones.clear()
        self.tombstone_set.clear()
        self.last_stream_id = 0

    def _claim_stream_id(self, stream_id: int) -> None:
        """Claim one strictly increasing stream ID for the current session epoch."""
        if stream_id <= self.last_stream_id or stream_id > _MAX_UINT64:
            raise ValueError("Runner Web stream ID is not monotonic")
        self.last_stream_id = stream_id

    def _retire(self, stream_id: int) -> None:
        """Retain one completed stream ID for bounded late-credit handling."""
        if stream_id in self.tombstone_set:
            return
        if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.tombstones.popleft()
            self.tombstone_set.remove(expired)
        self.tombstones.append(stream_id)
        self.tombstone_set.add(stream_id)

    async def _stream_end(self, stream_id: int, stream: _Stream) -> None:
        envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
        envelope.stream_end.SetInParent()
        await self._send(envelope, client=stream.client)

    async def _reset(
        self,
        stream_id: int,
        reason: CloseReason,
        *,
        stream: _Stream | None = None,
    ) -> None:
        offer = self.manager.offer if stream is None else stream.offer
        client = self.manager.client if stream is None else stream.client
        if client is None or offer is None:
            return
        envelope = self._envelope(stream_id=stream_id, offer=offer)
        envelope.reset.reason = _reason_proto(reason)
        self.resources.record_reset(reason)
        await self._send(envelope, client=client)

    async def _send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        client: GrpcRunnerWebSessionClient,
    ) -> None:
        await client.send(envelope)

    def _envelope(
        self,
        *,
        offer: RunnerSessionOffer,
        stream_id: int = 0,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        owner = offer.owner
        return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id=owner.session_lease_id,
            peer_boot_id=self.manager.runner_boot_id,
            owner_boot_id=owner.owner_boot_id,
            session_lease_id=owner.session_lease_id,
            lease_generation=owner.lease_generation,
            stream_id=stream_id,
        )


def _matches_offer(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    offer: RunnerSessionOffer,
) -> bool:
    owner = offer.owner
    return (
        envelope.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
        and envelope.session_id == owner.session_lease_id
        and envelope.owner_boot_id == owner.owner_boot_id
        and envelope.session_lease_id == owner.session_lease_id
        and envelope.lease_generation == owner.lease_generation
    )


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
        open_deadline_at=message.open_deadline_at.ToDatetime(tzinfo=UTC),
        approval_deadline_at=message.approval_deadline_at.ToDatetime(tzinfo=UTC),
        transport_deadline_at=message.transport_deadline_at.ToDatetime(tzinfo=UTC),
    )


def _head(message: runtime_web_session_pb2.RuntimeWebSessionRequestHead) -> RequestHead:
    if message.protocol == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_HTTP:
        protocol = StreamProtocol.HTTP
    elif (
        message.protocol
        == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_WEBSOCKET
    ):
        protocol = StreamProtocol.WEBSOCKET
    else:
        raise ValueError("Runner Web request protocol is invalid")
    return RequestHead(
        protocol=protocol,
        method=bytes(message.method),
        target=bytes(message.target),
        headers=tuple(
            Header(bytes(item.name), bytes(item.value)) for item in message.headers
        ),
    )


def _chunks(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        data[offset : offset + MANDATORY_DATA_FRAME_BYTES]
        for offset in range(0, len(data), MANDATORY_DATA_FRAME_BYTES)
    )


def _remaining(deadline: datetime) -> float:
    seconds = (deadline - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        raise TimeoutError
    return seconds


def _opcode(value: int) -> WebSocketOpcode:
    mapping = {
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT: WebSocketOpcode.TEXT,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY: WebSocketOpcode.BINARY,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION: WebSocketOpcode.CONTINUATION,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PING: WebSocketOpcode.PING,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PONG: WebSocketOpcode.PONG,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CLOSE: WebSocketOpcode.CLOSE,
    }
    try:
        return mapping[value]
    except KeyError:
        raise ValueError("Runner WebSocket opcode is invalid") from None


def _opcode_proto(opcode: WebSocketOpcode) -> int:
    return {
        WebSocketOpcode.TEXT: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT,
        WebSocketOpcode.BINARY: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY,
        WebSocketOpcode.CONTINUATION: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION,
        WebSocketOpcode.PING: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PING,
        WebSocketOpcode.PONG: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PONG,
        WebSocketOpcode.CLOSE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CLOSE,
    }[opcode]


def _reason_proto(reason: CloseReason) -> int:
    return {
        CloseReason.CALLER: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER,
        CloseReason.APPROVAL_EXPIRED: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPROVAL_EXPIRED,
        CloseReason.AUTHORITY_REVOKED: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_AUTHORITY_REVOKED,
        CloseReason.GENERATION_REPLACED: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_GENERATION_REPLACED,
        CloseReason.DEADLINE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_DEADLINE,
        CloseReason.SERVICE_DRAIN: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN,
        CloseReason.OWNER_LOST: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_OWNER_LOST,
        CloseReason.PROTOCOL_VIOLATION: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION,
        CloseReason.RESOURCE_EXHAUSTED: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_RESOURCE_EXHAUSTED,
        CloseReason.APPLICATION_UNAVAILABLE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE,
        CloseReason.TRANSPORT_UNAVAILABLE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE,
    }[reason]


def _application_payload_size(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> int:
    payload = envelope.WhichOneof("payload")
    if payload == "data":
        return len(envelope.data.data)
    if payload == "websocket":
        return len(envelope.websocket.data)
    return 0


def _finite_non_negative(value: float) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError("Runner Web duration metric must be finite and non-negative")
    return value


def _ws_event(opcode: WebSocketOpcode, data: bytes, *, final: bool) -> Event:
    if opcode is WebSocketOpcode.TEXT:
        return TextMessage(data=data.decode("utf-8"), message_finished=final)
    if opcode is WebSocketOpcode.BINARY:
        return BytesMessage(data=data, message_finished=final)
    if opcode is WebSocketOpcode.PING:
        return Ping(payload=data)
    if opcode is WebSocketOpcode.PONG:
        return Pong(payload=data)
    if opcode is WebSocketOpcode.CLOSE:
        code = int.from_bytes(data[:2], "big") if len(data) >= 2 else 1000
        return CloseConnection(
            code=code, reason=data[2:].decode("utf-8", errors="replace")
        )
    raise ValueError("Runner WebSocket continuation must retain its message type")


def _from_ws_event(event: Event) -> tuple[WebSocketOpcode, bool, bytes] | None:
    if isinstance(event, TextMessage):
        return WebSocketOpcode.TEXT, event.message_finished, event.data.encode()
    if isinstance(event, BytesMessage):
        return WebSocketOpcode.BINARY, event.message_finished, bytes(event.data)
    if isinstance(event, Ping):
        return WebSocketOpcode.PING, True, event.payload
    if isinstance(event, Pong):
        return WebSocketOpcode.PONG, True, event.payload
    if isinstance(event, CloseConnection):
        return (
            WebSocketOpcode.CLOSE,
            True,
            event.code.to_bytes(2, "big") + (event.reason or "").encode(),
        )
    return None
