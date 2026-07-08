"""add agent message input event kinds

Revision ID: f79809732650
Revises: e7e9f24edae0
Create Date: 2026-07-08 10:58:39.564717

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f79809732650"
down_revision: str | Sequence[str] | None = "e7e9f24edae0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE input_buffer_kind ADD VALUE IF NOT EXISTS 'agent_message'")
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'agent_message'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
