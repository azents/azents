"""Current catalog identities, entries and synchronization contracts."""

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.model_pricing import ModelPricingDefinition


@dataclass(frozen=True)
class CatalogRetryPolicy:
    """Scheduling policy decoded from the current diagnostics."""

    automatic_retry_blocked: bool

    @classmethod
    def from_diagnostics(
        cls, diagnostics: Mapping[str, object] | None
    ) -> "CatalogRetryPolicy":
        """Block only on literal True."""
        return cls(
            automatic_retry_blocked=diagnostics is not None
            and diagnostics.get("automatic_retry_blocked") is True
        )


@dataclass(frozen=True)
class LLMCatalogSyncStatus:
    """One current operational state; work ownership is not a data identity."""

    owner_id: str
    work_token: str | None
    status: LLMCatalogAttemptStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    matched_count: int
    skipped_count: int
    hidden_count: int
    diagnostics: dict[str, Any] | None


@dataclass(frozen=True)
class LLMCatalog:
    """Stable owner and coherent current model/status metadata."""

    id: str
    scope: LLMCatalogScope
    provider: LLMProvider
    purpose: LLMCatalogPurpose
    provider_integration_id: str | None
    entry_count: int
    visible_count: int
    hidden_count: int
    last_success_at: datetime.datetime | None
    image_usable: bool | None
    diagnostics: dict[str, Any] | None
    sync_status: LLMCatalogSyncStatus | None


@dataclass(frozen=True)
class LLMCatalogEntryCreate:
    """Prepared current conversation model, including server-normalized pricing."""

    provider: LLMProvider
    provider_model_identifier: str
    display_name: str
    normalized_capabilities: dict[str, Any]
    supported_execution_options: list[str]
    lifecycle_status: LLMModelLifecycleStatus
    visibility_status: LLMCatalogEntryVisibility
    provider_integration_id: str | None
    publisher: str | None
    family: str | None
    source_metadata: dict[str, Any] | None
    projection_metadata: dict[str, Any] | None
    hidden_reason: str | None
    pricing: ModelPricingDefinition


@dataclass(frozen=True)
class LLMCatalogEntry(LLMCatalogEntryCreate):
    """Detached current row; row creation is independent of latest refresh time."""

    id: str
    catalog_id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class ImageGenerationCatalogEntryCreate:
    """Prepared exact reviewed image model."""

    provider: LLMProvider
    provider_model_identifier: str
    display_name: str
    description: str
    recommendation_rank: int | None
    lifecycle_status: LLMModelLifecycleStatus
    visibility_status: LLMCatalogEntryVisibility
    provider_integration_id: str
    source_metadata: dict[str, Any] | None
    projection_metadata: dict[str, Any] | None
    hidden_reason: str | None


@dataclass(frozen=True)
class ImageGenerationCatalogEntry(ImageGenerationCatalogEntryCreate):
    """Detached current image row."""

    id: str
    catalog_id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class LLMCatalogEntryList:
    """Current selectable conversation page with coherent owner state."""

    catalog: LLMCatalog
    entries: list[LLMCatalogEntry]
    total: int


@dataclass(frozen=True)
class ImageGenerationCatalogEntryList:
    """Current selectable image entries with existing purpose-specific usability."""

    catalog: LLMCatalog
    entries: list[ImageGenerationCatalogEntry]
    total: int


@dataclass(frozen=True)
class LLMCatalogCounts:
    """Current owner count summary."""

    visible_count: int
    hidden_count: int


@dataclass(frozen=True)
class CatalogNotFound:
    """Catalog does not exist or is outside workspace scope."""

    integration_id: str


@dataclass(frozen=True)
class CatalogSyncAlreadyRunning:
    """An unexpired catalog refresh currently owns publication."""

    catalog_id: str
    work_token: str


@dataclass(frozen=True)
class IntegrationCatalogSyncClaim:
    """Transient work ownership and captured existing credential authority."""

    work_token: str
    catalog_configuration_version: int


@dataclass(frozen=True)
class ImageGenerationCatalogPublication:
    """Image publication outcome, without a model-data generation."""

    published: bool
    superseding_work_token: str | None
    current_configuration_version: int
    last_success_at: datetime.datetime | None
