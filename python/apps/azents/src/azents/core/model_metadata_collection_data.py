"""Detached model-source collection data passed to durable publication."""

import dataclasses

from azents.core.model_catalog_source import (
    CatalogSourcePayload,
    ModelMetadataSourceKind,
)


@dataclasses.dataclass(frozen=True)
class FetchedModelMetadataSource:
    """One typed immutable source and its collection provenance."""

    source_kind: ModelMetadataSourceKind
    source_schema_version: str
    source_url: str
    source_hash: str
    producer_name: str
    producer_version: str
    provider_count: int
    model_count: int
    payload: CatalogSourcePayload
    raw_document_hash: str
    etag: str | None
