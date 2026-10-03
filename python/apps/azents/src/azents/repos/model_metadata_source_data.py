"""Detached current source and narrow context repository data."""

import datetime
from dataclasses import dataclass

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import (
    CatalogSourcePayload,
    ModelMetadataSourceKind,
)
from azents.core.model_metadata_collection_data import CurrentSourceModel


@dataclass(frozen=True)
class ModelMetadataSource:
    """Maintenance-only complete view assembled from current per-model rows."""

    source_key: str
    source_kind: ModelMetadataSourceKind
    source_schema_version: str
    source_url: str
    producer_name: str
    producer_version: str | None
    provider_count: int
    model_count: int
    collected_at: datetime.datetime
    payload: CatalogSourcePayload
    models: tuple[CurrentSourceModel, ...]


@dataclass(frozen=True)
class SourceProjectionMetadata:
    """Descriptive source presence and provenance used by preparation."""

    source_key: str
    source_kind: ModelMetadataSourceKind
    collected_at: datetime.datetime


@dataclass(frozen=True)
class SourceModelExpectation:
    """Exact preparation input, including absence, rechecked under the source lock."""

    provider: str
    source_model_key: str
    current: CurrentSourceModel | None


@dataclass(frozen=True)
class ContextModelRequest:
    """One exact selected model needing optional context enrichment."""

    provider: LLMProvider
    model_identifier: str


@dataclass(frozen=True)
class ContextModelMetadata:
    """Only the optional maximum for one requested model."""

    provider: LLMProvider
    model_identifier: str
    max_input_tokens: int | None


@dataclass(frozen=True)
class CapturedContextSource:
    """Coherently captured requested maxima, including authoritative absence."""

    models: tuple[ContextModelMetadata, ...]
