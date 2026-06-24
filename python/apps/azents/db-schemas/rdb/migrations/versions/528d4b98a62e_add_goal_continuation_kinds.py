"""add goal continuation kinds

Revision ID: 528d4b98a62e
Revises: 4e6c8f2a1b9d
Create Date: 2026-06-15 10:04:43.513862

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "528d4b98a62e"
down_revision: str | Sequence[str] | None = "4e6c8f2a1b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE input_buffer_kind ADD VALUE IF NOT EXISTS 'goal_continuation'"
    )
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'goal_continuation'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
