"""move session execution state to agent sessions

Revision ID: 6e2d8a4e22fd
Revises: 5eb526754a74
Create Date: 2026-06-25 00:00:50.063743

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6e2d8a4e22fd"
down_revision: str | Sequence[str] | None = "5eb526754a74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move per-session execution state from AgentRuntime to AgentSession."""
    op.execute("ALTER TYPE agent_runtime_run_state RENAME TO agent_session_run_state")
    op.add_column(
        "agent_sessions",
        sa.Column(
            "run_state",
            postgresql.ENUM(name="agent_session_run_state", create_type=False),
            server_default="idle",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "run_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("pending_command_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("pending_command_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "pending_command_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("pending_command_user_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "pending_command_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("stop_requested_by", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("stop_request_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_sessions_pending_command_user_id_users",
        "agent_sessions",
        "users",
        ["pending_command_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_sessions_stop_requested_by_users",
        "agent_sessions",
        "users",
        ["stop_requested_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE agent_sessions s
        SET run_state = ar.run_state,
            run_heartbeat_at = ar.run_heartbeat_at,
            pending_command_id = ar.pending_command_id,
            pending_command_name = ar.pending_command_name,
            pending_command_payload = ar.pending_command_payload,
            pending_command_user_id = ar.pending_command_user_id,
            pending_command_created_at = ar.pending_command_created_at,
            stop_requested_at = ar.stop_requested_at,
            stop_requested_by = ar.stop_requested_by,
            stop_request_id = ar.stop_request_id
        FROM agent_runtimes ar
        WHERE ar.current_session_id = s.id
        """
    )

    op.create_index(
        "ix_agent_sessions_pending_command",
        "agent_sessions",
        ["pending_command_created_at"],
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_sessions_stop_requested_at",
        "agent_sessions",
        ["stop_requested_at"],
        postgresql_where=sa.text("stop_requested_at IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_sessions_run_state_running",
        "agent_sessions",
        ["run_heartbeat_at"],
        postgresql_where=sa.text("run_state = 'running'"),
    )

    op.drop_index("ix_agent_runtimes_pending_command", table_name="agent_runtimes")
    op.drop_index("ix_agent_runtimes_stop_requested_at", table_name="agent_runtimes")
    op.drop_index("ix_agent_runtimes_run_state_running", table_name="agent_runtimes")
    op.drop_column("agent_runtimes", "stop_request_id")
    op.drop_column("agent_runtimes", "stop_requested_by")
    op.drop_column("agent_runtimes", "stop_requested_at")
    op.drop_column("agent_runtimes", "pending_command_created_at")
    op.drop_column("agent_runtimes", "pending_command_user_id")
    op.drop_column("agent_runtimes", "pending_command_payload")
    op.drop_column("agent_runtimes", "pending_command_name")
    op.drop_column("agent_runtimes", "pending_command_id")
    op.drop_column("agent_runtimes", "run_heartbeat_at")
    op.drop_column("agent_runtimes", "run_state")


def downgrade() -> None:
    """Move per-session execution state back to AgentRuntime."""
    op.execute("ALTER TYPE agent_session_run_state RENAME TO agent_runtime_run_state")
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "run_state",
            postgresql.ENUM(name="agent_runtime_run_state", create_type=False),
            server_default="idle",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "run_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "pending_command_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_user_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "pending_command_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_requested_by", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_request_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_pending_command_user_id_users",
        "agent_runtimes",
        "users",
        ["pending_command_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_stop_requested_by_users",
        "agent_runtimes",
        "users",
        ["stop_requested_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE agent_runtimes ar
        SET run_state = s.run_state,
            run_heartbeat_at = s.run_heartbeat_at,
            pending_command_id = s.pending_command_id,
            pending_command_name = s.pending_command_name,
            pending_command_payload = s.pending_command_payload,
            pending_command_user_id = s.pending_command_user_id,
            pending_command_created_at = s.pending_command_created_at,
            stop_requested_at = s.stop_requested_at,
            stop_requested_by = s.stop_requested_by,
            stop_request_id = s.stop_request_id
        FROM agent_sessions s
        WHERE ar.current_session_id = s.id
        """
    )

    op.create_index(
        "ix_agent_runtimes_pending_command",
        "agent_runtimes",
        ["pending_command_created_at"],
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_runtimes_stop_requested_at",
        "agent_runtimes",
        ["stop_requested_at"],
        postgresql_where=sa.text("stop_requested_at IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_runtimes_run_state_running",
        "agent_runtimes",
        ["run_heartbeat_at"],
        postgresql_where=sa.text("run_state = 'running'"),
    )

    op.drop_index("ix_agent_sessions_run_state_running", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_stop_requested_at", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_pending_command", table_name="agent_sessions")
    op.drop_constraint(
        "fk_agent_sessions_stop_requested_by_users",
        "agent_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_sessions_pending_command_user_id_users",
        "agent_sessions",
        type_="foreignkey",
    )
    op.drop_column("agent_sessions", "stop_request_id")
    op.drop_column("agent_sessions", "stop_requested_by")
    op.drop_column("agent_sessions", "stop_requested_at")
    op.drop_column("agent_sessions", "pending_command_created_at")
    op.drop_column("agent_sessions", "pending_command_user_id")
    op.drop_column("agent_sessions", "pending_command_payload")
    op.drop_column("agent_sessions", "pending_command_name")
    op.drop_column("agent_sessions", "pending_command_id")
    op.drop_column("agent_sessions", "run_heartbeat_at")
    op.drop_column("agent_sessions", "run_state")
