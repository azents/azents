"""Current image-generation availability and synchronization outputs."""

import datetime
from typing import Any

from pydantic import BaseModel

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelLifecycleStatus,
    LLMProvider,
)


class ImageGenerationCatalogEntryOutput(BaseModel):
    """One reviewed exact explicit image choice."""

    id: str
    provider: LLMProvider
    provider_model_identifier: str
    display_name: str
    description: str
    recommendation_rank: int | None
    lifecycle_status: LLMModelLifecycleStatus
    visibility_status: LLMCatalogEntryVisibility
    source_metadata: dict[str, Any] | None
    projection_metadata: dict[str, Any] | None


class ImageGenerationCatalogSyncStatusOutput(BaseModel):
    """Latest current synchronization facts, without work-token exposure."""

    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    matched_count: int
    skipped_count: int
    hidden_count: int


class ImageGenerationModelCatalogOutput(BaseModel):
    """Current image-purpose availability preserving maintained defaults."""

    default_available: bool
    explicit_selection_supported: bool
    catalog_id: str | None
    last_success_at: datetime.datetime | None
    latest_sync: ImageGenerationCatalogSyncStatusOutput | None
    stale: bool
    usable: bool
    sync_available_at: datetime.datetime | None
    automatic_retry_blocked: bool
    entries: list[ImageGenerationCatalogEntryOutput]
    total: int
