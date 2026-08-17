"""add scheduled tasks domain foundation

Revision ID: 7686aeee9531
Revises: 0e5aa4745f0a
Create Date: 2026-08-16 10:20:16.067357

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7686aeee9531"
down_revision: str | Sequence[str] | None = "0e5aa4745f0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEDULE_TYPE_ENUM = postgresql.ENUM(
    "once",
    "cron",
    name="scheduled_task_schedule_type",
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    _SCHEDULE_TYPE_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "schedule_type",
            postgresql.ENUM(
                "once",
                "cron",
                name="scheduled_task_schedule_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("active_cycle_id", sa.String(length=32), nullable=True),
        sa.Column("active_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "((schedule_type = 'once' "
            "AND scheduled_at IS NOT NULL "
            "AND cron_expression IS NULL "
            "AND timezone IS NULL) "
            "OR (schedule_type = 'cron' "
            "AND scheduled_at IS NULL "
            "AND cron_expression IS NOT NULL "
            "AND timezone IS NOT NULL))",
            name="ck_scheduled_tasks_schedule_shape",
        ),
        sa.CheckConstraint(
            "((active_cycle_id IS NULL AND active_scheduled_for IS NULL) "
            "OR (active_cycle_id IS NOT NULL "
            "AND active_scheduled_for IS NOT NULL))",
            name="ck_scheduled_tasks_active_cycle_fence",
        ),
        sa.CheckConstraint(
            "(pending_scheduled_for IS NULL "
            "OR (schedule_type = 'cron' AND active_cycle_id IS NOT NULL))",
            name="ck_scheduled_tasks_pending_occurrence",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_scheduled_tasks_agent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            name="fk_scheduled_tasks_binding_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name="fk_scheduled_tasks_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_scheduled_tasks_workspace_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_tasks_active_cycle_id",
        "scheduled_tasks",
        ["active_cycle_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_tasks_binding_id",
        "scheduled_tasks",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_tasks_next_eligible_at_id",
        "scheduled_tasks",
        ["next_eligible_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_tasks_session_id",
        "scheduled_tasks",
        ["session_id"],
        unique=False,
    )

    op.add_column(
        "agent_runs",
        sa.Column("scheduled_task_cycle_id", sa.String(length=32), nullable=True),
    )

    op.execute(
        "ALTER TYPE mailbox_item_kind ADD VALUE IF NOT EXISTS 'scheduled_task_trigger'"
    )
    op.execute(
        "ALTER TYPE mailbox_item_kind "
        "ADD VALUE IF NOT EXISTS 'scheduled_task_continuation'"
    )
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'scheduled_task_trigger'")
    op.execute(
        "ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'scheduled_task_continuation'"
    )
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'scheduled_task_result'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "scheduled_task_cycle_id")
    op.drop_index(
        "ix_scheduled_tasks_session_id",
        table_name="scheduled_tasks",
    )
    op.drop_index(
        "ix_scheduled_tasks_next_eligible_at_id",
        table_name="scheduled_tasks",
    )
    op.drop_index(
        "ix_scheduled_tasks_binding_id",
        table_name="scheduled_tasks",
    )
    op.drop_index(
        "ix_scheduled_tasks_active_cycle_id",
        table_name="scheduled_tasks",
    )
    op.drop_table("scheduled_tasks")
    _SCHEDULE_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)

    # PostgreSQL enum values are intentionally retained on downgrade.
