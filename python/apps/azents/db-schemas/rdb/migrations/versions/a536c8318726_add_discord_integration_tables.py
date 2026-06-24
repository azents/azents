"""add discord integration tables

Revision ID: a536c8318726
Revises: 84ffecd96ca4
Create Date: 2026-03-10 12:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from alembic_postgresql_enum import TableReference
from sqlalchemy.dialects import postgresql

revision: str = "a536c8318726"
down_revision: str | Sequence[str] | None = "84ffecd96ca4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("platform", "byoa", name="discord_installation_mode").create(op.get_bind())
    op.create_table(
        "discord_installations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("discord_guild_id", sa.String(length=32), nullable=False),
        sa.Column("discord_guild_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_bot_token", sa.Text(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "platform",
                "byoa",
                name="discord_installation_mode",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
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
        sa.UniqueConstraint(
            "discord_guild_id", name="uq_discord_installations_discord_guild_id"
        ),
    )
    op.create_index(
        "ix_discord_installations_workspace_id",
        "discord_installations",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "discord_channel_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("discord_channel_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["discord_installations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "discord_channel_id",
            name="uq_discord_channel_bindings_installation_channel",
        ),
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
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="conversation_session_type",
        new_values=["user", "system", "subagent", "slack", "discord"],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="conversation_sessions",
                column_name="type",
            )
        ],
        enum_values_to_rename=[],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="conversation_session_type",
        new_values=["user", "system", "subagent", "slack"],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="conversation_sessions",
                column_name="type",
            )
        ],
        enum_values_to_rename=[],
    )
    op.drop_table("discord_user_links")
    op.drop_index("ix_discord_sessions_context", table_name="discord_sessions")
    op.drop_table("discord_sessions")
    op.drop_table("discord_channel_bindings")
    op.drop_index(
        "ix_discord_installations_workspace_id", table_name="discord_installations"
    )
    op.drop_table("discord_installations")
    sa.Enum("platform", "byoa", name="discord_installation_mode").drop(op.get_bind())
