"""Model catalog v1 Admin API data models."""

import datetime

from pydantic import BaseModel

from azents.core.enums import LLMProvider
from azents.services.llm_catalog import (
    ModelCatalogSyncAttemptOutput,
    SystemCatalogListItem,
    SystemCatalogProjectionSummary,
)


class SystemModelCatalogSyncAttemptResponse(BaseModel):
    """Latest model catalog sync attempt response."""

    id: str
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

    @classmethod
    def convert_from(
        cls,
        attempt: ModelCatalogSyncAttemptOutput,
    ) -> "SystemModelCatalogSyncAttemptResponse":
        """Convert service output to response model."""
        return cls.model_validate(attempt.model_dump())


class SystemModelCatalogResponse(BaseModel):
    """System model catalog response."""

    provider: LLMProvider
    catalog_id: str | None
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    latest_attempt: SystemModelCatalogSyncAttemptResponse | None

    @classmethod
    def convert_from(
        cls,
        item: SystemCatalogListItem,
    ) -> "SystemModelCatalogResponse":
        """Convert service output to response model."""
        return cls(
            provider=item.provider,
            catalog_id=item.catalog_id,
            snapshot_id=item.snapshot_id,
            visible_count=item.visible_count,
            hidden_count=item.hidden_count,
            latest_attempt=(
                SystemModelCatalogSyncAttemptResponse.convert_from(item.latest_attempt)
                if item.latest_attempt is not None
                else None
            ),
        )


class SystemModelCatalogListResponse(BaseModel):
    """System model catalog list response."""

    items: list[SystemModelCatalogResponse]


class SystemModelCatalogRefreshResponse(BaseModel):
    """System model catalog refresh response."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    status: str
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None

    @classmethod
    def convert_from(
        cls,
        summary: SystemCatalogProjectionSummary,
    ) -> "SystemModelCatalogRefreshResponse":
        """Convert service output to response model."""
        return cls(
            provider=summary.provider,
            catalog_id=summary.catalog_id,
            snapshot_id=summary.snapshot_id,
            visible_count=summary.visible_count,
            hidden_count=summary.hidden_count,
            status=summary.status,
            failure_code=summary.failure_code,
            failure_message=summary.failure_message,
            action_hint=summary.action_hint,
        )


class SystemModelCatalogRefreshListResponse(BaseModel):
    """System model catalog refresh list response."""

    items: list[SystemModelCatalogRefreshResponse]
