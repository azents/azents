"""Stable catalog owners, current entries and one current synchronization state."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

llm_catalog_scope_enum = ENUM(
    LLMCatalogScope,
    name="llm_catalog_scope",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
llm_catalog_purpose_enum = ENUM(
    LLMCatalogPurpose,
    name="llm_catalog_purpose",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
llm_catalog_sync_status_enum = ENUM(
    LLMCatalogAttemptStatus,
    name="llm_catalog_attempt_status",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
llm_catalog_entry_visibility_enum = ENUM(
    LLMCatalogEntryVisibility,
    name="llm_catalog_entry_visibility",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
llm_provider_enum = ENUM(
    LLMProvider,
    name="llm_provider",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
llm_model_lifecycle_status_enum = ENUM(
    LLMModelLifecycleStatus,
    name="llm_model_lifecycle_status",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)


class RDBLLMCatalog(RDBModel):
    """Current catalog identity, success metadata and purpose-specific authority."""

    __tablename__ = "llm_catalogs"

    UQ_SYSTEM_CATALOG = sa.Index(
        "ix_llm_catalogs_provider_purpose",
        "provider",
        "purpose",
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    UQ_INTEGRATION_CATALOG = sa.Index(
        "ix_llm_catalogs_provider_integration_id_purpose",
        "provider_integration_id",
        "purpose",
        unique=True,
        postgresql_where=sa.text("scope = 'integration'"),
    )
    IX_PROVIDER_INTEGRATION_ID = sa.Index(
        "ix_llm_catalogs_provider_integration_id", "provider_integration_id"
    )
    CK_IMAGE_USABILITY_PURPOSE = sa.CheckConstraint(
        "(purpose = 'image_generation' AND image_usable IS NOT NULL) "
        "OR (purpose = 'conversation' AND image_usable IS NULL)",
        name="ck_llm_catalogs_image_usability_purpose",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    scope: Mapped[LLMCatalogScope] = mapped_column(llm_catalog_scope_enum)
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum)
    purpose: Mapped[LLMCatalogPurpose] = mapped_column(llm_catalog_purpose_enum)
    provider_integration_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_provider_integrations.id", ondelete="CASCADE"),
        nullable=True,
    )
    image_usable: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    entry_count: Mapped[int] = mapped_column(sa.Integer, init=False, server_default="0")
    visible_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    hidden_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, server_default="0"
    )
    last_success_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True
    )
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, init=False, nullable=True
    )
    sync_work_token: Mapped[str | None] = mapped_column(
        sa.String(32), init=False, nullable=True
    )
    sync_status: Mapped[LLMCatalogAttemptStatus | None] = mapped_column(
        llm_catalog_sync_status_enum, init=False, nullable=True
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

    __table_args__ = (
        UQ_SYSTEM_CATALOG,
        UQ_INTEGRATION_CATALOG,
        IX_PROVIDER_INTEGRATION_ID,
        CK_IMAGE_USABILITY_PURPOSE,
    )


class RDBLLMCatalogEntry(RDBModel):
    """One current exact conversation model with compact normalized pricing."""

    __tablename__ = "llm_catalog_entries"

    UQ_CATALOG_MODEL = sa.UniqueConstraint(
        "catalog_id",
        "provider_model_identifier",
        name="uq_llm_catalog_entries_catalog_model",
    )
    IX_CATALOG_DISPLAY = sa.Index(
        "ix_llm_catalog_entries_catalog_id_display_name", "catalog_id", "display_name"
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE")
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum)
    provider_model_identifier: Mapped[str] = mapped_column(sa.String(300))
    display_name: Mapped[str] = mapped_column(sa.String(300))
    normalized_capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB)
    supported_execution_options: Mapped[list[str]] = mapped_column(JSONB)
    lifecycle_status: Mapped[LLMModelLifecycleStatus] = mapped_column(
        llm_model_lifecycle_status_enum
    )
    visibility_status: Mapped[LLMCatalogEntryVisibility] = mapped_column(
        llm_catalog_entry_visibility_enum
    )
    provider_integration_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    publisher: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    family: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    projection_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    hidden_reason: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    pricing: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (UQ_CATALOG_MODEL, IX_CATALOG_DISPLAY)


class RDBImageGenerationCatalogEntry(RDBModel):
    """One current reviewed image model under its stable catalog owner."""

    __tablename__ = "image_generation_catalog_entries"

    UQ_CATALOG_MODEL = sa.UniqueConstraint(
        "catalog_id",
        "provider_model_identifier",
        name="uq_image_generation_catalog_entries_catalog_model",
    )
    IX_CATALOG_RANK = sa.Index(
        "ix_image_generation_catalog_entries_catalog_rank",
        "catalog_id",
        "recommendation_rank",
        "display_name",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("llm_catalogs.id", ondelete="CASCADE")
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum)
    provider_model_identifier: Mapped[str] = mapped_column(sa.String(300))
    display_name: Mapped[str] = mapped_column(sa.String(300))
    description: Mapped[str] = mapped_column(sa.Text)
    recommendation_rank: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    lifecycle_status: Mapped[LLMModelLifecycleStatus] = mapped_column(
        llm_model_lifecycle_status_enum
    )
    visibility_status: Mapped[LLMCatalogEntryVisibility] = mapped_column(
        llm_catalog_entry_visibility_enum
    )
    provider_integration_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("llm_provider_integrations.id", ondelete="CASCADE")
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    projection_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    hidden_reason: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (UQ_CATALOG_MODEL, IX_CATALOG_RANK)
