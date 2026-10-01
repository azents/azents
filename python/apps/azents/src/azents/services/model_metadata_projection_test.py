"""Replacement model metadata shadow projection tests."""

import datetime
import importlib.metadata
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMProvider,
)
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.rdb.models.llm_catalog import RDBLLMCatalog, RDBLLMCatalogSnapshot
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata_projection import (
    ModelMetadataProjectionError,
    SystemCatalogShadowProjectionService,
    project_system_shadow_entries,
    projection_fingerprint,
)
from azents.services.model_metadata_source import (
    FetchedModelMetadataSource,
    GenAIPricesSourceAdapter,
    ModelMetadataSourceSyncError,
    ModelMetadataSourceSyncService,
)


def _provider(
    provider_id: str, models: list[SourceModelRecord]
) -> SourceProviderRecord:
    return SourceProviderRecord(
        id=provider_id,
        name=provider_id,
        api_pattern=f"https://{provider_id}.example/.*",
        model_match=None,
        provider_match=None,
        fallback_model_providers=None,
        models=models,
    )


def _model(
    identifier: str,
    *,
    context_window: int = 128_000,
    deprecated: bool = False,
) -> SourceModelRecord:
    return SourceModelRecord(
        id=identifier,
        name=identifier.upper(),
        match=SourceEqualsClause(value=identifier),
        context_window=context_window,
        deprecated=deprecated,
        prices=[],
    )


def _payload() -> ModelMetadataSourcePayload:
    return ModelMetadataSourcePayload(
        providers=[
            _provider(
                "openai",
                [
                    _model("gpt-5.4"),
                    _model("text-embedding-4"),
                ],
            ),
            _provider("anthropic", [_model("claude-sonnet-4-6")]),
            _provider(
                "google",
                [
                    _model("gemini-3.1-pro"),
                    _model("claude-sonnet-4-6"),
                ],
            ),
        ]
    )


