"""Add Session Routine definitions, retained work and Primary Binding authority."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "08a588456917"
down_revision: str | Sequence[str] | None = "004bda2b6938"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve Bindings and fail before backfill when authority is ambiguous."""
    op.execute("LOCK TABLE external_channel_bindings IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT agent_session_id FROM external_channel_bindings
            WHERE disconnected_at IS NULL
            GROUP BY agent_session_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'Primary migration found multiple connected Bindings';
          END IF;
          IF EXISTS (
            SELECT b.id FROM external_channel_bindings b
            JOIN agent_sessions s ON s.id = b.agent_session_id
            JOIN agents a ON a.id = s.agent_id
            JOIN external_channel_agent_routes r ON r.id = b.route_id
            JOIN external_channel_connections c ON c.id = r.connection_id
            JOIN external_channel_resources resource ON resource.id = b.resource_id
            WHERE b.disconnected_at IS NULL AND (
              r.agent_id IS DISTINCT FROM s.agent_id OR
              a.workspace_id IS DISTINCT FROM s.workspace_id OR
              c.workspace_id IS DISTINCT FROM s.workspace_id OR
              r.connection_app_mode IS DISTINCT FROM c.app_mode OR
              r.connection_id IS DISTINCT FROM resource.connection_id OR
              s.status <> 'active' OR a.lifecycle_status <> 'active' OR
              r.catalog_status <> 'available' OR resource.status <> 'active' OR
              c.status NOT IN ('active', 'degraded') OR c.disconnected_at IS NOT NULL
            )
          ) THEN
            RAISE EXCEPTION 'Primary migration found incompatible Binding owners';
          END IF;
        END $$
        """
    )
    op.add_column(
        "agent_sessions", sa.Column("primary_channel_binding_id", sa.String(32))
    )
    op.create_foreign_key(
        "fk_agent_sessions_primary_channel_binding",
        "agent_sessions",
        "external_channel_bindings",
        ["primary_channel_binding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_sessions_primary_channel_binding",
        "agent_sessions",
        ["primary_channel_binding_id"],
        postgresql_where=sa.text("primary_channel_binding_id IS NOT NULL"),
    )
    op.execute(
        """
        UPDATE agent_sessions s SET primary_channel_binding_id = b.id
        FROM external_channel_bindings b
        WHERE b.agent_session_id = s.id AND b.disconnected_at IS NULL
        """
    )
    op.execute("CREATE TYPE routine_objective_outcome AS ENUM ('finished', 'failed')")
    op.execute(
        "CREATE TYPE routine_delivery_status AS ENUM "
        "('not_requested', 'unobserved', 'delivered', 'failed')"
    )
    op.create_table(
        "routines",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
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
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "slug", name="uq_routines_session_slug"),
    )
    op.create_index("ix_routines_session_id", "routines", ["session_id"])
    op.create_index("ix_routines_agent_id", "routines", ["agent_id"])
    op.create_table(
        "routine_work_records",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("routine_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("execution_id", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "objective_outcome",
            postgresql.ENUM(
                "finished",
                "failed",
                name="routine_objective_outcome",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("next_hint", sa.Text(), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "delivery_status",
            postgresql.ENUM(
                "not_requested",
                "unobserved",
                "delivered",
                "failed",
                name="routine_delivery_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(notify AND message IS NOT NULL) OR (NOT notify AND message IS NULL)",
            name="ck_routine_work_records_notification_message",
        ),
        sa.CheckConstraint(
            "(NOT notify AND delivery_status = 'not_requested') OR "
            "(notify AND delivery_status <> 'not_requested')",
            name="ck_routine_work_records_delivery_choice",
        ),
        sa.ForeignKeyConstraint(["routine_id"], ["routines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id", name="uq_routine_work_records_execution_id"
        ),
    )
    op.create_index(
        "ix_routine_work_records_recency",
        "routine_work_records",
        ["routine_id", "completed_at", "id"],
    )
    op.create_index(
        "ix_routine_work_records_session_id", "routine_work_records", ["session_id"]
    )


def downgrade() -> None:
    """Reject destructive removal of admitted product data and Primary authority."""
    raise RuntimeError("Session Routine foundation migration is irreversible.")
