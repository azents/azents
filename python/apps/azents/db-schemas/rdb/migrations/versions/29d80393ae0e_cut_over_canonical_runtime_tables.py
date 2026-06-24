"""cut over canonical runtime tables

Revision ID: 29d80393ae0e
Revises: 11f70ca2bfde
Create Date: 2026-05-28 15:02:27.370260

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "29d80393ae0e"
down_revision: str | Sequence[str] | None = "11f70ca2bfde"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Cut over canonical runtime shadow tables to final table names."""
    _drop_legacy_tables()
    _rename_shadow_tables()
    _normalize_agent_session_enums()
    _rename_constraints_and_indexes()
    _add_session_compat_column()
    _recreate_external_session_fks()
    _drop_sdk_run_state()
    _drop_legacy_enums()


def downgrade() -> None:
    """Revert final canonical tables to shadow table names."""
    _drop_external_session_fks()
    op.drop_column("agent_sessions", "lifecycle_started_at")
    _restore_agent_session_next_enums()
    _rename_final_indexes_back()
    op.rename_table("agent_runs", "agent_runs_next")
    op.rename_table("events", "events_next")
    op.rename_table("agent_sessions", "agent_sessions_next")
    _create_legacy_agent_sessions()
    _create_legacy_events()
    _clear_external_session_references()
    _recreate_external_session_fks()
    _restore_sdk_run_state()


def _drop_legacy_tables() -> None:
    """Drop existing legacy transcript/session tables."""
    _drop_external_session_fks()
    _clear_external_session_references()
    op.drop_table("events")
    op.drop_table("agent_sessions")


def _clear_external_session_references() -> None:
    """Remove orphan session references before recreating agent_sessions FKs."""
    op.execute("UPDATE agent_runtimes SET current_session_id = NULL")
    op.execute("DELETE FROM input_buffers")
    op.execute("DELETE FROM toolkit_states")
    op.execute("DELETE FROM exchange_files")


def _drop_external_session_fks() -> None:
    """Drop external FKs that reference agent_sessions."""
    _drop_constraint_if_exists(
        "agent_runtimes",
        "fk_agent_runtimes_current_session_id_agent_sessions",
    )
    _drop_constraint_if_exists(
        "input_buffers",
        "fk_input_buffers_session_id_agent_sessions",
    )
    _drop_constraint_if_exists("toolkit_states", "toolkit_states_session_id_fkey")
    _drop_constraint_if_exists(
        "exchange_files",
        "exchange_files_agent_session_id_fkey",
    )


def _drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    """Drop the constraint if it exists."""
    op.execute(
        f"ALTER TABLE IF EXISTS {table_name} "
        f"DROP CONSTRAINT IF EXISTS {constraint_name}"
    )


def _rename_shadow_tables() -> None:
    """Rename shadow table names to final table names."""
    op.rename_table("agent_sessions_next", "agent_sessions")
    op.rename_table("events_next", "events")
    op.rename_table("agent_runs_next", "agent_runs")


def _normalize_agent_session_enums() -> None:
    """Convert agent_sessions_next enum types to final enum types."""
    op.drop_index("uq_agent_sessions_next_runtime_active", table_name="agent_sessions")
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN status "
        "TYPE agent_session_status USING status::text::agent_session_status"
    )
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN start_reason "
        "TYPE agent_session_start_reason "
        "USING start_reason::text::agent_session_start_reason"
    )
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN end_reason "
        "TYPE agent_session_end_reason "
        "USING end_reason::text::agent_session_end_reason"
    )
    bind = op.get_bind()
    postgresql.ENUM(name="agent_sessions_next_end_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="agent_sessions_next_start_reason").drop(
        bind,
        checkfirst=True,
    )
    postgresql.ENUM(name="agent_sessions_next_status").drop(bind, checkfirst=True)


