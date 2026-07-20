"""merge session unread and system settings heads

Revision ID: 38a236695c9e
Revises: 22f0f04e5ec0, 8842bd30d5c6
Create Date: 2026-07-20 14:45:53.070224

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "38a236695c9e"
down_revision: str | Sequence[str] | None = ("22f0f04e5ec0", "8842bd30d5c6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
