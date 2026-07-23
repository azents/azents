"""merge platform runtime settings and provider control

Revision ID: 033bd176af15
Revises: 48bc633b2746, 8d1ff4cc92a1
Create Date: 2026-07-22 23:44:57.816557

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "033bd176af15"
down_revision: str | Sequence[str] | None = ("48bc633b2746", "8d1ff4cc92a1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
