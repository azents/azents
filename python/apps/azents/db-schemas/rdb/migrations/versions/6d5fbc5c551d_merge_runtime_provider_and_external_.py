"""merge runtime provider and external channel heads

Revision ID: 6d5fbc5c551d
Revises: 10388ea1e1ed, 498257a85dc8
Create Date: 2026-07-22 15:54:14.843078

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "6d5fbc5c551d"
down_revision: str | Sequence[str] | None = ("10388ea1e1ed", "498257a85dc8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
