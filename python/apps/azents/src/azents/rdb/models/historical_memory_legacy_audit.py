"""Migration-only historical scalars, without legacy body or execution ownership."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.historical_memory_execution as _  # noqa: F401
from azents.core.historical_memory_legacy_audit import (
    MemoryLegacyCostMethod,
    MemoryLegacyRecordedOutcome,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

recorded_outcome_enum = ENUM(
    MemoryLegacyRecordedOutcome, name="consolidation_attempt_state", create_type=False
)
cost_method_enum = ENUM(
    MemoryLegacyCostMethod,
    name="memory_legacy_cost_method",
    create_type=False,
    values_callable=lambda enumeration: [member.value for member in enumeration],
)


class RDBMemoryLegacyJob(RDBModel):
    """Prior job identity and factual recorded outcome; never a current Session."""

    __tablename__ = "memory_legacy_jobs"
    IX_UNIT = sa.Index("ix_memory_legacy_jobs_unit_id", "unit_id")
    CK_COUNTS = sa.CheckConstraint(
        "model_requests >= 0 AND tool_calls >= 0 AND input_tokens >= 0 "
        "AND output_tokens >= 0 AND (rendered_bytes IS NULL "
        "OR rendered_bytes BETWEEN 0 AND 10000)",
        name="ck_memory_legacy_jobs_counts",
    )
    CK_PUBLICATION = sa.CheckConstraint(
        "(result_published_at IS NULL AND rendered_bytes IS NULL) OR "
        "(result_published_at IS NOT NULL AND rendered_bytes IS NOT NULL)",
        name="ck_memory_legacy_jobs_publication",
    )
    legacy_job_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("memory_units.id", ondelete="CASCADE")
    )
    recorded_outcome: Mapped[MemoryLegacyRecordedOutcome] = mapped_column(
        recorded_outcome_enum
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    deadline_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    model_requests: Mapped[int] = mapped_column(sa.Integer)
    tool_calls: Mapped[int] = mapped_column(sa.Integer)
    input_tokens: Mapped[int] = mapped_column(sa.BigInteger)
    output_tokens: Mapped[int] = mapped_column(sa.BigInteger)
    result_published_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    rendered_bytes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    __table_args__ = (IX_UNIT, CK_COUNTS, CK_PUBLICATION)


class RDBMemoryLegacyModelUsage(RDBModel):
    """Per-dispatch normalized usage, reservations and cost provenance only."""

    __tablename__ = "memory_legacy_model_usage"
    UQ_REQUEST = sa.UniqueConstraint(
        "legacy_job_id", "request_number", name="uq_memory_legacy_usage_request"
    )
    CK_RESERVATION = sa.CheckConstraint(
        "request_number >= 1 AND reserved_input_tokens >= 0 AND "
        "(reserved_output_tokens IS NULL OR reserved_output_tokens >= 1)",
        name="ck_memory_legacy_usage_reservation",
    )
    CK_USAGE = sa.CheckConstraint(
        "(prompt_tokens IS NULL OR prompt_tokens >= 0) AND "
        "(completion_tokens IS NULL OR completion_tokens >= 0) AND "
        "(total_tokens IS NULL OR total_tokens >= 0) AND "
        "(cached_tokens IS NULL OR cached_tokens >= 0) AND "
        "(cache_creation_tokens IS NULL OR cache_creation_tokens >= 0) AND "
        "(reasoning_tokens IS NULL OR reasoning_tokens >= 0) AND "
        "(cost_usd IS NULL OR cost_usd >= 0)",
        name="ck_memory_legacy_usage_scalars",
    )
    legacy_job_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("memory_legacy_jobs.legacy_job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    legacy_dispatch_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    request_number: Mapped[int] = mapped_column(sa.Integer)
    reserved_input_tokens: Mapped[int] = mapped_column(sa.BigInteger)
    reserved_output_tokens: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    usage_recorded: Mapped[bool] = mapped_column(sa.Boolean)
    prompt_tokens: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    reasoning_tokens: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    cost_method: Mapped[MemoryLegacyCostMethod | None] = mapped_column(
        cost_method_enum, nullable=True
    )
    cost_source_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    cost_collected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    cost_source_model_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    cost_estimator_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    __table_args__ = (UQ_REQUEST, CK_RESERVATION, CK_USAGE)
