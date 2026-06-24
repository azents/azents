"""drop input buffer images

Revision ID: 74d24674441d
Revises: e36b419c66b2
Create Date: 2026-06-02 00:48:21.024333

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "74d24674441d"
down_revision: str | Sequence[str] | None = "e36b419c66b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("input_buffers", "images")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "input_buffers",
        sa.Column(
            "images",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("input_buffers", "images", server_default=None)
