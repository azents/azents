"""add agent avatar cleanup jobs

Revision ID: 30c55c0ef241
Revises: 7686aeee9531
Create Date: 2026-08-18 10:46:23.247743

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "30c55c0ef241"
down_revision: str | Sequence[str] | None = "7686aeee9531"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_avatar_cleanup_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("avatar", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("lease_token", sa.String(length=120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_kind", sa.String(length=120), nullable=True),
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
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_agent_avatar_cleanup_jobs_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_avatar_cleanup_jobs_agent_id",
        "agent_avatar_cleanup_jobs",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_avatar_cleanup_jobs_next_attempt_lease_until",
        "agent_avatar_cleanup_jobs",
        ["next_attempt_at", "lease_until"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_avatar_cleanup_jobs_next_attempt_lease_until",
        table_name="agent_avatar_cleanup_jobs",
    )
    op.drop_index(
        "ix_agent_avatar_cleanup_jobs_agent_id",
        table_name="agent_avatar_cleanup_jobs",
    )
    op.drop_table("agent_avatar_cleanup_jobs")
