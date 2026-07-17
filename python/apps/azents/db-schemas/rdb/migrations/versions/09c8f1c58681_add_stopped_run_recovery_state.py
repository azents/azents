"""Add stopped run recovery state."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "09c8f1c58681"
down_revision: str | Sequence[str] | None = "a8ee43314ef5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add stopped recovery, retry provenance, and retry write type."""
    op.execute(
        "ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'stopped_run_retry'"
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "recovery_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("retry_source_run_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_retry_source_run_id_agent_runs",
        "agent_runs",
        "agent_runs",
        ["retry_source_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_runs_retry_source_run_id",
        "agent_runs",
        ["retry_source_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove stopped recovery and retry provenance columns."""
    op.drop_index("ix_agent_runs_retry_source_run_id", table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_retry_source_run_id_agent_runs",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "retry_source_run_id")
    op.drop_column("agent_runs", "recovery_state")
