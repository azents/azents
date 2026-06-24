"""add_metadata_to_messages

Revision ID: abd59068d224
Revises: c56f65b7863c
Create Date: 2026-02-25 00:52:56.726427

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "abd59068d224"
down_revision: str | Sequence[str] | None = "c56f65b7863c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("metadata", JSONB, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "metadata")
