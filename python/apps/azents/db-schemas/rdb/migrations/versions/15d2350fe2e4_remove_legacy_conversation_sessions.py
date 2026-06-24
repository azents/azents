"""remove legacy conversation sessions

Revision ID: 15d2350fe2e4
Revises: a9844c24a03b
Create Date: 2026-05-05 08:02:50.111733

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "15d2350fe2e4"
down_revision: str | Sequence[str] | None = "a9844c24a03b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy ConversationSession tables and channel bindings."""
    bind = op.get_bind()

    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_session_id_fkey")
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_v2_session_id_fkey")
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS fk_events_session_id")
    op.execute("DROP INDEX IF EXISTS uq_events_session_external")
    op.execute(
        """
        WITH mapped_events AS (
            SELECT
                e.id,
                COALESCE(cs.agent_session_id, e.session_id) AS target_session_id,
                e.external_id,
                CASE WHEN cs.agent_session_id IS NULL THEN 0 ELSE 1 END AS remap_order
            FROM events AS e
            LEFT JOIN conversation_sessions AS cs ON e.session_id = cs.id
            WHERE e.external_id IS NOT NULL
        ),
        ranked_events AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY target_session_id, external_id
                    ORDER BY remap_order, id
                ) AS row_number
            FROM mapped_events
        )
        DELETE FROM events AS e
        USING ranked_events AS ranked
        WHERE e.id = ranked.id
          AND ranked.row_number > 1
        """
    )
    op.execute(
        """
        UPDATE events AS e
        SET session_id = cs.agent_session_id
        FROM conversation_sessions AS cs
        WHERE e.session_id = cs.id
          AND cs.agent_session_id IS NOT NULL
        """
    )
    op.execute(
        """
        DELETE FROM events AS e
        WHERE NOT EXISTS (
            SELECT 1
            FROM agent_sessions AS agent_session
            WHERE agent_session.id = e.session_id
        )
        """
    )
    op.execute(
        """
        DELETE FROM events AS e
        USING events AS older
        WHERE e.session_id = older.session_id
          AND e.external_id = older.external_id
          AND e.external_id IS NOT NULL
          AND e.id > older.id
        """
    )
    op.create_index(
        "uq_events_session_external",
        "events",
        ["session_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.drop_constraint(
        "fk_events_agent_session_id_agent_sessions",
        "events",
        type_="foreignkey",
    )
    op.drop_index("ix_events_agent_session_id", table_name="events")
    op.drop_column("events", "agent_session_id")
    op.create_foreign_key(
        "events_session_id_fkey",
        "events",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        "ALTER TABLE session_snapshots "
        "DROP CONSTRAINT IF EXISTS session_snapshots_session_id_fkey"
    )
    op.execute(
        """
        UPDATE session_snapshots AS ss
        SET session_id = cs.agent_session_id
        FROM conversation_sessions AS cs
        WHERE ss.session_id = cs.id
          AND cs.agent_session_id IS NOT NULL
        """
    )
    op.execute(
        """
        DELETE FROM session_snapshots AS ss
        WHERE NOT EXISTS (
            SELECT 1
            FROM agent_sessions AS agent_session
            WHERE agent_session.id = ss.session_id
        )
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_session_snapshots_session_id_created_at")
    op.execute("DROP INDEX IF EXISTS ix_session_snapshots_session_id")
    op.rename_table("session_snapshots", "kubernetes_sandbox_snapshots")
    op.alter_column(
        "kubernetes_sandbox_snapshots",
        "session_id",
        new_column_name="agent_session_id",
    )
    op.create_foreign_key(
        "kubernetes_sandbox_snapshots_agent_session_id_fkey",
        "kubernetes_sandbox_snapshots",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_kubernetes_sandbox_snapshots_agent_session_id_created_at",
        "kubernetes_sandbox_snapshots",
        ["agent_session_id", sa.literal_column("created_at DESC")],
    )

    op.drop_table("slack_channel_bindings")
    op.drop_table("discord_channel_bindings")
    op.drop_table("conversation_sessions")

    postgresql.ENUM(name="conversation_session_run_state").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_session_type").drop(bind, checkfirst=True)


def downgrade() -> None:
    """Restore legacy ConversationSession tables and channel bindings.

    The restored tables use an empty schema.
    """
    bind = op.get_bind()

    conversation_session_type = postgresql.ENUM(
        "web",
        "subagent",
        "agent",
        name="conversation_session_type",
    )
    conversation_session_run_state = postgresql.ENUM(
        "idle",
        "running",
        name="conversation_session_run_state",
    )
    conversation_session_type.create(bind, checkfirst=True)
    conversation_session_run_state.create(bind, checkfirst=True)

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(name="conversation_session_type", create_type=False),
            nullable=False,
        ),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("parent_session_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
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
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "run_state",
            postgresql.ENUM(
                name="conversation_session_run_state",
                create_type=False,
            ),
            server_default="idle",
            nullable=False,
        ),
        sa.Column(
            "run_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("runtime_run_id", sa.String(length=80), nullable=True),
        sa.Column(
            "runtime_state",
            postgresql.ENUM(name="session_runtime_state", create_type=False),
            nullable=True,
        ),
        sa.Column("runtime_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_runtime_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sdk_run_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            name="fk_conversation_sessions_agent_runtime_id_agent_runtimes",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            name="fk_conversation_sessions_agent_session_id_agent_sessions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"], ["conversation_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_sessions_user_id", "conversation_sessions", ["user_id"]
    )
    op.create_index(
        "ix_conversation_sessions_parent_session_id",
        "conversation_sessions",
        ["parent_session_id"],
    )
    op.create_index(
        "ix_conversation_sessions_agent_id_last_activity_at",
        "conversation_sessions",
        ["agent_id", "last_activity_at"],
    )
    op.create_index(
        "ix_conversation_sessions_agent_runtime_id",
        "conversation_sessions",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_conversation_sessions_agent_session_id",
        "conversation_sessions",
        ["agent_session_id"],
    )
    op.create_index(
        "uq_conversation_sessions_agent_raw_session_agent_id",
        "conversation_sessions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("type = 'agent'"),
    )
    op.create_index(
        "ix_conversation_sessions_run_state_running",
        "conversation_sessions",
        ["run_heartbeat_at"],
        postgresql_where=sa.text("run_state = 'running'"),
    )
    op.create_index(
        "ix_conversation_sessions_runtime_state_deadline",
        "conversation_sessions",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
    op.create_index(
        "ix_conversation_sessions_runtime_claimed_at",
        "conversation_sessions",
        ["runtime_claimed_at"],
        postgresql_where=sa.text("runtime_run_id IS NOT NULL"),
    )
    op.execute(
        """
        INSERT INTO conversation_sessions (
            id,
            workspace_id,
            agent_id,
            type,
            agent_runtime_id,
            agent_session_id,
            title,
            created_at,
            updated_at,
            last_activity_at
        )
        SELECT
            agent_session.id,
            agent_session.workspace_id,
            agent_session.agent_id,
            'web',
            agent_session.agent_runtime_id,
            agent_session.id,
            agent_session.title,
            agent_session.created_at,
            agent_session.updated_at,
            COALESCE(agent_session.ended_at, agent_session.updated_at)
        FROM agent_sessions AS agent_session
        """
    )

    op.execute(
        "ALTER TABLE kubernetes_sandbox_snapshots "
        "DROP CONSTRAINT IF EXISTS kubernetes_sandbox_snapshots_agent_session_id_fkey"
    )
    op.drop_index(
        "ix_kubernetes_sandbox_snapshots_agent_session_id_created_at",
        table_name="kubernetes_sandbox_snapshots",
    )
    op.alter_column(
        "kubernetes_sandbox_snapshots",
        "agent_session_id",
        new_column_name="session_id",
    )
    op.rename_table("kubernetes_sandbox_snapshots", "session_snapshots")
    op.create_foreign_key(
        "session_snapshots_session_id_fkey",
        "session_snapshots",
        "conversation_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_session_snapshots_session_id",
        "session_snapshots",
        ["session_id"],
    )
    op.create_index(
        "ix_session_snapshots_session_id_created_at",
        "session_snapshots",
        ["session_id", sa.literal_column("created_at DESC")],
    )

    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_session_id_fkey")
    op.add_column(
        "events",
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
    )
    op.execute("UPDATE events SET agent_session_id = session_id")
    op.create_foreign_key(
        "fk_events_agent_session_id_agent_sessions",
        "events",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_events_agent_session_id", "events", ["agent_session_id"])
    op.create_foreign_key(
        "events_session_id_fkey",
        "events",
        "conversation_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
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
        "slack_channel_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("installation_id", sa.String(length=32), nullable=False),
        sa.Column("slack_channel_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["slack_installations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "slack_channel_id",
            name="uq_slack_channel_bindings_installation_channel",
        ),
    )
