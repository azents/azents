"""add external channel invocation projection

Revision ID: 498257a85dc8
Revises: 3a73e4fe7d58
Create Date: 2026-07-22 02:50:15.733011

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "498257a85dc8"
down_revision: str | Sequence[str] | None = "3a73e4fe7d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE input_buffer_kind "
        "ADD VALUE IF NOT EXISTS 'external_channel_invocation'"
    )
    op.execute(
        "ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'external_channel_message'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
