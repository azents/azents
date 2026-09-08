"""Add model execution option support and lifecycle state.

Revision ID: 6b53a0a15d11
Revises: 4ab7015e39b5
Create Date: 2026-09-08 02:56:07.926418

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6b53a0a15d11"
down_revision: str | Sequence[str] | None = "afd1289d7982"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY_OPTIONS_DEFAULT = sa.text("'[]'::jsonb")


def upgrade() -> None:
    """Add supported, applied, requested, and prepared execution option lists."""
    op.add_column(
        "llm_catalog_entries",
        sa.Column(
            "supported_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_EMPTY_OPTIONS_DEFAULT,
            nullable=False,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "current_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_EMPTY_OPTIONS_DEFAULT,
            nullable=False,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "applied_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_EMPTY_OPTIONS_DEFAULT,
            nullable=False,
        ),
    )
    op.add_column(
        "mailbox_items",
        sa.Column(
            "requested_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_EMPTY_OPTIONS_DEFAULT,
            nullable=False,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "requested_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_EMPTY_OPTIONS_DEFAULT,
            nullable=False,
        ),
    )

    op.drop_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        "(current_model_target_label IS NULL "
        "AND current_model_selection IS NULL "
        "AND current_model_settings IS NULL "
        "AND current_reasoning_effort IS NULL "
        "AND current_enabled_execution_options = '[]'::jsonb "
        "AND current_effective_context_window_tokens IS NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NULL "
        "AND current_inference_resolved_at IS NULL) OR "
        "(current_model_target_label IS NOT NULL "
        "AND current_model_selection IS NOT NULL "
        "AND current_model_settings IS NOT NULL "
        "AND current_effective_context_window_tokens IS NOT NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NOT NULL "
        "AND current_inference_resolved_at IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        "applied_model_target_label IS NOT NULL OR "
        "(applied_reasoning_effort IS NULL "
        "AND applied_enabled_execution_options = '[]'::jsonb)",
    )
    op.drop_constraint(
        "ck_mailbox_items_requested_profile",
        "mailbox_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_mailbox_items_requested_profile",
        "mailbox_items",
        "requested_model_target_label IS NOT NULL OR "
        "(requested_reasoning_effort IS NULL "
        "AND requested_enabled_execution_options = '[]'::jsonb)",
    )
    op.drop_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        "requested_model_target_label IS NOT NULL OR "
        "(requested_reasoning_effort IS NULL "
        "AND requested_enabled_execution_options = '[]'::jsonb)",
    )


def downgrade() -> None:
    """Remove model execution option support and lifecycle state."""
    op.drop_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_runs_requested_profile",
        "agent_runs",
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
    )
    op.drop_constraint(
        "ck_mailbox_items_requested_profile",
        "mailbox_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_mailbox_items_requested_profile",
        "mailbox_items",
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
    )
    op.drop_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        "applied_model_target_label IS NOT NULL OR applied_reasoning_effort IS NULL",
    )
    op.drop_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_sessions_current_inference_state",
        "agent_sessions",
        "(current_model_target_label IS NULL "
        "AND current_model_selection IS NULL "
        "AND current_model_settings IS NULL "
        "AND current_reasoning_effort IS NULL "
        "AND current_effective_context_window_tokens IS NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NULL "
        "AND current_inference_resolved_at IS NULL) OR "
        "(current_model_target_label IS NOT NULL "
        "AND current_model_selection IS NOT NULL "
        "AND current_model_settings IS NOT NULL "
        "AND current_effective_context_window_tokens IS NOT NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NOT NULL "
        "AND current_inference_resolved_at IS NOT NULL)",
    )

    op.drop_column("agent_runs", "requested_enabled_execution_options")
    op.drop_column("mailbox_items", "requested_enabled_execution_options")
    op.drop_column("agent_sessions", "applied_enabled_execution_options")
    op.drop_column("agent_sessions", "current_enabled_execution_options")
    op.drop_column("llm_catalog_entries", "supported_execution_options")
