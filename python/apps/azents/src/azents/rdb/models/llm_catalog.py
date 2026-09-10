"""LLM catalog projection models."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [v.value for v in enum_cls]


llm_catalog_scope_enum = ENUM(
    LLMCatalogScope,
    name="llm_catalog_scope",
    create_type=False,
    values_callable=_enum_values,
)
llm_catalog_purpose_enum = ENUM(
    LLMCatalogPurpose,
    name="llm_catalog_purpose",
    create_type=False,
    values_callable=_enum_values,
)
llm_catalog_lowerer_target_enum = ENUM(
    LLMCatalogLowererTarget,
    name="llm_catalog_lowerer_target",
    create_type=False,
    values_callable=_enum_values,
)
llm_catalog_attempt_status_enum = ENUM(
    LLMCatalogAttemptStatus,
    name="llm_catalog_attempt_status",
    create_type=False,
    values_callable=_enum_values,
)
llm_catalog_entry_visibility_enum = ENUM(
    LLMCatalogEntryVisibility,
    name="llm_catalog_entry_visibility",
    create_type=False,
    values_callable=_enum_values,
)
llm_provider_enum = ENUM(
    LLMProvider,
    name="llm_provider",
    create_type=False,
    values_callable=_enum_values,
)
llm_model_lifecycle_status_enum = ENUM(
    LLMModelLifecycleStatus,
    name="llm_model_lifecycle_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBLLMCatalog(RDBModel):
    """Logical current catalog identity."""

    __tablename__ = "llm_catalogs"

    UQ_SYSTEM_CATALOG = sa.Index(
        "uq_llm_catalogs_system_scope_provider_target_purpose",
        "provider",
        "lowerer_target",
        "purpose",
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    UQ_INTEGRATION_CATALOG = sa.Index(
        "uq_llm_catalogs_integration_target_purpose",
        "provider_integration_id",
        "lowerer_target",
        "purpose",
        unique=True,
        postgresql_where=sa.text("scope = 'integration'"),
    )
    IX_PROVIDER_INTEGRATION_ID = sa.Index(
        "ix_llm_catalogs_provider_integration_id", "provider_integration_id"
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    scope: Mapped[LLMCatalogScope] = mapped_column(
        llm_catalog_scope_enum,
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum, nullable=False)
    purpose: Mapped[LLMCatalogPurpose] = mapped_column(
        llm_catalog_purpose_enum,
        nullable=False,
    )
    lowerer_target: Mapped[LLMCatalogLowererTarget] = mapped_column(
        llm_catalog_lowerer_target_enum,
        nullable=False,
    )
    provider_integration_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_provider_integrations.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    current_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, default=None
    )
    latest_attempt_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, default=None
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

    __table_args__ = (
        UQ_SYSTEM_CATALOG,
        UQ_INTEGRATION_CATALOG,
        IX_PROVIDER_INTEGRATION_ID,
    )


class RDBLiteLLMSourceSnapshot(RDBModel):
    """Current LiteLLM source payload snapshot."""

    __tablename__ = "litellm_source_snapshots"

    UQ_SOURCE_HASH = sa.UniqueConstraint(
        "source_hash", name="uq_litellm_source_snapshots_source_hash"
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    source_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    loaded_source: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    litellm_version: Mapped[str | None] = mapped_column(
        sa.String(80), nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )

    __table_args__ = (UQ_SOURCE_HASH,)


class RDBLLMCatalogSnapshot(RDBModel):
    """Current successful catalog projection snapshot."""

    __tablename__ = "llm_catalog_snapshots"

    IX_CATALOG_ID = sa.Index("ix_llm_catalog_snapshots_catalog_id", "catalog_id")

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    visible_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hidden_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("litellm_source_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    catalog_configuration_version: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )

    __table_args__ = (IX_CATALOG_ID,)


class RDBLLMCatalogEntry(RDBModel):
    """Projected model catalog entry."""

    __tablename__ = "llm_catalog_entries"

    IX_CATALOG_DISPLAY = sa.Index(
        "ix_llm_catalog_entries_catalog_display", "catalog_id", "display_name"
    )
    IX_CATALOG_MODEL = sa.Index(
        "ix_llm_catalog_entries_catalog_model",
        "catalog_id",
        "provider_model_identifier",
    )
    IX_SNAPSHOT_ID = sa.Index("ix_llm_catalog_entries_snapshot_id", "snapshot_id")

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalog_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum, nullable=False)
    provider_model_identifier: Mapped[str] = mapped_column(
        sa.String(300), nullable=False
    )
    lowerer_target: Mapped[LLMCatalogLowererTarget] = mapped_column(
        llm_catalog_lowerer_target_enum, nullable=False
    )
    runtime_model_identifier: Mapped[str] = mapped_column(
        sa.String(300), nullable=False
    )
    display_name: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    normalized_capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    supported_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    lifecycle_status: Mapped[LLMModelLifecycleStatus] = mapped_column(
        llm_model_lifecycle_status_enum, nullable=False
    )
    visibility_status: Mapped[LLMCatalogEntryVisibility] = mapped_column(
        llm_catalog_entry_visibility_enum, nullable=False
    )
    provider_integration_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, default=None
    )
    publisher: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
    )
    family: Mapped[str | None] = mapped_column(
        sa.String(160), nullable=True, default=None
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    projection_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    hidden_reason: Mapped[str | None] = mapped_column(
        sa.String(160), nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )

    __table_args__ = (IX_CATALOG_DISPLAY, IX_CATALOG_MODEL, IX_SNAPSHOT_ID)


class RDBImageGenerationCatalogEntry(RDBModel):
    """Projected image-generation model catalog entry."""

    __tablename__ = "image_generation_catalog_entries"

    UQ_SNAPSHOT_MODEL = sa.UniqueConstraint(
        "snapshot_id",
        "provider_model_identifier",
        name="uq_image_generation_catalog_entries_snapshot_model",
    )
    IX_CATALOG_RANK = sa.Index(
        "ix_image_generation_catalog_entries_catalog_rank",
        "catalog_id",
        "recommendation_rank",
        "display_name",
    )
    IX_SNAPSHOT_ID = sa.Index(
        "ix_image_generation_catalog_entries_snapshot_id",
        "snapshot_id",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalog_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum, nullable=False)
    provider_model_identifier: Mapped[str] = mapped_column(
        sa.String(300),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    recommendation_rank: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    lifecycle_status: Mapped[LLMModelLifecycleStatus] = mapped_column(
        llm_model_lifecycle_status_enum,
        nullable=False,
    )
    visibility_status: Mapped[LLMCatalogEntryVisibility] = mapped_column(
        llm_catalog_entry_visibility_enum,
        nullable=False,
    )
    provider_integration_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_provider_integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    projection_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    hidden_reason: Mapped[str | None] = mapped_column(
        sa.String(160),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (UQ_SNAPSHOT_MODEL, IX_CATALOG_RANK, IX_SNAPSHOT_ID)


class RDBLLMCatalogSyncAttempt(RDBModel):
    """Latest catalog source/projection attempt state."""

    __tablename__ = "llm_catalog_sync_attempts"

    IX_CATALOG_ID = sa.Index("ix_llm_catalog_sync_attempts_catalog_id", "catalog_id")

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    status: Mapped[LLMCatalogAttemptStatus] = mapped_column(
        llm_catalog_attempt_status_enum, nullable=False
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    fetched_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    matched_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hidden_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    catalog_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )
    produced_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, default=None
    )
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
    )
    failure_message: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    action_hint: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    catalog_configuration_version: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )

    __table_args__ = (IX_CATALOG_ID,)
