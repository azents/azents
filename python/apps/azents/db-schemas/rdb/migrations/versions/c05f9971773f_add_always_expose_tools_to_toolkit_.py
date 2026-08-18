"""add always expose tools to toolkit configs

Revision ID: c05f9971773f
Revises: 5c044388362c
Create Date: 2026-08-18 18:20:42.380549

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c05f9971773f"
down_revision: str | Sequence[str] | None = "5c044388362c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "toolkit_configs",
        sa.Column(
            "always_expose_tools",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("toolkit_configs", "always_expose_tools")
