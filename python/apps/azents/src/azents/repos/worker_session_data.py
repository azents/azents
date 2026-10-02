"""Canonical Worker Session operation outcomes and work-drift error."""

import dataclasses
from enum import StrEnum

from azents.repos.session_execution import CanonicalExecutionSnapshotError


class CanonicalExecutionWorkDriftError(CanonicalExecutionSnapshotError):
    """Durable command or recoverable work changed after its canonical snapshot."""


class WorkerIdleDisposition(StrEnum):
    """Outcome of the existing atomic true-idle admission predicates."""

    IDLE = "idle"
    COMMAND_PENDING = "command_pending"
    WAKE_INPUT_PENDING = "wake_input_pending"
    RUN_ACTIVE = "run_active"


@dataclasses.dataclass(frozen=True)
class WorkerIdleTransition:
    """Detached idle decision with identities required for existing audit logs."""

    disposition: WorkerIdleDisposition
    command_id: str | None
    run_id: str | None


@dataclasses.dataclass(frozen=True)
class StuckWorkerSession:
    """Detached routing identities selected by the existing recovery scan."""

    id: str
    agent_id: str
