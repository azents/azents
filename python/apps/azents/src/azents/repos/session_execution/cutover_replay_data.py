"""Detached Team Session cutover replay results and invariant failures."""

import dataclasses

from azents.repos.session_execution.cutover_replay import CutoverReplayCandidate


@dataclasses.dataclass(frozen=True)
class TeamSessionCutoverReplayReport:
    """Content-free result of one bounded preflight or replay batch."""

    scanned_sessions: int
    valid_sessions: int
    replayed_sessions: int
    pending_input_sessions: int
    pending_command_sessions: int
    recoverable_run_sessions: int
    pending_idle_continuation_sessions: int
    stop_request_sessions: int
    invariant_failures: tuple[tuple[str, int], ...]
    next_session_cursor: str | None


@dataclasses.dataclass(frozen=True)
class TeamSessionCutoverReplayInvariantFailure(Exception):
    """A replay batch contains invalid durable execution state."""

    invariant_failures: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        Exception.__init__(self, "Team Session cutover replay preflight failed")


@dataclasses.dataclass(frozen=True)
class TeamSessionCutoverPreflightBatch:
    """One validated durable batch retained for exact replay."""

    report: TeamSessionCutoverReplayReport
    valid_candidates: tuple[CutoverReplayCandidate, ...]
