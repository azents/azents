"""add action message input

Revision ID: 108ab194ee85
Revises: 0d2a6cf4b7a1
Create Date: 2026-06-30 12:37:37.202435

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "108ab194ee85"
down_revision: str | Sequence[str] | None = "0d2a6cf4b7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE input_buffer_kind ADD VALUE IF NOT EXISTS 'action_message'")
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'action_message'")
    op.add_column(
        "input_buffers",
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("input_buffers", "action")
