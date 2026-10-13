"""Add independent compacted-event retention and backfill displacement age."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042a6603f202"
down_revision: str | Sequence[str] | None = "d4bf6286235d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "system_file_lifecycle_settings",
        sa.Column("compacted_event_retention_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_system_file_lifecycle_settings_compacted_event_days",
        "system_file_lifecycle_settings",
        "compacted_event_retention_days IS NULL OR compacted_event_retention_days >= 0",
    )
    op.add_column(
        "events",
        sa.Column("compacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        WITH spans AS (
            SELECT e.session_id, e.id AS end_id, e.created_at,
                   lag(e.id) OVER (PARTITION BY e.session_id ORDER BY e.id) AS start_id
            FROM events e
            JOIN agent_sessions s ON s.id = e.session_id
            WHERE e.kind = 'compaction_summary'
              AND e.id <= s.model_input_head_event_id
        )
        UPDATE events e
        SET compacted_at = spans.created_at
        FROM spans
        WHERE e.session_id = spans.session_id
          AND e.id < spans.end_id
          AND (spans.start_id IS NULL OR e.id >= spans.start_id)
          AND e.compacted_at IS NULL
        """
    )
    op.create_index(
        "ix_events_compacted_at",
        "events",
        ["compacted_at", "id"],
        postgresql_where=sa.text("compacted_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_events_compacted_at", table_name="events")
    op.drop_column("events", "compacted_at")
    op.drop_constraint(
        "ck_system_file_lifecycle_settings_compacted_event_days",
        "system_file_lifecycle_settings",
        type_="check",
    )
    op.drop_column("system_file_lifecycle_settings", "compacted_event_retention_days")
