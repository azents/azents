"""Chat session service data models."""

import dataclasses

from azents.core.enums import AgentRunPhase, AgentRunStatus, AgentRuntimeRunState
from azents.engine.events.types import Event
from azents.engine.tools.goal import GoalStateSnapshot, GoalStatus
from azents.engine.tools.todo import TodoStateSnapshot

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PaginatedEvents:
    """Paginated event result."""

    items: list[Event]
    has_more: bool
    has_newer: bool = False


@dataclasses.dataclass(frozen=True)
class ChatLiveRunState:
    """Current live execution state."""

    run_id: str
    phase: AgentRunPhase
    status: AgentRunStatus


@dataclasses.dataclass(frozen=True)
class ChatLiveStateSnapshot:
    """Current chat live state taxonomy snapshot."""

    partial_history_events: list[Event]
    input_buffer_events: list[Event]
    run: ChatLiveRunState | None = None
    session_run_state: AgentRuntimeRunState = AgentRuntimeRunState.IDLE
    todo: TodoStateSnapshot | None = None
    goal: GoalStateSnapshot | None = None


@dataclasses.dataclass(frozen=True)
class UpdateGoalResult:
    """Goal update result and wake-up information."""

    goal: GoalStateSnapshot
    agent_id: str
    workspace_id: str
    wake_up: bool
    event: Event | None = None


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class EnsureSessionInput:
    """Session ensure input."""

    session_id: str | None
    agent_id: str
    user_id: str


@dataclasses.dataclass(frozen=True)
class UpdateGoalStatusInput:
    """Goal status update input."""

    status: GoalStatus
    resume_hint: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AgentNotFound:
    """Agent not found."""


@dataclasses.dataclass(frozen=True)
class NotWorkspaceMember:
    """Not a workspace member."""


@dataclasses.dataclass(frozen=True)
class SessionAccessDenied:
    """Session access denied."""


@dataclasses.dataclass(frozen=True)
class SessionNotFound:
    """Session not found."""


@dataclasses.dataclass(frozen=True)
class InvalidGoalStatusTransition:
    """Disallowed Goal status transition."""


EnsureSessionError = AgentNotFound | NotWorkspaceMember | SessionAccessDenied
SessionAccessError = SessionNotFound | SessionAccessDenied
DeleteSessionError = SessionAccessDenied
DeleteInputBufferError = SessionNotFound | SessionAccessDenied
UpdateGoalError = SessionNotFound | SessionAccessDenied | InvalidGoalStatusTransition
