"""add inference profile provenance

Revision ID: 892929403f2a
Revises: b754406b3aee
Create Date: 2026-07-10 06:21:40.301120

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "892929403f2a"
down_revision: str | Sequence[str] | None = "b754406b3aee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

model_reasoning_effort = postgresql.ENUM(
    "low", "medium", "high", name="model_reasoning_effort"
)
inference_profile_source = postgresql.ENUM(
    "explicit_input",
    "session_last_used",
    "agent_default",
    "parent_run",
    "retry_original",
    name="inference_profile_source",
)
inference_profile_failure_code = postgresql.ENUM(
    "model_target_not_found",
    "model_target_resolution_failed",
    "reasoning_effort_unsupported",
    name="inference_profile_failure_code",
)


def upgrade() -> None:
    """Add requested and resolved inference profile provenance."""
    bind = op.get_bind()
    model_reasoning_effort.create(bind, checkfirst=False)
    inference_profile_source.create(bind, checkfirst=False)
    inference_profile_failure_code.create(bind, checkfirst=False)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE agent_run_status ADD VALUE IF NOT EXISTS 'pending'")

    op.add_column(
        "input_buffers",
        sa.Column("requested_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "input_buffers",
        sa.Column(
            "requested_reasoning_effort",
            postgresql.ENUM(
                "low",
                "medium",
                "high",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_input_buffers_requested_profile",
        "input_buffers",
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
    )

    op.add_column(
        "agent_sessions",
        sa.Column("last_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "last_reasoning_effort",
            postgresql.ENUM(
                "low",
                "medium",
                "high",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_agent_sessions_last_profile",
        "agent_sessions",
        "last_reasoning_effort IS NULL OR last_model_target_label IS NOT NULL",
    )

    op.add_column(
        "agent_runs",
        sa.Column("requested_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "requested_reasoning_effort",
            postgresql.ENUM(
                "low",
                "medium",
                "high",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "inference_profile_source",
            postgresql.ENUM(
                "explicit_input",
                "session_last_used",
                "agent_default",
                "parent_run",
                "retry_original",
                name="inference_profile_source",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("resolved_model_selection", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "resolved_reasoning_effort",
            postgresql.ENUM(
                "low",
                "medium",
                "high",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("effective_context_window_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "effective_auto_compaction_threshold_tokens", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "inference_profile_failure_code",
            postgresql.ENUM(
                "model_target_not_found",
                "model_target_resolution_failed",
                "reasoning_effort_unsupported",
                name="inference_profile_failure_code",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("inference_profile_failure_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("parent_agent_run_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.execute("UPDATE agent_runs SET created_at = started_at")
    op.alter_column("agent_runs", "created_at", nullable=False)
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )
    op.create_foreign_key(
        "fk_agent_runs_parent_agent_run_id_agent_runs",
        "agent_runs",
        "agent_runs",
        ["parent_agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_agent_runs_resolved_profile",
        "agent_runs",
        "resolved_reasoning_effort IS NULL OR resolved_model_selection IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_agent_runs_effective_context_window",
        "agent_runs",
        "effective_context_window_tokens IS NULL "
        "OR effective_context_window_tokens > 0",
    )
    op.create_check_constraint(
        "ck_agent_runs_effective_compaction_threshold",
        "agent_runs",
        "effective_auto_compaction_threshold_tokens IS NULL "
        "OR effective_auto_compaction_threshold_tokens > 0",
    )
    op.create_index(
        "ix_agent_runs_parent_agent_run_id",
        "agent_runs",
        ["parent_agent_run_id"],
        unique=False,
    )
    op.create_index(
        "uq_agent_runs_session_pending",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "agent_run_input_events",
        sa.Column("agent_run_id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("input_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "input_order >= 0", name="ck_agent_run_input_events_input_order"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_run_id", "event_id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "input_order",
            name="uq_agent_run_input_events_run_input_order",
        ),
    )
    op.create_index(
        "ix_agent_run_input_events_event_run",
        "agent_run_input_events",
        ["event_id", "agent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_run_input_events_run_input_order",
        "agent_run_input_events",
        ["agent_run_id", "input_order"],
        unique=False,
    )


def downgrade() -> None:
    """Remove inference profile provenance."""
    op.drop_index(
        "ix_agent_run_input_events_run_input_order", table_name="agent_run_input_events"
    )
    op.drop_index(
        "ix_agent_run_input_events_event_run", table_name="agent_run_input_events"
    )
    op.drop_table("agent_run_input_events")
    op.drop_index("uq_agent_runs_session_pending", table_name="agent_runs")
    op.drop_index("ix_agent_runs_parent_agent_run_id", table_name="agent_runs")
    op.drop_constraint(
        "ck_agent_runs_effective_compaction_threshold", "agent_runs", type_="check"
    )
    op.drop_constraint(
        "ck_agent_runs_effective_context_window", "agent_runs", type_="check"
    )
    op.drop_constraint("ck_agent_runs_resolved_profile", "agent_runs", type_="check")
    op.drop_constraint("ck_agent_runs_requested_profile", "agent_runs", type_="check")
    op.drop_constraint(
        "fk_agent_runs_parent_agent_run_id_agent_runs", "agent_runs", type_="foreignkey"
    )
    op.execute("UPDATE agent_runs SET started_at = created_at WHERE started_at IS NULL")
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    for column in (
        "created_at",
        "parent_agent_run_id",
        "inference_profile_failure_message",
        "inference_profile_failure_code",
        "effective_auto_compaction_threshold_tokens",
        "effective_context_window_tokens",
        "resolved_at",
        "resolved_reasoning_effort",
        "resolved_model_selection",
        "inference_profile_source",
        "requested_reasoning_effort",
        "requested_model_target_label",
    ):
        op.drop_column("agent_runs", column)
    op.drop_constraint(
        "ck_agent_sessions_last_profile", "agent_sessions", type_="check"
    )
    op.drop_column("agent_sessions", "last_reasoning_effort")
    op.drop_column("agent_sessions", "last_model_target_label")
    op.drop_constraint(
        "ck_input_buffers_requested_profile", "input_buffers", type_="check"
    )
    op.drop_column("input_buffers", "requested_reasoning_effort")
    op.drop_column("input_buffers", "requested_model_target_label")

    bind = op.get_bind()
    inference_profile_failure_code.drop(bind, checkfirst=False)
    inference_profile_source.drop(bind, checkfirst=False)
    model_reasoning_effort.drop(bind, checkfirst=False)

    op.execute("UPDATE agent_runs SET status = 'failed' WHERE status::text = 'pending'")
    op.execute("ALTER TABLE agent_runs ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE agent_runs ALTER COLUMN status TYPE text USING status::text"
    )
    op.execute("DROP TYPE agent_run_status")
    op.execute(
        "CREATE TYPE agent_run_status AS ENUM "
        "('running', 'completed', 'stopped', 'failed', 'interrupted', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE agent_runs ALTER COLUMN status TYPE agent_run_status "
        "USING status::agent_run_status"
    )
    op.execute(
        "ALTER TABLE agent_runs ALTER COLUMN status "
        "SET DEFAULT 'running'::agent_run_status"
    )
