"""Collect and atomically publish current source and system model data."""

import asyncio
import dataclasses
import datetime
import os
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx2
from fastapi import Depends
from pydantic import ValidationError

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
)
from azents.core.model_metadata_collection_data import (
    CurrentSourceModel,
    FetchedModelMetadataSource,
)
from azents.core.model_pricing import normalize_model_pricing
from azents.repos.model_metadata_operations import (
    ModelMetadataSourceOperations,
    SourceSyncAlreadyRunning,
    SystemCatalogProjectionFailure,
    SystemCatalogReplacement,
)
from azents.repos.model_metadata_source_data import ModelMetadataSource
from azents.services.catalog_source_collection import (
    CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS,
    CATALOG_SOURCE_MAX_BYTES,
    DEFAULT_CATALOG_SOURCE_URL,
    CatalogCollectionPolicy,
    CatalogSourceCollector,
)
from azents.services.model_metadata_projection import (
    ModelMetadataProjectionError,
    project_system_entries,
)

_SYSTEM_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
)


def get_catalog_collection_policy() -> CatalogCollectionPolicy:
    """Wire operator configuration at the source collection boundary."""
    return CatalogCollectionPolicy(
        source_url=os.environ.get(
            "MODEL_CATALOG_SOURCE_URL", DEFAULT_CATALOG_SOURCE_URL
        ),
        max_bytes=CATALOG_SOURCE_MAX_BYTES,
        timeout_seconds=CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS,
        allow_testenv_endpoint=os.environ.get("AZ_TESTENV_API_ENABLED") == "true",
    )


async def get_catalog_source_http_client() -> AsyncGenerator[httpx2.AsyncClient, None]:
    """Own one bounded collection transport without installing global state."""
    async with httpx2.AsyncClient(follow_redirects=False) as client:
        yield client


@dataclasses.dataclass(frozen=True)
class CatalogSourceAdapter:
    """Collect and normalize prices once outside publication transactions."""

    http_client: Annotated[httpx2.AsyncClient, Depends(get_catalog_source_http_client)]
    policy: Annotated[CatalogCollectionPolicy, Depends(get_catalog_collection_policy)]

    async def fetch(self) -> FetchedModelMetadataSource:
        """Return typed current facts and prices without a data content identity."""
        collected = await CatalogSourceCollector(
            http_client=self.http_client, policy=self.policy
        ).collect()
        payload = collected.payload
        collected_at = datetime.datetime.now(datetime.UTC)
        return FetchedModelMetadataSource(
            source_kind=collected.source_kind,
            source_schema_version=payload.schema_version,
            source_url=collected.source_url,
            producer_name="LiteLLM public catalog",
            producer_version=None,
            provider_count=payload.provider_count,
            model_count=payload.model_count,
            payload=payload,
            models=tuple(
                CurrentSourceModel(
                    model=model,
                    pricing=normalize_model_pricing(
                        source_key=collected.source_key,
                        source_model=model,
                        collected_at=collected_at,
                    ),
                    collected_at=collected_at,
                )
                for model in payload.models
            ),
            collected_at=collected_at,
        )


class ModelMetadataSourceSyncError(RuntimeError):
    """Collection or publication failed while successful current data remained."""


class ModelMetadataSourceSyncBusy(ModelMetadataSourceSyncError):
    """An atomic owner claim rejected concurrent source collection."""

    def __init__(self, work: SourceSyncAlreadyRunning) -> None:
        self.work = work
        super().__init__("Model source synchronization is already running.")


@dataclasses.dataclass(frozen=True)
class ModelMetadataSourceSyncService:
    """Refresh current source and every affected system owner atomically."""

    operations: Annotated[
        ModelMetadataSourceOperations, Depends(ModelMetadataSourceOperations)
    ]
    source_adapter: Annotated[CatalogSourceAdapter, Depends(CatalogSourceAdapter)]

    async def sync_current_source(self) -> ModelMetadataSource:
        """Collect outside locks and reprepare changed source inputs at most twice."""
        work_token = await self.operations.begin_sync(
            started_at=datetime.datetime.now(datetime.UTC)
        )
        if isinstance(work_token, SourceSyncAlreadyRunning):
            raise ModelMetadataSourceSyncBusy(work_token)
        try:
            expected_source = await self.operations.read_current()
            fetched = await self.source_adapter.fetch()
            effective_date = datetime.datetime.now(datetime.UTC).date()
            source = ModelMetadataSource(
                source_key=CATALOG_SOURCE_KEY,
                source_kind=fetched.source_kind,
                source_schema_version=fetched.source_schema_version,
                source_url=fetched.source_url,
                producer_name=fetched.producer_name,
                producer_version=fetched.producer_version,
                provider_count=fetched.provider_count,
                model_count=fetched.model_count,
                collected_at=fetched.collected_at,
                payload=fetched.payload,
                models=fetched.models,
            )
            replacements: list[
                SystemCatalogReplacement | SystemCatalogProjectionFailure
            ] = []
            for provider in _SYSTEM_PROVIDERS:
                diagnostics = {
                    "source_kind": source.source_kind,
                    "effective_date": effective_date.isoformat(),
                }
                try:
                    entries = project_system_entries(
                        provider=provider, source=source, effective_date=effective_date
                    )
                except ModelMetadataProjectionError as error:
                    replacements.append(
                        SystemCatalogProjectionFailure(
                            provider=provider,
                            failure_message=str(error),
                            diagnostics=diagnostics,
                        )
                    )
                else:
                    replacements.append(
                        SystemCatalogReplacement(
                            provider=provider,
                            entries=entries,
                            diagnostics=diagnostics,
                        )
                    )
            for retry in range(2):
                result = await self.operations.publish(
                    work_token=work_token,
                    fetched=fetched,
                    expected_source=expected_source,
                    replacements=replacements,
                    finished_at=datetime.datetime.now(datetime.UTC),
                )
                if result.source_changed and retry == 0:
                    expected_source = await self.operations.read_current()
                    continue
                if result.failure_message is not None:
                    raise ModelMetadataSourceSyncError(result.failure_message)
                if result.source_changed:
                    raise ModelMetadataSourceSyncError(
                        "The source changed during publication preparation."
                    )
                if result.source is None:
                    raise ModelMetadataSourceSyncError(
                        "The source synchronization was superseded."
                    )
                return result.source
            raise AssertionError("Source publication retry boundary was exhausted.")
        except (httpx2.HTTPError, TimeoutError, ValidationError, ValueError) as error:
            await self._record_failure(work_token=work_token, error=error)
            raise ModelMetadataSourceSyncError(
                "The remote model metadata source could not be ingested."
            ) from error
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._record_failure(work_token=work_token, error=error)
            raise

    async def get_current_source(self) -> ModelMetadataSource | None:
        """Read detached current maintenance data, never a historical source."""
        return await self.operations.read_current()

    async def _record_failure(self, *, work_token: str, error: Exception) -> None:
        await self.operations.fail_sync(
            work_token=work_token,
            finished_at=datetime.datetime.now(datetime.UTC),
            failure_code=type(error).__name__,
            diagnostics={
                "source_kind": CATALOG_SOURCE_KIND,
                "source_url": self.source_adapter.policy.source_url,
                "source_schema_version": CATALOG_SOURCE_SCHEMA_VERSION,
            },
        )
