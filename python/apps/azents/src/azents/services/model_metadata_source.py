"""Collect descriptive catalog data under Azents-owned durable authority."""

import dataclasses
import datetime
import os
from collections import Counter
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx2
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
    CatalogSourcePayload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.catalog_source_collection import (
    CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS,
    CATALOG_SOURCE_MAX_BYTES,
    DEFAULT_CATALOG_SOURCE_URL,
    CatalogCollectionPolicy,
    CatalogSourceCollector,
)

_SOURCE_MIN_REMOVAL_COUNT = 50
_SOURCE_MIN_REMOVAL_RATIO = 0.02
_PROVIDER_MIN_REMOVAL_COUNT = 5
_PROVIDER_MIN_REMOVAL_RATIO = 0.20


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
class FetchedModelMetadataSource:
    """One typed immutable source and its collection provenance."""

    source_kind: str
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

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]
    source_adapter: Annotated[CatalogSourceAdapter, Depends(CatalogSourceAdapter)]

    async def sync_current_source(self) -> ModelMetadataSourceSnapshot:
        """Collect outside transactions, then fence validated publication."""
        started_at = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            attempt_id = await self.repository.begin_attempt(
                session, source_key=CATALOG_SOURCE_KEY, started_at=started_at
            )
        try:
            fetched = await self.source_adapter.fetch()
        except (httpx2.HTTPError, TimeoutError, ValidationError, ValueError) as error:
            await self._record_failure(attempt_id=attempt_id, error=error)
            raise ModelMetadataSourceSyncError(
                "The remote model metadata source could not be ingested."
            ) from None
        finished_at = datetime.datetime.now(datetime.UTC)
        failure_message: str | None = None
        snapshot: ModelMetadataSourceSnapshot | None = None
        async with self.session_manager() as session:
            authority = await self.repository.lock_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            previous = await self.repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )
            diagnostics = _source_diagnostics(previous=previous, fetched=fetched)
            if authority.latest_attempt_id != attempt_id:
                await self.repository.fail_attempt(
                    session,
                    attempt_id=attempt_id,
                    finished_at=finished_at,
                    failure_code="ModelMetadataSourceSyncSuperseded",
                    failure_message="A newer synchronization superseded this result.",
                    action_hint="Use the newer source synchronization result.",
                    fetched_count=fetched.model_count,
                    diagnostics=diagnostics,
                )
                failure_message = "The source synchronization was superseded."
            elif (
                reduction := _material_reduction(previous=previous, fetched=fetched)
            ) is not None:
                await self.repository.fail_attempt(
                    session,
                    attempt_id=attempt_id,
                    finished_at=finished_at,
                    failure_code="ModelMetadataSourceModelCountReduction",
                    failure_message=(
                        "The source is materially smaller than the snapshot."
                    ),
                    action_hint="Verify upstream removals before replacing the source.",
                    fetched_count=fetched.model_count,
                    diagnostics={**diagnostics, "reduction_scope": reduction},
                )
                failure_message = "The source reduction requires operator review."
            else:
                snapshot = await self.repository.publish_snapshot(
                    session,
                    authority=authority,
                    attempt_id=attempt_id,
                    source_kind=fetched.source_kind,
                    source_schema_version=fetched.source_schema_version,
                    source_url=fetched.source_url,
                    source_hash=fetched.source_hash,
                    producer_name=fetched.producer_name,
                    producer_version=fetched.producer_version,
                    provider_count=fetched.provider_count,
                    model_count=fetched.model_count,
                    payload=fetched.payload,
                    finished_at=finished_at,
                    diagnostics=diagnostics,
                )
        if failure_message is not None:
            raise ModelMetadataSourceSyncError(failure_message)
        if snapshot is None:
            raise ModelMetadataSourceSyncError(
                "The source synchronization was superseded."
            )
        return snapshot

    async def get_current_source(self) -> ModelMetadataSourceSnapshot | None:
        """Return new-family local authority only, including an absent snapshot."""
        async with self.session_manager() as session:
            return await self.repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )

    async def _record_failure(
        self,
        *,
        attempt_id: str,
        error: httpx2.HTTPError | TimeoutError | ValidationError | ValueError,
    ) -> None:
        async with self.session_manager() as session:
            await self.repository.fail_attempt(
                session,
                attempt_id=attempt_id,
                finished_at=datetime.datetime.now(datetime.UTC),
                failure_code=type(error).__name__,
                failure_message=(
                    "The remote model metadata source could not be ingested."
                ),
                action_hint="Retry after the configured source becomes available.",
                fetched_count=0,
                diagnostics={
                    "source_kind": CATALOG_SOURCE_KIND,
                    "source_url": self.source_adapter.policy.source_url,
                    "source_schema_version": CATALOG_SOURCE_SCHEMA_VERSION,
                },
            )


def _source_diagnostics(
    *, previous: ModelMetadataSourceSnapshot | None, fetched: FetchedModelMetadataSource
) -> dict[str, object]:
    """Describe provenance without retaining raw exception or payload text."""
    return {
        "source_kind": fetched.source_kind,
        "source_url": fetched.source_url,
        "source_hash": fetched.source_hash,
        "raw_document_hash": fetched.raw_document_hash,
        "etag": fetched.etag,
        "source_schema_version": fetched.source_schema_version,
        "interpreter_version": fetched.payload.interpreter_version,
        "producer_name": fetched.producer_name,
        "producer_version": fetched.producer_version,
        "provider_count": fetched.provider_count,
        "model_count": fetched.model_count,
        "previous_model_count": previous.model_count if previous is not None else None,
        "supported_provider_counts": _provider_counts(fetched.payload),
        "previous_supported_provider_counts": (
            _provider_counts(previous.payload) if previous is not None else {}
        ),
    }


def _provider_counts(payload: CatalogSourcePayload) -> dict[str, int]:
    return dict(Counter(model.provider for model in payload.models))


def _material_reduction(
    *, previous: ModelMetadataSourceSnapshot | None, fetched: FetchedModelMetadataSource
) -> str | None:
    if previous is None:
        return None
    removed = previous.model_count - fetched.model_count
    if (
        removed >= _SOURCE_MIN_REMOVAL_COUNT
        and removed / previous.model_count >= _SOURCE_MIN_REMOVAL_RATIO
    ):
        return "global"
    previous_counts = _provider_counts(previous.payload)
    current_counts = _provider_counts(fetched.payload)
    for provider, count in previous_counts.items():
        removed = count - current_counts.get(provider, 0)
        if (
            removed >= _PROVIDER_MIN_REMOVAL_COUNT
            and removed / count >= _PROVIDER_MIN_REMOVAL_RATIO
        ):
            return f"provider:{provider}"
    return None
