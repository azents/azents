"""add channels, conversation_sessions, messages tables

Revision ID: 3156f6b811df
Revises: 453c23cfa3f5
Create Date: 2026-02-23 00:46:18.562018

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3156f6b811df"
down_revision: str | Sequence[str] | None = "453c23cfa3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create channels, conversation_sessions, messages tables, and related ENUMs."""
    # Create ENUMs
    channel_type_enum = postgresql.ENUM(
        "web", "group", "dm", name="channel_type", create_type=False
    )
    channel_type_enum.create(op.get_bind(), checkfirst=True)

    conversation_session_type_enum = postgresql.ENUM(
        "user", "system", name="conversation_session_type", create_type=False
    )
    conversation_session_type_enum.create(op.get_bind(), checkfirst=True)

    message_role_enum = postgresql.ENUM(
        "system",
        "user",
        "assistant",
        "tool",
        name="message_role",
        create_type=False,
    )
    message_role_enum.create(op.get_bind(), checkfirst=True)

    # Create the channels table
    op.create_table(
        "channels",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(
                "web",
                "group",
                "dm",
                name="channel_type",
                create_type=False,
            ),
            nullable=False,
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
    op.create_index("ix_channels_workspace_id", "channels", ["workspace_id"])
    op.create_index("ix_channels_agent_id", "channels", ["agent_id"])

    # Create the conversation_sessions table
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(32),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(
                "user",
                "system",
                name="conversation_session_type",
                create_type=False,
            ),
            nullable=False,
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
    op.create_index(
        "ix_conversation_sessions_channel_id",
        "conversation_sessions",
        ["channel_id"],
    )
    op.create_index(
        "ix_conversation_sessions_user_id",
        "conversation_sessions",
        ["user_id"],
    )

    # Create the messages table
    op.create_table(
        "messages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(32),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "system",
                "user",
                "assistant",
                "tool",
                name="message_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
        sa.Column("tool_call_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_messages_channel_id", "messages", ["channel_id"])


def downgrade() -> None:
    """Drop messages, conversation_sessions, channels tables, and related ENUMs."""
    op.drop_index("ix_messages_channel_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index(
        "ix_conversation_sessions_user_id",
        table_name="conversation_sessions",
    )
    op.drop_index(
        "ix_conversation_sessions_channel_id",
        table_name="conversation_sessions",
    )
    op.drop_table("conversation_sessions")

    op.drop_index("ix_channels_agent_id", table_name="channels")
    op.drop_index("ix_channels_workspace_id", table_name="channels")
    op.drop_table("channels")

    bind = op.get_bind()
    postgresql.ENUM(name="message_role").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_session_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="channel_type").drop(bind, checkfirst=True)
