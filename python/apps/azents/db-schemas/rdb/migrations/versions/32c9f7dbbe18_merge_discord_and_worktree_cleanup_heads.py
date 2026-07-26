"""merge discord and worktree cleanup heads

Revision ID: 32c9f7dbbe18
Revises: 26d36352bece, 3dd5802b8a10
Create Date: 2026-07-26 07:17:43.402981

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "32c9f7dbbe18"
down_revision: str | Sequence[str] | None = ("26d36352bece", "3dd5802b8a10")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
