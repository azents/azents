"""merge inference profile and xai provider heads

Revision ID: b06e712db40c
Revises: 25a661df4ff6, 892929403f2a
Create Date: 2026-07-10 16:03:40.348101

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "b06e712db40c"
down_revision: str | Sequence[str] | None = ("25a661df4ff6", "892929403f2a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
