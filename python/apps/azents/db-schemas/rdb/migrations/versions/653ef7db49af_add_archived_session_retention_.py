"""add archived session retention foundation

Revision ID: 653ef7db49af
Revises: f81c4d3b1f17
Create Date: 2026-07-19 12:47:56.695254

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "653ef7db49af"
down_revision: str | Sequence[str] | None = "f81c4d3b1f17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

application_status = postgresql.ENUM(
    "pending",
    "running",
    "retry_wait",
    "completed",
    name="archived_session_retention_application_status",
    create_type=False,
)
purge_status = postgresql.ENUM(
    "pending",
    "fencing",
    "cleaning",
    "retry_wait",
    "completed",
    "cancelled",
    name="archived_session_purge_status",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    application_status.create(bind, checkfirst=True)
    purge_status.create(bind, checkfirst=True)

    op.create_table(
        "system_file_lifecycle_settings",
        sa.Column("id", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column(
            "archived_session_retention_days",
            sa.Integer(),
            server_default="30",
            nullable=True,
        ),
        sa.Column("updated_by_user_id", sa.String(32), nullable=True),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
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
            "archived_session_retention_days IS NULL "
            "OR archived_session_retention_days >= 0",
            name="ck_system_file_lifecycle_settings_retention_days",
        ),
        sa.CheckConstraint(
            "id = 1",
            name="ck_system_file_lifecycle_settings_singleton_id",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO system_file_lifecycle_settings "
        "(id, archived_session_retention_days, revision) VALUES (1, 30, 1)"
    )

    op.add_column(
        "agent_sessions",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("archive_policy_revision", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "archive_retention_days_snapshot",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_sessions_archived_purge_after",
        "agent_sessions",
        ["purge_after"],
        unique=False,
        postgresql_where=sa.text(
            "status = 'archived' AND session_kind = 'root' AND purge_after IS NOT NULL"
        ),
    )

    op.create_table(
        "archived_session_retention_applications",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("target_revision", sa.BigInteger(), nullable=False),
        sa.Column("target_retention_days", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.String(32), nullable=True),
        sa.Column(
            "status",
            application_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("cursor_session_id", sa.String(32), nullable=True),
        sa.Column("affected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "immediately_eligible_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("cancelled_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(120), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "target_retention_days IS NULL OR target_retention_days >= 0",
            name="ck_archived_session_retention_applications_target_days",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_archived_session_retention_applications_lease_until",
        "archived_session_retention_applications",
        ["lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_archived_session_retention_applications_status_created_at",
        "archived_session_retention_applications",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_archived_session_retention_applications_active",
        "archived_session_retention_applications",
        [sa.literal_column("(1)")],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'retry_wait')"),
    )

    op.create_table(
        "archived_session_purge_jobs",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("root_session_id", sa.String(32), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("status", purge_status, server_default="pending", nullable=False),
        sa.Column("fencing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(120), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("model_file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("artifact_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "exchange_file_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("worktree_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "root_session_id",
            name="uq_archived_session_purge_jobs_root_session_id",
        ),
    )
    op.create_index(
        "ix_archived_session_purge_jobs_lease_until",
        "archived_session_purge_jobs",
        ["lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_archived_session_purge_jobs_status_eligible_at",
        "archived_session_purge_jobs",
        ["status", "eligible_at"],
        unique=False,
    )

    op.execute(
        """
        UPDATE agent_sessions
        SET archived_at = COALESCE(ended_at, updated_at, created_at),
            purge_after = now() + interval '30 days',
            archive_policy_revision = 1,
            archive_retention_days_snapshot = 30
        WHERE status = 'archived' AND session_kind = 'root'
        """
    )
    op.execute(
        """
        INSERT INTO archived_session_purge_jobs (
            id,
            root_session_id,
            eligible_at,
            policy_revision
        )
        SELECT replace(gen_random_uuid()::text, '-', ''), id, purge_after, 1
        FROM agent_sessions
        WHERE status = 'archived'
          AND session_kind = 'root'
          AND purge_after IS NOT NULL
        ON CONFLICT (root_session_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_archived_session_purge_jobs_status_eligible_at",
        table_name="archived_session_purge_jobs",
    )
    op.drop_index(
        "ix_archived_session_purge_jobs_lease_until",
        table_name="archived_session_purge_jobs",
    )
    op.drop_table("archived_session_purge_jobs")
    op.drop_index(
        "uq_archived_session_retention_applications_active",
        table_name="archived_session_retention_applications",
    )
    op.drop_index(
        "ix_archived_session_retention_applications_status_created_at",
        table_name="archived_session_retention_applications",
    )
    op.drop_index(
        "ix_archived_session_retention_applications_lease_until",
        table_name="archived_session_retention_applications",
    )
    op.drop_table("archived_session_retention_applications")
    op.drop_index(
        "ix_agent_sessions_archived_purge_after",
        table_name="agent_sessions",
    )
    op.drop_column("agent_sessions", "archive_retention_days_snapshot")
    op.drop_column("agent_sessions", "archive_policy_revision")
    op.drop_column("agent_sessions", "purge_after")
    op.drop_column("agent_sessions", "archived_at")
    op.drop_table("system_file_lifecycle_settings")
    purge_status.drop(op.get_bind(), checkfirst=True)
    application_status.drop(op.get_bind(), checkfirst=True)
