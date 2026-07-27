"""add external channel health code

Revision ID: e0615474dc27
Revises: 8ee8f5ae5a4d
Create Date: 2026-07-27 04:04:41.125950

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e0615474dc27"
down_revision: str | Sequence[str] | None = "8ee8f5ae5a4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_connections",
        sa.Column("last_health_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("external_channel_connections", "last_health_code")
