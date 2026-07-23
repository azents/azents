"""merge rebased provider migration heads

Revision ID: ae769da63fed
Revises: 43ecb24205aa, 815a7f8e72f2
Create Date: 2026-07-23 13:43:21.270054

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "ae769da63fed"
down_revision: str | Sequence[str] | None = ("43ecb24205aa", "815a7f8e72f2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
