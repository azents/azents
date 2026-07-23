"""merge provider control and main heads

Revision ID: 43ecb24205aa
Revises: 033bd176af15, 1d10cb8faa04
Create Date: 2026-07-23 13:41:44.982222

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "43ecb24205aa"
down_revision: str | Sequence[str] | None = ("033bd176af15", "1d10cb8faa04")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
