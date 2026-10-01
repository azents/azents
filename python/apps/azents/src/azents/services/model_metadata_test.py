"""Validated generic source capture stays local across model budgets."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.engine.context.window import resolve_model_input_tokens
from azents.rdb.models.model_metadata_source import (
    RDBModelMetadataSource,
    RDBModelMetadataSourceSnapshot,
)
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import make_test_model_metadata_service


def _provider(
    provider_id: str,
    model_id: str,
    context_window: int,
) -> SourceProviderRecord:
    return SourceProviderRecord(
        id=provider_id,
        name=provider_id,
        api_pattern=f"https://{provider_id}.example/.*",
        model_match=None,
        provider_match=None,
        fallback_model_providers=None,
        models=[
            SourceModelRecord(
                id=model_id,
                name=model_id,
                match=SourceEqualsClause(value=model_id),
                context_window=context_window,
                deprecated=False,
                prices=[],
            )
        ],
    )


def _payload() -> ModelMetadataSourcePayload:
    return ModelMetadataSourcePayload(
        providers=[
            _provider("openai", "main", 1_000_000),
            _provider("anthropic", "compaction", 300_000),
        ]
    )


class _CountingSourceRepository(ModelMetadataSourceRepository):
    """Count only the authoritative source DB read."""

    def __init__(self) -> None:
        self.capture_count = 0

    async def get_current(
        self, session: AsyncSession, *, source_key: str
    ) -> ModelMetadataSourceSnapshot | None:
        self.capture_count += 1
        return await super().get_current(session, source_key=source_key)


async def test_capture_uses_only_local_validated_remote_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only the explicitly selected generic source becomes context authority."""
    repository = _CountingSourceRepository()
    payload = _payload()
    source_id = "s" * 32
    async with rdb_session_manager() as session:
        session.add(
            RDBModelMetadataSource(
                source_key="genai_prices",
                current_snapshot_id=source_id,
                latest_attempt_id=None,
            )
        )
        session.add(
            RDBModelMetadataSourceSnapshot(
                id=source_id,
                source_key="genai_prices",
                source_kind="genai_prices",
                source_schema_version="1",
                source_url="https://source.example.test/models.json",
                source_hash=payload.content_hash(),
                producer_name="genai-prices",
                producer_version="0.1.9",
                provider_count=payload.provider_count,
                model_count=payload.model_count,
                payload=payload.model_dump(mode="json"),
            )
        )
    service = ModelMetadataService(
        session_manager=rdb_session_manager,
        source_snapshot_repository=repository,
    )
    assert (
        await service.capture_for_context(capability_maximums=[128_000, 272_000])
        is None
    )
    assert repository.capture_count == 0
    captured = await service.capture_for_context(capability_maximums=[None, None])
    assert captured is not None
    assert captured.id == source_id
    main = resolve_model_input_tokens(
        128_000,
        None,
        service.maximum_input_tokens(
            captured,
            provider=LLMProvider.OPENAI,
            model_identifier="main",
        ),
        700_000,
    )
    compaction = resolve_model_input_tokens(
        None,
        None,
        service.maximum_input_tokens(
            captured,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="compaction",
        ),
        None,
    )
    assert main.effective_input_tokens == 700_000
    assert compaction.effective_input_tokens == 300_000
    assert repository.capture_count == 1


async def test_absent_local_source_has_no_remote_or_package_fallback() -> None:
    """Missing evidence remains unknown before stable context math resolves it."""
    service = make_test_model_metadata_service(snapshot=None)
    assert await service.capture() is None
    maximum = service.maximum_input_tokens(
        None, provider=LLMProvider.XAI_OAUTH, model_identifier="visible-model"
    )
    assert maximum is None
    limits = resolve_model_input_tokens(272_000, None, maximum, None)
    assert limits.max_input_tokens == 272_000


async def test_captured_identity_stays_stable_for_all_local_lookups() -> None:
    """Source identity accompanies a model match without another read."""
    payload = ModelMetadataSourcePayload(
        providers=[_provider("openai", "alias", 256_000)]
    )
    snapshot = ModelMetadataSourceSnapshot(
        id="source-id",
        source_key="genai_prices",
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://source.example.test/models.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    service = make_test_model_metadata_service(snapshot=snapshot)
    captured = await service.capture()
    match = service.lookup(
        captured, provider=LLMProvider.OPENAI, model_identifier="alias"
    )
    assert captured is snapshot
    assert match is not None
    assert match.provider.id == "openai"
    assert match.model.id == "alias"
    assert match.model.context_window == 256_000
