"""add toolkit revision

Revision ID: e7b9efaae7a5
Revises: 6412e7bf0530
Create Date: 2026-07-21 14:06:11.282100

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b9efaae7a5"
down_revision: str | Sequence[str] | None = "6412e7bf0530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a persisted revision to every ToolkitConfig."""
    op.add_column(
        "toolkit_configs",
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    """Remove ToolkitConfig source revisions."""
    op.drop_column("toolkit_configs", "revision")
