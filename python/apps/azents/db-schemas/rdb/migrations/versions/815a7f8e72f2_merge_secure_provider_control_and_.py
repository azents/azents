"""merge secure provider control and provider policy

Revision ID: 815a7f8e72f2
Revises: 033bd176af15, 6d5fbc5c551d
Create Date: 2026-07-23 00:20:12.796194

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "815a7f8e72f2"
down_revision: str | Sequence[str] | None = ("033bd176af15", "6d5fbc5c551d")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
