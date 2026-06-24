"""add model config parameters

Revision ID: 5022328fd325
Revises: 31222c42bd84
Create Date: 2026-05-19 05:04:44.163831

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5022328fd325"
down_revision: str = "31222c42bd84"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

reasoning_effort_enum = postgresql.ENUM(
    "low",
    "medium",
    "high",
    name="model_config_reasoning_effort",
)


def upgrade() -> None:
    reasoning_effort_enum.create(op.get_bind())
    op.add_column(
        "model_configs",
        sa.Column("temperature", sa.Float(), nullable=True),
    )
    op.add_column(
        "model_configs",
        sa.Column("max_tokens", sa.Integer(), nullable=True),
    )
    op.add_column("model_configs", sa.Column("top_p", sa.Float(), nullable=True))
    op.add_column("model_configs", sa.Column("top_k", sa.Integer(), nullable=True))
    op.add_column(
        "model_configs",
        sa.Column("stop_sequences", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "model_configs",
        sa.Column("reasoning_effort", reasoning_effort_enum, nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE model_configs
            SET
              temperature = CASE
                WHEN jsonb_typeof(default_parameters -> 'temperature') = 'number'
                  THEN (default_parameters ->> 'temperature')::double precision
                ELSE temperature
              END,
              max_tokens = CASE
                WHEN jsonb_typeof(default_parameters -> 'max_tokens') = 'number'
                  THEN (default_parameters ->> 'max_tokens')::integer
                ELSE max_tokens
              END,
              top_p = CASE
                WHEN jsonb_typeof(default_parameters -> 'top_p') = 'number'
                  THEN (default_parameters ->> 'top_p')::double precision
                ELSE top_p
              END,
              top_k = CASE
                WHEN jsonb_typeof(default_parameters -> 'top_k') = 'number'
                  THEN (default_parameters ->> 'top_k')::integer
                ELSE top_k
              END,
              stop_sequences = CASE
                WHEN jsonb_typeof(default_parameters -> 'stop_sequences') = 'array'
                  THEN ARRAY(
                    SELECT jsonb_array_elements_text(
                      default_parameters -> 'stop_sequences'
                    )
                  )
                ELSE stop_sequences
              END,
              reasoning_effort = CASE
                WHEN (default_parameters ->> 'reasoning_effort') IN (
                  'low', 'medium', 'high'
                )
                  THEN (
                    default_parameters ->> 'reasoning_effort'
                  )::model_config_reasoning_effort
                ELSE reasoning_effort
              END
            WHERE default_parameters IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("model_configs", "reasoning_effort")
    op.drop_column("model_configs", "stop_sequences")
    op.drop_column("model_configs", "top_k")
    op.drop_column("model_configs", "top_p")
    op.drop_column("model_configs", "max_tokens")
    op.drop_column("model_configs", "temperature")
    reasoning_effort_enum.drop(op.get_bind())
