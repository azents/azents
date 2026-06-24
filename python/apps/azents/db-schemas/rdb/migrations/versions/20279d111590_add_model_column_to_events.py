"""add model column to events

Revision ID: 20279d111590
Revises: a2f1c3e5d7b9
Create Date: 2026-03-04 06:01:33.270290

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20279d111590"
down_revision: str | Sequence[str] | None = "a2f1c3e5d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the model column to the events table."""
    op.add_column("events", sa.Column("model", sa.Text, nullable=True))


def downgrade() -> None:
    """Remove the model column from the events table."""
    op.drop_column("events", "model")
