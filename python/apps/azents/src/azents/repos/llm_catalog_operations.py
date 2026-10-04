"""Completed current conversation catalog reads, claims and atomic publication."""

import dataclasses
import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncTrigger,
)
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.rdb.deps import get_session_manager
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.llm_catalog import CatalogEntryWithCatalog, LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogCounts,
    LLMCatalogEntryCreate,
    LLMCatalogEntryList,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.model_catalog_sync_state import fail_sync as fail_current_sync
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import (
    SourceModelExpectation,
    SourceProjectionMetadata,
)


@dataclasses.dataclass(frozen=True)
class CatalogReadPage:
    """Current page plus workspace cooldown facts captured in a completed read."""

    page: LLMCatalogEntryList
    latest_workspace_sync: LLMCatalogSyncStatus | None
    current_projection_version: CatalogProjectionVersion | None
    active_inputs: CapturedActiveChoiceInputs


@dataclasses.dataclass(frozen=True)
class CapturedSelectableCatalogEntry:
    """One selected row and current declarations from the same completed read."""

    selected: CatalogEntryWithCatalog
    active_inputs: CapturedActiveChoiceInputs


@dataclasses.dataclass(frozen=True)
class SystemCatalogRead:
    """One system provider's current owner/counts."""

    provider: LLMProvider
    catalog: LLMCatalog | None
    counts: LLMCatalogCounts | None
    latest_sync: LLMCatalogSyncStatus | None


@dataclasses.dataclass(frozen=True)
class CatalogSyncStart:
    """Stable identity and the existing atomic synchronization policy outcome."""

    catalog: LLMCatalog
    claim: IntegrationCatalogSyncClaim | IntegrationCatalogSyncPolicyDecision


@dataclasses.dataclass(frozen=True)
class CatalogSyncFailure:
    """Failure facts to record only while the specified work still owns its owner."""

    catalog_id: str
    work_token: str
    finished_at: datetime.datetime
    failure_code: str
    failure_message: str
    action_hint: str | None
    diagnostics: dict[str, Any] | None


@dataclasses.dataclass(frozen=True)
class CatalogPublicationSucceeded:
    """Current published owner and counts; no dataset identity."""

    catalog: LLMCatalog
    visible_count: int
    hidden_count: int


@dataclasses.dataclass(frozen=True)
class CatalogPublicationSuperseded:
    """Current work or credential authority rejected stale discovery."""

    superseding_work_token: str | None


@dataclasses.dataclass(frozen=True)
class CatalogPublicationSourceChanged:
    """Preparation must repeat after an exact source value/presence change."""


