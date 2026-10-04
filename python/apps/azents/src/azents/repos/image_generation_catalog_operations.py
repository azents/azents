"""Completed current image-catalog reads and credential-fenced publication."""

import dataclasses
import datetime
from typing import Annotated, Any

from fastapi import Depends

from azents.core.enums import LLMCatalogAttemptStatus, LLMCatalogPurpose, LLMProvider
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.rdb.deps import get_session_manager
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.llm_catalog import (
    ImageGenerationCatalogEntryWithCatalog,
    LLMCatalogRepository,
)
from azents.repos.llm_catalog.data import (
    ImageGenerationCatalogEntryCreate,
    ImageGenerationCatalogEntryList,
    ImageGenerationCatalogPublication,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_catalog_operations import CatalogSyncFailure, CatalogSyncStart
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclasses.dataclass(frozen=True)
class ImageCatalogRead:
    """Current integration/page/cooldown facts, including default-only providers."""

    integration: LLMProviderIntegration
    page: ImageGenerationCatalogEntryList | None
    latest_workspace_sync: LLMCatalogSyncStatus | None


@dataclasses.dataclass(frozen=True)
class ImageOptionAuthority:
    """Coherent integration eligibility and an optional exact current image model."""

    integration: LLMProviderIntegration | None
    entry: ImageGenerationCatalogEntryWithCatalog | None


@dataclasses.dataclass(frozen=True)
class ImageRuntimeAuthority:
    """Coherent current image usability and optional exact model."""

    page: ImageGenerationCatalogEntryList | None
    entry: ImageGenerationCatalogEntryWithCatalog | None


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogOperationsRepository:
    """Finish every transaction before service/provider I/O."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]

    async def load_integration(
        self, integration_id: str
    ) -> LLMProviderIntegration | None:
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id(session, integration_id)

    async def load_listing_integration(
        self, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def read(
        self, *, integration_id: str, workspace_id: str
    ) -> ImageCatalogRead | None:
        async with self.session_manager() as session:
            authority = await self.catalog_repository.lock_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
                shared=True,
            )
            if authority is None:
                return None
            integration = await self.integration_repository.get_by_id(
                session, integration_id
            )
            if integration is None:
                return None
            if integration.provider != LLMProvider.OPENAI:
                return ImageCatalogRead(
                    integration=integration, page=None, latest_workspace_sync=None
                )
            await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration.id,
                provider=integration.provider,
                purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            )
            catalogs = self.catalog_repository
            page = await catalogs.list_image_generation_entries_by_integration(
                session, integration_id=integration.id, workspace_id=workspace_id
            )
            if page is None:
                raise RuntimeError(
                    "Current image catalog creation did not become readable."
                )
            workspace_sync = (
                await self.catalog_repository.get_latest_integration_sync_for_workspace(
                    session, workspace_id=workspace_id
                )
            )
            return ImageCatalogRead(
                integration=integration, page=page, latest_workspace_sync=workspace_sync
            )

    async def begin_sync(
        self,
        *,
        integration_id: str,
        provider: LLMProvider,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> CatalogSyncStart:
        async with self.session_manager() as session:
            integration = await self.catalog_repository.lock_integration(
                session, integration_id=integration_id, workspace_id=workspace_id
            )
            if integration is None or integration.provider != provider:
                raise ValueError(
                    "Image integration has the wrong workspace or provider."
                )
            catalog = await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration_id,
                provider=provider,
                purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            )
            claim = await self.catalog_repository.begin_integration_sync(
                session,
                catalog_id=catalog.id,
                workspace_id=workspace_id,
                started_at=started_at,
                trigger=trigger,
                required_projection_version=None,
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
        entries: list[ImageGenerationCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
        sync_diagnostics: dict[str, Any] | None,
        fetched_count: int,
        finished_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> ImageGenerationCatalogPublication:
        if catalog.provider_integration_id is None:
            raise ValueError("Image publication requires integration ownership.")
        async with self.session_manager() as session:
            integration = await self.catalog_repository.lock_integration(
                session,
                integration_id=catalog.provider_integration_id,
                workspace_id=None,
            )
            if integration is None:
                return ImageGenerationCatalogPublication(
                    published=False,
                    superseding_work_token=None,
                    current_configuration_version=claim.catalog_configuration_version,
                    last_success_at=None,
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
                await self.catalog_repository.fail_sync(
                    session,
                    catalog_id=owner.id,
                    work_token=claim.work_token,
                    finished_at=finished_at,
                    failure_code="CatalogSyncSuperseded",
                    failure_message="Image catalog synchronization was superseded.",
                    action_hint="Use the newer integration configuration.",
                    diagnostics={
                        "catalog_purpose": "image_generation",
                        "failure_category": "configuration_superseded",
                        "automatic_retry_blocked": False,
                        "trigger": trigger.value,
                    },
                )
                return ImageGenerationCatalogPublication(
                    published=False,
                    superseding_work_token=owner.sync_work_token,
                    current_configuration_version=integration.catalog_configuration_version,
                    last_success_at=owner.last_success_at,
                )
            await self.catalog_repository.replace_current_image_entries(
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
                skipped_count=fetched_count - len(entries),
                hidden_count=owner.hidden_count,
                diagnostics=sync_diagnostics,
            )
            return ImageGenerationCatalogPublication(
                published=True,
                superseding_work_token=None,
                current_configuration_version=integration.catalog_configuration_version,
                last_success_at=owner.last_success_at,
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

    async def option_authority(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        expected_provider: LLMProvider,
        model_identifier: str | None,
    ) -> ImageOptionAuthority:
        async with self.session_manager() as session:
            authority = await self.catalog_repository.lock_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
                shared=True,
            )
            if authority is None:
                return ImageOptionAuthority(integration=None, entry=None)
            integration = await self.integration_repository.get_by_id(
                session, integration_id
            )
            entry = None
            if (
                integration is not None
                and integration.provider == expected_provider
                and integration.enabled
                and integration.provider == LLMProvider.OPENAI
                and model_identifier is not None
            ):
                entry = (
                    await self.catalog_repository.get_selectable_image_generation_entry(
                        session,
                        integration_id=integration.id,
                        workspace_id=workspace_id,
                        model_identifier=model_identifier,
                    )
                )
            return ImageOptionAuthority(integration=integration, entry=entry)

    async def runtime_authority(
        self, *, integration_id: str, workspace_id: str, model_identifier: str
    ) -> ImageRuntimeAuthority:
        async with self.session_manager() as session:
            catalogs = self.catalog_repository
            page = await catalogs.list_image_generation_entries_by_integration(
                session, integration_id=integration_id, workspace_id=workspace_id
            )
            entry = None
            if (
                page is not None
                and page.catalog.image_usable is True
                and page.catalog.last_success_at is not None
            ):
                entry = (
                    await self.catalog_repository.get_selectable_image_generation_entry(
                        session,
                        integration_id=integration_id,
                        workspace_id=workspace_id,
                        model_identifier=model_identifier,
                    )
                )
            return ImageRuntimeAuthority(page=page, entry=entry)
