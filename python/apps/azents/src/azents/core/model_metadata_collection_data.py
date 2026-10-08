"""Detached current model-source collection data passed to publication."""

import dataclasses
import datetime

from azents.core.model_catalog_source import (
    CatalogSourceModel,
    CatalogSourcePayload,
    ModelMetadataSourceKind,
)
from azents.core.model_pricing import ModelPricingDefinition


@dataclasses.dataclass(frozen=True)
class CurrentSourceModel:
    """One exact current source fact and its normalized price definition."""

    model: CatalogSourceModel
    pricing: ModelPricingDefinition
    collected_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class FetchedModelMetadataSource:
    """Validated transient collection; no whole-source body is persisted."""

    source_kind: ModelMetadataSourceKind
    source_schema_version: str
    source_url: str
    producer_name: str
    producer_version: str | None
    provider_count: int
    model_count: int
    payload: CatalogSourcePayload
    models: tuple[CurrentSourceModel, ...]
    collected_at: datetime.datetime
