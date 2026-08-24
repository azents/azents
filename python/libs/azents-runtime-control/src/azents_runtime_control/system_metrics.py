"""Shared Runtime Runner system-metrics contracts."""

import dataclasses
import enum

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
class CollectedRunnerSystemMetrics:
    """One collector result before Runtime identity and sequence are attached."""

    scope: RunnerSystemMetricsScope
    cpu: RunnerSystemMetricObservation
    memory: RunnerSystemMetricObservation
    disk: RunnerSystemMetricObservation


@dataclasses.dataclass(frozen=True)
class RunnerSystemMetricsReport:
    """One normalized Runner report sent to Runtime Control."""

    runtime_id: str
    sequence: int
    scope: RunnerSystemMetricsScope
    cpu: RunnerSystemMetricObservation
    memory: RunnerSystemMetricObservation
    disk: RunnerSystemMetricObservation

    def __post_init__(self) -> None:
        """Validate report identity and ordering fields."""
        if not self.runtime_id or len(self.runtime_id) > 120:
            raise ValueError("Runtime metrics identity must be within 120 characters")
        if self.sequence <= 0:
            raise ValueError("Runtime metrics sequence must be positive")
