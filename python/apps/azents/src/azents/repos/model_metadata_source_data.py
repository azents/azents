"""Model metadata source repository data objects."""

import datetime
from dataclasses import dataclass

from azents.core.enums import LLMCatalogAttemptStatus
from azents.core.model_catalog_source import CatalogSourcePayload


@dataclass(frozen=True)
class ModelMetadataSourceSnapshot:
    """One durable canonical model metadata source snapshot."""

    id: str
    source_key: str
    source_kind: str
    source_schema_version: str
    source_url: str
    source_hash: str
    producer_name: str
    producer_version: str
    provider_count: int
    model_count: int
    payload: CatalogSourcePayload
    created_at: datetime.datetime


@dataclass(frozen=True)
class ModelMetadataSourceAttempt:
    """One source synchronization attempt."""

    id: str
    source_key: str
    status: LLMCatalogAttemptStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    produced_snapshot_id: str | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    diagnostics: dict[str, object] | None
