"""Remove stopped run recovery state."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d54f4767b88e"
down_revision: str | Sequence[str] | None = "e63aa6b8545b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove stopped recovery, retry provenance, and retry write type."""
    op.execute(
        "DELETE FROM chat_write_requests "
        "WHERE write_type = 'stopped_run_retry' "
        "OR accepted_type = 'stopped_run_retry'"
    )
    op.execute(
        "ALTER TYPE chat_write_request_type RENAME TO chat_write_request_type_old"
    )
    op.execute(
        "CREATE TYPE chat_write_request_type AS ENUM "
        "('edit_message', 'command', 'failed_run_retry')"
    )
    op.execute(
        "ALTER TABLE chat_write_requests "
        "ALTER COLUMN write_type TYPE chat_write_request_type "
        "USING write_type::text::chat_write_request_type"
    )
    op.execute(
        "ALTER TABLE chat_write_requests "
        "ALTER COLUMN accepted_type TYPE chat_write_request_type "
        "USING accepted_type::text::chat_write_request_type"
    )
    op.execute("DROP TYPE chat_write_request_type_old")

    op.drop_index("ix_agent_runs_retry_source_run_id", table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_retry_source_run_id_agent_runs",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "retry_source_run_id")
    op.drop_column("agent_runs", "recovery_state")


def downgrade() -> None:
    """Restore stopped recovery, retry provenance, and retry write type."""
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
