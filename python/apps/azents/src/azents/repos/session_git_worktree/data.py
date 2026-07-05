"""Session Git worktree repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)


class SessionGitWorktree(BaseModel):
    """Azents-owned Git worktree allocation."""

    id: str = Field(description="Session Git worktree ID")
    session_id: str = Field(description="AgentSession ID")
    initialization_id: str = Field(description="SessionInitialization ID")
    step_id: str = Field(description="Create Git worktree initialization step ID")
    action_execution_id: str | None = Field(
        description="ActionExecution ID for operation-based worktree creation"
    )
    session_workspace_project_id: str | None = Field(
        description="Registered SessionWorkspaceProject ID"
    )
    source_project_path: str = Field(description="Source Project path")
    starting_ref: str = Field(description="User-selected starting ref")
    base_commit: str | None = Field(description="Runner-resolved base commit")
    worktree_path: str = Field(description="Allocated worktree path")
    branch_name: str = Field(description="Allocated Git branch name")
    branch_created_by: SessionGitWorktreeBranchCreatedBy = Field(
        description="Branch creator"
    )
    status: SessionGitWorktreeStatus = Field(description="Worktree lifecycle status")
    failure_summary: str | None = Field(description="User-safe creation failure")
    cleanup_summary: str | None = Field(description="User-safe cleanup failure")
    ready_at: datetime.datetime | None = Field(description="Ready time")
    failed_at: datetime.datetime | None = Field(description="Failure time")
    cleaned_at: datetime.datetime | None = Field(description="Cleanup completion time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionGitWorktreeCreate(BaseModel):
    """Session Git worktree create schema."""

    id: str = Field(description="Session Git worktree ID")
    session_id: str = Field(description="AgentSession ID")
    initialization_id: str = Field(description="SessionInitialization ID")
    step_id: str = Field(description="Create Git worktree initialization step ID")
    action_execution_id: str | None = Field(
        description="ActionExecution ID for operation-based worktree creation"
    )
    session_workspace_project_id: str | None = Field(
        description="Registered SessionWorkspaceProject ID"
    )
    source_project_path: str = Field(description="Source Project path")
    starting_ref: str = Field(description="User-selected starting ref")
    worktree_path: str = Field(description="Allocated worktree path")
    branch_name: str = Field(description="Allocated Git branch name")
    branch_created_by: SessionGitWorktreeBranchCreatedBy = Field(
        description="Branch creator"
    )
    status: SessionGitWorktreeStatus = Field(description="Initial status")
