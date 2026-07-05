"""add action execution state

Revision ID: 19deaed8bcd4
Revises: 7a2b40acb270
Create Date: 2026-07-05 08:33:19.625778

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "19deaed8bcd4"
down_revision: str | Sequence[str] | None = "7a2b40acb270"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


action_execution_status = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    "failed_final",
    name="action_execution_status",
)
action_execution_event_kind = postgresql.ENUM(
    "info",
    "step_started",
    "command_started",
    "stdout",
    "stderr",
    "command_completed",
    "warning",
    "failed",
    "retry_requested",
    "failed_finalized",
    "completed",
    name="action_execution_event_kind",
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    action_execution_status.create(bind, checkfirst=True)
    action_execution_event_kind.create(bind, checkfirst=True)
    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("action_event_id", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            action_execution_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_final_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["action_event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "action_event_id",
            name="uq_action_executions_action_event_id",
        ),
    )
    op.create_index(
        "ix_action_executions_session_id",
        "action_executions",
        ["session_id"],
    )
    op.create_index(
        "ix_action_executions_session_id_action_event_id",
        "action_executions",
        ["session_id", "action_event_id"],
    )
    op.create_index(
        "ix_action_executions_session_id_status",
        "action_executions",
        ["session_id", "status"],
    )
    op.create_table(
        "action_execution_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("action_execution_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", action_execution_event_kind, nullable=False),
        sa.Column("step_key", sa.Text(), nullable=True),
        sa.Column("command_argv", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["action_execution_id"],
            ["action_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "action_execution_id",
            "sequence",
            name="uq_action_execution_events_execution_sequence",
        ),
    )
    op.create_index(
        "ix_action_execution_events_action_execution_id",
        "action_execution_events",
        ["action_execution_id"],
    )
    op.create_index(
        "ix_action_execution_events_session_id",
        "action_execution_events",
        ["session_id"],
    )
    op.add_column(
        "session_git_worktrees",
        sa.Column("action_execution_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_session_git_worktrees_action_execution_id_action_executions",
        "session_git_worktrees",
        "action_executions",
        ["action_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_session_git_worktrees_action_execution_id",
        "session_git_worktrees",
        ["action_execution_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_session_git_worktrees_action_execution_id",
        table_name="session_git_worktrees",
    )
    op.drop_constraint(
        "fk_session_git_worktrees_action_execution_id_action_executions",
        "session_git_worktrees",
        type_="foreignkey",
    )
    op.drop_column("session_git_worktrees", "action_execution_id")
    op.drop_index(
        "ix_action_execution_events_session_id",
        table_name="action_execution_events",
    )
    op.drop_index(
        "ix_action_execution_events_action_execution_id",
        table_name="action_execution_events",
    )
    op.drop_table("action_execution_events")
    op.drop_index(
        "ix_action_executions_session_id_status",
        table_name="action_executions",
    )
    op.drop_index(
        "ix_action_executions_session_id_action_event_id",
        table_name="action_executions",
    )
    op.drop_index("ix_action_executions_session_id", table_name="action_executions")
    op.drop_table("action_executions")
    bind = op.get_bind()
    action_execution_event_kind.drop(bind, checkfirst=True)
    action_execution_status.drop(bind, checkfirst=True)