def _source(payload: ModelMetadataSourcePayload) -> ModelMetadataSourceSnapshot:
    return ModelMetadataSourceSnapshot(
        id="s" * 32,
        source_key="genai_prices",
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        created_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def test_projection_uses_runtime_profile_and_source_neutral_metadata() -> None:
    """Execution capabilities come from the shared resolver, not source flags."""
    entries = project_system_shadow_entries(
        provider=LLMProvider.OPENAI,
        source=_source(_payload()),
    )
    by_id = {entry.provider_model_identifier: entry for entry in entries}

    gpt = by_id["gpt-5.4"]
    assert gpt.visibility_status is LLMCatalogEntryVisibility.SELECTABLE
    assert gpt.normalized_capabilities["tool_calling"]["supported"] is True
    assert gpt.normalized_capabilities["reasoning"]["supported"] is True
    assert gpt.normalized_capabilities["context_window"]["max_input_tokens"] == (
        128_000
    )
    assert gpt.source_metadata == {
        "source_kind": "genai_prices",
        "source_provider_id": "openai",
        "source_model_id": "gpt-5.4",
        "source_hash": _source(_payload()).source_hash,
        "context_window": 128_000,
        "deprecated": False,
    }
    assert gpt.projection_metadata is not None
    assert "litellm_provider" not in gpt.projection_metadata

    embedding = by_id["text-embedding-4"]
    assert embedding.visibility_status is LLMCatalogEntryVisibility.HIDDEN
    assert embedding.hidden_reason == "unsupported_model_kind"


def test_google_system_projection_excludes_vertex_anthropic_family() -> None:
    """The direct Gemini catalog does not expose Vertex-hosted Claude records."""
    entries = project_system_shadow_entries(
        provider=LLMProvider.GOOGLE_GEMINI,
        source=_source(_payload()),
    )
    by_id = {entry.provider_model_identifier: entry for entry in entries}

    assert by_id["gemini-3.1-pro"].visibility_status is (
        LLMCatalogEntryVisibility.SELECTABLE
    )
    assert by_id["claude-sonnet-4-6"].hidden_reason == ("unsupported_model_family")


def test_projection_fingerprint_uses_installed_dependency_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dependency upgrade reprojections unchanged normalized source content."""
    source = _source(_payload())
    real_version = importlib.metadata.version
    genai_prices_version = "0.1.9"

    def dependency_version(package: str) -> str:
        if package == "genai-prices":
            return genai_prices_version
        return real_version(package)

    monkeypatch.setattr(
        "azents.services.model_metadata_projection.importlib.metadata.version",
        dependency_version,
    )
    first = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)
    genai_prices_version = "0.2.0"
    second = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)

    assert source.producer_version == "0.1.9"
    assert first != second


@pytest.mark.parametrize("provider_id", [None, "empty"])
def test_projection_rejects_missing_or_empty_required_provider(
    provider_id: str | None,
) -> None:
    """A required provider must produce a non-empty complete candidate."""
    payload = _payload()
    source_providers = payload.providers
    providers = [
        provider for provider in source_providers if provider.id != "anthropic"
    ]
    if provider_id == "empty":
        providers.append(_provider("anthropic", []))
    incomplete = payload.model_copy(update={"providers": providers})

    with pytest.raises(ModelMetadataProjectionError, match="anthropic"):
        project_system_shadow_entries(
            provider=LLMProvider.ANTHROPIC,
            source=_source(incomplete),
        )


async def test_shadow_service_creates_non_current_candidates(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Shadow orchestration persists candidates without current or rollback pointers."""
    payload = _payload()
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.fetch.return_value = FetchedModelMetadataSource(
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
    source_service = ModelMetadataSourceSyncService(
        session_manager=rdb_session_manager,
        repository=ModelMetadataSourceRepository(),
        source_adapter=adapter,
    )
    service = SystemCatalogShadowProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=LLMCatalogRepository(),
        source_sync_service=source_service,
    )

    summaries = await service.prepare_candidates()

    assert {summary.provider for summary in summaries} == {
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    }
    async with rdb_session_manager() as session:
        catalogs = list(
            (
                await session.execute(
                    sa.select(RDBLLMCatalog).order_by(RDBLLMCatalog.provider)
                )
            ).scalars()
        )
        candidates = list(
            (await session.execute(sa.select(RDBLLMCatalogSnapshot))).scalars()
        )
    assert len(catalogs) == 3
    assert all(catalog.current_snapshot_id is None for catalog in catalogs)
    assert all(catalog.rollback_snapshot_id is None for catalog in catalogs)
    assert len(candidates) == 3
    assert all(
        candidate.metadata_source_snapshot_id is not None for candidate in candidates
    )
    assert all(candidate.genai_prices_version == "0.1.9" for candidate in candidates)


async def test_shadow_service_preflights_all_required_providers_before_candidates(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Incomplete source evidence creates no partial catalog candidates."""
    payload = _payload()
    incomplete = payload.model_copy(
        update={
            "providers": [
                provider for provider in payload.providers if provider.id != "google"
            ]
        }
    )
    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.fetch.return_value = FetchedModelMetadataSource(
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=incomplete.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=incomplete.provider_count,
        model_count=incomplete.model_count,
        payload=incomplete,
    )
    service = SystemCatalogShadowProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=LLMCatalogRepository(),
        source_sync_service=ModelMetadataSourceSyncService(
            session_manager=rdb_session_manager,
            repository=ModelMetadataSourceRepository(),
            source_adapter=adapter,
        ),
    )

    with pytest.raises(ModelMetadataProjectionError, match="google_gemini"):
        await service.prepare_candidates()

    async with rdb_session_manager() as session:
        catalogs = list((await session.execute(sa.select(RDBLLMCatalog))).scalars())
        candidates = list(
            (await session.execute(sa.select(RDBLLMCatalogSnapshot))).scalars()
        )
    assert catalogs == []
    assert candidates == []


async def test_source_fetch_failure_preserves_existing_catalog_pointer(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Replacement collection failure cannot alter current catalog authority."""
    catalog_repository = LLMCatalogRepository()
    async with rdb_session_manager() as session:
        catalog = await catalog_repository.ensure_system_catalog(
            session,
            provider=LLMProvider.OPENAI,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        current_snapshot_id = await catalog_repository.replace_current_snapshot(
            session,
            catalog=catalog,
            source_snapshot_id=None,
            entries=[],
            diagnostics={"authority": "legacy"},
        )

    adapter = AsyncMock(spec=GenAIPricesSourceAdapter)
    adapter.source_url = "https://metadata.example/data.json"
    adapter.fetch.side_effect = ValueError("malformed source")
    service = SystemCatalogShadowProjectionService(
        session_manager=rdb_session_manager,
        catalog_repository=catalog_repository,
        source_sync_service=ModelMetadataSourceSyncService(
            session_manager=rdb_session_manager,
            repository=ModelMetadataSourceRepository(),
            source_adapter=adapter,
        ),
    )

    with pytest.raises(ModelMetadataSourceSyncError):
        await service.prepare_candidates()

    async with rdb_session_manager() as session:
        refreshed = await session.get(RDBLLMCatalog, catalog.id)
        snapshots = list(
            (
                await session.execute(
                    sa.select(RDBLLMCatalogSnapshot).where(
                        RDBLLMCatalogSnapshot.catalog_id == catalog.id
                    )
                )
            ).scalars()
        )
    assert refreshed is not None
    assert refreshed.current_snapshot_id == current_snapshot_id
    assert refreshed.rollback_snapshot_id is None
    assert [snapshot.id for snapshot in snapshots] == [current_snapshot_id]
