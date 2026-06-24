"""rename_messages_table_to_events

Revision ID: a896d8c01d0f
Revises: 5617a7c97af5
Create Date: 2026-03-01 10:40:17.247039

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a896d8c01d0f"
down_revision: str | Sequence[str] | None = "5617a7c97af5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the messages table to events."""
    op.rename_table("messages", "events")
    op.execute("ALTER INDEX ix_messages_channel_id RENAME TO ix_events_channel_id")


def downgrade() -> None:
    """Rename the events table back to messages."""
    op.execute("ALTER INDEX ix_events_channel_id RENAME TO ix_messages_channel_id")
    op.rename_table("events", "messages")
