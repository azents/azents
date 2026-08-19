"""add session applied inference profile

Revision ID: 936373d16d53
Revises: c05f9971773f
Create Date: 2026-08-19 07:44:46.431514

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "936373d16d53"
down_revision: str | Sequence[str] | None = "c05f9971773f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Session-owned applied model intent."""
    op.execute(
        "ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'model_profile'"
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM agent_sessions
                    WHERE NOT (
                        current_model_target_label IS NULL
                        AND current_model_selection IS NULL
                        AND current_model_settings IS NULL
                        AND current_reasoning_effort IS NULL
                        AND current_effective_context_window_tokens IS NULL
                        AND current_effective_auto_compaction_threshold_tokens IS NULL
                        AND current_inference_resolved_at IS NULL
                    )
                    AND NOT (
                        current_model_target_label IS NOT NULL
                        AND current_model_selection IS NOT NULL
                        AND current_model_settings IS NOT NULL
                        AND current_effective_context_window_tokens IS NOT NULL
                        AND current_effective_auto_compaction_threshold_tokens
                            IS NOT NULL
                        AND current_inference_resolved_at IS NOT NULL
                    )
                ) THEN
                    RAISE EXCEPTION
                        'agent_sessions contains partial current inference state';
                END IF;
            END
            $$;
            """
        )
    )
    op.add_column(
        "agent_sessions",
        sa.Column("applied_model_target_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "applied_reasoning_effort",
            postgresql.ENUM(
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_sessions
            SET applied_model_target_label = current_model_target_label,
                applied_reasoning_effort = current_reasoning_effort
            WHERE current_model_target_label IS NOT NULL
            """
        )
    )
    op.create_check_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        "applied_model_target_label IS NOT NULL OR applied_reasoning_effort IS NULL",
    )


def downgrade() -> None:
    """Remove Session-owned applied model intent."""
    op.drop_constraint(
        "ck_agent_sessions_applied_inference_profile",
        "agent_sessions",
        type_="check",
    )
    op.drop_column("agent_sessions", "applied_reasoning_effort")
    op.drop_column("agent_sessions", "applied_model_target_label")
