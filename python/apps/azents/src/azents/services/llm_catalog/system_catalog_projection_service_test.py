"""Active replacement system catalog projection service tests."""

from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.model_metadata_operations import (
    ModelMetadataProjectionOperations,
    ModelMetadataSourceOperations,
)
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.llm_catalog import SystemCatalogProjectionService
from azents.services.model_metadata_projection import (
    SystemCatalogReplacementProjectionService,
)
from azents.services.model_metadata_source import (
    CatalogSourceAdapter,
    ModelMetadataSourceSyncService,
)


async def test_system_catalogs_exclude_integration_scoped_providers(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Expose only providers with system-owned model visibility without fetching."""
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    repository = LLMCatalogRepository()
    replacement = SystemCatalogReplacementProjectionService(
        operations=ModelMetadataProjectionOperations(
            session_manager=rdb_session_manager, repository=repository
        ),
        source_sync_service=ModelMetadataSourceSyncService(
            read_repository=ModelMetadataReadRepository(
                session_manager=rdb_session_manager,
                source_snapshot_repository=ModelMetadataSourceRepository(),
            ),
            operations=ModelMetadataSourceOperations(
                session_manager=rdb_session_manager,
                repository=ModelMetadataSourceRepository(),
            ),
            source_adapter=adapter,
        ),
    )
    service = SystemCatalogProjectionService(
        operations=LLMCatalogOperationsRepository(
            session_manager=rdb_session_manager,
            catalog_repository=repository,
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
        ),
        replacement_projection_service=replacement,
    )
    items = await service.list_system_catalogs()
    assert {item.provider for item in items} == {
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    }
    adapter.fetch.assert_not_awaited()
