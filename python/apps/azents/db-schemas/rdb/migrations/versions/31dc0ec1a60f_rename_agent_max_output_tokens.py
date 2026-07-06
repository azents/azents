"""rename agent max output tokens

Revision ID: 31dc0ec1a60f
Revises: 19deaed8bcd4
Create Date: 2026-07-06 04:24:24.990563

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31dc0ec1a60f"
down_revision: str | Sequence[str] | None = "19deaed8bcd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RENAME_TO_MAX_OUTPUT_TOKENS = """
UPDATE agents
SET model_parameters = CASE
    WHEN model_parameters ? 'max_output_tokens'
    THEN model_parameters - 'max_tokens'
    ELSE jsonb_set(
        model_parameters - 'max_tokens',
        '{max_output_tokens}',
        model_parameters -> 'max_tokens',
        true
    )
END
WHERE jsonb_typeof(model_parameters) = 'object'
  AND model_parameters ? 'max_tokens'
"""

_RENAME_TO_MAX_TOKENS = """
UPDATE agents
SET model_parameters = CASE
    WHEN model_parameters ? 'max_tokens'
    THEN model_parameters - 'max_output_tokens'
    ELSE jsonb_set(
        model_parameters - 'max_output_tokens',
        '{max_tokens}',
        model_parameters -> 'max_output_tokens',
        true
    )
END
WHERE jsonb_typeof(model_parameters) = 'object'
  AND model_parameters ? 'max_output_tokens'
"""


def upgrade() -> None:
    """Rename Agent model parameter output token cap key."""
    op.execute(_RENAME_TO_MAX_OUTPUT_TOKENS)


def downgrade() -> None:
    """Restore previous Agent model parameter output token cap key."""
    op.execute(_RENAME_TO_MAX_TOKENS)
