"""add reasoning column to events

Revision ID: 95bc6cdc7b07
Revises: 9bf9866e78a9
Create Date: 2026-03-04 02:51:22.940687

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "95bc6cdc7b07"
down_revision: str | Sequence[str] | None = "9bf9866e78a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the reasoning JSONB column to the events table."""
    op.add_column(
        "events",
        sa.Column("reasoning", JSONB, nullable=True),
    )


def downgrade() -> None:
    """Remove the reasoning column from the events table."""
    op.drop_column("events", "reasoning")
