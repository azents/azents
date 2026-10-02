"""Validated exact-scoped source capture stays local across model budgets."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY, CATALOG_SOURCE_KIND
from azents.engine.context.window import resolve_model_input_tokens
from azents.rdb.models.model_metadata_source import RDBModelMetadataSourceSnapshot
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import (
    make_test_model_metadata_service,
    make_test_source_payload,
    make_test_source_snapshot,
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
    repository = _CountingSourceRepository()
    payload = make_test_source_payload(
        {
            "main": {"litellm_provider": "openai", "max_input_tokens": 1_000_000},
            "compaction": {
                "litellm_provider": "anthropic",
                "max_input_tokens": 300_000,
            },
        }
    )
    source_id = "s" * 32
    async with rdb_session_manager() as session:
        # The cutover migration seeds an inactive authority. Publish only after
        # its referenced validated snapshot exists, as the writer guard requires.
        authority = await repository.lock_authority(
            session, source_key=CATALOG_SOURCE_KEY
        )
        assert authority.current_snapshot_id is None
        session.add(
            RDBModelMetadataSourceSnapshot(
                id=source_id,
                source_key=CATALOG_SOURCE_KEY,
                source_kind=CATALOG_SOURCE_KIND,
                source_schema_version=payload.schema_version,
                source_url="https://source.example.test/models.json",
                source_hash=payload.content_hash,
                producer_name="LiteLLM public catalog",
                producer_version="fixture-data-1",
                provider_count=payload.provider_count,
                model_count=payload.model_count,
                payload=payload.model_dump(mode="json"),
            )
        )
        await session.flush()
        authority.current_snapshot_id = source_id
        await session.flush()
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
            captured, provider=LLMProvider.OPENAI, model_identifier="main"
        ),
        700_000,
    )
    compaction = resolve_model_input_tokens(
        None,
        None,
        service.maximum_input_tokens(
            captured, provider=LLMProvider.ANTHROPIC, model_identifier="compaction"
        ),
        None,
    )
    assert main.effective_input_tokens == 700_000
    assert compaction.effective_input_tokens == 300_000
    assert repository.capture_count == 1


async def test_absent_local_source_has_no_remote_or_package_fallback() -> None:
    service = make_test_model_metadata_service(snapshot=None)
    assert await service.capture() is None
    maximum = service.maximum_input_tokens(
        None, provider=LLMProvider.XAI_OAUTH, model_identifier="visible-model"
    )
    assert maximum is None
    limits = resolve_model_input_tokens(272_000, None, maximum, None)
    assert limits.max_input_tokens == 272_000


async def test_captured_identity_stays_stable_for_all_local_lookups() -> None:
    payload = make_test_source_payload(
        {"literal": {"litellm_provider": "openai", "max_input_tokens": 256_000}}
    )
    snapshot = make_test_source_snapshot(payload)
    service = make_test_model_metadata_service(snapshot=snapshot)
    captured = await service.capture()
    model = service.lookup(
        captured, provider=LLMProvider.OPENAI, model_identifier="literal"
    )
    assert captured is snapshot
    assert model is payload.models[0]
    assert model is not None
    assert model.provider == "openai"
    assert model.source_key == "literal"
    assert model.facts.max_input_tokens.value == 256_000
    assert (
        service.lookup(
            captured, provider=LLMProvider.CHATGPT_OAUTH, model_identifier="literal"
        )
        is None
    )
    assert (
        service.lookup(
            captured, provider=LLMProvider.OPENAI, model_identifier="openai/literal"
        )
        is None
    )
