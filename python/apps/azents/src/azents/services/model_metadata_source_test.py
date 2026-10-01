"""Pydantic ecosystem model metadata source adapter tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from genai_prices import UpdatePrices
from genai_prices.data_snapshot import DataSnapshot
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.services.model_metadata_source import (
    FetchedModelMetadataSource,
    GenAIPricesSourceAdapter,
    ModelMetadataSourceSyncError,
    ModelMetadataSourceSyncService,
    get_genai_prices_source_url,
    validate_genai_prices_source_url,
)


def _payload(count: int) -> ModelMetadataSourcePayload:
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
                        name=None,
                        match=SourceEqualsClause(value=f"gpt-test-{index}"),
                        context_window=128_000,
                        deprecated=False,
                        prices=[],
                    )
                    for index in range(count)
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


def test_default_source_url_comes_from_public_library(
    monkeypatch: MonkeyPatch,
) -> None:
    """The adapter delegates source URL ownership to the pinned library default."""
    monkeypatch.delenv("GENAI_PRICES_SOURCE_URL", raising=False)

    assert get_genai_prices_source_url().startswith(
        "https://raw.githubusercontent.com/pydantic/genai-prices/"
    )


async def test_fetch_uses_public_operation_without_global_update(
    monkeypatch: MonkeyPatch,
) -> None:
    """One explicit fetch returns canonical durable evidence."""
    captured: list[str] = []

    def fake_fetch(updater: UpdatePrices) -> DataSnapshot:
        captured.append(updater.url)
        return DataSnapshot(providers=[], from_auto_update=True)

    monkeypatch.setattr(UpdatePrices, "fetch", fake_fetch)
    adapter = GenAIPricesSourceAdapter(source_url="https://metadata.example/data.json")

    result = await adapter.fetch()

    assert captured == ["https://metadata.example/data.json"]
    assert result.source_kind == "genai_prices"
    assert result.source_schema_version == "1"
    assert result.provider_count == 0
    assert result.model_count == 0
    assert len(result.source_hash) == 64
    assert result.payload.providers == []


@pytest.mark.parametrize(
    "source_url",
    [
        "http://metadata.example/data.json",
        "file:///tmp/source.json",
        "https://user:password@metadata.example/data.json",
        "https://metadata.example/data.json?token=secret",
        "https://metadata.example/data.json#fragment",
    ],
)
def test_source_url_rejects_untrusted_or_credential_bearing_values(
    source_url: str,
) -> None:
    """Persisted source provenance cannot contain credentials or ambiguous URLs."""
    with pytest.raises(ValueError):
        validate_genai_prices_source_url(source_url)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://metadata.example/data.json",
        "http://127.0.0.1:8080/data.json",
        "http://[::1]:8080/data.json",
        "http://localhost:8080/data.json",
    ],
)
def test_source_url_accepts_https_and_loopback(source_url: str) -> None:
    """Production HTTPS and deterministic loopback endpoints remain valid."""
    validate_genai_prices_source_url(source_url)


async def test_sync_publishes_and_selects_current_source(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The Azents lifecycle owns durable publication and attempt state."""
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.fetch.return_value = _fetched(_payload(12))
    service = ModelMetadataSourceSyncService(
        session_manager=rdb_session_manager,
        repository=ModelMetadataSourceRepository(),
        source_adapter=adapter,
    )

    snapshot = await service.sync_current_source()

    assert snapshot.model_count == 12
    assert snapshot.source_kind == "genai_prices"
    assert await service.get_current_source() == snapshot
    adapter.fetch.assert_awaited_once_with()


async def test_sync_rejects_material_provider_reduction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A materially smaller supported provider cannot replace last success."""
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
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
            session,
            source_key="genai_prices",
        )
    assert attempt is not None
    assert attempt.finished_at is not None
    assert attempt.finished_at <= datetime.datetime.now(datetime.UTC)
    assert attempt.failure_code == "ModelMetadataSourceModelCountReduction"


async def test_adapter_converts_future_typed_variant_to_validation_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    """Unsupported upstream variants fail through the caught adapter boundary."""

    def fake_fetch(updater: UpdatePrices) -> DataSnapshot:
        return DataSnapshot(providers=[], from_auto_update=True)

    def unsupported_encoder(snapshot: DataSnapshot) -> ModelMetadataSourcePayload:
        raise AssertionError("future source variant")

    monkeypatch.setattr(UpdatePrices, "fetch", fake_fetch)
    monkeypatch.setattr(
        "azents.services.model_metadata_source.encode_data_snapshot",
        unsupported_encoder,
    )
    adapter = GenAIPricesSourceAdapter(source_url="https://metadata.example/data.json")

    with pytest.raises(ValueError, match="unsupported typed variant"):
        await adapter.fetch()


async def test_fetch_failure_immediately_fails_attempt_and_preserves_source(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A validation failure terminalizes the attempt and retains last success."""
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.source_url = "https://metadata.example/data.json"
    adapter.fetch.side_effect = [
        _fetched(_payload(12)),
        ValueError("unsupported typed variant"),
    ]
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
            session,
            source_key="genai_prices",
        )
    assert attempt is not None
    assert attempt.finished_at is not None
    assert attempt.failure_code == "ValueError"
