"""Catalog discovery sequencing across completed repository operations."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import LLMCatalogPurpose, LLMProvider
from azents.repos.catalog_operations_test import (
    _NOW,
    _catalog,
    _claim,
    _TransactionProbe,
)
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.llm_catalog import (
    IntegrationCatalogProjectionService,
    IntegrationModelListing,
)
from azents.services.model_listing.data import ModelListingOutput, ModelListingSummary
from azents.services.model_listing.providers import (
    ListingClientFactories,
    create_listing_client_factories,
)
from azents.services.model_metadata_source import ModelMetadataSourceSyncService
from azents.services.oauth_runtime_clients import create_runtime_oauth_client_factories


def _integration() -> LLMProviderIntegrationWithSecrets:
    """Build a normal API-key integration without deterministic fixture routing."""
    return LLMProviderIntegrationWithSecrets(
        id="integration",
        workspace_id="workspace",
        provider=LLMProvider.XAI,
        name="Normal integration",
        config=None,
        secrets=ApiKeySecrets(api_key="fixture"),
        enabled=True,
        created_at=_NOW,
        updated_at=_NOW,
        catalog_configuration_version=4,
    )


def _service(
    manager: _TransactionProbe,
    catalogs: AsyncMock,
    listing: IntegrationModelListing,
) -> IntegrationCatalogProjectionService:
    """Wire actual operation ownership with mocked persistence/provider dependencies."""
    integrations = AsyncMock(spec=LLMProviderIntegrationRepository)
    integrations.get_by_id_with_secrets.return_value = _integration()
    catalogs.ensure_integration_catalog.return_value = _catalog(
        LLMCatalogPurpose.CONVERSATION
    )
    catalogs.begin_integration_attempt.return_value = _claim()
    catalogs.lock_catalog_for_attempt_completion.return_value = "attempt"
    catalogs.create_candidate_snapshot.return_value = "candidate"
    catalogs.publish_candidate_snapshot.return_value = "published"
    source = AsyncMock(spec=ModelMetadataSourceSyncService)
    source.get_current_source.return_value = None
    return IntegrationCatalogProjectionService(
        operations=LLMCatalogOperationsRepository(manager, catalogs, integrations),
        chatgpt_oauth_runtime_repository=AsyncMock(spec=ChatGPTOAuthRuntimeRepository),
        xai_oauth_runtime_repository=AsyncMock(spec=XaiOAuthRuntimeRepository),
        kimi_oauth_runtime_repository=AsyncMock(spec=KimiOAuthRuntimeRepository),
        listing_clients=create_listing_client_factories(),
        oauth_clients=create_runtime_oauth_client_factories(),
        source_sync_service=source,
        provider_listing=listing,
    )


async def test_provider_listing_starts_only_after_claim_and_reload_complete() -> None:
    """Provider callbacks cannot observe an active catalog database transaction."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)

    async def listing(
        integration: LLMProviderIntegrationWithSecrets,
        clients: ListingClientFactories,
    ) -> ModelListingOutput:
        assert manager.active is False
        assert manager.commits == 3
        assert integration.catalog_configuration_version == 4
        assert isinstance(clients, ListingClientFactories)
        return ModelListingOutput(
            summary=ModelListingSummary(
                source="fixture:provider-visibility",
                fetched_at=_NOW,
                returned_count=0,
                skipped_count=0,
            ),
            models=[],
            skips=[],
        )

    service = _service(manager, catalogs, listing)
    result = await service.sync_integration_catalog(
        integration_id="integration", workspace_id="workspace"
    )
    assert isinstance(result, Success)
    assert result.value.snapshot_id == "published"
    assert manager.commits == 4
    assert manager.active is False


async def test_unexpected_listing_failure_is_recorded_after_closure_and_raised() -> (
    None
):
    """Completed failure persistence does not disguise an unexpected exception."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)

    async def listing(
        integration: LLMProviderIntegrationWithSecrets,
        clients: ListingClientFactories,
    ) -> ModelListingOutput:
        del integration, clients
        assert manager.active is False
        raise RuntimeError("Unexpected provider failure")

    service = _service(manager, catalogs, listing)
    with pytest.raises(RuntimeError, match="Unexpected provider failure"):
        await service.sync_integration_catalog(
            integration_id="integration", workspace_id="workspace"
        )
    catalogs.create_candidate_snapshot.assert_not_awaited()
    catalogs.mark_attempt_failed.assert_awaited_once()
    failure = catalogs.mark_attempt_failed.await_args
    assert failure is not None
    assert failure.kwargs["failure_code"] == "RuntimeError"
    assert (
        failure.kwargs["diagnostics"]["failure_category"] == "catalog_service_failure"
    )
    assert manager.commits == 4
    assert manager.active is False
