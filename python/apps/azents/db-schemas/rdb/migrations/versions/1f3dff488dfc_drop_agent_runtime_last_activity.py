"""drop agent runtime last activity

Revision ID: 1f3dff488dfc
Revises: 8f0b8e4f0c9a
Create Date: 2026-06-14 18:58:38.023334

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f3dff488dfc"
down_revision: str | Sequence[str] | None = "8f0b8e4f0c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema."""
    op.drop_column("agent_runtimes", "last_activity_at")


def downgrade() -> None:
    """Downgrade the schema."""
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
