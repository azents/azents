"""add_file_columns_to_events

Revision ID: 7c99853a1843
Revises: a896d8c01d0f
Create Date: 2026-03-01 11:54:57.081036

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "7c99853a1843"
down_revision: str | Sequence[str] | None = "a896d8c01d0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add file-related JSONB columns to the events table."""
    op.add_column("events", sa.Column("inbox_files", JSONB, nullable=True))
    op.add_column("events", sa.Column("outbox_files", JSONB, nullable=True))
    op.add_column("events", sa.Column("thumbnails", JSONB, nullable=True))


def downgrade() -> None:
    """Remove file-related columns from the events table."""
    op.drop_column("events", "thumbnails")
    op.drop_column("events", "outbox_files")
    op.drop_column("events", "inbox_files")
