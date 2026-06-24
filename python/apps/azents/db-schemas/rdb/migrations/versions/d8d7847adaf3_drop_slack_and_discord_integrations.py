"""drop slack and discord integrations

Revision ID: d8d7847adaf3
Revises: 1f3dff488dfc
Create Date: 2026-06-15 00:59:33.410953

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8d7847adaf3"
down_revision: str | Sequence[str] | None = "1f3dff488dfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the Slack/Discord integration schema."""
    op.execute("DROP TABLE IF EXISTS discord_external_watch_deliveries")
    op.execute("DROP TABLE IF EXISTS slack_external_watch_deliveries")
    op.drop_table("discord_watch_bot_messages")
    op.drop_table("discord_external_watches")
    op.drop_table("slack_external_watches")
    op.drop_table("discord_agent_configs")
    op.drop_table("slack_agent_configs")
    op.drop_table("discord_user_links")
    op.drop_table("slack_user_links")
    op.drop_table("discord_installations")
    op.drop_table("slack_installations")
    op.execute("DROP TYPE IF EXISTS external_watch_status")
    op.execute("DROP TYPE IF EXISTS slack_installation_mode")


def downgrade() -> None:
    """Restore the Slack/Discord integration schema."""
    sa.Enum("platform", "byoa", name="slack_installation_mode").create(op.get_bind())

    op.create_table(
        "slack_installations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("slack_team_id", sa.String(length=32), nullable=False),
        sa.Column("slack_team_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_bot_token", sa.Text(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "platform", "byoa", name="slack_installation_mode", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("installed_by", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("slack_app_id", sa.String(length=32), nullable=True),
        sa.Column("encrypted_signing_secret", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_slack_installations_workspace_id",
        "slack_installations",
        ["workspace_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_slack_app_id "
            "ON slack_installations (slack_app_id) "
            "WHERE slack_app_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_workspace_agent "
            "ON slack_installations (workspace_id, agent_id) "
            "WHERE mode = 'byoa'"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_workspace_platform "
            "ON slack_installations (workspace_id) "
            "WHERE mode = 'platform'"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_slack_installations_team_platform "
            "ON slack_installations (slack_team_id) "
            "WHERE mode = 'platform'"
        )
    )

    op.create_table(
        "discord_installations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("discord_guild_id", sa.String(length=32), nullable=False),
        sa.Column("discord_guild_name", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discord_guild_id", name="uq_discord_installations_discord_guild_id"
        ),
        sa.UniqueConstraint(
            "workspace_id", name="uq_discord_installations_workspace_id"
        ),
    )
    op.create_index(
        "ix_discord_installations_workspace_id",
        "discord_installations",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "slack_user_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("slack_user_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["slack_installations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "slack_user_id",
            name="uq_slack_user_links_installation_slack_user",
        ),
    )
    op.create_table(
        "discord_user_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("discord_user_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["discord_installations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "discord_user_id",
            name="uq_discord_user_links_installation_discord_user",
        ),
    )
    op.create_table(
        "slack_agent_configs",
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("read", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("write", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "reactions", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "privacy", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "discord_agent_configs",
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("read", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("write", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "reactions", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "privacy", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "management", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    external_watch_status = postgresql.ENUM(
        "active",
        "paused",
        "deleted",
        name="external_watch_status",
    )
    external_watch_status.create(op.get_bind(), checkfirst=True)
    _create_external_watch_table(
        "slack_external_watches",
        thread_column="thread_ts",
    )
    _create_external_watch_indexes(
        "slack_external_watches",
        prefix="slack",
        thread_column="thread_ts",
    )
    _create_external_watch_table(
        "discord_external_watches",
        thread_column="thread_id",
    )
    _create_external_watch_indexes(
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


def _create_external_watch_table(table_name: str, *, thread_column: str) -> None:
    """Create the external watch table."""
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


def _create_external_watch_indexes(
    table_name: str,
    *,
    prefix: str,
    thread_column: str,
) -> None:
    """Create the external watch index."""
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
