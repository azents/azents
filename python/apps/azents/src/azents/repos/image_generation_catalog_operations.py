"""Completed image-catalog reads, attempt claims and generation-fenced publication."""

import dataclasses
import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogPurpose, LLMProvider
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import (
    ImageGenerationCatalogEntryWithCatalog,
    LLMCatalogRepository,
)
from azents.repos.llm_catalog.data import (
    ImageGenerationCatalogEntryCreate,
    ImageGenerationCatalogEntryList,
    ImageGenerationCatalogPublication,
    LLMCatalog,
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_catalog_operations import (
    CatalogAttemptFailure,
    CatalogAttemptStart,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)

_IMAGE_GENERATION_SOURCE_KEY = "openai_models_list:image_generation"


@dataclasses.dataclass(frozen=True)
class ImageCatalogRead:
    """Local integration/page/cooldown evidence, including default-only providers."""

    integration: LLMProviderIntegration
    page: ImageGenerationCatalogEntryList | None
    latest_workspace_attempt: LLMCatalogSyncAttempt | None


@dataclasses.dataclass(frozen=True)
class ImageOptionAuthority:
    """Detached integration and optional exact entry from one authority read."""

    integration: LLMProviderIntegration | None
    entry: ImageGenerationCatalogEntryWithCatalog | None


@dataclasses.dataclass(frozen=True)
class ImageRuntimeAuthority:
    """Page generation and optional selectable entry captured in one transaction."""

    page: ImageGenerationCatalogEntryList | None
    entry: ImageGenerationCatalogEntryWithCatalog | None


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogOperationsRepository:
    """Keep complete image-catalog database transactions outside service I/O."""

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
    ) -> LLMProviderIntegration | None:
        """Finish the non-secret scope read before any sync sequencing."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id(session, integration_id)

    async def load_listing_integration(
        self, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Finish credential capture before invoking the provider SDK."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def read(
        self, *, integration_id: str, workspace_id: str
    ) -> ImageCatalogRead | None:
        """Capture response authority without creating default-only catalogs."""
        async with self.session_manager() as session:
            catalogs = self.catalog_repository
            integration = await self.integration_repository.get_by_id(
                session, integration_id
            )
            if integration is None or integration.workspace_id != workspace_id:
                return None
            if integration.provider != LLMProvider.OPENAI:
                return ImageCatalogRead(
                    integration=integration,
                    page=None,
                    latest_workspace_attempt=None,
                )
            await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration.id,
                provider=integration.provider,
                purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            )
            page = await catalogs.list_image_generation_entries_by_integration(
                session,
                integration_id=integration.id,
                workspace_id=workspace_id,
            )
            if page is None:
                raise RuntimeError("Image catalog creation did not become readable.")
            workspace_attempt = catalogs.get_latest_integration_attempt_for_workspace
            latest_workspace_attempt = await workspace_attempt(
                session, workspace_id=workspace_id
            )
            return ImageCatalogRead(
                integration=integration,
                page=page,
                latest_workspace_attempt=latest_workspace_attempt,
            )

    async def begin_attempt(
        self,
        *,
        integration_id: str,
        provider: LLMProvider,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> CatalogAttemptStart:
        """Claim an image attempt and purpose-specific catalog atomically."""
        async with self.session_manager() as session:
            catalog = await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration_id,
                provider=provider,
                purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            )
            claim = await self.catalog_repository.begin_integration_attempt(
                session,
                catalog_id=catalog.id,
                workspace_id=workspace_id,
                source_key=_IMAGE_GENERATION_SOURCE_KEY,
                started_at=started_at,
                trigger=trigger,
                required_projection_version=None,
            )
            return CatalogAttemptStart(catalog=catalog, claim=claim)

    async def publish(
        self,
        *,
        catalog: LLMCatalog,
        attempt_id: str,
        entries: list[ImageGenerationCatalogEntryCreate],
        candidate_diagnostics: dict[str, Any] | None,
        attempt_diagnostics: dict[str, Any] | None,
        fetched_count: int,
        finished_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
    ) -> ImageGenerationCatalogPublication:
        """Publish and finish success or superseded failure in the same transaction."""
        async with self.session_manager() as session:
            publication = (
                await self.catalog_repository.replace_current_image_generation_snapshot(
                    session,
                    catalog=catalog,
                    attempt_id=attempt_id,
                    entries=entries,
                    diagnostics=candidate_diagnostics,
                )
            )
            if publication.snapshot_id is None:
                await self.catalog_repository.mark_attempt_failed(
                    session,
                    attempt_id=attempt_id,
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
                return publication
            await self.catalog_repository.mark_attempt_succeeded(
                session,
                attempt_id=attempt_id,
                finished_at=finished_at,
                produced_snapshot_id=publication.snapshot_id,
                fetched_count=fetched_count,
                matched_count=len(entries),
                skipped_count=fetched_count - len(entries),
                hidden_count=0,
                diagnostics=attempt_diagnostics,
            )
            return publication

    async def fail_attempt(self, failure: CatalogAttemptFailure) -> None:
        """Record external/unexpected failure after the previous operation closes."""
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

    async def option_authority(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        expected_provider: LLMProvider,
        model_identifier: str | None,
    ) -> ImageOptionAuthority:
        """Capture integration eligibility and a reviewed explicit pin together."""
        async with self.session_manager() as session:
            integration = await self.integration_repository.get_by_id(
                session, integration_id
            )
            entry = None
            if (
                integration is not None
                and integration.workspace_id == workspace_id
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
        self,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
    ) -> ImageRuntimeAuthority:
        """Capture catalog generation and selectable-entry authority together."""
        async with self.session_manager() as session:
            catalogs = self.catalog_repository
            page = await catalogs.list_image_generation_entries_by_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
            )
            entry = None
            if (
                page is not None
                and page.catalog.current_snapshot_id is not None
                and page.snapshot_catalog_configuration_version
                == page.current_integration_catalog_configuration_version
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
