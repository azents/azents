"""Agent Runtime system-metrics read models."""

import datetime
import enum

from azents_runtime_control.system_metrics import (
    RunnerSystemMetricAvailability,
    RunnerSystemMetricsScope,
)
from pydantic import BaseModel


class RuntimeSystemMetricState(enum.StrEnum):
    """Server-derived state of one current metric projection."""

    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    STOPPED = "stopped"
    DISCONNECTED = "disconnected"


class RuntimeSystemMetricsSummary(enum.StrEnum):
    """Server-derived overall Runtime metrics summary."""

    FRESH = "fresh"
    PARTIAL = "partial"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    STOPPED = "stopped"
    DISCONNECTED = "disconnected"


class RuntimeSystemMetricCurrent(BaseModel):
    """Current privacy-safe projection for one metric."""

    state: RuntimeSystemMetricState
    measured_at: datetime.datetime | None
    used: int | None
    total: int | None
    percentage: float | None


class RuntimeSystemMetricObservation(BaseModel):
    """One normalized observation in a retained sample."""

    availability: RunnerSystemMetricAvailability
    used: int | None
    total: int | None


class RuntimeSystemMetricsSample(BaseModel):
    """One privacy-safe retained metrics sample."""

    measured_at: datetime.datetime
    scope: RunnerSystemMetricsScope
    cpu: RuntimeSystemMetricObservation
    memory: RuntimeSystemMetricObservation
    disk: RuntimeSystemMetricObservation


class AgentRuntimeSystemMetricsOutput(BaseModel):
    """Dedicated Agent Runtime system-metrics overview."""

    summary: RuntimeSystemMetricsSummary
    scope: RunnerSystemMetricsScope | None
    cpu: RuntimeSystemMetricCurrent
    memory: RuntimeSystemMetricCurrent
    disk: RuntimeSystemMetricCurrent
    samples: list[RuntimeSystemMetricsSample]
