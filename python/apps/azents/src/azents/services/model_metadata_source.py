"""Collect descriptive catalog data under Azents-owned durable authority."""

import dataclasses
import datetime
import os
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx2
from fastapi import Depends
from pydantic import ValidationError

from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
)
from azents.core.model_metadata_collection_data import FetchedModelMetadataSource
from azents.repos.model_metadata_operations import ModelMetadataSourceOperations
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.catalog_source_collection import (
    CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS,
    CATALOG_SOURCE_MAX_BYTES,
    DEFAULT_CATALOG_SOURCE_URL,
    CatalogCollectionPolicy,
    CatalogSourceCollector,
)


def get_catalog_collection_policy() -> CatalogCollectionPolicy:
    """Wire operator configuration only at the source collection boundary."""
    return CatalogCollectionPolicy(
        source_url=os.environ.get(
            "MODEL_CATALOG_SOURCE_URL", DEFAULT_CATALOG_SOURCE_URL
        ),
        max_bytes=CATALOG_SOURCE_MAX_BYTES,
        timeout_seconds=CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS,
        allow_testenv_endpoint=os.environ.get("AZ_TESTENV_API_ENABLED") == "true",
    )


async def get_catalog_source_http_client() -> AsyncGenerator[httpx2.AsyncClient, None]:
    """Own one collection client's resources without starting a library updater."""
    async with httpx2.AsyncClient(follow_redirects=False) as client:
        yield client


@dataclasses.dataclass(frozen=True)
class CatalogSourceAdapter:
    """Collect inert data through an explicit HTTP transport and policy."""

    http_client: Annotated[httpx2.AsyncClient, Depends(get_catalog_source_http_client)]
    policy: Annotated[CatalogCollectionPolicy, Depends(get_catalog_collection_policy)]

    async def fetch(self) -> FetchedModelMetadataSource:
        """Fetch one descriptive document; do not publish or install global state."""
        collected = await CatalogSourceCollector(
            http_client=self.http_client, policy=self.policy
        ).collect()
        payload = collected.payload
        return FetchedModelMetadataSource(
            source_kind=collected.source_kind,
            source_schema_version=payload.schema_version,
            source_url=collected.source_url,
            source_hash=collected.source_hash,
            producer_name="LiteLLM public catalog",
            # Identify published data bytes, not an installed package version.
            producer_version=f"sha256:{collected.raw_document_hash}",
            provider_count=payload.provider_count,
            model_count=payload.model_count,
            payload=payload,
            raw_document_hash=collected.raw_document_hash,
            etag=collected.etag,
        )


class ModelMetadataSourceSyncError(RuntimeError):
    """Model metadata collection failed without replacing successful authority."""


@dataclasses.dataclass(frozen=True)
class ModelMetadataSourceSyncService:
    """Synchronize source-only attempts independently of catalog reads."""

    operations: Annotated[
        ModelMetadataSourceOperations, Depends(ModelMetadataSourceOperations)
    ]
    read_repository: Annotated[
        ModelMetadataReadRepository, Depends(ModelMetadataReadRepository)
    ]
    source_adapter: Annotated[CatalogSourceAdapter, Depends(CatalogSourceAdapter)]

    async def sync_current_source(self) -> ModelMetadataSourceSnapshot:
        """Collect outside transactions, then fence validated publication."""
        started_at = datetime.datetime.now(datetime.UTC)
        attempt_id = await self.operations.begin_attempt(started_at=started_at)
        try:
            fetched = await self.source_adapter.fetch()
        except (httpx2.HTTPError, TimeoutError, ValidationError, ValueError) as error:
            await self._record_failure(attempt_id=attempt_id, error=error)
            raise ModelMetadataSourceSyncError(
                "The remote model metadata source could not be ingested."
            ) from None
        finished_at = datetime.datetime.now(datetime.UTC)
        result = await self.operations.publish(
            attempt_id=attempt_id, fetched=fetched, finished_at=finished_at
        )
        if result.failure_message is not None:
            raise ModelMetadataSourceSyncError(result.failure_message)
        if result.snapshot is None:
            raise ModelMetadataSourceSyncError(
                "The source synchronization was superseded."
            )
        return result.snapshot

    async def get_current_source(self) -> ModelMetadataSourceSnapshot | None:
        """Return new-family local authority only, including an absent snapshot."""
        return await self.read_repository.capture()

    async def _record_failure(
        self,
        *,
        attempt_id: str,
        error: httpx2.HTTPError | TimeoutError | ValidationError | ValueError,
    ) -> None:
        await self.operations.fail_collection(
            attempt_id=attempt_id,
            finished_at=datetime.datetime.now(datetime.UTC),
            failure_code=type(error).__name__,
            diagnostics={
                "source_kind": CATALOG_SOURCE_KIND,
                "source_url": self.source_adapter.policy.source_url,
                "source_schema_version": CATALOG_SOURCE_SCHEMA_VERSION,
            },
        )
