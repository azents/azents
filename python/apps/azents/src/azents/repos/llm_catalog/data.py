"""LLM catalog repository data models."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelLifecycleStatus,
    LLMProvider,
)


@dataclass(frozen=True)
class LLMCatalog:
    """Stored LLM catalog identity."""

    id: str
    scope: LLMCatalogScope
    provider: LLMProvider
    purpose: LLMCatalogPurpose
    provider_integration_id: str | None
    lowerer_target: LLMCatalogLowererTarget
    current_snapshot_id: str | None
    latest_attempt_id: str | None


@dataclass(frozen=True)
class LLMCatalogEntry:
    """Stored projected catalog entry."""

    id: str
    catalog_id: str
    snapshot_id: str
    provider: LLMProvider
    provider_model_identifier: str
    lowerer_target: LLMCatalogLowererTarget
    runtime_model_identifier: str
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
    created_at: datetime.datetime


@dataclass(frozen=True)
class LLMCatalogEntryCreate:
    """Catalog entry values to materialize."""

    provider: LLMProvider
    provider_model_identifier: str
    lowerer_target: LLMCatalogLowererTarget
    runtime_model_identifier: str
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


@dataclass(frozen=True)
class ImageGenerationCatalogEntry:
    """Stored projected image-generation catalog entry."""

    id: str
    catalog_id: str
    snapshot_id: str
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
    created_at: datetime.datetime


@dataclass(frozen=True)
class ImageGenerationCatalogEntryCreate:
    """Image catalog entry values to materialize."""

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
class LLMCatalogEntryList:
    """Catalog entry list page."""

    catalog: LLMCatalog
    entries: list[LLMCatalogEntry]
    total: int
    current_snapshot_created_at: datetime.datetime | None
    latest_attempt: "LLMCatalogSyncAttempt | None"


@dataclass(frozen=True)
class ImageGenerationCatalogEntryList:
    """Complete current image-generation catalog entry list."""

    catalog: LLMCatalog
    entries: list[ImageGenerationCatalogEntry]
    total: int
    current_snapshot_created_at: datetime.datetime | None
    snapshot_catalog_configuration_version: int | None
    current_integration_catalog_configuration_version: int
    latest_attempt: "LLMCatalogSyncAttempt | None"


@dataclass(frozen=True)
class LLMCatalogSnapshotCounts:
    """Current catalog snapshot count summary."""

    visible_count: int
    hidden_count: int


@dataclass(frozen=True)
class CatalogNotFound:
    """Catalog does not exist or is outside workspace scope."""

    integration_id: str


@dataclass(frozen=True)
class CatalogSyncAlreadyRunning:
    """Catalog sync attempt is already running."""

    catalog_id: str
    attempt_id: str


@dataclass(frozen=True)
class LLMCatalogSyncAttempt:
    """Catalog source/projection attempt state."""

    id: str
    catalog_id: str | None
    source_key: str
    status: LLMCatalogAttemptStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    produced_snapshot_id: str | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    matched_count: int
    skipped_count: int
    hidden_count: int
    diagnostics: dict[str, Any] | None
    catalog_configuration_version: int | None


@dataclass(frozen=True)
class ImageGenerationCatalogPublication:
    """Image catalog publication result after generation fencing."""

    snapshot_id: str | None
    superseding_attempt_id: str | None
    current_catalog_configuration_version: int


@dataclass(frozen=True)
class LiteLLMSourceSnapshot:
    """Stored LiteLLM source snapshot."""

    id: str
    source_key: str
    source_url: str | None
    source_hash: str
    model_count: int
    litellm_version: str | None
    loaded_source: str
    payload: dict[str, Any]
    created_at: datetime.datetime
