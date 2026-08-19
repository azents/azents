"""AgentSession repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    SessionAgentKind,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.inference_profile import (
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)


@dataclasses.dataclass(frozen=True)
class AgentSessionUnreadTerminalRunProjection:
    """AgentSession with its sparse shared unread terminal Run boundary."""

    session: "AgentSession"
    unread_terminal_run_id: str | None
    auto_archive_after: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class AgentSessionPage:
    """One bounded AgentSession page."""

    items: list["AgentSession"]
    total_count: int


@dataclasses.dataclass(frozen=True)
class AgentSessionProjectionPage:
    """One bounded AgentSession projection page."""

    items: list[AgentSessionUnreadTerminalRunProjection]
    total_count: int


@dataclasses.dataclass(frozen=True)
class AgentSessionSidebarSummary:
    """Bounded sidebar projections for one Agent."""

    pinned: list[AgentSessionUnreadTerminalRunProjection]
    recent: list[AgentSessionUnreadTerminalRunProjection]


@dataclasses.dataclass(frozen=True)
class AgentSessionEnsureTeamPrimaryResult:
    """Race-aware team-primary ensure result."""

    session: "AgentSession"
    created: bool


class AgentSession(BaseModel):
    """AgentSession domain model."""

    id: str = Field(description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    handle: str = Field(description="Human-readable session handle")
    inference_state: SessionInferenceState | None = Field(
        description="Resolved inference configuration prepared for the current turn",
    )
    applied_inference_profile: SessionAppliedInferenceProfile | None = Field(
        default=None,
        description="Agent-owned model intent applied to the Session",
    )
    session_kind: AgentSessionKind = Field(description="Session listing category")
    status: AgentSessionStatus = Field(description="AgentSession status")
    primary_kind: AgentSessionPrimaryKind | None = Field(
        default=None,
        description="Primary session role",
    )
    product_mode: AgentSessionProductMode | None = Field(
        description="Root product mode; null for subagent rows",
    )
    associated_user_id: str | None = Field(
        description="Durable associated User for root User Sessions",
    )
    start_reason: AgentSessionStartReason = Field(description="Start reason")
    title: str | None = Field(description="User-facing session title")
    title_source: AgentSessionTitleSource | None = Field(
        description="Source of the current session title",
    )
    title_generated_at: datetime.datetime | None = Field(
        description="Automatic title generation time",
    )
    title_generation_event_id: str | None = Field(
        description="Event ID used for automatic title generation",
    )
    last_user_input_at: datetime.datetime = Field(
        description="Latest user input timestamp or creation-time baseline",
    )
    last_activity_at: datetime.datetime = Field(
        description="Latest user, Agent, or tool activity timestamp",
    )
    pinned: bool = Field(
        description="Whether this root Session is excluded from automatic archive",
    )
    end_reason: AgentSessionEndReason | None = Field(
        default=None, description="End reason"
    )
    model_input_head_event_id: str | None = Field(
        default=None,
        description="Model input head event ID",
    )
    model_input_head_model_order: int | None = Field(
        default=None,
        description="Model input head model order",
    )
    model_file_gc_cursor_event_id: str | None = Field(
        default=None,
        description="ModelFile GC cursor event ID",
    )
    model_file_gc_cursor_model_order: int = Field(
        default=0,
        description="ModelFile GC cursor model order",
    )
    started_at: datetime.datetime = Field(description="Start time")
    lifecycle_started_at: datetime.datetime | None = Field(
        default=None, description="Lifecycle start hook claim time"
    )
    run_state: AgentSessionRunState = Field(
        default=AgentSessionRunState.IDLE,
        description="Session execution state",
    )
    run_heartbeat_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        description="Run heartbeat time",
    )
    pending_idle_continuation_run_id: str | None = Field(
        default=None,
        description="Completed Run awaiting session idle continuation evaluation",
    )
    owner_generation: int = Field(
        ge=0,
        description="Durable session ownership generation",
    )
    pending_command_id: str | None = Field(
        default=None, description="Pending command ID"
    )
    pending_command_name: str | None = Field(
        default=None, description="Pending command name"
    )
    pending_command_payload: dict[str, object] | None = Field(
        default=None,
        description="Pending command payload",
    )
    pending_command_requester_user_id: str | None = Field(
        default=None, description="Pending command requester User ID"
    )
    pending_command_created_at: datetime.datetime | None = Field(
        default=None,
        description="Pending command created timestamp",
    )
    stop_requested_at: datetime.datetime | None = Field(
        default=None,
        description="Stop intent timestamp",
    )
    stop_requester_user_id: str | None = Field(
        default=None, description="Stop requester User ID"
    )
    stop_request_id: str | None = Field(
        default=None, description="Stop request correlation ID"
    )
    archived_at: datetime.datetime | None = Field(
        default=None, description="Archive boundary timestamp"
    )
    purge_after: datetime.datetime | None = Field(
        default=None, description="Scheduled purge eligibility timestamp"
    )
    archive_policy_revision: int | None = Field(
        default=None, description="Retention policy revision snapshot"
    )
    archive_retention_days_snapshot: int | None = Field(
        default=None, description="Retention days snapshot; null means Unlimited"
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionAgent(BaseModel):
    """SessionAgent domain model."""

    id: str = Field(description="SessionAgent ID")
    context_id: str = Field(description="SessionAgentContext ID")
    root_session_agent_id: str = Field(description="Root SessionAgent ID")
    agent_session_id: str = Field(description="Linked AgentSession ID")
    kind: SessionAgentKind = Field(description="SessionAgent tree node kind")
    name: str = Field(description="Tree-local name")
    path: str = Field(description="Canonical absolute tree path")
    agent_type: str = Field(description="Agent type identifier")
    parent_session_agent_id: str | None = Field(
        description="Parent SessionAgent ID",
    )
    last_task_message: str | None = Field(description="Latest delegated task preview")
    last_message_at: datetime.datetime | None = Field(
        description="Latest agent-to-agent message activity time",
    )
    parent_observed_run_index: int | None = Field(
        description="Latest terminal run index observed by parent",
    )
    parent_observed_event_id: str | None = Field(
        description="Latest terminal event ID observed by parent",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionWorkingFolderContext(BaseModel):
    """Stored Session working-folder ownership context."""

    id: str = Field(description="SessionAgentContext ID")
    agent_id: str = Field(description="Agent ID")
    agent_runtime_id: str | None = Field(description="Current AgentRuntime ID")
    working_folder_path: str | None = Field(
        description="Exact historical working-folder path"
    )
    binding_state: SessionWorkingFolderBindingState = Field(
        description="Current working-folder Runtime authority"
    )
    invalidated_by_removal_id: str | None = Field(
        description="Runtime removal operation that invalidated this binding"
    )
    invalidated_at: datetime.datetime | None = Field(
        description="Working-folder binding invalidation time"
    )
    cleanup_status: SessionWorkingFolderCleanupStatus = Field(
        description="Latest archive cleanup state"
    )


def require_session_working_folder_path(
    context: SessionWorkingFolderContext,
) -> str:
    """Return the stored path while legacy path authority remains active."""
    if context.working_folder_path is None:
        raise RuntimeError("Session working-folder path is unavailable")
    return context.working_folder_path


class PendingSessionCommand(BaseModel):
    """AgentSession pending command."""

    id: str = Field(description="Pending command ID")
    name: str = Field(description="Command name")
    payload: dict[str, object] = Field(description="Command payload")
    requester_user_id: str | None = Field(description="Command requester User ID")
    created_at: datetime.datetime = Field(description="Command created timestamp")


class AgentSessionCreate(BaseModel):
    """AgentSession create schema."""

    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    title: str | None = Field(description="User-facing session title")
    session_kind: AgentSessionKind = Field(
        default=AgentSessionKind.ROOT,
        description="Session listing category",
    )
    primary_kind: AgentSessionPrimaryKind | None = Field(
        default=None,
        description="Primary session role",
    )
    product_mode: AgentSessionProductMode | None = Field(
        description="Root product mode; null for subagent rows",
    )
    associated_user_id: str | None = Field(
        description="Durable associated User for root User Sessions",
    )
    start_reason: AgentSessionStartReason = Field(
        default=AgentSessionStartReason.INITIAL,
        description="Start reason",
    )
