"""Chat session service data models."""

import dataclasses
import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from azents.core.enums import AgentRunPhase, AgentRunStatus, AgentSessionRunState
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.engine.events.action_messages import ChatAction
from azents.engine.events.types import Event, FileOutputPart
from azents.engine.run.failure import (
    FailedRunAttemptSource,
    FailedRunErrorKind,
    FailedRunRetryability,
)
from azents.engine.tools.goal import GoalStateSnapshot, GoalStatus
from azents.engine.tools.todo import TodoStateSnapshot
from azents.repos.action_execution.data import ActionExecutionProjection


class PendingMailboxUserMessagePresentation(BaseModel):
    """Safe pending user-message presentation."""

    type: Literal["user_message"]
    content: str
    attachments: list[str] = Field(default_factory=list)
    file_parts: list[FileOutputPart] = Field(default_factory=list)
    requested_inference_profile: RequestedInferenceProfile | None = None


class PendingMailboxGoalContinuationPresentation(BaseModel):
    """Safe pending Goal continuation presentation."""

    type: Literal["goal_continuation"]
    content: str
    requested_inference_profile: RequestedInferenceProfile | None = None


class PendingMailboxExternalChannelContinuationPresentation(BaseModel):
    """Safe pending External Channel continuation presentation."""

    type: Literal["external_channel_continuation"]
    content: str
    requested_inference_profile: RequestedInferenceProfile | None = None


class PendingMailboxAgentMessagePresentation(BaseModel):
    """Safe pending Agent-to-Agent message presentation."""

    type: Literal["agent_message"]
    message_kind: Literal[
        "spawn_agent",
        "send_message",
        "followup_task",
        "agent_result",
    ]
    content: str


class PendingMailboxExternalChannelPresentation(BaseModel):
    """Safe pending External Channel message presentation."""

    type: Literal["external_channel_message"]
    provider: str
    resource_label: str
    resource_type: str
    external_message_id: str
    sender_display_name: str | None
    author_type: str
    authorization: Literal["context_only", "authorized_invocation"]
    body: str | None
    original_url: str | None


class PendingMailboxActionPresentation(BaseModel):
    """Safe pending Turn Action presentation."""

    type: Literal["action_message"]
    action: ChatAction
    message: str
    requested_inference_profile: RequestedInferenceProfile | None = None


PendingMailboxPresentation = Annotated[
    PendingMailboxUserMessagePresentation
    | PendingMailboxGoalContinuationPresentation
    | PendingMailboxExternalChannelContinuationPresentation
    | PendingMailboxAgentMessagePresentation
    | PendingMailboxExternalChannelPresentation
    | PendingMailboxActionPresentation,
    Field(discriminator="type"),
]


class PendingMailboxItem(BaseModel):
    """One stable pending mailbox presentation item."""

    id: str
    mailbox_item_id: str
    item_key: str
    kind: str
    state: Literal["pending"] = "pending"
    created_at: datetime.datetime
    presentation: PendingMailboxPresentation


class PendingMailboxEnvelope(BaseModel):
    """Stable pending mailbox envelope projection."""

    mailbox_item_id: str
    session_id: str
    kind: str
    scheduling_mode: str
    created_at: datetime.datetime
    items: list[PendingMailboxItem] = Field(min_length=1)


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
    mailbox_items: list[PendingMailboxEnvelope]
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
class UnreadTerminalRunNotTerminal:
    """Observed Run is not terminal and cannot acknowledge review."""


@dataclasses.dataclass(frozen=True)
class InvalidGoalStatusTransition:
    """Disallowed Goal status transition."""


@dataclasses.dataclass(frozen=True)
class PrimarySessionArchiveBlocked:
    """Team primary AgentSession archive is blocked."""


@dataclasses.dataclass(frozen=True)
class PrimarySessionPinBlocked:
    """Team primary AgentSession pin updates are blocked."""


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
DeleteMailboxItemError = SessionNotFound | SessionAccessDenied | SubagentSessionReadOnly
PrepareSessionWorkingFolderError = (
    SessionNotFound | SessionAccessDenied | SubagentSessionReadOnly
)
AcknowledgeUnreadTerminalRunError = SessionNotFound | UnreadTerminalRunNotTerminal
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
SetSessionPinnedError = (
    SessionNotFound
    | SessionAccessDenied
    | SubagentSessionReadOnly
    | PrimarySessionPinBlocked
)
