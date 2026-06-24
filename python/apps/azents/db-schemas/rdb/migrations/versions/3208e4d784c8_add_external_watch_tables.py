"""add external watch tables

Revision ID: 3208e4d784c8
Revises: abd47854fe61
Create Date: 2026-05-04 00:11:05.914241

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3208e4d784c8"
down_revision: str | Sequence[str] | None = "abd47854fe61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_watch_table(table_name: str, *, thread_column: str) -> None:
    """Create the Slack/Discord domain watch table."""
    op.create_table(
        table_name,
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column(thread_column, sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="external_watch_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_watch_indexes(
    table_name: str,
    *,
    prefix: str,
    thread_column: str,
) -> None:
    """Create the Slack/Discord domain watch index."""
    op.create_index(
        f"uq_{prefix}_external_watches_active_channel_identity",
        table_name,
        ["workspace_id", "installation_id", "channel_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text(f"status != 'deleted' AND {thread_column} IS NULL"),
    )
    op.create_index(
        f"uq_{prefix}_external_watches_active_thread_identity",
        table_name,
        ["workspace_id", "installation_id", "channel_id", thread_column, "agent_id"],
        unique=True,
        postgresql_where=sa.text(
            f"status != 'deleted' AND {thread_column} IS NOT NULL"
        ),
    )
    op.create_index(
        f"ix_{prefix}_external_watches_fanout",
        table_name,
        ["workspace_id", "installation_id", "channel_id", thread_column, "status"],
    )
    op.create_index(
        f"ix_{prefix}_external_watches_agent_id",
        table_name,
        ["agent_id", "status"],
    )
    op.create_index(
        f"ix_{prefix}_external_watches_installation_id",
        table_name,
        ["installation_id"],
    )


def upgrade() -> None:
    """Add the ExternalWatch foundation table and enum."""
    external_watch_status = postgresql.ENUM(
        "active",
        "paused",
        "deleted",
        name="external_watch_status",
    )
    external_watch_status.create(op.get_bind(), checkfirst=True)

    _create_watch_table("slack_external_watches", thread_column="thread_ts")
    _create_watch_indexes(
        "slack_external_watches",
        prefix="slack",
        thread_column="thread_ts",
    )

    _create_watch_table("discord_external_watches", thread_column="thread_id")
    _create_watch_indexes(
        "discord_external_watches",
        prefix="discord",
        thread_column="thread_id",
    )

    op.create_table(
        "discord_watch_bot_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("watch_id", sa.String(length=32), nullable=False),
        sa.Column("discord_message_id", sa.String(length=64), nullable=False),
        sa.Column("discord_channel_id", sa.String(length=64), nullable=True),
        sa.Column("discord_thread_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["watch_id"], ["discord_external_watches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_discord_watch_bot_messages_watch_message",
        "discord_watch_bot_messages",
        ["watch_id", "discord_message_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the ExternalWatch foundation table and enum."""
    op.drop_table("discord_watch_bot_messages")
    op.drop_table("discord_external_watches")
    op.drop_table("slack_external_watches")
    op.execute("DROP TYPE IF EXISTS external_watch_status")
