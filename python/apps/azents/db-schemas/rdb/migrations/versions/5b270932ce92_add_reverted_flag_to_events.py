"""add reverted flag to events

Revision ID: 5b270932ce92
Revises: 0b4f8c2d1e9a
Create Date: 2026-05-31 11:48:01.874275

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b270932ce92"
down_revision: str | Sequence[str] | None = "0b4f8c2d1e9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "events",
        sa.Column(
            "reverted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "reverted")
