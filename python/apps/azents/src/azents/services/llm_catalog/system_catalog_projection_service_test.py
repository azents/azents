"""Current system catalog service composition tests."""

from unittest.mock import AsyncMock

from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.llm_catalog import SystemCatalogProjectionService
from azents.services.model_metadata_source import ModelMetadataSourceSyncService


async def test_system_catalogs_exclude_integration_scoped_providers(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Listing local current state never starts remote source collection."""
    source = AsyncMock(spec=ModelMetadataSourceSyncService)
    service = SystemCatalogProjectionService(
        operations=LLMCatalogOperationsRepository(
            session_manager=rdb_session_manager,
            read_session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
            source_repository=ModelMetadataSourceRepository(),
            active_repository=AsyncMock(spec=ActiveModelCapabilitiesRepository),
        ),
        source_sync_service=source,
    )
    items = await service.list_system_catalogs()
    assert {item.provider for item in items} == {
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    }
    source.sync_current_source.assert_not_awaited()
