"""normalize agent model parameters arrays

Revision ID: 283acd188c50
Revises: 1d69c2e86ea4
Create Date: 2026-06-16 11:52:57.170029

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "283acd188c50"
down_revision: str | Sequence[str] | None = "1d69c2e86ea4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize Agent model_parameters that were incorrectly stored as arrays."""
    op.execute(
        sa.text("""
        UPDATE agents
        SET model_parameters = CASE
            WHEN jsonb_array_length(model_parameters) = 2
             AND jsonb_typeof(model_parameters -> 0) = 'object'
             AND jsonb_typeof(model_parameters -> 1) = 'null'
            THEN NULLIF(model_parameters -> 0, '{}'::jsonb)
            WHEN jsonb_array_length(model_parameters) = 2
             AND jsonb_typeof(model_parameters -> 0) = 'null'
             AND jsonb_typeof(model_parameters -> 1) = 'object'
            THEN NULLIF(model_parameters -> 1, '{}'::jsonb)
            ELSE model_parameters
        END
        WHERE jsonb_typeof(model_parameters) = 'array'
          AND jsonb_array_length(model_parameters) = 2
          AND (
            (
                jsonb_typeof(model_parameters -> 0) = 'object'
                AND jsonb_typeof(model_parameters -> 1) = 'null'
            )
            OR (
                jsonb_typeof(model_parameters -> 0) = 'null'
                AND jsonb_typeof(model_parameters -> 1) = 'object'
            )
          )
        """)
    )


def downgrade() -> None:
    """Do not revert data normalization."""
