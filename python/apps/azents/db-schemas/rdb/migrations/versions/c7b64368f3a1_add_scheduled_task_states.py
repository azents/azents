"""add scheduled task states

Revision ID: c7b64368f3a1
Revises: 03710bae417a
Create Date: 2026-06-20 18:23:30.817663

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7b64368f3a1"
down_revision: str | Sequence[str] | None = "03710bae417a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    scheduled_task_status = postgresql.ENUM(
        "idle",
        "running",
        "succeeded",
        "failed",
        name="scheduled_task_status",
    )
    scheduled_task_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "scheduled_task_states",
        sa.Column("task_key", sa.String(length=120), nullable=False),
        sa.Column(
            "latest_status",
            postgresql.ENUM(name="scheduled_task_status", create_type=False),
            server_default="idle",
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_error_code", sa.String(length=120), nullable=True),
        sa.Column("latest_error_message", sa.Text(), nullable=True),
        sa.Column(
            "latest_result_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_requested_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("task_key"),
    )
    op.create_index(
        "ix_scheduled_task_states_next_run_at",
        "scheduled_task_states",
        ["next_run_at"],
    )
    op.create_index(
        "ix_scheduled_task_states_lease_until",
        "scheduled_task_states",
        ["lease_until"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_scheduled_task_states_lease_until",
        table_name="scheduled_task_states",
    )
    op.drop_index(
        "ix_scheduled_task_states_next_run_at",
        table_name="scheduled_task_states",
    )
    op.drop_table("scheduled_task_states")
    scheduled_task_status = postgresql.ENUM(name="scheduled_task_status")
    scheduled_task_status.drop(op.get_bind(), checkfirst=True)
