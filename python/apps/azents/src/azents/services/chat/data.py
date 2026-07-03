"""Chat session service data models."""

import dataclasses
from typing import Literal

from azents.core.enums import AgentRunPhase, AgentRunStatus, AgentSessionRunState
from azents.engine.events.types import Event
from azents.engine.tools.goal import GoalStateSnapshot, GoalStatus
from azents.engine.tools.todo import TodoStateSnapshot
from azents.services.session_initialization import SessionInitializationProjection

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
class ChatLiveRunRetryState:
    """Current live failed-run retry state."""

    status: str
    last_error_message: str
    failed_attempt_count: int
    max_retries: int
    backoff_seconds: int
    next_retry_at: str


@dataclasses.dataclass(frozen=True)
class ChatLiveRunState:
    """Current live execution state."""

    run_id: str
    phase: AgentRunPhase
    status: AgentRunStatus
    retry: ChatLiveRunRetryState | None = None


@dataclasses.dataclass(frozen=True)
class ChatLiveStateSnapshot:
    """Current chat live state taxonomy snapshot."""

    partial_history_events: list[Event]
    input_buffer_events: list[Event]
    run: ChatLiveRunState | None = None
    session_run_state: AgentSessionRunState = AgentSessionRunState.IDLE
    todo: TodoStateSnapshot | None = None
    goal: GoalStateSnapshot | None = None
    initialization: SessionInitializationProjection | None = None


@dataclasses.dataclass(frozen=True)
class UpdateGoalResult:
    """Goal update result and wake-up information."""

    goal: GoalStateSnapshot
    agent_id: str
    workspace_id: str
    wake_up: bool
    event: Event | None = None


@dataclasses.dataclass(frozen=True)
class ArchiveSessionResult:
    """AgentSession archive result."""

    archived_session_id: str


@dataclasses.dataclass(frozen=True)
class NewSessionProjectDefaultsSource:
    """Source metadata for new-session Project defaults."""

    type: Literal["empty", "last_created_session"]
    session_id: str | None = None


@dataclasses.dataclass(frozen=True)
class NewSessionProjectDefaults:
    """Default Project paths for a new non-primary AgentSession."""

    project_paths: list[str]
    source: NewSessionProjectDefaultsSource


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


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


@dataclasses.dataclass(frozen=True)
class PrimarySessionArchiveBlocked:
    """Team primary AgentSession archive is blocked."""


@dataclasses.dataclass(frozen=True)
class RunningSessionArchiveBlocked:
    """Running AgentSession archive is blocked."""


@dataclasses.dataclass(frozen=True)
class InvalidSessionTitle:
    """Invalid AgentSession title."""

    reason: str


EnsureSessionError = AgentNotFound | NotWorkspaceMember | SessionAccessDenied
SessionAccessError = SessionNotFound | SessionAccessDenied
DeleteSessionError = SessionAccessDenied
DeleteInputBufferError = SessionNotFound | SessionAccessDenied
UpdateGoalError = SessionNotFound | SessionAccessDenied | InvalidGoalStatusTransition
ArchiveSessionError = (
    SessionNotFound
    | SessionAccessDenied
    | PrimarySessionArchiveBlocked
    | RunningSessionArchiveBlocked
)
UpdateSessionTitleError = SessionNotFound | SessionAccessDenied | InvalidSessionTitle
