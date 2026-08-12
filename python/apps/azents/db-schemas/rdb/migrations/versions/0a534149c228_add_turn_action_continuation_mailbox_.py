"""Add TurnAction continuation mailbox kind.

Revision ID: 0a534149c228
Revises: 3d9280a9ce92
Create Date: 2026-08-12 11:22:48.959589

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0a534149c228"
down_revision: str | Sequence[str] | None = "3d9280a9ce92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the hidden durable TurnAction continuation kind."""
    op.execute(
        "ALTER TYPE mailbox_item_kind "
        "ADD VALUE IF NOT EXISTS 'turn_action_continuation'"
    )


def downgrade() -> None:
    """PostgreSQL enum values are intentionally retained on downgrade."""
