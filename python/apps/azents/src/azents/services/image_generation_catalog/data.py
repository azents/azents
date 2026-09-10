"""Image-generation catalog service response data."""

import datetime
from typing import Any

from pydantic import BaseModel, Field

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelLifecycleStatus,
    LLMProvider,
)


class ImageGenerationCatalogEntryOutput(BaseModel):
    """One stored selectable image-generation catalog entry."""

    id: str = Field(description="Image catalog entry ID")
    provider: LLMProvider = Field(description="Hosting provider")
    provider_model_identifier: str = Field(
        description="Exact provider model identifier"
    )
    display_name: str = Field(description="Registry-owned display name")
    description: str = Field(description="Registry-owned description")
    recommendation_rank: int | None = Field(
        description="Nullable stable recommendation ordering rank"
    )
    lifecycle_status: LLMModelLifecycleStatus = Field(description="Registry lifecycle")
    visibility_status: LLMCatalogEntryVisibility = Field(description="Visibility state")
    source_metadata: dict[str, Any] | None = Field(
        description="Bounded provider discovery provenance"
    )
    projection_metadata: dict[str, Any] | None = Field(
        description="Registry projection diagnostics"
    )


class ImageGenerationCatalogAttemptOutput(BaseModel):
    """Latest image-generation catalog synchronization attempt."""

    id: str = Field(description="Attempt ID")
    status: str = Field(description="Attempt status")
    started_at: datetime.datetime = Field(description="Attempt start time")
    finished_at: datetime.datetime | None = Field(description="Attempt finish time")
    failure_code: str | None = Field(description="Sanitized failure code")
    failure_message: str | None = Field(description="Sanitized failure message")
    action_hint: str | None = Field(description="Recovery guidance")
    fetched_count: int = Field(description="Provider-visible identifier count")
    matched_count: int = Field(description="Registry intersection count")
    skipped_count: int = Field(description="Skipped provider identifier count")
    hidden_count: int = Field(description="Hidden catalog entry count")


class ImageGenerationModelCatalogOutput(BaseModel):
    """Stored image-generation availability for one provider integration."""

    default_available: bool = Field(
        description="Whether maintained default dispatch works"
    )
    explicit_selection_supported: bool = Field(
        description="Whether this provider supports verified explicit image pins"
    )
    catalog_id: str | None = Field(description="Image catalog ID")
    snapshot_id: str | None = Field(description="Current image snapshot ID")
    snapshot_configuration_version: int | None = Field(
        description="Configuration version captured by the current snapshot"
    )
    current_configuration_version: int | None = Field(
        description="Current integration catalog configuration version"
    )
    snapshot_created_at: datetime.datetime | None = Field(
        description="Current image snapshot creation time"
    )
    latest_attempt: ImageGenerationCatalogAttemptOutput | None = Field(
        description="Latest image catalog synchronization attempt"
    )
    stale: bool = Field(description="Whether stored availability needs refresh")
    generation_current: bool = Field(
        description=(
            "Whether the stored snapshot matches current integration configuration"
        )
    )
    sync_available_at: datetime.datetime | None = Field(
        description="Earliest time an explicit sync can start"
    )
    automatic_retry_blocked: bool = Field(
        description="Whether automatic stale retry is blocked"
    )
    entries: list[ImageGenerationCatalogEntryOutput] = Field(
        description="Ordered selectable explicit image choices"
    )
    total: int = Field(description="Total selectable explicit image choices")
