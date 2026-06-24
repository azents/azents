"""add goal briefing event kind

Revision ID: 8d3953d75338
Revises: 528d4b98a62e
Create Date: 2026-06-15 12:52:14.658000

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d3953d75338"
down_revision: str | Sequence[str] | None = "528d4b98a62e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'goal_updated'")
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'goal_briefing'")


def downgrade() -> None:
    """Downgrade schema."""
