"""add agent runtime sessions

Revision ID: cb74afe5f751
Revises: 3208e4d784c8
Create Date: 2026-05-04 10:31:02.312532

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "cb74afe5f751"
down_revision: str | Sequence[str] | None = "9ddc078c204a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add AgentRuntime and AgentSession foundation tables."""
    agent_runtime_run_state = postgresql.ENUM(
        "idle",
        "running",
        name="agent_runtime_run_state",
    )
    agent_session_status = postgresql.ENUM(
        "active",
        "archived",
        name="agent_session_status",
    )
    agent_session_start_reason = postgresql.ENUM(
        "initial",
        "manual_new",
        "manual_reset",
        "system_recovery",
        "compact_rotate",
        name="agent_session_start_reason",
    )
    agent_session_end_reason = postgresql.ENUM(
        "manual_new",
        "manual_reset",
        "idle",
        "safety",
        "compact_rotate",
        "deleted",
        name="agent_session_end_reason",
    )

    bind = op.get_bind()
    agent_runtime_run_state.create(bind, checkfirst=True)
    agent_session_status.create(bind, checkfirst=True)
    agent_session_start_reason.create(bind, checkfirst=True)
    agent_session_end_reason.create(bind, checkfirst=True)

    op.create_table(
        "agent_runtimes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("current_session_id", sa.String(length=32), nullable=True),
        sa.Column(
            "run_state",
            postgresql.ENUM(name="agent_runtime_run_state", create_type=False),
            server_default="idle",
            nullable=False,
        ),
        sa.Column(
            "run_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "sdk_run_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("runtime_run_id", sa.String(length=80), nullable=True),
        sa.Column(
            "runtime_state",
            postgresql.ENUM(name="session_runtime_state", create_type=False),
            nullable=True,
        ),
        sa.Column("runtime_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_runtime_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_runtimes_agent_id"),
    )
    op.create_index(
        "ix_agent_runtimes_workspace_id", "agent_runtimes", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_runtimes_current_session_id",
        "agent_runtimes",
        ["current_session_id"],
    )
    op.create_index(
        "ix_agent_runtimes_run_state_running",
        "agent_runtimes",
        ["run_heartbeat_at"],
        postgresql_where=sa.text("run_state = 'running'"),
    )
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
    op.create_index(
        "ix_agent_runtimes_runtime_claimed_at",
        "agent_runtimes",
        ["runtime_claimed_at"],
        postgresql_where=sa.text("runtime_run_id IS NOT NULL"),
    )

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_session_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "start_reason",
            postgresql.ENUM(name="agent_session_start_reason", create_type=False),
            server_default="initial",
            nullable=False,
        ),
        sa.Column(
            "end_reason",
            postgresql.ENUM(name="agent_session_end_reason", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"], ["agent_runtimes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_sessions_workspace_id", "agent_sessions", ["workspace_id"]
    )
    op.create_index("ix_agent_sessions_agent_id", "agent_sessions", ["agent_id"])
    op.create_index(
        "ix_agent_sessions_agent_runtime_id",
        "agent_sessions",
        ["agent_runtime_id"],
    )
    op.create_index(
        "uq_agent_sessions_runtime_active",
        "agent_sessions",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        "agent_sessions",
        ["current_session_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "conversation_sessions",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversation_sessions_agent_runtime_id_agent_runtimes",
        "conversation_sessions",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_conversation_sessions_agent_session_id_agent_sessions",
        "conversation_sessions",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversation_sessions_agent_runtime_id",
        "conversation_sessions",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_conversation_sessions_agent_session_id",
        "conversation_sessions",
        ["agent_session_id"],
    )

    op.execute(
        """
        INSERT INTO agent_runtimes (id, workspace_id, agent_id)
        SELECT replace(gen_random_uuid()::text, '-', ''), workspace_id, id
        FROM agents
        ON CONFLICT (agent_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO agent_sessions (id, workspace_id, agent_runtime_id, agent_id)
        SELECT
            replace(gen_random_uuid()::text, '-', ''),
            ar.workspace_id,
            ar.id,
            ar.agent_id
        FROM agent_runtimes ar
        WHERE NOT EXISTS (
            SELECT 1
            FROM agent_sessions s
            WHERE s.agent_runtime_id = ar.id
              AND s.status = 'active'
        )
        """
    )
    op.execute(
        """
        UPDATE agent_runtimes ar
        SET current_session_id = s.id
        FROM agent_sessions s
        WHERE s.agent_runtime_id = ar.id
          AND s.status = 'active'
          AND ar.current_session_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE conversation_sessions cs
        SET agent_runtime_id = ar.id,
            agent_session_id = ar.current_session_id
        FROM agent_runtimes ar
        WHERE ar.agent_id = cs.agent_id
          AND cs.agent_runtime_id IS NULL
        """
    )


def downgrade() -> None:
    """Remove AgentRuntime and AgentSession foundation tables."""
    op.drop_index(
        "ix_conversation_sessions_agent_session_id", table_name="conversation_sessions"
    )
    op.drop_index(
        "ix_conversation_sessions_agent_runtime_id", table_name="conversation_sessions"
    )
    op.drop_constraint(
        "fk_conversation_sessions_agent_session_id_agent_sessions",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_conversation_sessions_agent_runtime_id_agent_runtimes",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_column("conversation_sessions", "agent_session_id")
    op.drop_column("conversation_sessions", "agent_runtime_id")

    op.drop_constraint(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_index("uq_agent_sessions_runtime_active", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_agent_runtime_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_agent_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_workspace_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    op.drop_index("ix_agent_runtimes_runtime_claimed_at", table_name="agent_runtimes")
    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline", table_name="agent_runtimes"
    )
    op.drop_index("ix_agent_runtimes_run_state_running", table_name="agent_runtimes")
    op.drop_index("ix_agent_runtimes_current_session_id", table_name="agent_runtimes")
    op.drop_index("ix_agent_runtimes_workspace_id", table_name="agent_runtimes")
    op.drop_table("agent_runtimes")

    op.execute("DROP TYPE IF EXISTS agent_session_end_reason")
    op.execute("DROP TYPE IF EXISTS agent_session_start_reason")
    op.execute("DROP TYPE IF EXISTS agent_session_status")
    op.execute("DROP TYPE IF EXISTS agent_runtime_run_state")
