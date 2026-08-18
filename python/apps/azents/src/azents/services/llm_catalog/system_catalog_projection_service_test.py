"""System catalog projection service tests."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import (
    LiteLLMSourceSnapshotRepository,
    LLMCatalogRepository,
)
from azents.services.llm_catalog import (
    LiteLLMSourceLoader,
    LiteLLMSourceSyncError,
    LiteLLMSourceSyncService,
    SystemCatalogProjectionService,
)


async def test_system_catalogs_exclude_integration_scoped_providers(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Expose only providers with system-owned model visibility."""
    catalog_repository = LLMCatalogRepository()
    async with httpx.AsyncClient() as client:
        service = SystemCatalogProjectionService(
            session_manager=rdb_session_manager,
            catalog_repository=catalog_repository,
            source_sync_service=LiteLLMSourceSyncService(
                session_manager=rdb_session_manager,
                snapshot_repository=LiteLLMSourceSnapshotRepository(),
                source_loader=LiteLLMSourceLoader(
                    http_client=client,
                    source_url="https://catalog.example.test/models.json",
                    litellm_version="1.91.3",
                ),
            ),
        )
        items = await service.list_system_catalogs()

    assert [item.provider for item in items] == [
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    ]


async def test_blocked_source_does_not_replace_current_system_catalog(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Retain the published projection when source ingestion is blocked."""
    requests = 0
    original_payload = {
        f"openai/model-{index}": {
            "litellm_provider": "openai",
            "mode": "chat",
        }
        for index in range(100)
    }
    reduced_payload = dict(list(original_payload.items())[:40])

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        payload = original_payload if requests == 1 else reduced_payload
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SystemCatalogProjectionService(
            session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            source_sync_service=LiteLLMSourceSyncService(
                session_manager=rdb_session_manager,
                snapshot_repository=LiteLLMSourceSnapshotRepository(),
                source_loader=LiteLLMSourceLoader(
                    http_client=client,
                    source_url="https://catalog.example.test/models.json",
                    litellm_version="1.91.3",
                ),
            ),
        )
        original = await service.sync_system_catalog(provider=LLMProvider.OPENAI)

        with pytest.raises(LiteLLMSourceSyncError):
            await service.sync_system_catalog(provider=LLMProvider.OPENAI)

        items = await service.list_system_catalogs()

    openai = next(item for item in items if item.provider == LLMProvider.OPENAI)
    assert openai.snapshot_id == original.snapshot_id
    assert openai.visible_count == original.visible_count