@dataclasses.dataclass(frozen=True)
class LLMCatalogOperationsRepository:
    """Own complete DB-only operations outside service/provider I/O."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    source_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]
    active_repository: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ]

    async def load_integration(
        self, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def selectable_entry(
        self, *, integration_id: str, workspace_id: str, model_identifier: str
    ) -> CapturedSelectableCatalogEntry | None:
        async with self.session_manager() as session:
            scope = await self.active_repository.prepare_read_scope_in_session(
                session, workspace_id=workspace_id, integration_ids=(integration_id,)
            )
            selected = (
                await self.catalog_repository.get_selectable_entry_by_integration_model(
                    session,
                    integration_id=integration_id,
                    workspace_id=workspace_id,
                    model_identifier=model_identifier,
                    purpose=LLMCatalogPurpose.CONVERSATION,
                )
            )
            if selected is None:
                return None
            active_inputs = (
                await self.active_repository.capture_current_entries_in_session(
                    session,
                    scope=scope,
                    integration_id=integration_id,
                    entries=(selected,),
                )
            )
            return CapturedSelectableCatalogEntry(selected, active_inputs)

    async def read_page(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        search: str | None,
        limit: int,
        offset: int,
    ) -> CatalogReadPage | None:
        async with self.session_manager() as session:
            scope = await self.active_repository.prepare_read_scope_in_session(
                session, workspace_id=workspace_id, integration_ids=(integration_id,)
            )
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
            active_inputs = (
                await self.active_repository.capture_current_entries_in_session(
                    session,
                    scope=scope,
                    integration_id=integration_id,
                    entries=tuple(
                        CatalogEntryWithCatalog(catalog=page.catalog, entry=entry)
                        for entry in page.entries
                    ),
                )
            )
            latest = None
            if page.catalog.scope == LLMCatalogScope.INTEGRATION:
                catalogs = self.catalog_repository
                latest = await catalogs.get_latest_integration_sync_for_workspace(
                    session, workspace_id=workspace_id
                )
            return CatalogReadPage(
                page=page,
                latest_workspace_sync=latest,
                current_projection_version=self.catalog_repository.projection_version(
                    page.catalog
                ),
                active_inputs=active_inputs,
            )

    async def read_system_catalogs(
        self, providers: tuple[LLMProvider, ...]
    ) -> list[SystemCatalogRead]:
        """Acquire all owner read locks in the same sorted order as publication."""
        async with self.session_manager() as session:
            result = await session.write_session.execute(
                sa.select(RDBLLMCatalog.id, RDBLLMCatalog.provider)
                .where(
                    RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                    RDBLLMCatalog.purpose == LLMCatalogPurpose.CONVERSATION,
                    RDBLLMCatalog.provider.in_(providers),
                )
                .order_by(RDBLLMCatalog.id)
            )
            current: dict[LLMProvider, LLMCatalog] = {}
            for row in result:
                owner = await self.catalog_repository.lock_catalog(
                    session, catalog_id=row.id, shared=True
                )
                current[owner.provider] = self.catalog_repository.build_catalog(owner)
            return [
                SystemCatalogRead(
                    provider=provider,
                    catalog=current.get(provider),
                    counts=None
                    if provider not in current
                    or current[provider].last_success_at is None
                    else LLMCatalogCounts(
                        visible_count=current[provider].visible_count,
                        hidden_count=current[provider].hidden_count,
                    ),
                    latest_sync=None
                    if provider not in current
                    else current[provider].sync_status,
                )
                for provider in providers
            ]

    async def begin_sync(
        self,
        *,
        integration_id: str,
        provider: LLMProvider,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
        required_projection_version: CatalogProjectionVersion,
    ) -> CatalogSyncStart:
        async with self.session_manager() as session:
            integration = await self.catalog_repository.lock_integration(
                session, integration_id=integration_id, workspace_id=workspace_id
            )
            if integration is None or integration.provider != provider:
                raise ValueError(
                    "Catalog integration does not belong to this workspace/provider."
                )
            catalog = await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration_id,
                provider=provider,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            claim = await self.catalog_repository.begin_integration_sync(
                session,
                catalog_id=catalog.id,
                workspace_id=workspace_id,
                started_at=started_at,
                trigger=trigger,
                required_projection_version=required_projection_version,
            )
            owner = await self.catalog_repository.lock_catalog(
                session, catalog_id=catalog.id
            )
            return CatalogSyncStart(
                catalog=self.catalog_repository.build_catalog(owner), claim=claim
            )

    async def publish(
        self,
        *,
        catalog: LLMCatalog,
        claim: IntegrationCatalogSyncClaim,
        entries: list[LLMCatalogEntryCreate],
        expected_source_metadata: SourceProjectionMetadata | None,
        expected_source_models: tuple[SourceModelExpectation, ...],
        diagnostics: dict[str, Any] | None,
        sync_diagnostics: dict[str, Any] | None,
        fetched_count: int,
        skipped_count: int,
        finished_at: datetime.datetime,
    ) -> (
        CatalogPublicationSucceeded
        | CatalogPublicationSuperseded
        | CatalogPublicationSourceChanged
    ):
        """Recheck integration, exact source inputs and work before replacing rows."""
        if catalog.provider_integration_id is None:
            raise ValueError("Integration publication requires integration ownership.")
        async with self.session_manager() as session:
            integration = await self.catalog_repository.lock_integration(
                session,
                integration_id=catalog.provider_integration_id,
                workspace_id=None,
            )
            if integration is None:
                return CatalogPublicationSuperseded(superseding_work_token=None)
            await self.source_repository.ensure_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            await self.source_repository.lock_authority(
                session, source_key=CATALOG_SOURCE_KEY
            )
            inputs_current = await self.source_repository.projection_inputs_match(
                session,
                expected_metadata=expected_source_metadata,
                expectations=expected_source_models,
            )
            owner = await self.catalog_repository.lock_catalog(
                session, catalog_id=catalog.id
            )
            if (
                owner.provider_integration_id != integration.id
                or owner.provider != integration.provider
                or integration.catalog_configuration_version
                != claim.catalog_configuration_version
                or not integration.enabled
                or owner.sync_work_token != claim.work_token
                or owner.sync_status != LLMCatalogAttemptStatus.RUNNING
            ):
                fail_current_sync(
                    owner,
                    work_token=claim.work_token,
                    finished_at=finished_at,
                    failure_code="CatalogSyncSuperseded",
                    failure_message="Current integration authority rejected discovery.",
                    action_hint="Refresh with the current integration configuration.",
                    diagnostics={
                        "failure_category": "configuration_superseded",
                        "automatic_retry_blocked": False,
                    },
                )
                await session.write_session.flush()
                return CatalogPublicationSuperseded(
                    superseding_work_token=owner.sync_work_token
                )
            if not inputs_current:
                return CatalogPublicationSourceChanged()
            await self.catalog_repository.replace_current_entries(
                session,
                owner=owner,
                entries=entries,
                diagnostics=diagnostics,
                finished_at=finished_at,
            )
            await self.catalog_repository.complete_sync(
                session,
                catalog_id=owner.id,
                work_token=claim.work_token,
                finished_at=finished_at,
                fetched_count=fetched_count,
                matched_count=len(entries),
                skipped_count=skipped_count,
                hidden_count=owner.hidden_count,
                diagnostics=sync_diagnostics,
            )
            return CatalogPublicationSucceeded(
                catalog=self.catalog_repository.build_catalog(owner),
                visible_count=owner.visible_count,
                hidden_count=owner.hidden_count,
            )

    async def fail_sync(self, failure: CatalogSyncFailure) -> None:
        async with self.session_manager() as session:
            initial = await session.write_session.get(RDBLLMCatalog, failure.catalog_id)
            if initial is None:
                return
            if initial.provider_integration_id is not None:
                await self.catalog_repository.lock_integration(
                    session,
                    integration_id=initial.provider_integration_id,
                    workspace_id=None,
                )
            await self.catalog_repository.fail_sync(
                session,
                catalog_id=failure.catalog_id,
                work_token=failure.work_token,
                finished_at=failure.finished_at,
                failure_code=failure.failure_code,
                failure_message=failure.failure_message,
                action_hint=failure.action_hint,
                diagnostics=failure.diagnostics,
            )
