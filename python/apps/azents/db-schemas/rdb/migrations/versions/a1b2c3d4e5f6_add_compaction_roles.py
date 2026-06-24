"""add compaction roles to message_role enum

Revision ID: a1b2c3d4e5f6
Revises: 264da0406a89
Create Date: 2026-03-05 12:00:00.000000

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "264da0406a89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add compaction and compaction_started values to message_role."""
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'compaction'")
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'compaction_started'")


def downgrade() -> None:
    """Leave the values in place because PostgreSQL ENUM values cannot be deleted."""
