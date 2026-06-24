"""add discord_bot_messages table

Revision ID: df34bef59381
Revises: a536c8318726
Create Date: 2026-03-10 18:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "df34bef59381"
down_revision: str | Sequence[str] | None = "a536c8318726"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "discord_bot_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("discord_session_id", sa.String(length=32), nullable=False),
        sa.Column("discord_message_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["discord_session_id"],
            ["discord_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discord_bot_messages_discord_session_id",
        "discord_bot_messages",
        ["discord_session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_discord_bot_messages_discord_session_id",
        table_name="discord_bot_messages",
    )
    op.drop_table("discord_bot_messages")
