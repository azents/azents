"""add interrupted event kind

Revision ID: f0bf7772358f
Revises: 8d3953d75338
Create Date: 2026-06-16 10:19:39.998597

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0bf7772358f"
down_revision: str | Sequence[str] | None = "8d3953d75338"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'interrupted'")


def downgrade() -> None:
    """Downgrade schema."""
