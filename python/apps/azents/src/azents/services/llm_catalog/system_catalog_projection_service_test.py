"""Active replacement system catalog projection service tests."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogPurpose, LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.llm_catalog import SystemCatalogProjectionService
from azents.services.model_metadata_projection import (
    SystemCatalogShadowProjectionService,
)
from azents.services.model_metadata_source import (
    FetchedModelMetadataSource,
    GenAIPricesSourceAdapter,
    ModelMetadataSourceSyncError,
    ModelMetadataSourceSyncService,
)


def _payload(model_count: int) -> ModelMetadataSourcePayload:
    return ModelMetadataSourcePayload(
        providers=[
            SourceProviderRecord(
                id="openai",
                name="OpenAI",
                api_pattern=r"https://api\.openai\.com/.*",
                model_match=None,
                provider_match=None,
                fallback_model_providers=None,
                models=[
                    SourceModelRecord(
                        id=f"gpt-test-{index}",
                        name=f"GPT Test {index}",
                        match=SourceEqualsClause(value=f"gpt-test-{index}"),
                        context_window=128_000,
                        deprecated=False,
                        prices=[],
                    )
                    for index in range(model_count)
                ],
            )
        ]
    )


def _fetched(payload: ModelMetadataSourcePayload) -> FetchedModelMetadataSource:
    return FetchedModelMetadataSource(
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
    )


def _service(
    *,
    rdb_session_manager: SessionManager[AsyncSession],
    adapter: GenAIPricesSourceAdapter,
    catalog_repository: LLMCatalogRepository,
) -> SystemCatalogProjectionService:
    replacement = SystemCatalogShadowProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=catalog_repository,
        source_sync_service=ModelMetadataSourceSyncService(
            session_manager=rdb_session_manager,
            repository=ModelMetadataSourceRepository(),
            source_adapter=adapter,
        ),
    )
    return SystemCatalogProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=catalog_repository,
        replacement_projection_service=replacement,
    )


async def test_system_catalogs_exclude_integration_scoped_providers(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Expose only providers with system-owned model visibility."""
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    service = _service(
        rdb_session_manager=rdb_session_manager,
        adapter=adapter,
        catalog_repository=LLMCatalogRepository(),
    )

    items = await service.list_system_catalogs()

    assert {item.provider for item in items} == {
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    }
    adapter.fetch.assert_not_awaited()


async def test_blocked_source_does_not_replace_current_system_catalog(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Retain the published replacement projection when source ingestion is blocked."""
    original_payload = _payload(100)
    reduced_payload = _payload(40)
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.fetch.side_effect = [
        _fetched(original_payload),
        _fetched(reduced_payload),
    ]
    catalog_repository = LLMCatalogRepository()
    async with rdb_session_manager() as session:
        catalog = await catalog_repository.ensure_system_catalog(
            session,
            provider=LLMProvider.OPENAI,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        legacy_snapshot_id = await catalog_repository.replace_current_snapshot(
            session,
            catalog=catalog,
            source_snapshot_id=None,
            entries=[],
            diagnostics={"authority": "legacy"},
        )
    service = _service(
        rdb_session_manager=rdb_session_manager,
        adapter=adapter,
        catalog_repository=catalog_repository,
    )
    first = await service.sync_system_catalog(provider=LLMProvider.OPENAI)

    with pytest.raises(ModelMetadataSourceSyncError, match="operator review"):
        await service.sync_system_catalog(provider=LLMProvider.OPENAI)

    items = await service.list_system_catalogs()
    openai = next(item for item in items if item.provider is LLMProvider.OPENAI)
    assert first.snapshot_id != legacy_snapshot_id
    assert openai.snapshot_id == first.snapshot_id
