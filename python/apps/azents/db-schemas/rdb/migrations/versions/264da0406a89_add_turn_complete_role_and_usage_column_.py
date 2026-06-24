"""add turn_complete role and usage column to events

Revision ID: 264da0406a89
Revises: 66fb4793017f
Create Date: 2026-03-05 02:30:14.527839

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "264da0406a89"
down_revision: str | Sequence[str] | None = "66fb4793017f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the turn_complete value to message_role and the usage column to events."""
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'turn_complete'")
    op.add_column(
        "events",
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Remove the usage column from the events table.

    PostgreSQL ENUM values cannot be deleted, so turn_complete is left in place.
    """
    op.drop_column("events", "usage")
