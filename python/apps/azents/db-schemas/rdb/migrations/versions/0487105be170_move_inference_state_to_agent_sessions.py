"""Move resolved inference state from AgentRun to AgentSession."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0487105be170"
down_revision: str | Sequence[str] | None = "d866866e726f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REASONING_EFFORT = postgresql.ENUM(
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    name="model_reasoning_effort",
    create_type=False,
)
_INFERENCE_PROFILE_SOURCE = postgresql.ENUM(
    "explicit_input",
    "session_last_used",
    "agent_default",
    "parent_run",
    "spawn_override",
    "retry_original",
    name="inference_profile_source",
    create_type=False,
)
_INFERENCE_PROFILE_FAILURE_CODE = postgresql.ENUM(
    "model_target_not_found",
    "model_target_resolution_failed",
    "reasoning_effort_unsupported",
    name="inference_profile_failure_code",
    create_type=False,
)


def upgrade() -> None:
    """Move the complete latest resolved profile to each Session."""
    op.add_column(
        "agent_sessions",
        sa.Column("current_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("current_reasoning_effort", _REASONING_EFFORT, nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_effective_context_window_tokens", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_effective_auto_compaction_threshold_tokens",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_inference_resolved_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (run.session_id)
                    run.session_id,
                    run.requested_model_target_label,
                    run.resolved_model_selection,
                    run.resolved_reasoning_effort,
                    run.effective_context_window_tokens,
                    run.effective_auto_compaction_threshold_tokens,
                    run.resolved_at
                FROM agent_runs AS run
                WHERE run.requested_model_target_label IS NOT NULL
                  AND run.resolved_model_selection IS NOT NULL
                  AND run.effective_context_window_tokens IS NOT NULL
                  AND run.effective_auto_compaction_threshold_tokens IS NOT NULL
                  AND run.resolved_at IS NOT NULL
                ORDER BY run.session_id, run.run_index DESC
            )
            UPDATE agent_sessions AS session
            SET current_model_target_label = latest.requested_model_target_label,
                current_model_selection = latest.resolved_model_selection,
                current_reasoning_effort = latest.resolved_reasoning_effort,
                current_effective_context_window_tokens =
                    latest.effective_context_window_tokens,
                current_effective_auto_compaction_threshold_tokens =
                    latest.effective_auto_compaction_threshold_tokens,
                current_inference_resolved_at = latest.resolved_at
            FROM latest
            WHERE latest.session_id = session.id
            """
        )
    )
    op.drop_constraint(
        "ck_agent_sessions_last_profile", "agent_sessions", type_="check"
    )
    op.drop_column("agent_sessions", "last_reasoning_effort")
    op.drop_column("agent_sessions", "last_model_target_label")
    op.create_check_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        "(current_model_target_label IS NULL "
        "AND current_model_selection IS NULL "
        "AND current_reasoning_effort IS NULL "
        "AND current_effective_context_window_tokens IS NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NULL "
        "AND current_inference_resolved_at IS NULL) OR "
        "(current_model_target_label IS NOT NULL "
        "AND current_model_selection IS NOT NULL "
        "AND current_effective_context_window_tokens IS NOT NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NOT NULL "
        "AND current_inference_resolved_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_agent_sessions_current_context_window",
        "agent_sessions",
        "current_effective_context_window_tokens IS NULL "
        "OR current_effective_context_window_tokens > 0",
    )
    op.create_check_constraint(
        "ck_agent_sessions_current_compaction_threshold",
        "agent_sessions",
        "current_effective_auto_compaction_threshold_tokens IS NULL "
        "OR current_effective_auto_compaction_threshold_tokens > 0",
    )
    op.drop_constraint("ck_agent_runs_requested_profile", "agent_runs", type_="check")
    op.drop_constraint("ck_agent_runs_resolved_profile", "agent_runs", type_="check")
    op.drop_constraint(
        "ck_agent_runs_effective_context_window", "agent_runs", type_="check"
    )
    op.drop_constraint(
        "ck_agent_runs_effective_compaction_threshold", "agent_runs", type_="check"
    )
    for column_name in (
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
        op.drop_column("agent_runs", column_name)


def downgrade() -> None:
    """Restore the former run-bound inference columns."""
    op.add_column(
        "agent_runs",
        sa.Column("requested_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("requested_reasoning_effort", _REASONING_EFFORT, nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("inference_profile_source", _INFERENCE_PROFILE_SOURCE, nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "resolved_model_selection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("resolved_reasoning_effort", _REASONING_EFFORT, nullable=True),
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
            _INFERENCE_PROFILE_FAILURE_CODE,
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("inference_profile_failure_message", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text("""
        UPDATE agent_runs AS run
        SET requested_model_target_label = session.current_model_target_label,
            requested_reasoning_effort = session.current_reasoning_effort,
            inference_profile_source = 'session_last_used',
            resolved_model_selection = session.current_model_selection,
            resolved_reasoning_effort = session.current_reasoning_effort,
            resolved_at = session.current_inference_resolved_at,
            effective_context_window_tokens =
                session.current_effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens =
                session.current_effective_auto_compaction_threshold_tokens
        FROM agent_sessions AS session
        WHERE session.id = run.session_id
          AND session.current_model_target_label IS NOT NULL
    """)
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
    op.drop_constraint(
        "ck_agent_sessions_current_compaction_threshold",
        "agent_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_sessions_current_context_window", "agent_sessions", type_="check"
    )
    op.drop_constraint(
        "ck_agent_sessions_current_inference_state", "agent_sessions", type_="check"
    )
    op.add_column(
        "agent_sessions",
        sa.Column("last_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("last_reasoning_effort", _REASONING_EFFORT, nullable=True),
    )
    op.execute(
        sa.text("""
        UPDATE agent_sessions
        SET last_model_target_label = current_model_target_label,
            last_reasoning_effort = current_reasoning_effort
        WHERE current_model_target_label IS NOT NULL
    """)
    )
    op.create_check_constraint(
        "ck_agent_sessions_last_profile",
        "agent_sessions",
        "last_reasoning_effort IS NULL OR last_model_target_label IS NOT NULL",
    )
    for column_name in (
        "current_inference_resolved_at",
        "current_effective_auto_compaction_threshold_tokens",
        "current_effective_context_window_tokens",
        "current_reasoning_effort",
        "current_model_selection",
        "current_model_target_label",
    ):
        op.drop_column("agent_sessions", column_name)
