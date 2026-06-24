"""add canonical runtime shadow tables

Revision ID: 11f70ca2bfde
Revises: 4b6e803cae38
Create Date: 2026-05-27 23:18:31.933300

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "11f70ca2bfde"
down_revision: str | Sequence[str] | None = "4b6e803cae38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add canonical runtime shadow tables."""
    _create_enums()
    _create_agent_sessions_next()
    _create_events_next()
    _create_agent_runs_next()


def downgrade() -> None:
    """Drop canonical runtime shadow tables."""
    op.drop_index("ix_agent_runs_next_status", table_name="agent_runs_next")
    op.drop_index("ix_agent_runs_next_session_status", table_name="agent_runs_next")
    op.drop_index("ix_agent_runs_next_session_id", table_name="agent_runs_next")
    op.drop_index("ix_agent_runs_next_phase", table_name="agent_runs_next")
    op.drop_table("agent_runs_next")

    op.drop_index("uq_events_next_session_external", table_name="events_next")
    op.drop_index("ix_events_next_session_id", table_name="events_next")
    op.drop_index("ix_events_next_session_created", table_name="events_next")
    op.drop_table("events_next")

    op.drop_index(
        "uq_agent_sessions_next_runtime_active",
        table_name="agent_sessions_next",
    )
    op.drop_index(
        "ix_agent_sessions_next_workspace_id",
        table_name="agent_sessions_next",
    )
    op.drop_index(
        "ix_agent_sessions_next_model_input_head_event_id",
        table_name="agent_sessions_next",
    )
    op.drop_index(
        "ix_agent_sessions_next_agent_runtime_id",
        table_name="agent_sessions_next",
    )
    op.drop_index("ix_agent_sessions_next_agent_id", table_name="agent_sessions_next")
    op.drop_table("agent_sessions_next")

    bind = op.get_bind()
    postgresql.ENUM(name="agent_sessions_next_end_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="agent_sessions_next_start_reason").drop(
        bind,
        checkfirst=True,
    )
    postgresql.ENUM(name="agent_sessions_next_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="agent_run_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="agent_run_phase").drop(bind, checkfirst=True)
    postgresql.ENUM(name="canonical_event_kind").drop(bind, checkfirst=True)


def _create_enums() -> None:
    """Create canonical runtime enum types."""
    bind = op.get_bind()
    postgresql.ENUM(
        "user_message",
        "assistant_message",
        "reasoning",
        "client_tool_call",
        "client_tool_result",
        "provider_tool_call",
        "provider_tool_result",
        "turn_marker",
        "run_marker",
        "compaction_marker",
        "compaction_summary",
        "subagent_start",
        "subagent_end",
        "system_reminder",
        "system_error",
        "unknown_adapter_output",
        name="canonical_event_kind",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "idle",
        "preparing_input",
        "waiting_for_model",
        "streaming_model",
        "normalizing_output",
        "executing_tools",
        "appending_events",
        "compacting",
        "stopping",
        name="agent_run_phase",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "running",
        "completed",
        "stopped",
        "failed",
        "interrupted",
        "cancelled",
        name="agent_run_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "active",
        "archived",
        name="agent_sessions_next_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "initial",
        "manual_new",
        "manual_reset",
        "system_recovery",
        "compact_rotate",
        name="agent_sessions_next_start_reason",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "manual_new",
        "manual_reset",
        "idle",
        "safety",
        "compact_rotate",
        "deleted",
        name="agent_sessions_next_end_reason",
    ).create(bind, checkfirst=True)


def _create_agent_sessions_next() -> None:
    """Create the agent_sessions_next table."""
    op.create_table(
        "agent_sessions_next",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_sessions_next_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "start_reason",
            postgresql.ENUM(
                name="agent_sessions_next_start_reason",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "end_reason",
            postgresql.ENUM(name="agent_sessions_next_end_reason", create_type=False),
            nullable=True,
        ),
        sa.Column("model_input_head_event_id", sa.String(length=32), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_sessions_next_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            name="fk_agent_sessions_next_agent_runtime_id_agent_runtimes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_agent_sessions_next_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_sessions_next"),
    )
    op.create_index(
        "ix_agent_sessions_next_agent_id",
        "agent_sessions_next",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_sessions_next_agent_runtime_id",
        "agent_sessions_next",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_agent_sessions_next_model_input_head_event_id",
        "agent_sessions_next",
        ["model_input_head_event_id"],
    )
    op.create_index(
        "ix_agent_sessions_next_workspace_id",
        "agent_sessions_next",
        ["workspace_id"],
    )
    op.create_index(
        "uq_agent_sessions_next_runtime_active",
        "agent_sessions_next",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _create_events_next() -> None:
    """Create the events_next table."""
    op.create_table(
        "events_next",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="canonical_event_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("adapter", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("native_format", sa.Text(), nullable=True),
        sa.Column(
            "schema_version",
            sa.String(length=20),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions_next.id"],
            name="fk_events_next_session_id_agent_sessions_next",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events_next"),
    )
    op.create_index(
        "ix_events_next_session_created",
        "events_next",
        ["session_id", "id"],
    )
    op.create_index("ix_events_next_session_id", "events_next", ["session_id"])
    op.create_index(
        "uq_events_next_session_external",
        "events_next",
        ["session_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def _create_agent_runs_next() -> None:
    """Create the agent_runs_next table."""
    op.create_table(
        "agent_runs_next",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "phase",
            postgresql.ENUM(name="agent_run_phase", create_type=False),
            server_default="idle",
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_run_status", create_type=False),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "active_tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_completed_event_id", sa.String(length=32), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions_next.id"],
            name="fk_agent_runs_next_session_id_agent_sessions_next",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs_next"),
    )
    op.create_index("ix_agent_runs_next_phase", "agent_runs_next", ["phase"])
    op.create_index(
        "ix_agent_runs_next_session_id",
        "agent_runs_next",
        ["session_id"],
    )
    op.create_index(
        "ix_agent_runs_next_session_status",
        "agent_runs_next",
        ["session_id", "status"],
    )
    op.create_index("ix_agent_runs_next_status", "agent_runs_next", ["status"])
