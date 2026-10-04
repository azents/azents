"""Historical Memory source and preparation state model."""

import datetime

import sqlalchemy as sa
from azcommon.types import JSONValue
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent_session as _  # noqa: F401  # Register FK metadata.
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBHistoricalMemorySource(RDBModel):
    """Latest Historical Memory result and minimal progress for one root Session."""

    __tablename__ = "historical_memory_sources"

    CK_COMPLETED_RESULT = sa.CheckConstraint(
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
    )
    CK_FAILURE_COUNT = sa.CheckConstraint(
        "failure_count >= 0",
        name="ck_historical_memory_sources_failure_count",
    )
    CK_EVIDENCE_GENERATIONS = sa.CheckConstraint(
        "summary_generation >= 0 AND availability_generation >= 1",
        name="ck_historical_memory_sources_evidence_generations",
    )
    CK_EVIDENCE_HASH = sa.CheckConstraint(
        "evidence_hash IS NULL OR evidence_hash ~ '^[0-9a-f]{64}$'",
        name="ck_historical_memory_sources_evidence_hash",
    )
    IX_NEXT_RETRY_AT = sa.Index(
        "ix_historical_memory_sources_next_retry_at",
        "next_retry_at",
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    IX_PREPARED_AT = sa.Index(
        "ix_historical_memory_sources_prepared_at",
        "prepared_at",
        postgresql_where=sa.text("prepared_at IS NOT NULL"),
    )
    IX_ADMITTED_UNPREPARED = sa.Index(
        "ix_historical_memory_sources_admitted_at",
        "admitted_at",
        postgresql_where=sa.text("prepared_at IS NULL"),
    )

    source_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    admitted_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    last_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    next_retry_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    failure_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    last_failure_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    model_operation_state: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB,
        init=False,
        nullable=True,
        default=None,
    )
    completed_source_activity_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    completed_source_tail_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
        nullable=True,
        default=None,
    )
    prepared_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    source_title_snapshot: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    summary: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    summary_generation: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="0"
    )
    evidence_hash: Mapped[str | None] = mapped_column(
        sa.String(64), init=False, nullable=True, default=None
    )
    availability_generation: Mapped[int] = mapped_column(
        sa.BigInteger, init=False, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_COMPLETED_RESULT,
        CK_FAILURE_COUNT,
        CK_EVIDENCE_GENERATIONS,
        CK_EVIDENCE_HASH,
        IX_NEXT_RETRY_AT,
        IX_PREPARED_AT,
        IX_ADMITTED_UNPREPARED,
    )
