"""Atomic current source and affected system-catalog replacement operations."""

import dataclasses
import datetime
from collections import Counter
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY, CatalogSourcePayload
from azents.core.model_metadata_collection_data import FetchedModelMetadataSource
from azents.rdb.deps import get_session_manager
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntryCreate,
    LLMCatalogSyncStatus,
)
from azents.repos.model_catalog_sync_state import fail_sync, start_sync, succeed_sync
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSource

_SOURCE_MIN_REMOVAL_COUNT = 50
_SOURCE_MIN_REMOVAL_RATIO = 0.02
_PROVIDER_MIN_REMOVAL_COUNT = 5
_PROVIDER_MIN_REMOVAL_RATIO = 0.20
_SYSTEM_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
)
_SYSTEM_SYNC_LEASE = datetime.timedelta(minutes=5)


@dataclasses.dataclass(frozen=True)
class SourceSyncAlreadyRunning:
    """Atomic source/system claim denial under the current publication owners."""

    catalog_id: str
    work_token: str


@dataclasses.dataclass(frozen=True)
class SystemCatalogReplacement:
    """Transient prepared current entries for one affected system provider."""

    provider: LLMProvider
    entries: list[LLMCatalogEntryCreate]
    diagnostics: dict[str, Any] | None


@dataclasses.dataclass(frozen=True)
class SourcePublicationResult:
    """Atomic success, current diagnostic rejection, or value-change retry."""

    source: ModelMetadataSource | None
    catalogs: list[LLMCatalog]
    failure_message: str | None
    source_changed: bool


