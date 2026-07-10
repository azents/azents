"""expand reasoning effort levels

Revision ID: 3865d27c9b0a
Revises: b06e712db40c
Create Date: 2026-07-10 18:41:54.279021

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3865d27c9b0a"
down_revision: str | Sequence[str] | None = "b06e712db40c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE model_reasoning_effort ADD VALUE IF NOT EXISTS 'none' BEFORE 'low'"
    )
    op.execute(
        "ALTER TYPE model_reasoning_effort "
        "ADD VALUE IF NOT EXISTS 'minimal' BEFORE 'low'"
    )
    op.execute(
        "ALTER TYPE model_reasoning_effort ADD VALUE IF NOT EXISTS 'xhigh' AFTER 'high'"
    )
    op.execute(
        "ALTER TYPE model_reasoning_effort ADD VALUE IF NOT EXISTS 'max' AFTER 'xhigh'"
    )


def downgrade() -> None:
    """Downgrade schema."""
