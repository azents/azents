"""reconcile validated catalog cutover with current main schema

Revision ID: 2d91f8044dad
Revises: 43a0fbdc96fe, 4550a9c9083a
Create Date: 2026-09-30 20:42:29.000644

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "2d91f8044dad"
down_revision: str | Sequence[str] | None = ("43a0fbdc96fe", "4550a9c9083a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
