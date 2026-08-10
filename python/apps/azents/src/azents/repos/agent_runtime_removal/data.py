"""Agent Runtime removal repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)


class AgentRuntimeRemovalOperation(BaseModel):
    """Durable content-free Agent Runtime removal operation."""

    id: str = Field(description="Runtime removal operation ID")
    agent_id: str = Field(description="Target Agent ID")
    workspace_id: str = Field(description="Target Workspace ID")
    requested_by_workspace_user_id: str | None = Field(
        description="WorkspaceUser that confirmed removal"
    )
    idempotency_key: str = Field(description="Removal request idempotency key")
    expected_capability_version: int = Field(
        ge=1,
        description="Capability version supplied by the requester",
    )
    committed_capability_version: int = Field(
        ge=2,
        description="Capability version committed with the removal fence",
    )
    agent_runtime_id: str | None = Field(description="Logical Runtime ID")
    status: AgentRuntimeRemovalStatus = Field(description="Operation status")
    stage: AgentRuntimeRemovalStage = Field(description="Current removal stage")
    confirmed_at: datetime.datetime = Field(description="Final confirmation time")
    destructive_scope_version: int = Field(
        ge=1,
        description="Immutable destructive-scope contract version",
    )
    active_root_session_count: int = Field(
        ge=0,
        description="Privacy-safe active root Session count",
    )
    active_subagent_count: int = Field(
        ge=0,
        description="Privacy-safe active subagent count",
    )
    active_run_count: int = Field(
        ge=0,
        description="Privacy-safe active Run count",
    )
    queued_runtime_action_count: int = Field(
        ge=0,
        description="Privacy-safe queued Runtime action count",
    )
    cleanup_cursor_context_id: str | None = Field(
        description="Internal bounded cleanup cursor"
    )
    cleanup_scanned_context_count: int = Field(
        ge=0,
        description="Root contexts covered by cleanup",
    )
    cleanup_invalidated_context_count: int = Field(
        ge=0,
        description="Root contexts invalidated by cleanup",
    )
    product_cleanup_completed_at: datetime.datetime | None = Field(
        description="Product cleanup completion time"
    )
    physical_deletion_required: bool | None = Field(
        description="Whether physical deletion is required"
    )
    target_terminal_delete_generation: int | None = Field(
        description="Exact terminal-delete generation"
    )
    physical_delete_requested_at: datetime.datetime | None = Field(
        description="Physical delete request time"
    )
    physical_delete_acknowledgement_kind: (
        RuntimeTerminalDeleteAcknowledgementKind | None
    ) = Field(description="Authority that proved physical deletion")
    physical_delete_acknowledged_at: datetime.datetime | None = Field(
        description="Physical delete acknowledgement time"
    )
    attempt_count: int = Field(ge=0, description="Coordinator attempt count")
    lease_owner: str | None = Field(description="Coordinator lease owner")
    lease_until: datetime.datetime | None = Field(description="Lease expiry")
    next_attempt_at: datetime.datetime | None = Field(
        description="Scheduled retry time"
    )
    last_error_kind: str | None = Field(description="Last bounded error kind")
    last_error_summary: str | None = Field(description="Last safe error summary")
    started_at: datetime.datetime | None = Field(
        description="First coordinator processing time"
    )
    completed_at: datetime.datetime | None = Field(
        description="Operation completion time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalCreateResult:
    """Idempotent Runtime removal operation creation result."""

    operation: AgentRuntimeRemovalOperation
    idempotency_match: bool
