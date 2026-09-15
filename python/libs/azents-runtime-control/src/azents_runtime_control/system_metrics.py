"""Shared Runtime Runner system-metrics contracts."""

import dataclasses
import enum
import math
from typing import Self

from azents_runtime_control.runtime_web_session import (
    CloseReason,
    StreamDirection,
    StreamProtocol,
)

RUNNER_SYSTEM_METRICS_CAPABILITY = "runtime.system-metrics.v1"
RUNNER_SYSTEM_METRICS_MAX_MESSAGE_BYTES = 4 * 1024


class RunnerSystemMetricsScope(enum.StrEnum):
    """Physical execution environment visible to the Runner."""

    HOST = "host"
    VM = "vm"
    CONTAINER = "container"


class RunnerSystemMetricAvailability(enum.StrEnum):
    """Availability of one normalized metric observation."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclasses.dataclass(frozen=True)
class RunnerSystemMetricObservation:
    """One normalized CPU, memory, or disk observation."""

    availability: RunnerSystemMetricAvailability
    used: int | None
    total: int | None

    def __post_init__(self) -> None:
        """Validate normalized observation invariants."""
        if self.availability is RunnerSystemMetricAvailability.AVAILABLE:
            if self.used is None or self.used < 0:
                raise ValueError("Available metric usage must be non-negative")
            if self.total is not None and self.total <= 0:
                raise ValueError("Metric total must be positive when supplied")
            return
        if self.used is not None or self.total is not None:
            raise ValueError("Unavailable metrics must not carry values")


@dataclasses.dataclass(frozen=True)
class RunnerRuntimeWebProtocolCount:
    """One bounded Runtime Web protocol counter."""

    protocol: StreamProtocol
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("Runtime Web protocol count must not be negative")


@dataclasses.dataclass(frozen=True)
class RunnerRuntimeWebReasonCount:
    """One bounded Runtime Web close-reason counter."""

    reason: CloseReason
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("Runtime Web reason count must not be negative")


@dataclasses.dataclass(frozen=True)
class RunnerRuntimeWebTrafficCount:
    """One bounded Runtime Web protocol and direction traffic aggregate."""

    protocol: StreamProtocol
    direction: StreamDirection
    frames: int
    bytes: int

    def __post_init__(self) -> None:
        if self.frames < 0 or self.bytes < 0:
            raise ValueError("Runtime Web traffic counts must not be negative")


@dataclasses.dataclass(frozen=True)
class RunnerRuntimeWebMetrics:
    """Bounded content-free Runtime Web process aggregate."""

    active_sessions: int
    active_streams: int
    maximum_sessions: int
    maximum_active_streams: int
    application_buffer_bytes: int
    application_buffer_limit_bytes: int
    control_buffer_bytes: int
    control_buffer_limit_bytes: int
    queued_envelopes: int
    queued_envelope_limit: int
    pending_tasks: int
    pending_task_limit: int
    event_loop_lag_milliseconds: float
    event_loop_lag_limit_milliseconds: int
    resident_memory_bytes: int
    resident_memory_limit_bytes: int
    credit_stalls_total: int
    credit_stall_seconds: float
    request_consumed_bytes: int
    response_sent_bytes: int
    response_consumed_bytes: int
    heartbeats_total: int
    go_aways_total: int
    epoch_transitions_total: int
    setup_seconds_sum: float
    setup_count: int
    ttfb_seconds_sum: float
    ttfb_count: int
    duration_seconds_sum: float
    duration_count: int
    goodput_bytes: int
    active_streams_by_protocol: tuple[RunnerRuntimeWebProtocolCount, ...]
    opens_accepted_by_protocol: tuple[RunnerRuntimeWebProtocolCount, ...]
    opens_rejected_by_reason: tuple[RunnerRuntimeWebReasonCount, ...]
    resets_by_reason: tuple[RunnerRuntimeWebReasonCount, ...]
    closes_by_reason: tuple[RunnerRuntimeWebReasonCount, ...]
    traffic: tuple[RunnerRuntimeWebTrafficCount, ...]

    @classmethod
    def zero(
        cls,
        *,
        maximum_sessions: int,
        maximum_active_streams: int,
        application_buffer_limit_bytes: int,
        control_buffer_limit_bytes: int,
        queued_envelope_limit: int,
        pending_task_limit: int,
        event_loop_lag_limit_milliseconds: int,
        resident_memory_limit_bytes: int,
    ) -> Self:
        """Create a zero-usage aggregate for explicit positive hard limits."""
        return cls(
            active_sessions=0,
            active_streams=0,
            maximum_sessions=maximum_sessions,
            maximum_active_streams=maximum_active_streams,
            application_buffer_bytes=0,
            application_buffer_limit_bytes=application_buffer_limit_bytes,
            control_buffer_bytes=0,
            control_buffer_limit_bytes=control_buffer_limit_bytes,
            queued_envelopes=0,
            queued_envelope_limit=queued_envelope_limit,
            pending_tasks=0,
            pending_task_limit=pending_task_limit,
            event_loop_lag_milliseconds=0.0,
            event_loop_lag_limit_milliseconds=event_loop_lag_limit_milliseconds,
            resident_memory_bytes=0,
            resident_memory_limit_bytes=resident_memory_limit_bytes,
            credit_stalls_total=0,
            credit_stall_seconds=0.0,
            request_consumed_bytes=0,
            response_sent_bytes=0,
            response_consumed_bytes=0,
            heartbeats_total=0,
            go_aways_total=0,
            epoch_transitions_total=0,
            setup_seconds_sum=0.0,
            setup_count=0,
            ttfb_seconds_sum=0.0,
            ttfb_count=0,
            duration_seconds_sum=0.0,
            duration_count=0,
            goodput_bytes=0,
            active_streams_by_protocol=tuple(
                RunnerRuntimeWebProtocolCount(protocol=protocol, value=0)
                for protocol in StreamProtocol
            ),
            opens_accepted_by_protocol=tuple(
                RunnerRuntimeWebProtocolCount(protocol=protocol, value=0)
                for protocol in StreamProtocol
            ),
            opens_rejected_by_reason=tuple(
                RunnerRuntimeWebReasonCount(reason=reason, value=0)
                for reason in CloseReason
            ),
            resets_by_reason=tuple(
                RunnerRuntimeWebReasonCount(reason=reason, value=0)
                for reason in CloseReason
            ),
            closes_by_reason=tuple(
                RunnerRuntimeWebReasonCount(reason=reason, value=0)
                for reason in CloseReason
            ),
            traffic=tuple(
                RunnerRuntimeWebTrafficCount(
                    protocol=protocol,
                    direction=direction,
                    frames=0,
                    bytes=0,
                )
                for protocol in StreamProtocol
                for direction in StreamDirection
            ),
        )

    def __post_init__(self) -> None:
        """Validate bounded dimensions, finite sums, usage, and hard limits."""
        integers = (
            self.active_sessions,
            self.active_streams,
            self.application_buffer_bytes,
            self.control_buffer_bytes,
            self.queued_envelopes,
            self.pending_tasks,
            self.resident_memory_bytes,
            self.credit_stalls_total,
            self.request_consumed_bytes,
            self.response_sent_bytes,
            self.response_consumed_bytes,
            self.heartbeats_total,
            self.go_aways_total,
            self.epoch_transitions_total,
            self.setup_count,
            self.ttfb_count,
            self.duration_count,
            self.goodput_bytes,
        )
        if any(value < 0 for value in integers):
            raise ValueError("Runtime Web metric values must not be negative")
        limits = (
            self.maximum_sessions,
            self.maximum_active_streams,
            self.application_buffer_limit_bytes,
            self.control_buffer_limit_bytes,
            self.queued_envelope_limit,
            self.pending_task_limit,
            self.event_loop_lag_limit_milliseconds,
            self.resident_memory_limit_bytes,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("Runtime Web metric limits must be positive")
        floating = (
            self.event_loop_lag_milliseconds,
            self.credit_stall_seconds,
            self.setup_seconds_sum,
            self.ttfb_seconds_sum,
            self.duration_seconds_sum,
        )
        if any(not math.isfinite(value) or value < 0 for value in floating):
            raise ValueError(
                "Runtime Web metric durations must be finite and non-negative"
            )
        _validate_exact_values(
            tuple(item.protocol for item in self.active_streams_by_protocol),
            frozenset(StreamProtocol),
            "active stream protocol",
        )
        _validate_exact_values(
            tuple(item.protocol for item in self.opens_accepted_by_protocol),
            frozenset(StreamProtocol),
            "accepted open protocol",
        )
        _validate_exact_values(
            tuple(item.reason for item in self.opens_rejected_by_reason),
            frozenset(CloseReason),
            "rejected open reason",
        )
        _validate_exact_values(
            tuple(item.reason for item in self.resets_by_reason),
            frozenset(CloseReason),
            "reset reason",
        )
        _validate_exact_values(
            tuple(item.reason for item in self.closes_by_reason),
            frozenset(CloseReason),
            "close reason",
        )
        _validate_exact_values(
            tuple((item.protocol, item.direction) for item in self.traffic),
            frozenset(
                (protocol, direction)
                for protocol in StreamProtocol
                for direction in StreamDirection
            ),
            "traffic",
        )


@dataclasses.dataclass(frozen=True)
class CollectedRunnerSystemMetrics:
    """One collector result before Runtime identity and sequence are attached."""

    scope: RunnerSystemMetricsScope
    cpu: RunnerSystemMetricObservation
    memory: RunnerSystemMetricObservation
    disk: RunnerSystemMetricObservation
    runtime_web: RunnerRuntimeWebMetrics


@dataclasses.dataclass(frozen=True)
class RunnerSystemMetricsReport:
    """One normalized Runner report sent to Runtime Control."""

    runtime_id: str
    sequence: int
    scope: RunnerSystemMetricsScope
    cpu: RunnerSystemMetricObservation
    memory: RunnerSystemMetricObservation
    disk: RunnerSystemMetricObservation
    runtime_web: RunnerRuntimeWebMetrics

    def __post_init__(self) -> None:
        """Validate report identity and ordering fields."""
        if not self.runtime_id or len(self.runtime_id) > 120:
            raise ValueError("Runtime metrics identity must be within 120 characters")
        if self.sequence <= 0:
            raise ValueError("Runtime metrics sequence must be positive")


def _validate_exact_values[ValueT](
    values: tuple[ValueT, ...],
    expected: frozenset[ValueT],
    dimension: str,
) -> None:
    if len(values) != len(expected) or set(values) != expected:
        raise ValueError(
            f"Runtime Web {dimension} dimensions must exactly cover the closed set"
        )
