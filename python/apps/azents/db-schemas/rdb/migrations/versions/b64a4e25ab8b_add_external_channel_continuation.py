"""Add External Channel continuation kinds.

Revision ID: b64a4e25ab8b
Revises: dc82433bef40
Create Date: 2026-07-31

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b64a4e25ab8b"
down_revision: str | Sequence[str] | None = "dc82433bef40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add dedicated durable External Channel continuation kinds."""
    op.execute(
        "ALTER TYPE mailbox_item_kind "
        "ADD VALUE IF NOT EXISTS 'external_channel_continuation'"
    )
    op.execute(
        "ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'external_channel_continuation'"
    )


def downgrade() -> None:
    """PostgreSQL enum values are intentionally retained on downgrade."""
