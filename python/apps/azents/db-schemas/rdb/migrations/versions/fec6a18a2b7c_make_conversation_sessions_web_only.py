"""make conversation sessions main only

Revision ID: fec6a18a2b7c
Revises: 948f4d95cfd0
Create Date: 2026-05-03 23:30:36.472888

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fec6a18a2b7c"
down_revision: str | Sequence[str] | None = "948f4d95cfd0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy external session mappings."""
    op.drop_index(
        "ix_discord_bot_messages_discord_session_id",
        table_name="discord_bot_messages",
    )
    op.drop_table("discord_bot_messages")
    op.drop_index(
        "ix_discord_sessions_context",
        table_name="discord_sessions",
    )
    op.drop_table("discord_sessions")
    op.drop_index(
        "ix_slack_sessions_context",
        table_name="slack_sessions",
    )
    op.drop_table("slack_sessions")
    op.drop_constraint(
        "fk_conversation_sessions_scheduled_task_id",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_column("conversation_sessions", "scheduled_task_id")
    op.drop_column("conversation_sessions", "external_channel_id")
    op.drop_column("conversation_sessions", "channel_connection_id")


def downgrade() -> None:
    """Restore legacy external session mappings."""
    op.add_column(
        "conversation_sessions",
        sa.Column("channel_connection_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("external_channel_id", sa.String(), nullable=True),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("scheduled_task_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversation_sessions_scheduled_task_id",
        "conversation_sessions",
        "scheduled_tasks",
        ["scheduled_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "slack_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("slack_channel_id", sa.String(length=64), nullable=False),
        sa.Column("slack_user_id", sa.String(length=64), nullable=False),
        sa.Column("slack_thread_ts", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["slack_installations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_slack_sessions_session_id"),
    )
    op.create_index(
        "ix_slack_sessions_context",
        "slack_sessions",
        ["installation_id", "slack_channel_id", "slack_thread_ts", "slack_user_id"],
        unique=False,
    )
    op.create_table(
        "discord_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("discord_channel_id", sa.String(length=64), nullable=False),
        sa.Column("discord_thread_id", sa.String(length=64), nullable=False),
        sa.Column("discord_user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["discord_installations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_discord_sessions_session_id"),
    )
    op.create_index(
        "ix_discord_sessions_context",
        "discord_sessions",
        [
            "installation_id",
            "discord_channel_id",
            "discord_thread_id",
            "discord_user_id",
        ],
        unique=False,
    )
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
            ["discord_session_id"], ["discord_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discord_bot_messages_discord_session_id",
        "discord_bot_messages",
        ["discord_session_id"],
        unique=False,
    )
