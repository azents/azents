"""add owner lifecycle jobs and user access disabled at

Revision ID: d0c984babbb1
Revises: 2a9ad984951f
Create Date: 2026-08-06 09:24:01.814601

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0c984babbb1"
down_revision: str | Sequence[str] | None = "2a9ad984951f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    owner_lifecycle_kind = postgresql.ENUM(
        "membership_archive",
        "account_purge",
        name="owner_lifecycle_kind",
        create_type=False,
    )
    owner_lifecycle_status = postgresql.ENUM(
        "pending",
        "retiring_sessions",
        "waiting_purge",
        "finalizing",
        "retry_wait",
        "completed",
        name="owner_lifecycle_status",
        create_type=False,
    )
    owner_lifecycle_kind.create(op.get_bind(), checkfirst=True)
    owner_lifecycle_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column("access_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "owner_lifecycle_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", owner_lifecycle_kind, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            owner_lifecycle_status,
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
        sa.CheckConstraint(
            "(kind = 'membership_archive' AND workspace_id IS NOT NULL) OR "
            "(kind = 'account_purge' AND workspace_id IS NULL)",
            name="ck_owner_lifecycle_jobs_kind_workspace",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_owner_lifecycle_jobs_membership_archive",
        "owner_lifecycle_jobs",
        ["workspace_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'membership_archive'"),
    )
    op.create_index(
        "uq_owner_lifecycle_jobs_account_purge",
        "owner_lifecycle_jobs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'account_purge'"),
    )
    op.create_index(
        "ix_owner_lifecycle_jobs_status_next_attempt_at",
        "owner_lifecycle_jobs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_owner_lifecycle_jobs_status_next_attempt_at",
        table_name="owner_lifecycle_jobs",
    )
    op.drop_index(
        "uq_owner_lifecycle_jobs_account_purge",
        table_name="owner_lifecycle_jobs",
        postgresql_where=sa.text("kind = 'account_purge'"),
    )
    op.drop_index(
        "uq_owner_lifecycle_jobs_membership_archive",
        table_name="owner_lifecycle_jobs",
        postgresql_where=sa.text("kind = 'membership_archive'"),
    )
    op.drop_table("owner_lifecycle_jobs")
    op.drop_column("users", "access_disabled_at")
    postgresql.ENUM(name="owner_lifecycle_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="owner_lifecycle_kind").drop(op.get_bind(), checkfirst=True)
