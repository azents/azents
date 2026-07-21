"""add agent run vfs projection

Revision ID: 6b4ed906ae81
Revises: 725b487eaaca
Create Date: 2026-07-19 18:17:32.115638

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "6b4ed906ae81"
down_revision: str | Sequence[str] | None = "725b487eaaca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column("vfs_projection", JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "vfs_projection")
