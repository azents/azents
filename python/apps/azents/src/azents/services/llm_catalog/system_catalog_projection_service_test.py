"""System catalog projection service tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import (
    LiteLLMSourceSnapshotRepository,
    LLMCatalogRepository,
)
from azents.services.llm_catalog import (
    LiteLLMSourceSyncService,
    SystemCatalogProjectionService,
)


async def test_system_catalogs_exclude_chatgpt_oauth(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Expose only providers with system-owned model visibility."""
    catalog_repository = LLMCatalogRepository()
    service = SystemCatalogProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=catalog_repository,
        source_sync_service=LiteLLMSourceSyncService(
            session_manager=rdb_session_manager,
            snapshot_repository=LiteLLMSourceSnapshotRepository(),
        ),
    )

    items = await service.list_system_catalogs()

    assert [item.provider for item in items] == [
        LLMProvider.OPENAI,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    ]
