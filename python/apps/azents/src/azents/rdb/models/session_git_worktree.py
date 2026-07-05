"""Session Git worktree allocation model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _session_git_worktree_status_values(
    enum_cls: type[SessionGitWorktreeStatus],
) -> list[str]:
    """Return SessionGitWorktreeStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_git_worktree_branch_created_by_values(
    enum_cls: type[SessionGitWorktreeBranchCreatedBy],
) -> list[str]:
    """Return SessionGitWorktreeBranchCreatedBy enum values stored in the DB."""
    return [v.value for v in enum_cls]


session_git_worktree_status_enum = ENUM(
    SessionGitWorktreeStatus,
    name="session_git_worktree_status",
    create_type=False,
    values_callable=_session_git_worktree_status_values,
)
session_git_worktree_branch_created_by_enum = ENUM(
    SessionGitWorktreeBranchCreatedBy,
    name="session_git_worktree_branch_created_by",
    create_type=False,
    values_callable=_session_git_worktree_branch_created_by_values,
)


class RDBSessionGitWorktree(RDBModel):
    """Authoritative Azents-owned Git worktree allocation."""

    __tablename__ = "session_git_worktrees"

    IX_SESSION_ID = sa.Index("ix_session_git_worktrees_session_id", "session_id")
    IX_STATUS = sa.Index("ix_session_git_worktrees_status", "status")
    IX_SESSION_STATUS = sa.Index(
        "ix_session_git_worktrees_session_id_status",
        "session_id",
        "status",
    )
    IX_SESSION_WORKSPACE_PROJECT_ID = sa.Index(
        "ix_session_git_worktrees_session_workspace_project_id",
        "session_workspace_project_id",
    )
    IX_ACTION_EXECUTION_ID = sa.Index(
        "ix_session_git_worktrees_action_execution_id",
        "action_execution_id",
    )
    IX_WORKTREE_PATH = sa.Index(
        "ix_session_git_worktrees_worktree_path",
        "worktree_path",
    )
    IX_BRANCH_NAME = sa.Index(
        "ix_session_git_worktrees_branch_name",
        "branch_name",
    )

    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    initialization_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_initializations.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_initialization_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_project_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    starting_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    worktree_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    branch_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    branch_created_by: Mapped[SessionGitWorktreeBranchCreatedBy] = mapped_column(
        session_git_worktree_branch_created_by_enum,
        nullable=False,
        default=SessionGitWorktreeBranchCreatedBy.AZENTS,
    )
    action_execution_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("action_executions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    status: Mapped[SessionGitWorktreeStatus] = mapped_column(
        session_git_worktree_status_enum,
        nullable=False,
        default=SessionGitWorktreeStatus.PENDING,
    )
    session_workspace_project_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_workspace_projects.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    base_commit: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    failure_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    cleanup_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    ready_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    failed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    cleaned_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_SESSION_ID,
        IX_STATUS,
        IX_SESSION_STATUS,
        IX_SESSION_WORKSPACE_PROJECT_ID,
        IX_ACTION_EXECUTION_ID,
        IX_WORKTREE_PATH,
        IX_BRANCH_NAME,
    )
