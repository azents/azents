"""normalize json null workspace defaults

Revision ID: b754406b3aee
Revises: e5f4b33f401e
Create Date: 2026-07-09 19:46:58.639364

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b754406b3aee"
down_revision: str | Sequence[str] | None = "e5f4b33f401e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize empty workspace defaults stored as JSONB literal null."""
    op.execute(
        """
        UPDATE workspace_model_settings
        SET
            default_model_selection = NULL,
            default_lightweight_model_selection = NULL,
            default_selectable_model_options = NULL,
            default_main_model_label = NULL,
            default_lightweight_model_label = NULL
        WHERE default_model_selection = 'null'::jsonb
        """
    )


def downgrade() -> None:
    """Keep normalized data when downgrading."""
