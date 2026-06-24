"""drop scheduled tasks

Revision ID: 9b9479c34ec7
Revises: 3758f4f8112a
Create Date: 2026-05-29 07:14:44.705944

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9b9479c34ec7"
down_revision: str | Sequence[str] | None = "3758f4f8112a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_scheduled_tasks_workspace_id", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_agent_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "schedule_type",
            postgresql.ENUM("cron", "once", name="schedule_type", create_type=False),
            nullable=False,
        ),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interface_type", sa.String(length=20), nullable=True),
        sa.Column(
            "interface_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
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
