"""remove_channel_entity_session_owns_events

Remove the Channel entity and let Session directly own Events.
- events.channel_id to events.session_id, including data migration
- Remove conversation_sessions.channel_id
- Add channel_connection_id and external_channel_id to conversation_sessions
- Drop channels table
- Drop channel_type ENUM

Revision ID: d7c5a3ffce2c
Revises: ddf5e52ff2d8
Create Date: 2026-03-06 22:02:48.027830

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7c5a3ffce2c"
down_revision: str | Sequence[str] | None = "ddf5e52ff2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the Channel entity and let Session directly own Events."""
    # 1. Add session_id column to events as nullable and without FK
    op.add_column("events", sa.Column("session_id", sa.String(32), nullable=True))

    # 2. Data migration: map channel_id to session_id
    #    Multiple sessions can share the same channel_id due to a subagent bug.
    #    Prefer the parent session where type != 'subagent'.
    op.execute(
        sa.text("""
        UPDATE events e
        SET session_id = (
            SELECT cs.id
            FROM conversation_sessions cs
            WHERE cs.channel_id = e.channel_id
            ORDER BY CASE WHEN cs.type = 'subagent' THEN 1 ELSE 0 END,
                     cs.created_at
            LIMIT 1
        )
        """)
    )

    # 3. Delete unmapped orphan events with a channel but no session
    op.execute(sa.text("DELETE FROM events WHERE session_id IS NULL"))

    # 4. Change session_id to NOT NULL
    op.alter_column("events", "session_id", nullable=False)

    # 4. Add FK to events.session_id
    op.create_foreign_key(
        "fk_events_session_id",
        "events",
        "conversation_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 5. Add index to events.session_id
    op.create_index("ix_events_session_id", "events", ["session_id"])

    # 6. Drop events.channel_id FK, index, and column
    op.drop_constraint("messages_channel_id_fkey", "events", type_="foreignkey")
    op.drop_index("ix_events_channel_id", table_name="events")
    op.drop_column("events", "channel_id")

    # 7. Add new columns to conversation_sessions
    op.add_column(
        "conversation_sessions",
        sa.Column("channel_connection_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("external_channel_id", sa.String, nullable=True),
    )

    # 8. Drop conversation_sessions.channel_id FK, index, and column
    op.drop_constraint(
        "conversation_sessions_channel_id_fkey",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_conversation_sessions_channel_id",
        table_name="conversation_sessions",
    )
    op.drop_column("conversation_sessions", "channel_id")

    # 9. Drop channels table
    op.drop_index("ix_channels_agent_id", table_name="channels")
    op.drop_index("ix_channels_workspace_id", table_name="channels")
    op.drop_table("channels")

    # 10. Drop channel_type ENUM
    bind = op.get_bind()
    postgresql.ENUM(name="channel_type").drop(bind, checkfirst=True)


def downgrade() -> None:
    """Restore the Channel entity."""
    # Restore channel_type ENUM
    channel_type_enum = postgresql.ENUM(
        "web", "group", "dm", name="channel_type", create_type=False
    )
    channel_type_enum.create(op.get_bind(), checkfirst=True)

    # Restore channels table
    op.create_table(
        "channels",
        sa.Column("id", sa.String(32), nullable=False),
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
            channel_type_enum,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channels_workspace_id", "channels", ["workspace_id"])
    op.create_index("ix_channels_agent_id", "channels", ["agent_id"])

    # Restore conversation_sessions.channel_id
    op.add_column(
        "conversation_sessions",
        sa.Column("channel_id", sa.String(32), nullable=True),
    )

    # Restore data by creating and linking a channel for each session
    # NOTE: perfect restoration is impossible, so set defaults
    op.execute(
        sa.text("""
        INSERT INTO channels (id, workspace_id, agent_id, type)
        SELECT id, workspace_id, agent_id, 'web'
        FROM conversation_sessions
        """)
    )
    op.execute(
        sa.text("""
        UPDATE conversation_sessions SET channel_id = id
        """)
    )

    op.alter_column("conversation_sessions", "channel_id", nullable=False)
    op.create_foreign_key(
        "conversation_sessions_channel_id_fkey",
        "conversation_sessions",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conversation_sessions_channel_id",
        "conversation_sessions",
        ["channel_id"],
    )

    # Drop new conversation_sessions columns
    op.drop_column("conversation_sessions", "external_channel_id")
    op.drop_column("conversation_sessions", "channel_connection_id")

    # Restore events.session_id to events.channel_id
    op.add_column(
        "events",
        sa.Column("channel_id", sa.String(32), nullable=True),
    )
    op.execute(
        sa.text("""
        UPDATE events e
        SET channel_id = cs.channel_id
        FROM conversation_sessions cs
        WHERE cs.id = e.session_id
        """)
    )
    op.alter_column("events", "channel_id", nullable=False)
    op.create_foreign_key(
        "messages_channel_id_fkey",
        "events",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_events_channel_id", "events", ["channel_id"])

    # Drop events.session_id
    op.drop_constraint("fk_events_session_id", "events", type_="foreignkey")
    op.drop_index("ix_events_session_id", table_name="events")
    op.drop_column("events", "session_id")
