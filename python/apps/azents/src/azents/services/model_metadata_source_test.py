"""Bounded source normalization and atomic current publication tests."""

import datetime
from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogPurpose, LLMProvider
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
)
from azents.core.model_metadata_collection_data import FetchedModelMetadataSource
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.model_metadata_operations import (
    ModelMetadataSourceOperations,
    SourceSyncAlreadyRunning,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.catalog_source_collection import (
    DEFAULT_CATALOG_SOURCE_URL,
    CatalogCollectionPolicy,
)
from azents.services.model_metadata_source import (
    CatalogSourceAdapter,
    ModelMetadataSourceSyncBusy,
    ModelMetadataSourceSyncError,
    ModelMetadataSourceSyncService,
    get_catalog_collection_policy,
)
from azents.testing.model_metadata import make_test_source, make_test_source_payload


def _payload(count: int) -> CatalogSourcePayload:
    return make_test_source_payload(
        {
            **{
                f"gpt-test-{index}": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 128_000,
                    "mode": "chat",
                }
                for index in range(count)
            },
            "claude-test": {"litellm_provider": "anthropic", "mode": "chat"},
            "gemini/gemini-test": {"litellm_provider": "gemini", "mode": "chat"},
        }
    )


def _fetched(payload: CatalogSourcePayload) -> FetchedModelMetadataSource:
    source = make_test_source(payload)
    return FetchedModelMetadataSource(
        source_kind=source.source_kind,
        source_schema_version=source.source_schema_version,
        source_url=source.source_url,
        producer_name=source.producer_name,
        producer_version=source.producer_version,
        provider_count=source.provider_count,
        model_count=source.model_count,
        payload=source.payload,
        models=source.models,
        collected_at=source.collected_at,
    )


def _service(
    manager: SessionManager[AsyncSession], adapter: CatalogSourceAdapter
) -> ModelMetadataSourceSyncService:
    return ModelMetadataSourceSyncService(
        operations=ModelMetadataSourceOperations(
            session_manager=manager,
            repository=ModelMetadataSourceRepository(),
            catalog_repository=LLMCatalogRepository(),
        ),
        source_adapter=adapter,
    )


def test_source_configuration_is_owned_by_collection_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MODEL_CATALOG_SOURCE_URL", raising=False)
    assert get_catalog_collection_policy().source_url == DEFAULT_CATALOG_SOURCE_URL
    monkeypatch.setenv("MODEL_CATALOG_SOURCE_URL", "https://metadata.example/data.json")
    assert (
        get_catalog_collection_policy().source_url
        == "https://metadata.example/data.json"
    )


async def test_fetch_normalizes_once_and_returns_descriptive_provenance() -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=b'{"literal":{"litellm_provider":"openai","mode":"chat","input_cost_per_token":0.000001}}',
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        result = await CatalogSourceAdapter(
            http_client=client,
            policy=CatalogCollectionPolicy(
                source_url="https://metadata.example/data.json",
                max_bytes=10_000,
                timeout_seconds=2,
                allow_testenv_endpoint=False,
            ),
        ).fetch()
    assert result.source_kind == CATALOG_SOURCE_KIND
    assert result.model_count == result.provider_count == 1
    assert result.payload.models[0].source_key == "literal"
    assert result.producer_version is None
    assert result.models[0].pricing.rules is not None
    assert result.models[0].pricing.collected_at == result.collected_at
    assert result.collected_at.utcoffset() is not None


async def test_busy_atomic_claim_performs_no_collection() -> None:
    operations = AsyncMock(spec=ModelMetadataSourceOperations)
    operations.begin_sync.return_value = SourceSyncAlreadyRunning("catalog", "work")
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    service = ModelMetadataSourceSyncService(
        operations=operations, source_adapter=adapter
    )
    with pytest.raises(ModelMetadataSourceSyncBusy):
        await service.sync_current_source()
    adapter.fetch.assert_not_awaited()
    operations.publish.assert_not_awaited()


async def test_sync_publishes_source_and_affected_systems(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    adapter.fetch.return_value = _fetched(_payload(12))
    service = _service(rdb_session_manager, adapter)
    source = await service.sync_current_source()
    assert source.model_count == 14
    assert source.source_kind == CATALOG_SOURCE_KIND
    assert await service.get_current_source() == source
    adapter.fetch.assert_awaited_once_with()
    async with rdb_session_manager() as session:
        for provider in (
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC,
            LLMProvider.GOOGLE_GEMINI,
        ):
            owner = await service.operations.catalog_repository.get_system_catalog(
                session,
                provider=provider,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            assert owner is not None and owner.last_success_at is not None
            assert (
                owner.sync_status is not None
                and owner.sync_status.status.value == "succeeded"
            )


async def test_sync_rejects_material_provider_reduction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    adapter.policy = CatalogCollectionPolicy(
        source_url="https://metadata.example/data.json",
        max_bytes=10_000,
        timeout_seconds=2,
        allow_testenv_endpoint=False,
    )
    adapter.fetch.side_effect = [_fetched(_payload(30)), _fetched(_payload(3))]
    service = _service(rdb_session_manager, adapter)
    original = await service.sync_current_source()
    with pytest.raises(ModelMetadataSourceSyncError, match="operator review"):
        await service.sync_current_source()
    assert await service.get_current_source() == original
    async with rdb_session_manager() as session:
        status = await service.operations.repository.get_sync_status(
            session, source_key=CATALOG_SOURCE_KEY
        )
    assert status is not None and status.finished_at is not None
    assert status.finished_at <= datetime.datetime.now(datetime.UTC)
    assert status.failure_code == "ModelMetadataSourceModelCountReduction"
    assert (
        status.diagnostics is not None
        and status.diagnostics["reduction_scope"] == "provider:openai"
    )


@pytest.mark.parametrize(
    "failure", [ValueError("invalid data"), TimeoutError("deadline")]
)
async def test_fetch_failure_updates_latest_status_and_preserves_current_data(
    rdb_session_manager: SessionManager[AsyncSession],
    failure: ValueError | TimeoutError,
) -> None:
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    adapter.policy = CatalogCollectionPolicy(
        source_url="https://metadata.example/data.json",
        max_bytes=10_000,
        timeout_seconds=2,
        allow_testenv_endpoint=False,
    )
    adapter.fetch.side_effect = [_fetched(_payload(12)), failure]
    service = _service(rdb_session_manager, adapter)
    original = await service.sync_current_source()
    with pytest.raises(ModelMetadataSourceSyncError):
        await service.sync_current_source()
    assert await service.get_current_source() == original
    async with rdb_session_manager() as session:
        status = await service.operations.repository.get_sync_status(
            session, source_key=CATALOG_SOURCE_KEY
        )
    assert status is not None and status.finished_at is not None
    assert status.failure_code == type(failure).__name__
    assert status.diagnostics is not None and "invalid data" not in str(
        status.diagnostics
    )
