"""Current model metadata source authority and exact per-model facts."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import LLMCatalogAttemptStatus
from azents.core.model_catalog_source import ModelMetadataSourceKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

source_kind_enum = ENUM(
    ModelMetadataSourceKind,
    name="model_metadata_source_kind",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
sync_status_enum = ENUM(
    LLMCatalogAttemptStatus,
    name="llm_catalog_attempt_status",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)


class RDBModelMetadataSource(RDBModel):
    """Stable current source owner, collection provenance and synchronization state."""

    __tablename__ = "model_metadata_sources"

    source_key: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    source_kind: Mapped[ModelMetadataSourceKind] = mapped_column(source_kind_enum)
    source_schema_version: Mapped[str] = mapped_column(sa.String(20))
    source_url: Mapped[str | None] = mapped_column(sa.Text, init=False, nullable=True)
    producer_name: Mapped[str | None] = mapped_column(
        sa.String(80), init=False, nullable=True
    )
    producer_version: Mapped[str | None] = mapped_column(
        sa.String(80), init=False, nullable=True
    )
    provider_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    model_count: Mapped[int] = mapped_column(sa.Integer, init=False, server_default="0")
    last_success_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True
    )
    sync_work_token: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True
    )
    sync_status: Mapped[LLMCatalogAttemptStatus | None] = mapped_column(
        sync_status_enum, init=False, nullable=True
    )
    sync_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True
    )
    sync_finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True
    )
    sync_failure_code: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True
    )
    sync_failure_message: Mapped[str | None] = mapped_column(
        sa.Text, init=False, nullable=True
    )
    sync_action_hint: Mapped[str | None] = mapped_column(
        sa.Text, init=False, nullable=True
    )
    sync_fetched_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    sync_matched_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    sync_skipped_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    sync_hidden_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    sync_diagnostics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, init=False, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class RDBModelMetadataSourceModel(RDBModel):
    """One current exact source identity; no raw or canonical dataset blob."""

    __tablename__ = "model_metadata_source_models"

    source_key: Mapped[str] = mapped_column(
        sa.String(120),
        sa.ForeignKey("model_metadata_sources.source_key", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    source_model_key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    model_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pricing: Mapped[dict[str, Any]] = mapped_column(JSONB)
    collected_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
