from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "23591a43ab9a"
down_revision: str | Sequence[str] | None = "6eccf341e890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

purge_participant_phase = postgresql.ENUM(
    "pending",
    "prepared",
    "cleanup_completed",
    "verified",
    name="archived_session_purge_participant_phase",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    purge_participant_phase.create(bind, checkfirst=True)

    op.add_column(
        "archived_session_purge_jobs",
        sa.Column("last_error_participant_key", sa.String(120), nullable=True),
    )
    op.add_column(
        "archived_session_purge_jobs",
        sa.Column("last_error_phase", purge_participant_phase, nullable=True),
    )
    op.create_table(
        "archived_session_purge_participant_executions",
        sa.Column("purge_job_id", sa.String(32), nullable=False),
        sa.Column("participant_key", sa.String(120), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "phase",
            purge_participant_phase,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_by_participant_key", sa.String(120), nullable=True),
        sa.Column("last_error_kind", sa.String(120), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column(
            "operational_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cleanup_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
            name=(
                "ck_archived_session_purge_participant_executions_"
                "attempt_count_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name=(
                "ck_archived_session_purge_participant_executions_"
                "policy_version_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["purge_job_id"],
            ["archived_session_purge_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("purge_job_id", "participant_key"),
    )
    op.create_index(
        "ix_archived_session_purge_participant_executions_purge_job_id_phase",
        "archived_session_purge_participant_executions",
        ["purge_job_id", "phase"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_archived_session_purge_participant_executions_purge_job_id_phase",
        table_name="archived_session_purge_participant_executions",
    )
    op.drop_table("archived_session_purge_participant_executions")
    op.drop_column("archived_session_purge_jobs", "last_error_phase")
    op.drop_column("archived_session_purge_jobs", "last_error_participant_key")
    purge_participant_phase.drop(op.get_bind(), checkfirst=True)
