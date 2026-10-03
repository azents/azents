"""Current Model Catalog v1 Admin API response contracts."""

import datetime
import enum

from pydantic import BaseModel

from azents.core.enums import LLMProvider
from azents.services.llm_catalog import (
    ModelCatalogSyncStatusOutput,
    SystemCatalogListItem,
    SystemCatalogProjectionSummary,
)


class SystemCatalogProvider(enum.StrEnum):
    """Provider with a system-owned model catalog."""

    OPENAI = LLMProvider.OPENAI.value
    ANTHROPIC = LLMProvider.ANTHROPIC.value
    GOOGLE_GEMINI = LLMProvider.GOOGLE_GEMINI.value

    def to_llm_provider(self) -> LLMProvider:
        return LLMProvider(self.value)


class SystemModelCatalogSyncStatusResponse(BaseModel):
    """Latest operational state, excluding opaque active work ownership."""

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
        cls, status: ModelCatalogSyncStatusOutput
    ) -> "SystemModelCatalogSyncStatusResponse":
        return cls.model_validate(status.model_dump())


class SystemModelCatalogResponse(BaseModel):
    provider: SystemCatalogProvider
    catalog_id: str | None
    last_success_at: datetime.datetime | None
    visible_count: int
    hidden_count: int
    latest_sync: SystemModelCatalogSyncStatusResponse | None

    @classmethod
    def convert_from(cls, item: SystemCatalogListItem) -> "SystemModelCatalogResponse":
        return cls(
            provider=SystemCatalogProvider(item.provider.value),
            catalog_id=item.catalog_id,
            last_success_at=item.last_success_at,
            visible_count=item.visible_count,
            hidden_count=item.hidden_count,
            latest_sync=SystemModelCatalogSyncStatusResponse.convert_from(
                item.latest_sync
            )
            if item.latest_sync is not None
            else None,
        )


class SystemModelCatalogListResponse(BaseModel):
    items: list[SystemModelCatalogResponse]


class SystemModelCatalogRefreshResponse(BaseModel):
    provider: SystemCatalogProvider
    catalog_id: str
    last_success_at: datetime.datetime | None
    visible_count: int
    hidden_count: int
    status: str
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None

    @classmethod
    def convert_from(
        cls, summary: SystemCatalogProjectionSummary
    ) -> "SystemModelCatalogRefreshResponse":
        return cls(
            provider=SystemCatalogProvider(summary.provider.value),
            catalog_id=summary.catalog_id,
            last_success_at=summary.last_success_at,
            visible_count=summary.visible_count,
            hidden_count=summary.hidden_count,
            status=summary.status,
            failure_code=summary.failure_code,
            failure_message=summary.failure_message,
            action_hint=summary.action_hint,
        )


class SystemModelCatalogRefreshListResponse(BaseModel):
    items: list[SystemModelCatalogRefreshResponse]
