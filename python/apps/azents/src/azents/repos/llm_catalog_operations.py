"""Completed conversation-catalog reads, claims, and fenced publication operations."""

import dataclasses
import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog_sync import (
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import CatalogEntryWithCatalog, LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogEntryCreate,
    LLMCatalogEntryList,
    LLMCatalogSnapshotCounts,
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclasses.dataclass(frozen=True)
class CatalogReadPage:
    """One page and workspace policy evidence captured in the same transaction."""

    page: LLMCatalogEntryList
    latest_workspace_attempt: LLMCatalogSyncAttempt | None


@dataclasses.dataclass(frozen=True)
class SystemCatalogRead:
    """Detached state of one provider in a completed system-catalog read."""

    provider: LLMProvider
    catalog: LLMCatalog | None
    counts: LLMCatalogSnapshotCounts | None
    latest_attempt: LLMCatalogSyncAttempt | None


@dataclasses.dataclass(frozen=True)
class CatalogAttemptStart:
    """Catalog identity and the atomic attempt-policy claim outcome."""

    catalog: LLMCatalog
    claim: IntegrationCatalogSyncClaim | IntegrationCatalogSyncPolicyDecision


@dataclasses.dataclass(frozen=True)
class CatalogAttemptFailure:
    """Failure metadata to persist without a live service-layer transaction."""

    attempt_id: str
    finished_at: datetime.datetime
    failure_code: str
    failure_message: str
    action_hint: str
    diagnostics: dict[str, Any] | None


@dataclasses.dataclass(frozen=True)
class CatalogPublicationSucceeded:
    """Detached counts and identity of one atomically published snapshot."""

    snapshot_id: str
    visible_count: int
    hidden_count: int


@dataclasses.dataclass(frozen=True)
class CatalogPublicationSuperseded:
    """Newer attempt authority prevented any candidate/publication write."""

    superseding_attempt_id: str


@dataclasses.dataclass(frozen=True)
class LLMCatalogOperationsRepository:
    """Own completed DB-only operations used by conversation-catalog services."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]

    async def load_integration(
        self, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Finish credential-snapshot reads before discovery or OAuth refresh."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def selectable_entry(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
    ) -> CatalogEntryWithCatalog | None:
        """Resolve exact conversation-model identity in one completed read."""
        async with self.session_manager() as session:
            return (
                await self.catalog_repository.get_selectable_entry_by_integration_model(
                    session,
                    integration_id=integration_id,
                    workspace_id=workspace_id,
                    model_identifier=model_identifier,
                    purpose=LLMCatalogPurpose.CONVERSATION,
                )
            )

    async def read_page(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        search: str | None,
        limit: int,
        offset: int,
    ) -> CatalogReadPage | None:
        """Capture the page and shared-workspace cooldown evidence atomically."""
        async with self.session_manager() as session:
            page = await self.catalog_repository.list_entries_by_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
                purpose=LLMCatalogPurpose.CONVERSATION,
                search=search,
                limit=limit,
                offset=offset,
            )
            if page is None:
                return None
            latest_workspace_attempt = None
            if page.catalog.scope == LLMCatalogScope.INTEGRATION:
                catalogs = self.catalog_repository
                workspace_attempt = (
                    catalogs.get_latest_integration_attempt_for_workspace
                )
                latest_workspace_attempt = await workspace_attempt(
                    session, workspace_id=workspace_id
                )
            return CatalogReadPage(
                page=page, latest_workspace_attempt=latest_workspace_attempt
            )

    async def read_system_catalogs(
        self, providers: tuple[LLMProvider, ...]
    ) -> list[SystemCatalogRead]:
        """Read one consistent local status group without remote discovery."""
        async with self.session_manager() as session:
            items: list[SystemCatalogRead] = []
            for provider in providers:
                catalog = await self.catalog_repository.get_system_catalog(
                    session,
                    provider=provider,
                    purpose=LLMCatalogPurpose.CONVERSATION,
                )
                if catalog is None:
                    items.append(
                        SystemCatalogRead(
                            provider=provider,
                            catalog=None,
                            counts=None,
                            latest_attempt=None,
                        )
                    )
                    continue
                counts = await self.catalog_repository.get_current_snapshot_counts(
                    session, catalog=catalog
                )
                latest_attempt = await self.catalog_repository.get_latest_attempt(
                    session, catalog=catalog
                )
                items.append(
                    SystemCatalogRead(
                        provider=provider,
                        catalog=catalog,
                        counts=counts,
                        latest_attempt=latest_attempt,
                    )
                )
            return items

    async def begin_attempt(
        self,
        *,
        integration_id: str,
        provider: LLMProvider,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> CatalogAttemptStart:
        """Create the catalog and claim under the existing workspace/catalog locks."""
        async with self.session_manager() as session:
            catalog = await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration_id,
                provider=provider,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            claim = await self.catalog_repository.begin_integration_attempt(
                session,
                catalog_id=catalog.id,
                workspace_id=workspace_id,
                source_key=CATALOG_SOURCE_KEY,
                started_at=started_at,
                trigger=trigger,
            )
            return CatalogAttemptStart(catalog=catalog, claim=claim)

    async def publish(
        self,
        *,
        catalog: LLMCatalog,
        claim: IntegrationCatalogSyncClaim,
        entries: list[LLMCatalogEntryCreate],
        provenance: CatalogProjectionProvenance,
        candidate_diagnostics: dict[str, Any] | None,
        attempt_diagnostics: dict[str, Any] | None,
        fetched_count: int,
        skipped_count: int,
        finished_at: datetime.datetime,
    ) -> CatalogPublicationSucceeded | CatalogPublicationSuperseded:
        """Atomically fence, create, publish and finalize a conversation candidate."""
        async with self.session_manager() as session:
            current_attempt_id = (
                await self.catalog_repository.lock_catalog_for_attempt_completion(
                    session, catalog_id=catalog.id
                )
            )
            if current_attempt_id is None:
                raise RuntimeError(
                    "Integration catalog has no attempt allowed to publish."
                )
            if current_attempt_id != claim.attempt_id:
                return CatalogPublicationSuperseded(
                    superseding_attempt_id=current_attempt_id
                )
            candidate_snapshot_id = (
                await self.catalog_repository.create_candidate_snapshot(
                    session,
                    catalog=catalog,
                    entries=entries,
                    diagnostics=candidate_diagnostics,
                    provenance=provenance,
                    catalog_configuration_version=claim.catalog_configuration_version,
                )
            )
            snapshot_id = await self.catalog_repository.publish_candidate_snapshot(
                session,
                catalog_id=catalog.id,
                candidate_snapshot_id=candidate_snapshot_id,
                expected_current_snapshot_id=claim.expected_current_snapshot_id,
                expected_catalog_configuration_version=claim.catalog_configuration_version,
                expected_projection_fingerprint=provenance.projection_fingerprint,
                fence_latest_attempt=True,
                expected_latest_attempt_id=claim.attempt_id,
            )
            visible_count = sum(
                entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                for entry in entries
            )
            hidden_count = len(entries) - visible_count
            await self.catalog_repository.mark_attempt_succeeded(
                session,
                attempt_id=claim.attempt_id,
                finished_at=finished_at,
                produced_snapshot_id=snapshot_id,
                fetched_count=fetched_count,
                matched_count=len(entries),
                skipped_count=skipped_count,
                hidden_count=hidden_count,
                diagnostics=attempt_diagnostics,
            )
            return CatalogPublicationSucceeded(
                snapshot_id=snapshot_id,
                visible_count=visible_count,
                hidden_count=hidden_count,
            )

    async def fail_attempt(self, failure: CatalogAttemptFailure) -> None:
        """Commit failure metadata only after any failed publication rolls back."""
        async with self.session_manager() as session:
            await self.catalog_repository.mark_attempt_failed(
                session,
                attempt_id=failure.attempt_id,
                finished_at=failure.finished_at,
                failure_code=failure.failure_code,
                failure_message=failure.failure_message,
                action_hint=failure.action_hint,
                diagnostics=failure.diagnostics,
            )
