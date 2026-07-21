"""add agent decommission

Revision ID: 9d73ed4d3a13
Revises: 36d3c4f9deef
Create Date: 2026-07-21 17:54:10.737286

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d73ed4d3a13"
down_revision: str | Sequence[str] | None = "36d3c4f9deef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    agent_lifecycle_status = sa.Enum(
        "active",
        "decommissioning",
        name="agent_lifecycle_status",
    )
    agent_decommission_status = sa.Enum(
        "pending",
        "retiring_sessions",
        "waiting_retention",
        "finalizing",
        "retry_wait",
        "completed",
        name="agent_decommission_status",
    )
    agent_lifecycle_status.create(op.get_bind(), checkfirst=True)
    agent_decommission_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agents",
        sa.Column(
            "lifecycle_status",
            agent_lifecycle_status,
            nullable=False,
            server_default="active",
        ),
    )
    op.create_table(
        "agent_decommission_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            agent_decommission_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=120), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_decommission_jobs_agent_id"),
    )
    op.create_index(
        "ix_agent_decommission_jobs_status_next_attempt_at",
        "agent_decommission_jobs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_decommission_jobs_status_next_attempt_at",
        table_name="agent_decommission_jobs",
    )
    op.drop_table("agent_decommission_jobs")
    op.drop_column("agents", "lifecycle_status")
    sa.Enum(name="agent_decommission_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="agent_lifecycle_status").drop(op.get_bind(), checkfirst=True)
