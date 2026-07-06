"""remove session initialization schema

Revision ID: d7bb232faa3c
Revises: 19deaed8bcd4
Create Date: 2026-07-06 00:51:18.623468

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7bb232faa3c"
down_revision: str | Sequence[str] | None = "19deaed8bcd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

session_initialization_status = postgresql.ENUM(
    "pending",
    "running",
    "ready",
    "failed",
    "canceled",
    "cleanup_required",
    "cleaned",
    name="session_initialization_status",
)
session_initialization_step_status = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "canceled",
    name="session_initialization_step_status",
)
session_initialization_step_type = postgresql.ENUM(
    "noop_ready",
    "create_git_worktree",
    "register_workspace_project",
    "upsert_project_catalog",
    "refresh_project_status",
    "run_workspace_setup_script",
    "verify_required_credentials",
    name="session_initialization_step_type",
)
session_initialization_event_kind = postgresql.ENUM(
    "info",
    "command_started",
    "stdout",
    "stderr",
    "command_completed",
    "warning",
    "failed",
    name="session_initialization_event_kind",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'action_execution_result'"
    )

    op.drop_constraint(
        "session_git_worktrees_step_id_fkey",
        "session_git_worktrees",
        type_="foreignkey",
    )
    op.drop_constraint(
        "session_git_worktrees_initialization_id_fkey",
        "session_git_worktrees",
        type_="foreignkey",
    )
    op.drop_column("session_git_worktrees", "step_id")
    op.drop_column("session_git_worktrees", "initialization_id")

    op.drop_table("session_initialization_events")
    op.drop_table("session_initialization_steps")
    op.drop_table("session_initializations")

    bind = op.get_bind()
    session_initialization_event_kind.drop(bind, checkfirst=True)
    session_initialization_step_type.drop(bind, checkfirst=True)
    session_initialization_step_status.drop(bind, checkfirst=True)
    session_initialization_status.drop(bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    session_initialization_status.create(bind, checkfirst=True)
    session_initialization_step_status.create(bind, checkfirst=True)
    session_initialization_step_type.create(bind, checkfirst=True)
    session_initialization_event_kind.create(bind, checkfirst=True)

    op.create_table(
        "session_initializations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_initialization_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
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
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_session_initializations_session_id"),
    )
    op.create_index(
        "ix_session_initializations_session_id",
        "session_initializations",
        ["session_id"],
    )
    op.create_index(
        "ix_session_initializations_status",
        "session_initializations",
        ["status"],
    )

    op.create_table(
        "session_initialization_steps",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("initialization_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column(
            "step_type",
            postgresql.ENUM(
                name="session_initialization_step_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_initialization_step_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "depends_on_step_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "resource_descriptors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["initialization_id"],
            ["session_initializations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initialization_id",
            "sequence",
            name="uq_session_initialization_steps_initialization_sequence",
        ),
        sa.UniqueConstraint(
            "initialization_id",
            "step_key",
            name="uq_session_initialization_steps_initialization_step_key",
        ),
    )
    op.create_index(
        "ix_session_initialization_steps_initialization_id",
        "session_initialization_steps",
        ["initialization_id"],
    )
    op.create_index(
        "ix_session_initialization_steps_initialization_sequence",
        "session_initialization_steps",
        ["initialization_id", "sequence"],
    )
    op.create_index(
        "ix_session_initialization_steps_session_status",
        "session_initialization_steps",
        ["session_id", "status"],
    )

    op.create_table(
        "session_initialization_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("initialization_id", sa.String(length=32), nullable=False),
        sa.Column("step_id", sa.String(length=32), nullable=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                name="session_initialization_event_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "command_argv",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["initialization_id"],
            ["session_initializations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["session_initialization_steps.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initialization_id",
            "sequence",
            name="uq_session_initialization_events_initialization_sequence",
        ),
    )
    op.create_index(
        "ix_session_initialization_events_initialization_sequence",
        "session_initialization_events",
        ["initialization_id", "sequence"],
    )
    op.create_index(
        "ix_session_initialization_events_session_created",
        "session_initialization_events",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_session_initialization_events_step_id",
        "session_initialization_events",
        ["step_id"],
    )

    op.add_column(
        "session_git_worktrees",
        sa.Column("initialization_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_git_worktrees",
        sa.Column("step_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        INSERT INTO session_initializations (
            id,
            session_id,
            status,
            completed_at
        )
        SELECT md5(agent_sessions.id || '-downgrade-ready'),
               agent_sessions.id,
               'ready'::session_initialization_status,
               now()
        FROM agent_sessions
        ON CONFLICT (session_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO session_initialization_steps (
            id,
            initialization_id,
            session_id,
            sequence,
            step_key,
            step_type,
            status,
            blocking,
            retryable,
            depends_on_step_keys,
            resource_descriptors,
            completed_at
        )
        SELECT md5(session_initializations.id || '-noop-ready'),
               session_initializations.id,
               session_initializations.session_id,
               1,
               'noop_ready',
               'noop_ready'::session_initialization_step_type,
               'completed'::session_initialization_step_status,
               false,
               false,
               '[]'::jsonb,
               '[]'::jsonb,
               now()
        FROM session_initializations
        ON CONFLICT (initialization_id, step_key) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE session_git_worktrees
        SET initialization_id = session_initializations.id,
            step_id = session_initialization_steps.id
        FROM session_initializations
        JOIN session_initialization_steps
          ON session_initialization_steps.initialization_id = session_initializations.id
         AND session_initialization_steps.step_key = 'noop_ready'
        WHERE session_initializations.session_id = session_git_worktrees.session_id
        """
    )
    op.alter_column("session_git_worktrees", "initialization_id", nullable=False)
    op.alter_column("session_git_worktrees", "step_id", nullable=False)
    op.create_foreign_key(
        "session_git_worktrees_initialization_id_fkey",
        "session_git_worktrees",
        "session_initializations",
        ["initialization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "session_git_worktrees_step_id_fkey",
        "session_git_worktrees",
        "session_initialization_steps",
        ["step_id"],
        ["id"],
        ondelete="CASCADE",
    )
