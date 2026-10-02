"""Bounded inert collection and durable source lifecycle tests."""

import datetime
from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
)
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.catalog_source_collection import (
    DEFAULT_CATALOG_SOURCE_URL,
    CatalogCollectionPolicy,
)
from azents.services.model_metadata_source import (
    CatalogSourceAdapter,
    FetchedModelMetadataSource,
    ModelMetadataSourceSyncError,
    ModelMetadataSourceSyncService,
    get_catalog_collection_policy,
)
from azents.testing.model_metadata import make_test_source_payload


def _payload(count: int) -> CatalogSourcePayload:
    return make_test_source_payload(
        {
            f"gpt-test-{index}": {
                "litellm_provider": "openai",
                "max_input_tokens": 128_000,
                "mode": "chat",
            }
            for index in range(count)
        }
    )


def _fetched(payload: CatalogSourcePayload) -> FetchedModelMetadataSource:
    return FetchedModelMetadataSource(
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash,
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        raw_document_hash="a" * 64,
        etag=None,
    )


def test_source_configuration_is_owned_by_collection_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MODEL_CATALOG_SOURCE_URL", raising=False)
    policy = get_catalog_collection_policy()
    assert policy.source_url == DEFAULT_CATALOG_SOURCE_URL
    monkeypatch.setenv("MODEL_CATALOG_SOURCE_URL", "https://metadata.example/data.json")
    assert (
        get_catalog_collection_policy().source_url
        == "https://metadata.example/data.json"
    )


async def test_fetch_returns_typed_canonical_and_raw_provenance() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            content=b'{"literal":{"litellm_provider":"openai","mode":"chat"}}',
            headers={"etag": '"revision-1"'},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        adapter = CatalogSourceAdapter(
            http_client=client,
            policy=CatalogCollectionPolicy(
                source_url="https://metadata.example/data.json",
                max_bytes=10_000,
                timeout_seconds=2,
                allow_testenv_endpoint=False,
            ),
        )
        result = await adapter.fetch()
    assert len(requests) == 1
    assert result.source_kind == CATALOG_SOURCE_KIND
    assert result.model_count == 1
    assert result.provider_count == 1
    assert result.payload.models[0].source_key == "literal"
    assert result.source_hash == result.payload.content_hash
    assert len(result.raw_document_hash) == 64
    assert result.producer_version == f"sha256:{result.raw_document_hash}"
    assert result.etag == '"revision-1"'


async def test_sync_publishes_and_selects_current_source(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    adapter.fetch.return_value = _fetched(_payload(12))
    service = ModelMetadataSourceSyncService(
        session_manager=rdb_session_manager,
        repository=ModelMetadataSourceRepository(),
        source_adapter=adapter,
    )
    snapshot = await service.sync_current_source()
    assert snapshot.model_count == 12
    assert snapshot.source_kind == CATALOG_SOURCE_KIND
    assert await service.get_current_source() == snapshot
    adapter.fetch.assert_awaited_once_with()


async def test_sync_rejects_material_provider_reduction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    adapter = AsyncMock(spec=CatalogSourceAdapter)
    adapter.fetch.side_effect = [_fetched(_payload(30)), _fetched(_payload(3))]
    repository = ModelMetadataSourceRepository()
    service = ModelMetadataSourceSyncService(
        session_manager=rdb_session_manager,
        repository=repository,
        source_adapter=adapter,
    )
    original = await service.sync_current_source()
    with pytest.raises(ModelMetadataSourceSyncError, match="operator review"):
        await service.sync_current_source()
    assert await service.get_current_source() == original
    async with rdb_session_manager() as session:
        attempt = await repository.get_latest_attempt(
            session, source_key=CATALOG_SOURCE_KEY
        )
    assert attempt is not None
    assert attempt.finished_at is not None
    assert attempt.finished_at <= datetime.datetime.now(datetime.UTC)
    assert attempt.failure_code == "ModelMetadataSourceModelCountReduction"
    assert attempt.diagnostics is not None
    assert attempt.diagnostics["reduction_scope"] == "provider:openai"


@pytest.mark.parametrize(
    "failure", [ValueError("invalid data"), TimeoutError("deadline")]
)
async def test_fetch_failure_terminalizes_attempt_and_preserves_source(
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
    repository = ModelMetadataSourceRepository()
    service = ModelMetadataSourceSyncService(
        session_manager=rdb_session_manager,
        repository=repository,
        source_adapter=adapter,
    )
    original = await service.sync_current_source()
    with pytest.raises(ModelMetadataSourceSyncError):
        await service.sync_current_source()
    assert await service.get_current_source() == original
    async with rdb_session_manager() as session:
        attempt = await repository.get_latest_attempt(
            session, source_key=CATALOG_SOURCE_KEY
        )
    assert attempt is not None
    assert attempt.finished_at is not None
    assert attempt.failure_code == type(failure).__name__
    assert attempt.diagnostics is not None
    assert "invalid data" not in str(attempt.diagnostics)
