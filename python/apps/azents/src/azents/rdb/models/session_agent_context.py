"""SessionAgentContext shared root-tree resource models."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.session_git_worktree import (
    session_git_worktree_branch_created_by_enum,
    session_git_worktree_status_enum,
)
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBSessionAgentContext(RDBModel):
    """Shared context for one root SessionAgent tree."""

    __tablename__ = "session_agent_contexts"

    UQ_ROOT_SESSION_AGENT_ID = sa.UniqueConstraint(
        "root_session_agent_id",
        name="uq_session_agent_contexts_root_session_agent_id",
    )
    IX_AGENT_ID = sa.Index("ix_session_agent_contexts_agent_id", "agent_id")
    IX_WORKSPACE_ID = sa.Index(
        "ix_session_agent_contexts_workspace_id",
        "workspace_id",
    )
    IX_AGENT_RUNTIME_ID = sa.Index(
        "ix_session_agent_contexts_agent_runtime_id",
        "agent_runtime_id",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    root_session_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "session_agents.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_session_agent_contexts_root_session_agent_id_session_agents",
        ),
        nullable=True,
        default=None,
    )
    agent_runtime_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
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
        UQ_ROOT_SESSION_AGENT_ID,
        IX_AGENT_ID,
        IX_WORKSPACE_ID,
        IX_AGENT_RUNTIME_ID,
    )


class RDBSessionAgentContextProject(RDBModel):
    """Project registered for a SessionAgentContext."""

    __tablename__ = "session_agent_context_projects"

    UQ_CONTEXT_PATH = sa.UniqueConstraint(
        "session_agent_context_id",
        "path",
        name="uq_session_agent_context_projects_context_path",
    )
    IX_CONTEXT_ID = sa.Index(
        "ix_session_agent_context_projects_context_id",
        "session_agent_context_id",
    )

    session_agent_context_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agent_contexts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
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

    __table_args__ = (UQ_CONTEXT_PATH, IX_CONTEXT_ID)


class RDBSessionAgentContextGitWorktree(RDBModel):
    """Authoritative Azents-owned Git worktree allocation for a context."""

    __tablename__ = "session_agent_context_git_worktrees"

    IX_CONTEXT_ID = sa.Index(
        "ix_session_agent_context_git_worktrees_context_id",
        "session_agent_context_id",
    )
    IX_STATUS = sa.Index("ix_session_agent_context_git_worktrees_status", "status")
    IX_CONTEXT_STATUS = sa.Index(
        "ix_session_agent_context_git_worktrees_context_id_status",
        "session_agent_context_id",
        "status",
    )
    IX_CONTEXT_PROJECT_ID = sa.Index(
        "ix_session_agent_context_git_worktrees_context_project_id",
        "session_agent_context_project_id",
    )
    IX_ACTION_EXECUTION_ID = sa.Index(
        "ix_session_agent_context_git_worktrees_action_execution_id",
        "action_execution_id",
    )
    IX_WORKTREE_PATH = sa.Index(
        "ix_session_agent_context_git_worktrees_worktree_path",
        "worktree_path",
    )
    IX_BRANCH_NAME = sa.Index(
        "ix_session_agent_context_git_worktrees_branch_name",
        "branch_name",
    )

    session_agent_context_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agent_contexts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_project_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    starting_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    worktree_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    branch_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    branch_created_by: Mapped[SessionGitWorktreeBranchCreatedBy] = mapped_column(
        session_git_worktree_branch_created_by_enum,
        nullable=False,
    )
    status: Mapped[SessionGitWorktreeStatus] = mapped_column(
        session_git_worktree_status_enum,
        nullable=False,
    )
    created_by_session_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agents.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_by_agent_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    action_execution_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("action_executions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    session_agent_context_project_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_agent_context_projects.id", ondelete="SET NULL"),
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

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
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
        IX_CONTEXT_ID,
        IX_STATUS,
        IX_CONTEXT_STATUS,
        IX_CONTEXT_PROJECT_ID,
        IX_ACTION_EXECUTION_ID,
        IX_WORKTREE_PATH,
        IX_BRANCH_NAME,
    )
