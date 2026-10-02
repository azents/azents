"""Detached database inputs for Provider and Runner report operations."""

from dataclasses import dataclass
from datetime import datetime

from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence

from azents.core.enums import RuntimeProviderObservedState, RuntimeRunnerState


@dataclass(frozen=True)
class ProviderReportInput:
    """Lifecycle and configuration facts decoded before database persistence."""

    runtime_id: str
    provider_id: str
    provider_generation: int
    observed_state: RuntimeProviderObservedState
    observed_desired_generation: int
    provider_runtime_id: str | None
    terminal_delete_acknowledged: bool
    runtime_configuration: RuntimeConfigurationEvidence
    reported_at: datetime


@dataclass(frozen=True)
class RunnerReportInput:
    """Runner facts with transport state mapped before database persistence."""

    runtime_id: str
    runner_generation: int
    runner_state: RuntimeRunnerState
    runner_stream_closed: bool
    unsupported_runner_state: str | None
    workspace_path: str
    runtime_configuration: RuntimeConfigurationEvidence
    reported_at: datetime
