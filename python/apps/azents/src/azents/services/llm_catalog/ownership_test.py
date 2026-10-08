"""Provider I/O sequencing and bounded source repreparation at service boundaries."""

import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import LLMCatalogPurpose, LLMCatalogScope, LLMProvider
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_catalog.data import IntegrationCatalogSyncClaim, LLMCatalog
from azents.repos.llm_catalog_operations import (
    CatalogPublicationSourceChanged,
    CatalogPublicationSucceeded,
    CatalogSyncStart,
    LLMCatalogOperationsRepository,
)
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

_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


def _integration() -> LLMProviderIntegrationWithSecrets:
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


def _catalog() -> LLMCatalog:
    return LLMCatalog(
        id="catalog",
        scope=LLMCatalogScope.INTEGRATION,
        provider=LLMProvider.XAI,
        purpose=LLMCatalogPurpose.CONVERSATION,
        provider_integration_id="integration",
        entry_count=0,
        visible_count=0,
        hidden_count=0,
        last_success_at=_NOW,
        image_usable=None,
        diagnostics=None,
        sync_status=None,
    )


def _service(
    operations: AsyncMock, listing: IntegrationModelListing
) -> IntegrationCatalogProjectionService:
    operations.load_integration.return_value = _integration()
    operations.begin_sync.return_value = CatalogSyncStart(
        catalog=_catalog(),
        claim=IntegrationCatalogSyncClaim(
            work_token="work", catalog_configuration_version=4
        ),
    )
    operations.publish.return_value = CatalogPublicationSucceeded(
        catalog=_catalog(), visible_count=0, hidden_count=0
    )
    source = AsyncMock(spec=ModelMetadataSourceSyncService)
    source.get_current_source.return_value = None
    return IntegrationCatalogProjectionService(
        operations=operations,
        chatgpt_oauth_runtime_repository=AsyncMock(spec=ChatGPTOAuthRuntimeRepository),
        xai_oauth_runtime_repository=AsyncMock(spec=XaiOAuthRuntimeRepository),
        kimi_oauth_runtime_repository=AsyncMock(spec=KimiOAuthRuntimeRepository),
        listing_clients=create_listing_client_factories(),
        oauth_clients=create_runtime_oauth_client_factories(),
        source_sync_service=source,
        provider_listing=listing,
    )


def _listing() -> ModelListingOutput:
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


async def test_provider_listing_starts_after_completed_claim_and_reload() -> None:
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)

    async def listing(
        integration: LLMProviderIntegrationWithSecrets, clients: ListingClientFactories
    ) -> ModelListingOutput:
        operations.begin_sync.assert_awaited_once()
        assert operations.load_integration.await_count == 2
        assert integration.catalog_configuration_version == 4
        assert isinstance(clients, ListingClientFactories)
        operations.publish.assert_not_awaited()
        return _listing()

    result = await _service(operations, listing).sync_integration_catalog(
        integration_id="integration", workspace_id="workspace"
    )
    assert isinstance(result, Success)
    assert result.value.last_success_at == _NOW
    operations.publish.assert_awaited_once()


async def test_source_change_reprepares_without_repeating_provider_io() -> None:
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    count = 0

    async def listing(
        integration: LLMProviderIntegrationWithSecrets, clients: ListingClientFactories
    ) -> ModelListingOutput:
        nonlocal count
        count += 1
        return _listing()

    service = _service(operations, listing)
    operations.publish.side_effect = [
        CatalogPublicationSourceChanged(),
        CatalogPublicationSucceeded(
            catalog=_catalog(), visible_count=0, hidden_count=0
        ),
    ]
    result = await service.sync_integration_catalog(
        integration_id="integration", workspace_id="workspace"
    )
    assert isinstance(result, Success)
    assert count == 1 and operations.publish.await_count == 2


async def test_unexpected_listing_failure_records_current_failure_and_raises() -> None:
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)

    async def listing(
        integration: LLMProviderIntegrationWithSecrets, clients: ListingClientFactories
    ) -> ModelListingOutput:
        raise RuntimeError("Unexpected provider failure")

    service = _service(operations, listing)
    with pytest.raises(RuntimeError, match="Unexpected provider failure"):
        await service.sync_integration_catalog(
            integration_id="integration", workspace_id="workspace"
        )
    operations.publish.assert_not_awaited()
    operations.fail_sync.assert_awaited_once()
    recorded = operations.fail_sync.await_args
    assert recorded is not None and recorded.args[0].failure_code == "RuntimeError"
    assert recorded.args[0].diagnostics["failure_category"] == "catalog_service_failure"
