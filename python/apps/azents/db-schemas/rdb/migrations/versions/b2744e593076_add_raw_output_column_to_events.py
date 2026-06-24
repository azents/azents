"""add raw_output column to events

Revision ID: b2744e593076
Revises: 20279d111590
Create Date: 2026-03-05 00:22:10.210258

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2744e593076"
down_revision: str | Sequence[str] | None = "20279d111590"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the raw_output JSONB column to the events table."""
    op.add_column(
        "events",
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Remove the raw_output column from the events table."""
    op.drop_column("events", "raw_output")
