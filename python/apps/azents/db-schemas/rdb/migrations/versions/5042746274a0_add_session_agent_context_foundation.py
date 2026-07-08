"""add session agent context foundation

Revision ID: 5042746274a0
Revises: fcca7ecdd59b
Create Date: 2026-07-08 08:31:19.596333

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5042746274a0"
down_revision: str | Sequence[str] | None = "fcca7ecdd59b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_SESSION_KIND_VALUES = ("root", "subagent")
SESSION_AGENT_KIND_VALUES = ("root", "subagent")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    postgresql.ENUM(
        *AGENT_SESSION_KIND_VALUES,
        name="agent_session_kind",
    ).create(bind)
    postgresql.ENUM(
        *SESSION_AGENT_KIND_VALUES,
        name="session_agent_kind",
    ).create(bind)

    op.add_column(
        "agent_sessions",
        sa.Column(
            "session_kind",
            postgresql.ENUM(name="agent_session_kind", create_type=False),
            nullable=True,
        ),
    )
    op.execute("UPDATE agent_sessions SET session_kind = 'root'")
    op.alter_column("agent_sessions", "session_kind", nullable=False)
    op.create_index(
        "ix_agent_sessions_session_kind",
        "agent_sessions",
        ["session_kind"],
    )

    op.create_table(
        "session_agent_contexts",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("root_session_agent_id", sa.String(length=32), nullable=True),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"], ["agent_runtimes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "root_session_agent_id",
            name="uq_session_agent_contexts_root_session_agent_id",
        ),
    )
    op.create_index(
        "ix_session_agent_contexts_agent_id",
        "session_agent_contexts",
        ["agent_id"],
    )
    op.create_index(
        "ix_session_agent_contexts_workspace_id",
        "session_agent_contexts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_session_agent_contexts_agent_runtime_id",
        "session_agent_contexts",
        ["agent_runtime_id"],
    )

    op.create_table(
        "session_agents",
        sa.Column("context_id", sa.String(length=32), nullable=False),
        sa.Column("root_session_agent_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="session_agent_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("agent_type", sa.String(length=120), nullable=False),
        sa.Column("parent_session_agent_id", sa.String(length=32), nullable=True),
        sa.Column("last_task_message", sa.Text(), nullable=True),
        sa.Column("parent_observed_run_index", sa.Integer(), nullable=True),
        sa.Column("parent_observed_event_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["context_id"], ["session_agent_contexts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_agent_id"], ["session_agents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["root_session_agent_id"], ["session_agents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_session_id",
            name="uq_session_agents_agent_session_id",
        ),
        sa.UniqueConstraint(
            "root_session_agent_id",
            "path",
            name="uq_session_agents_root_path",
        ),
        sa.UniqueConstraint(
            "parent_session_agent_id",
            "name",
            name="uq_session_agents_parent_name",
        ),
    )
    op.create_index("ix_session_agents_context_id", "session_agents", ["context_id"])
    op.create_index(
        "ix_session_agents_root_session_agent_id",
        "session_agents",
        ["root_session_agent_id"],
    )
    op.create_index(
        "ix_session_agents_parent_session_agent_id",
        "session_agents",
        ["parent_session_agent_id"],
    )
    op.create_table(
        "session_agent_context_projects",
        sa.Column("session_agent_context_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_agent_context_id"],
            ["session_agent_contexts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_agent_context_id",
            "path",
            name="uq_session_agent_context_projects_context_path",
        ),
    )
    op.create_index(
        "ix_session_agent_context_projects_context_id",
        "session_agent_context_projects",
        ["session_agent_context_id"],
    )

    op.create_table(
        "session_agent_context_git_worktrees",
        sa.Column("session_agent_context_id", sa.String(length=32), nullable=False),
        sa.Column("source_project_path", sa.Text(), nullable=False),
        sa.Column("starting_ref", sa.Text(), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column(
            "branch_created_by",
            postgresql.ENUM(
                name="session_git_worktree_branch_created_by",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="session_git_worktree_status", create_type=False),
            nullable=False,
        ),
        sa.Column("created_by_session_agent_id", sa.String(length=32), nullable=True),
        sa.Column("created_by_agent_session_id", sa.String(length=32), nullable=True),
        sa.Column("action_execution_id", sa.String(length=32), nullable=True),
        sa.Column(
            "session_agent_context_project_id", sa.String(length=32), nullable=True
        ),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("cleanup_summary", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"], ["action_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_session_id"],
            ["agent_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_session_agent_id"], ["session_agents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_agent_context_id"],
            ["session_agent_contexts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_agent_context_project_id"],
            ["session_agent_context_projects.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_context_id",
        "session_agent_context_git_worktrees",
        ["session_agent_context_id"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_status",
        "session_agent_context_git_worktrees",
        ["status"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_context_id_status",
        "session_agent_context_git_worktrees",
        ["session_agent_context_id", "status"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_context_project_id",
        "session_agent_context_git_worktrees",
        ["session_agent_context_project_id"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_action_execution_id",
        "session_agent_context_git_worktrees",
        ["action_execution_id"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_worktree_path",
        "session_agent_context_git_worktrees",
        ["worktree_path"],
    )
    op.create_index(
        "ix_session_agent_context_git_worktrees_branch_name",
        "session_agent_context_git_worktrees",
        ["branch_name"],
    )

    op.execute(
        """
        INSERT INTO session_agent_contexts (
            id,
            agent_id,
            workspace_id,
            root_session_agent_id,
            agent_runtime_id,
            created_at,
            updated_at
        )
        SELECT
            md5('session-agent-context:' || s.id),
            s.agent_id,
            s.workspace_id,
            md5('session-agent:' || s.id),
            r.id,
            s.created_at,
            s.updated_at
        FROM agent_sessions s
        LEFT JOIN agent_runtimes r ON r.agent_id = s.agent_id
        """
    )
    op.execute(
        """
        INSERT INTO session_agents (
            id,
            context_id,
            root_session_agent_id,
            parent_session_agent_id,
            agent_session_id,
            kind,
            name,
            path,
            agent_type,
            created_at,
            updated_at
        )
        SELECT
            md5('session-agent:' || s.id),
            md5('session-agent-context:' || s.id),
            md5('session-agent:' || s.id),
            NULL,
            s.id,
            'root',
            'root',
            '/root',
            'default',
            s.created_at,
            s.updated_at
        FROM agent_sessions s
        """
    )
    op.create_foreign_key(
        "fk_session_agent_contexts_root_session_agent_id_session_agents",
        "session_agent_contexts",
        "session_agents",
        ["root_session_agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute(
        """
        INSERT INTO session_agent_context_projects (
            id,
            session_agent_context_id,
            path,
            created_at,
            updated_at
        )
        SELECT
            p.id,
            sa.context_id,
            p.path,
            p.created_at,
            p.updated_at
        FROM session_workspace_projects p
        JOIN session_agents sa ON sa.agent_session_id = p.session_id
        """
    )
    op.execute(
        """
        INSERT INTO session_agent_context_git_worktrees (
            id,
            session_agent_context_id,
            created_by_session_agent_id,
            created_by_agent_session_id,
            action_execution_id,
            session_agent_context_project_id,
            source_project_path,
            starting_ref,
            base_commit,
            worktree_path,
            branch_name,
            branch_created_by,
            status,
            failure_summary,
            cleanup_summary,
            ready_at,
            failed_at,
            cleaned_at,
            created_at,
            updated_at
        )
        SELECT
            w.id,
            sa.context_id,
            sa.id,
            w.session_id,
            w.action_execution_id,
            w.session_workspace_project_id,
            w.source_project_path,
            w.starting_ref,
            w.base_commit,
            w.worktree_path,
            w.branch_name,
            w.branch_created_by,
            w.status,
            w.failure_summary,
            w.cleanup_summary,
            w.ready_at,
            w.failed_at,
            w.cleaned_at,
            w.created_at,
            w.updated_at
        FROM session_git_worktrees w
        JOIN session_agents sa ON sa.agent_session_id = w.session_id
        """
    )

    op.drop_table("session_git_worktrees")
    op.drop_table("session_workspace_projects")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "session_workspace_projects",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "path",
            name="uq_session_workspace_projects_session_path",
        ),
    )
    op.create_index(
        "ix_session_workspace_projects_session_id",
        "session_workspace_projects",
        ["session_id"],
    )

    op.create_table(
        "session_git_worktrees",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("source_project_path", sa.Text(), nullable=False),
        sa.Column("starting_ref", sa.Text(), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column(
            "branch_created_by",
            postgresql.ENUM(
                name="session_git_worktree_branch_created_by",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("action_execution_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="session_git_worktree_status", create_type=False),
            nullable=False,
        ),
        sa.Column("session_workspace_project_id", sa.String(length=32), nullable=True),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("cleanup_summary", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"],
            ["action_executions.id"],
            name="fk_session_git_worktrees_action_execution_id_action_executions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_workspace_project_id"],
            ["session_workspace_projects.id"],
            name="fk_session_git_worktrees_session_workspace_project_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_git_worktrees_session_id",
        "session_git_worktrees",
        ["session_id"],
    )
    op.create_index(
        "ix_session_git_worktrees_status",
        "session_git_worktrees",
        ["status"],
    )
    op.create_index(
        "ix_session_git_worktrees_session_id_status",
        "session_git_worktrees",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_session_git_worktrees_session_workspace_project_id",
        "session_git_worktrees",
        ["session_workspace_project_id"],
    )
    op.create_index(
        "ix_session_git_worktrees_action_execution_id",
        "session_git_worktrees",
        ["action_execution_id"],
    )
    op.create_index(
        "ix_session_git_worktrees_worktree_path",
        "session_git_worktrees",
        ["worktree_path"],
    )
    op.create_index(
        "ix_session_git_worktrees_branch_name",
        "session_git_worktrees",
        ["branch_name"],
    )

    op.execute(
        """
        INSERT INTO session_workspace_projects (
            id,
            session_id,
            path,
            created_at,
            updated_at
        )
        SELECT
            p.id,
            sa.agent_session_id,
            p.path,
            p.created_at,
            p.updated_at
        FROM session_agent_context_projects p
        JOIN session_agents sa ON sa.context_id = p.session_agent_context_id
        WHERE sa.parent_session_agent_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO session_git_worktrees (
            id,
            session_id,
            action_execution_id,
            session_workspace_project_id,
            source_project_path,
            starting_ref,
            base_commit,
            worktree_path,
            branch_name,
            branch_created_by,
            status,
            failure_summary,
            cleanup_summary,
            ready_at,
            failed_at,
            cleaned_at,
            created_at,
            updated_at
        )
        SELECT
            w.id,
            COALESCE(w.created_by_agent_session_id, sa.agent_session_id),
            w.action_execution_id,
            w.session_agent_context_project_id,
            w.source_project_path,
            w.starting_ref,
            w.base_commit,
            w.worktree_path,
            w.branch_name,
            w.branch_created_by,
            w.status,
            w.failure_summary,
            w.cleanup_summary,
            w.ready_at,
            w.failed_at,
            w.cleaned_at,
            w.created_at,
            w.updated_at
        FROM session_agent_context_git_worktrees w
        JOIN session_agents sa ON sa.context_id = w.session_agent_context_id
        WHERE sa.parent_session_agent_id IS NULL
        """
    )

    op.drop_index(
        "ix_session_agent_context_git_worktrees_branch_name",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_worktree_path",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_action_execution_id",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_context_project_id",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_context_id_status",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_status",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_index(
        "ix_session_agent_context_git_worktrees_context_id",
        table_name="session_agent_context_git_worktrees",
    )
    op.drop_table("session_agent_context_git_worktrees")

    op.drop_index(
        "ix_session_agent_context_projects_context_id",
        table_name="session_agent_context_projects",
    )
    op.drop_table("session_agent_context_projects")

    op.drop_constraint(
        "fk_session_agent_contexts_root_session_agent_id_session_agents",
        "session_agent_contexts",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_session_agents_parent_session_agent_id",
        table_name="session_agents",
    )
    op.drop_index(
        "ix_session_agents_root_session_agent_id",
        table_name="session_agents",
    )
    op.drop_index("ix_session_agents_context_id", table_name="session_agents")
    op.drop_table("session_agents")

    op.drop_index(
        "ix_session_agent_contexts_agent_runtime_id",
        table_name="session_agent_contexts",
    )
    op.drop_index(
        "ix_session_agent_contexts_workspace_id",
        table_name="session_agent_contexts",
    )
    op.drop_index(
        "ix_session_agent_contexts_agent_id",
        table_name="session_agent_contexts",
    )
    op.drop_table("session_agent_contexts")

    op.drop_index("ix_agent_sessions_session_kind", table_name="agent_sessions")
    op.drop_column("agent_sessions", "session_kind")

    bind = op.get_bind()
    postgresql.ENUM(name="session_agent_kind").drop(bind)
    postgresql.ENUM(name="agent_session_kind").drop(bind)
