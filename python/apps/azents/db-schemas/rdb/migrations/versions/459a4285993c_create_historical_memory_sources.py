"""create historical memory sources

Revision ID: 459a4285993c
Revises: cda14157c46c
Create Date: 2026-10-01 12:18:39.998384

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "459a4285993c"
down_revision: str | Sequence[str] | None = "cda14157c46c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "historical_memory_sources",
        sa.Column("source_session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "admitted_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_attempt_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "next_retry_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_failure_code", sa.String(length=120), nullable=True),
        sa.Column(
            "model_operation_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "completed_source_activity_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_source_tail_event_id", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "prepared_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("source_title_snapshot", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "("
            "prepared_at IS NULL "
            "AND completed_source_activity_at IS NULL "
            "AND completed_source_tail_event_id IS NULL"
            ") OR ("
            "prepared_at IS NOT NULL "
            "AND completed_source_activity_at IS NOT NULL "
            "AND completed_source_tail_event_id IS NOT NULL"
            ")",
            name="ck_historical_memory_sources_completed_result",
        ),
        sa.CheckConstraint(
            "failure_count >= 0", name="ck_historical_memory_sources_failure_count"
        ),
        sa.ForeignKeyConstraint(
            ["source_session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("source_session_id"),
    )
    op.create_index(
        "ix_historical_memory_sources_admitted_unprepared",
        "historical_memory_sources",
        ["admitted_at"],
        unique=False,
        postgresql_where=sa.text("prepared_at IS NULL"),
    )
    op.create_index(
        "ix_historical_memory_sources_next_retry_at",
        "historical_memory_sources",
        ["next_retry_at"],
        unique=False,
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    op.create_index(
        "ix_historical_memory_sources_prepared_at",
        "historical_memory_sources",
        ["prepared_at"],
        unique=False,
        postgresql_where=sa.text("prepared_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_historical_memory_sources_prepared_at",
        table_name="historical_memory_sources",
        postgresql_where=sa.text("prepared_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_historical_memory_sources_next_retry_at",
        table_name="historical_memory_sources",
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_historical_memory_sources_admitted_unprepared",
        table_name="historical_memory_sources",
        postgresql_where=sa.text("prepared_at IS NULL"),
    )
    op.drop_table("historical_memory_sources")
