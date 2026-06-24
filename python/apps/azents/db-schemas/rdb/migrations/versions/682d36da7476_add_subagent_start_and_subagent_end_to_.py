"""add subagent_start and subagent_end to message_role enum

Revision ID: 682d36da7476
Revises: d7c5a3ffce2c
Create Date: 2026-03-07 01:00:08.708191

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "682d36da7476"
down_revision: str | Sequence[str] | None = "d7c5a3ffce2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add subagent_start and subagent_end values to the message_role ENUM."""
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'subagent_start'")
    op.execute("ALTER TYPE message_role ADD VALUE IF NOT EXISTS 'subagent_end'")


def downgrade() -> None:
    """No-op because values cannot be removed from PostgreSQL ENUMs."""
