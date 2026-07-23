"""merge runtime provider and external channel file heads

Revision ID: b976b12168b5
Revises: 2743073ba95b, 496235caed34
Create Date: 2026-07-24 01:02:21.092567

"""

from typing import Sequence

revision: str = "b976b12168b5"
down_revision: str | Sequence[str] | None = ("2743073ba95b", "496235caed34")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
