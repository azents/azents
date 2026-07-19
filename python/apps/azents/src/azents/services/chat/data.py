"""Chat session service data models."""

import dataclasses
import datetime
from typing import Literal

from azents.core.enums import AgentRunPhase, AgentRunStatus, AgentSessionRunState
from azents.core.inference_profile import AppliedInferenceProfile
from azents.engine.events.types import Event
from azents.engine.run.failure import (
    FailedRunAttemptSource,
    FailedRunErrorKind,
    FailedRunRetryability,
)
from azents.engine.tools.goal import GoalStateSnapshot, GoalStatus
from azents.engine.tools.todo import TodoStateSnapshot
from azents.repos.action_execution.data import ActionExecutionProjection

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
class ChatLiveRunOperation:
    """Current live operation projected within one Run."""

    kind: Literal["preparing_context"]
    operation_id: str
    status: Literal["running"]


@dataclasses.dataclass(frozen=True)
class ChatLiveRunRetryAttempt:
    """User-safe failed-run retry attempt summary."""

    attempt_number: int
    user_message: str
    error_type: str
    source: FailedRunAttemptSource
    failed_at: str
    backoff_seconds: int
    next_retry_at: str
    retryability: FailedRunRetryability
    failure_code: str | None
    truncated: bool


@dataclasses.dataclass(frozen=True)
class ChatLiveRunRetryState:
    """Current live failed-run retry state."""

    error_kind: FailedRunErrorKind
    status: str
    last_error_message: str
    failed_attempt_count: int
    max_retries: int
    backoff_seconds: int
    next_retry_at: str
    attempts: list[ChatLiveRunRetryAttempt]


@dataclasses.dataclass(frozen=True)
class ChatLiveRunState:
    """Current live execution state."""

    run_id: str
    phase: AgentRunPhase
    status: AgentRunStatus
    inference_profile: AppliedInferenceProfile
    model_call_started_at: datetime.datetime | None
    operation: ChatLiveRunOperation | None = None
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
    action_executions: list[ActionExecutionProjection] = dataclasses.field(
        default_factory=list,
    )


@dataclasses.dataclass(frozen=True)
class SubagentTreeNode:
    """Subagent tree projection node."""

    session_agent_id: str
    agent_session_id: str
    parent_session_agent_id: str | None
    name: str
    path: str
    agent_type: str
    status: str
    last_task_message: str | None
    last_message_at: datetime.datetime | None
    unread_result: bool
    latest_run_id: str | None
    latest_run_index: int | None
    latest_run_status: AgentRunStatus | None
    terminal_result_event_id: str | None
    terminal_result_message: str | None
    children: list["SubagentTreeNode"] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class SubagentTreeProjection:
    """Subagent tree projection for one root SessionAgent tree."""

    root_session_agent_id: str
    root_agent_session_id: str
    current_session_agent_id: str
    nodes: list[SubagentTreeNode]


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
    cleanup_requested: bool


@dataclasses.dataclass(frozen=True)
class NewSessionProjectDefaultsSource:
    """Source metadata for new-session Project defaults."""

    type: Literal["empty", "last_created_session"]
    session_id: str | None = None


@dataclasses.dataclass(frozen=True)
class NewSessionDefaultExistingProjectWorkspaceItem:
    """Existing Project item default for a new AgentSession."""

    path: str


@dataclasses.dataclass(frozen=True)
class NewSessionDefaultGitWorktreeWorkspaceItem:
    """Git worktree item default for a new AgentSession."""

    source_project_path: str
    starting_ref: str | None


NewSessionProjectDefaultWorkspaceItem = (
    NewSessionDefaultExistingProjectWorkspaceItem
    | NewSessionDefaultGitWorktreeWorkspaceItem
)


@dataclasses.dataclass(frozen=True)
class NewSessionProjectDefaults:
    """Default workspace items for a new non-primary AgentSession."""

    project_paths: list[str]
    items: list[NewSessionProjectDefaultWorkspaceItem]
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
class SubagentSessionReadOnly:
    """Child subagent session does not accept direct human writes."""


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
class PurgeStartedRestoreBlocked:
    """Restore is blocked after irreversible purge fencing starts."""


@dataclasses.dataclass(frozen=True)
class InvalidSessionTitle:
    """Invalid AgentSession title."""

    reason: str


EnsureSessionError = AgentNotFound | NotWorkspaceMember | SessionAccessDenied
SessionAccessError = SessionNotFound | SessionAccessDenied
DeleteInputBufferError = SessionNotFound | SessionAccessDenied | SubagentSessionReadOnly
UpdateGoalError = (
    SessionNotFound
    | SessionAccessDenied
    | SubagentSessionReadOnly
    | InvalidGoalStatusTransition
)
ArchiveSessionError = (
    SessionNotFound
    | SessionAccessDenied
    | SubagentSessionReadOnly
    | PrimarySessionArchiveBlocked
    | RunningSessionArchiveBlocked
)
RestoreSessionError = SessionNotFound | SessionAccessDenied | PurgeStartedRestoreBlocked
UpdateSessionTitleError = (
    SessionNotFound
    | SessionAccessDenied
    | SubagentSessionReadOnly
    | InvalidSessionTitle
)
