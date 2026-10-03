"""Completed database-only model-source authority operations."""

import dataclasses
import datetime
from collections import Counter
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogEntryVisibility, LLMCatalogPurpose, LLMProvider
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY, CatalogSourcePayload
from azents.core.model_metadata_collection_data import FetchedModelMetadataSource
from azents.core.model_metadata_projection_data import SystemCatalogCandidateSummary
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    CatalogSyncAlreadyRunning,
    LLMCatalogEntryCreate,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot

_SOURCE_MIN_REMOVAL_COUNT = 50
_SOURCE_MIN_REMOVAL_RATIO = 0.02
_PROVIDER_MIN_REMOVAL_COUNT = 5
_PROVIDER_MIN_REMOVAL_RATIO = 0.20


class _SystemCatalogPublicationBusy(RuntimeError):
    """Abort all attempt claims when any catalog is already running."""


@dataclasses.dataclass(frozen=True)
class ModelMetadataProjectionOperations:
    """Own atomic catalog claims, candidate writes and multi-provider publication."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]

    async def create_candidate(
        self,
        *,
        provider: LLMProvider,
        entries: list[LLMCatalogEntryCreate],
        provenance: CatalogProjectionProvenance,
        diagnostics: dict[str, object],
    ) -> SystemCatalogCandidateSummary:
        async with self.session_manager() as session:
            catalog = await self.repository.ensure_system_catalog(
                session, provider=provider, purpose=LLMCatalogPurpose.CONVERSATION
            )
            candidate_id = await self.repository.create_candidate_snapshot(
                session,
                catalog=catalog,
                entries=entries,
                diagnostics=diagnostics,
                provenance=provenance,
                catalog_configuration_version=None,
            )
            visible = sum(
                entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                for entry in entries
            )
            return SystemCatalogCandidateSummary(
                provider=provider,
                catalog_id=catalog.id,
                candidate_snapshot_id=candidate_id,
                expected_current_snapshot_id=catalog.current_snapshot_id,
                visible_count=visible,
                hidden_count=len(entries) - visible,
                projection_fingerprint=provenance.projection_fingerprint,
            )

    async def begin_publication(
        self,
        *,
        candidates: list[SystemCatalogCandidateSummary],
        source_key: str,
    ) -> dict[str, str] | None:
        attempt_ids: dict[str, str] = {}
        try:
            async with self.session_manager() as session:
                for candidate in candidates:
                    attempt = await self.repository.begin_attempt(
                        session,
                        catalog_id=candidate.catalog_id,
                        source_key=source_key,
                        started_at=datetime.datetime.now(datetime.UTC),
                    )
                    if isinstance(attempt, CatalogSyncAlreadyRunning):
                        raise _SystemCatalogPublicationBusy
                    attempt_ids[candidate.catalog_id] = attempt
        except _SystemCatalogPublicationBusy:
            # Raising inside the context rolls back every partial claim.
            return None
        return attempt_ids

    async def publish(
        self,
        *,
        candidates: list[SystemCatalogCandidateSummary],
        source: ModelMetadataSourceSnapshot,
        attempt_ids: dict[str, str],
    ) -> dict[str, str]:
        snapshot_ids: dict[str, str] = {}
        async with self.session_manager() as session:
            for candidate in candidates:
                latest = await self.repository.lock_catalog_for_attempt_completion(
                    session, catalog_id=candidate.catalog_id
                )
                if latest != attempt_ids[candidate.catalog_id]:
                    raise RuntimeError("The system catalog refresh was superseded.")
                snapshot_ids[
                    candidate.catalog_id
                ] = await self.repository.publish_candidate_snapshot(
                    session,
                    catalog_id=candidate.catalog_id,
                    candidate_snapshot_id=candidate.candidate_snapshot_id,
                    expected_current_snapshot_id=candidate.expected_current_snapshot_id,
                    expected_catalog_configuration_version=None,
                    expected_projection_fingerprint=candidate.projection_fingerprint,
                    expected_source_key=source.source_key,
                    expected_source_snapshot_id=source.id,
                    fence_latest_attempt=True,
                    expected_latest_attempt_id=attempt_ids[candidate.catalog_id],
                )
            for candidate in candidates:
                await self.repository.mark_attempt_succeeded(
                    session,
                    attempt_id=attempt_ids[candidate.catalog_id],
                    finished_at=datetime.datetime.now(datetime.UTC),
                    produced_snapshot_id=snapshot_ids[candidate.catalog_id],
                    fetched_count=source.model_count,
                    matched_count=candidate.visible_count + candidate.hidden_count,
                    skipped_count=0,
                    hidden_count=candidate.hidden_count,
                    diagnostics={
                        "provider": candidate.provider.value,
                        "source_snapshot_id": source.id,
                        "projection_fingerprint": candidate.projection_fingerprint,
                    },
                )
        return snapshot_ids

    async def fail_publication(
        self,
        *,
        candidates: list[SystemCatalogCandidateSummary],
        source_snapshot_id: str,
        attempt_ids: dict[str, str],
        failure_code: str,
        failure_message: str,
    ) -> None:
        async with self.session_manager() as session:
            for candidate in candidates:
                await self.repository.mark_attempt_failed(
                    session,
                    attempt_id=attempt_ids[candidate.catalog_id],
                    finished_at=datetime.datetime.now(datetime.UTC),
                    failure_code=failure_code,
                    failure_message=failure_message,
                    action_hint="Check replacement source and projection readiness.",
                    diagnostics={
                        "provider": candidate.provider.value,
                        "source_snapshot_id": source_snapshot_id,
                        "projection_fingerprint": candidate.projection_fingerprint,
                    },
                )


@dataclasses.dataclass(frozen=True)
class SourcePublicationResult:
    """A committed source result or an explicitly persisted rejection."""

    snapshot: ModelMetadataSourceSnapshot | None
    failure_message: str | None


@dataclasses.dataclass(frozen=True)
class ModelMetadataSourceOperations:
    """Own source attempts and fenced publication transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]

    async def begin_attempt(self, *, started_at: datetime.datetime) -> str:
        async with self.session_manager() as session:
            return await self.repository.begin_attempt(
                session, source_key=CATALOG_SOURCE_KEY, started_at=started_at
            )

    async def publish(
        self,
        *,
        attempt_id: str,
        fetched: FetchedModelMetadataSource,
        finished_at: datetime.datetime,
    ) -> SourcePublicationResult:
        """Compare and publish under the same source-authority lock."""
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
                return SourcePublicationResult(
                    snapshot=None,
                    failure_message="The source synchronization was superseded.",
                )
            if (
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
                return SourcePublicationResult(
                    snapshot=None,
                    failure_message="The source reduction requires operator review.",
                )
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
            return SourcePublicationResult(snapshot=snapshot, failure_message=None)

    async def fail_collection(
        self,
        *,
        attempt_id: str,
        finished_at: datetime.datetime,
        failure_code: str,
        diagnostics: dict[str, object],
    ) -> None:
        async with self.session_manager() as session:
            await self.repository.fail_attempt(
                session,
                attempt_id=attempt_id,
                finished_at=finished_at,
                failure_code=failure_code,
                failure_message=(
                    "The remote model metadata source could not be ingested."
                ),
                action_hint="Retry after the configured source becomes available.",
                fetched_count=0,
                diagnostics=diagnostics,
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