@dataclasses.dataclass(frozen=True)
class ModelMetadataSourceOperations:
    """Keep source and all affected system entries in one DB-only commit."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]

    async def _system_owners(self, session: AsyncSession) -> list[RDBLLMCatalog]:
        """Find/create stable identities, then acquire every owner lock in ID order."""
        result = await session.execute(
            sa.select(RDBLLMCatalog.id, RDBLLMCatalog.provider).where(
                RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                RDBLLMCatalog.purpose == LLMCatalogPurpose.CONVERSATION,
                RDBLLMCatalog.provider.in_(_SYSTEM_PROVIDERS),
            )
        )
        identities = {row.provider: row.id for row in result}
        for provider in _SYSTEM_PROVIDERS:
            if provider not in identities:
                catalog = await self.catalog_repository.ensure_system_catalog(
                    session, provider=provider, purpose=LLMCatalogPurpose.CONVERSATION
                )
                identities[provider] = catalog.id
        owners: list[RDBLLMCatalog] = []
        for identity in sorted(identities.values()):
            owners.append(
                await self.catalog_repository.lock_catalog(session, catalog_id=identity)
            )
        return owners

    async def begin_sync(
        self, *, started_at: datetime.datetime
    ) -> str | SourceSyncAlreadyRunning:
        async with self.session_manager() as session:
            await self.repository.ensure_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            await self.repository.lock_authority(session, source_key=CATALOG_SOURCE_KEY)
            owners = await self._system_owners(session)
            for owner in owners:
                if (
                    owner.sync_status == LLMCatalogAttemptStatus.RUNNING
                    and owner.sync_started_at is not None
                    and started_at < owner.sync_started_at + _SYSTEM_SYNC_LEASE
                ):
                    if owner.sync_work_token is None:
                        raise ValueError(
                            "Running synchronization is missing its work token."
                        )
                    return SourceSyncAlreadyRunning(
                        catalog_id=owner.id, work_token=owner.sync_work_token
                    )
            token = await self.repository.begin_sync(
                session, source_key=CATALOG_SOURCE_KEY, started_at=started_at
            )
            for owner in owners:
                start_sync(
                    owner,
                    work_token=token,
                    started_at=started_at,
                    diagnostics={"source_key": CATALOG_SOURCE_KEY},
                )
            await session.flush()
            return token

    async def read_current(self) -> ModelMetadataSource | None:
        async with self.session_manager() as session:
            return await self.repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )

    async def read_sync_status(self) -> LLMCatalogSyncStatus | None:
        async with self.session_manager() as session:
            return await self.repository.get_sync_status(
                session, source_key=CATALOG_SOURCE_KEY
            )

    async def publish(
        self,
        *,
        work_token: str,
        fetched: FetchedModelMetadataSource,
        expected_source: ModelMetadataSource | None,
        replacements: list[SystemCatalogReplacement],
        finished_at: datetime.datetime,
    ) -> SourcePublicationResult:
        """Compare prepared source inputs and replace source/system rows atomically."""
        if {item.provider for item in replacements} != set(_SYSTEM_PROVIDERS) or len(
            replacements
        ) != len(_SYSTEM_PROVIDERS):
            raise ValueError(
                "Source publication must replace every affected system provider."
            )
        by_provider = {item.provider: item for item in replacements}
        async with self.session_manager() as session:
            source_owner = await self.repository.lock_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            if (
                source_owner is None
                or source_owner.sync_work_token != work_token
                or source_owner.sync_status != LLMCatalogAttemptStatus.RUNNING
            ):
                return SourcePublicationResult(
                    source=None,
                    catalogs=[],
                    failure_message="The source synchronization was superseded.",
                    source_changed=False,
                )
            previous = await self.repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )
            if previous != expected_source:
                return SourcePublicationResult(
                    source=None,
                    catalogs=[],
                    failure_message="Current source preparation inputs changed.",
                    source_changed=True,
                )
            owners = await self._system_owners(session)
            if any(
                owner.sync_work_token != work_token
                or owner.sync_status != LLMCatalogAttemptStatus.RUNNING
                for owner in owners
            ):
                return SourcePublicationResult(
                    source=None,
                    catalogs=[],
                    failure_message="System catalog synchronization was superseded.",
                    source_changed=False,
                )
            diagnostics = _source_diagnostics(previous=previous, fetched=fetched)
            if (
                reduction := _material_reduction(previous=previous, fetched=fetched)
            ) is not None:
                failure = "The source reduction requires operator review."
                for owner in [source_owner, *owners]:
                    fail_sync(
                        owner,
                        work_token=work_token,
                        finished_at=finished_at,
                        failure_code="ModelMetadataSourceModelCountReduction",
                        failure_message="The source has a material model reduction.",
                        action_hint="Verify removals before replacing the source.",
                        diagnostics={**diagnostics, "reduction_scope": reduction},
                    )
                await session.flush()
                return SourcePublicationResult(
                    source=None,
                    catalogs=[],
                    failure_message=failure,
                    source_changed=False,
                )
            await self.repository.replace_current(
                session,
                owner=source_owner,
                work_token=work_token,
                fetched=fetched,
                finished_at=finished_at,
                diagnostics=diagnostics,
            )
            for owner in owners:
                replacement = by_provider[owner.provider]
                await self.catalog_repository.replace_current_entries(
                    session,
                    owner=owner,
                    entries=replacement.entries,
                    diagnostics=replacement.diagnostics,
                    finished_at=finished_at,
                )
                succeed_sync(
                    owner,
                    work_token=work_token,
                    finished_at=finished_at,
                    fetched_count=fetched.model_count,
                    matched_count=owner.entry_count,
                    skipped_count=0,
                    hidden_count=owner.hidden_count,
                    diagnostics={
                        "provider": owner.provider.value,
                        "source_key": CATALOG_SOURCE_KEY,
                    },
                )
            await session.flush()
            source = await self.repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )
            return SourcePublicationResult(
                source=source,
                catalogs=[
                    self.catalog_repository.build_catalog(owner) for owner in owners
                ],
                failure_message=None,
                source_changed=False,
            )

    async def fail_sync(
        self,
        *,
        work_token: str,
        finished_at: datetime.datetime,
        failure_code: str,
        diagnostics: dict[str, object],
    ) -> None:
        """Only still-owned state can change; successful data stays untouched."""
        async with self.session_manager() as session:
            owner = await self.repository.lock_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            if owner is None or owner.sync_work_token != work_token:
                return
            owners = await self._system_owners(session)
            for current in [owner, *owners]:
                fail_sync(
                    current,
                    work_token=work_token,
                    finished_at=finished_at,
                    failure_code=failure_code,
                    failure_message="Current model source publication failed.",
                    action_hint="Retry after the configured source becomes available.",
                    diagnostics=diagnostics,
                )
            await session.flush()


def _source_diagnostics(
    *, previous: ModelMetadataSource | None, fetched: FetchedModelMetadataSource
) -> dict[str, object]:
    return {
        "source_kind": fetched.source_kind.value,
        "source_url": fetched.source_url,
        "source_schema_version": fetched.source_schema_version,
        "producer_name": fetched.producer_name,
        "producer_version": fetched.producer_version,
        "provider_count": fetched.provider_count,
        "model_count": fetched.model_count,
        "previous_model_count": previous.model_count if previous is not None else None,
        "supported_provider_counts": _provider_counts(fetched.payload),
        "previous_supported_provider_counts": _provider_counts(previous.payload)
        if previous is not None
        else {},
    }


def _provider_counts(payload: CatalogSourcePayload) -> dict[str, int]:
    return dict(Counter(model.provider for model in payload.models))


def _material_reduction(
    *, previous: ModelMetadataSource | None, fetched: FetchedModelMetadataSource
) -> str | None:
    if previous is None:
        return None
    removed = previous.model_count - fetched.model_count
    if (
        removed >= _SOURCE_MIN_REMOVAL_COUNT
        and removed / previous.model_count >= _SOURCE_MIN_REMOVAL_RATIO
    ):
        return "global"
    current_counts = _provider_counts(fetched.payload)
    for provider, count in _provider_counts(previous.payload).items():
        removed = count - current_counts.get(provider, 0)
        if (
            removed >= _PROVIDER_MIN_REMOVAL_COUNT
            and removed / count >= _PROVIDER_MIN_REMOVAL_RATIO
        ):
            return f"provider:{provider}"
    return None
