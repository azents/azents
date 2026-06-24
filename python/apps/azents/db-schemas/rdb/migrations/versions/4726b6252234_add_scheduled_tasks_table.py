"""add scheduled_tasks table

Revision ID: c6ef061e5744
Revises: 2ff518daad00
Create Date: 2026-03-31 02:24:09.734304

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6ef061e5744"
down_revision: str | Sequence[str] | None = "2ff518daad00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sa.Enum("cron", "once", name="schedule_type").create(op.get_bind())
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "schedule_type",
            postgresql.ENUM("cron", "once", name="schedule_type", create_type=False),
            nullable=False,
        ),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("interface_type", sa.String(length=20), nullable=True),
        sa.Column(
            "interface_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
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
            ["agent_id"],
            ["agents.id"],
            name="fk_scheduled_tasks_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_scheduled_tasks_workspace_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_tasks_agent_id", "scheduled_tasks", ["agent_id"], unique=False
    )
    op.create_index(
        "ix_scheduled_tasks_next_run_at",
        "scheduled_tasks",
        ["next_run_at"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_tasks_workspace_id",
        "scheduled_tasks",
        ["workspace_id"],
        unique=False,
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


def downgrade() -> None:
    op.drop_constraint(
        "fk_conversation_sessions_scheduled_task_id",
        "conversation_sessions",
        type_="foreignkey",
    )
    op.drop_column("conversation_sessions", "scheduled_task_id")
    op.drop_index("ix_scheduled_tasks_workspace_id", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_agent_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
    sa.Enum("cron", "once", name="schedule_type").drop(op.get_bind())