def _rename_constraints_and_indexes() -> None:
    """Rename shadow constraint/index names to final names."""
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT pk_agent_sessions_next TO pk_agent_sessions"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_next_agent_id_agents "
        "TO fk_agent_sessions_agent_id_agents"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_next_agent_runtime_id_agent_runtimes "
        "TO fk_agent_sessions_agent_runtime_id_agent_runtimes"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_next_workspace_id_workspaces "
        "TO fk_agent_sessions_workspace_id_workspaces"
    )
    op.execute("ALTER TABLE events RENAME CONSTRAINT pk_events_next TO pk_events")
    op.execute(
        "ALTER TABLE events "
        "RENAME CONSTRAINT fk_events_next_session_id_agent_sessions_next "
        "TO fk_events_session_id_agent_sessions"
    )
    op.execute(
        "ALTER TABLE agent_runs RENAME CONSTRAINT pk_agent_runs_next TO pk_agent_runs"
    )
    op.execute(
        "ALTER TABLE agent_runs "
        "RENAME CONSTRAINT fk_agent_runs_next_session_id_agent_sessions_next "
        "TO fk_agent_runs_session_id_agent_sessions"
    )
    _rename_index(
        "ix_agent_sessions_next_agent_id",
        "ix_agent_sessions_agent_id",
    )
    _rename_index(
        "ix_agent_sessions_next_agent_runtime_id",
        "ix_agent_sessions_agent_runtime_id",
    )
    _rename_index(
        "ix_agent_sessions_next_model_input_head_event_id",
        "ix_agent_sessions_model_input_head_event_id",
    )
    _rename_index(
        "ix_agent_sessions_next_workspace_id",
        "ix_agent_sessions_workspace_id",
    )
    op.create_index(
        "uq_agent_sessions_runtime_active",
        "agent_sessions",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    _rename_index("ix_events_next_session_created", "ix_events_session_created")
    _rename_index("ix_events_next_session_id", "ix_events_session_id")
    _rename_index("uq_events_next_session_external", "uq_events_session_external")
    _rename_index("ix_agent_runs_next_phase", "ix_agent_runs_phase")
    _rename_index("ix_agent_runs_next_session_id", "ix_agent_runs_session_id")
    _rename_index(
        "ix_agent_runs_next_session_status",
        "ix_agent_runs_session_status",
    )
    _rename_index("ix_agent_runs_next_status", "ix_agent_runs_status")


def _rename_index(old_name: str, new_name: str) -> None:
    """Rename the index."""
    op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")


def _add_session_compat_column() -> None:
    """Keep the nullable marker column used by existing runtime lifecycle code."""
    op.add_column(
        "agent_sessions",
        sa.Column("lifecycle_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def _recreate_external_session_fks() -> None:
    """Recreate external FKs for final agent_sessions."""
    op.create_foreign_key(
        "fk_agent_runtimes_current_session_id_agent_sessions",
        "agent_runtimes",
        "agent_sessions",
        ["current_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_input_buffers_session_id_agent_sessions",
        "input_buffers",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "toolkit_states_session_id_fkey",
        "toolkit_states",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "exchange_files_agent_session_id_fkey",
        "exchange_files",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def _drop_legacy_enums() -> None:
    """Drop legacy event enum types."""
    bind = op.get_bind()
    postgresql.ENUM(name="event_type").drop(bind, checkfirst=True)


def _drop_sdk_run_state() -> None:
    """Drop the SDK RunState compatibility column."""
    op.drop_column("agent_runtimes", "sdk_run_state")


def _restore_sdk_run_state() -> None:
    """Restore the SDK RunState column for the downgrade chain."""
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "sdk_run_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def _create_legacy_event_enum() -> None:
    """Restore the legacy event_type enum for downgrade."""
    bind = op.get_bind()
    postgresql.ENUM(
        "text_item",
        "reasoning_item",
        "tool_call_item",
        "tool_call_output_item",
        "image_generation_item",
        "unknown_item",
        "user_input",
        "system_reminder",
        "compaction",
        "turn_complete",
        "run_complete",
        "compaction_started",
        "subagent_start",
        "subagent_end",
        "error",
        name="event_type",
    ).create(bind, checkfirst=True)


def _create_legacy_agent_sessions() -> None:
    """Restore the legacy agent_sessions table for the downgrade chain."""
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_session_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "start_reason",
            postgresql.ENUM(name="agent_session_start_reason", create_type=False),
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
        sa.Column("lifecycle_started_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_agent_sessions_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            name="fk_agent_sessions_agent_runtime_id_agent_runtimes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_agent_sessions_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_sessions"),
    )
    op.create_index("ix_agent_sessions_agent_id", "agent_sessions", ["agent_id"])
    op.create_index(
        "ix_agent_sessions_agent_runtime_id",
        "agent_sessions",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_agent_sessions_workspace_id",
        "agent_sessions",
        ["workspace_id"],
    )
    op.create_index(
        "uq_agent_sessions_runtime_active",
        "agent_sessions",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _create_legacy_events() -> None:
    """Restore the legacy events table for the downgrade chain."""
    _create_legacy_event_enum()
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(name="event_type", create_type=False),
            nullable=False,
        ),
        sa.Column("item", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("source_model", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
    )
    op.create_index("ix_events_session_id", "events", ["session_id"])
    op.create_index(
        "ix_events_session_created",
        "events",
        ["session_id", "created_at"],
    )
    op.create_index(
        "uq_events_session_external",
        "events",
        ["session_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def _restore_agent_session_next_enums() -> None:
    """Restore next enum types and revert columns for downgrade."""
    bind = op.get_bind()
    op.drop_index("uq_agent_sessions_runtime_active", table_name="agent_sessions")
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
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN status "
        "TYPE agent_sessions_next_status "
        "USING status::text::agent_sessions_next_status"
    )
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN start_reason "
        "TYPE agent_sessions_next_start_reason "
        "USING start_reason::text::agent_sessions_next_start_reason"
    )
    op.execute(
        "ALTER TABLE agent_sessions ALTER COLUMN end_reason "
        "TYPE agent_sessions_next_end_reason "
        "USING end_reason::text::agent_sessions_next_end_reason"
    )


def _rename_final_indexes_back() -> None:
    """Revert final index/constraint names to shadow names."""
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT pk_agent_sessions TO pk_agent_sessions_next"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_agent_id_agents "
        "TO fk_agent_sessions_next_agent_id_agents"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_agent_runtime_id_agent_runtimes "
        "TO fk_agent_sessions_next_agent_runtime_id_agent_runtimes"
    )
    op.execute(
        "ALTER TABLE agent_sessions "
        "RENAME CONSTRAINT fk_agent_sessions_workspace_id_workspaces "
        "TO fk_agent_sessions_next_workspace_id_workspaces"
    )
    op.execute("ALTER TABLE events RENAME CONSTRAINT pk_events TO pk_events_next")
    op.execute(
        "ALTER TABLE events "
        "RENAME CONSTRAINT fk_events_session_id_agent_sessions "
        "TO fk_events_next_session_id_agent_sessions_next"
    )
    op.execute(
        "ALTER TABLE agent_runs RENAME CONSTRAINT pk_agent_runs TO pk_agent_runs_next"
    )
    op.execute(
        "ALTER TABLE agent_runs "
        "RENAME CONSTRAINT fk_agent_runs_session_id_agent_sessions "
        "TO fk_agent_runs_next_session_id_agent_sessions_next"
    )
    _rename_index("ix_agent_sessions_agent_id", "ix_agent_sessions_next_agent_id")
    _rename_index(
        "ix_agent_sessions_agent_runtime_id",
        "ix_agent_sessions_next_agent_runtime_id",
    )
    _rename_index(
        "ix_agent_sessions_model_input_head_event_id",
        "ix_agent_sessions_next_model_input_head_event_id",
    )
    _rename_index(
        "ix_agent_sessions_workspace_id",
        "ix_agent_sessions_next_workspace_id",
    )
    op.create_index(
        "uq_agent_sessions_next_runtime_active",
        "agent_sessions",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    _rename_index("ix_events_session_created", "ix_events_next_session_created")
    _rename_index("ix_events_session_id", "ix_events_next_session_id")
    _rename_index("uq_events_session_external", "uq_events_next_session_external")
    _rename_index("ix_agent_runs_phase", "ix_agent_runs_next_phase")
    _rename_index("ix_agent_runs_session_id", "ix_agent_runs_next_session_id")
    _rename_index(
        "ix_agent_runs_session_status",
        "ix_agent_runs_next_session_status",
    )
    _rename_index("ix_agent_runs_status", "ix_agent_runs_next_status")
