"""Validated source capture stays local and is shared across model budgets."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.engine.context.window import resolve_model_input_tokens
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LiteLLMSourceSnapshotRepository
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import make_test_model_metadata_service


class _CountingSourceRepository(LiteLLMSourceSnapshotRepository):
    """Count only the authoritative source DB read."""

    def __init__(self) -> None:
        self.capture_count = 0

    async def get_latest_authoritative(
        self, session: AsyncSession, *, source_key: str
    ) -> LiteLLMSourceSnapshot | None:
        self.capture_count += 1
        return await super().get_latest_authoritative(session, source_key=source_key)


async def test_capture_uses_only_local_validated_remote_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A later unvalidated package snapshot cannot become context authority."""
    repository = _CountingSourceRepository()
    async with rdb_session_manager() as session:
        valid = await repository.create_if_missing(
            session,
            source_key="litellm_model_cost",
            source_url="https://source.example.test/models.json",
            source_hash="validated-hash",
            model_count=2,
            litellm_version=None,
            loaded_source="remote",
            payload={
                "openai/main": {"max_input_tokens": 1_000_000},
                "anthropic/compaction": {"max_input_tokens": 300_000},
            },
        )
        await repository.create_if_missing(
            session,
            source_key="litellm_model_cost",
            source_url=None,
            source_hash="unvalidated-hash",
            model_count=1,
            litellm_version="historical-version",
            loaded_source="litellm_runtime",
            payload={"openai/main": {"max_input_tokens": 2_000_000}},
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
    assert captured.id == valid.id
    assert captured.source_hash == valid.source_hash
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
    snapshot = LiteLLMSourceSnapshot(
        id="source-id",
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="source-hash",
        model_count=1,
        litellm_version=None,
        loaded_source="remote",
        payload={"openai/alias": {"max_input_tokens": 256_000}},
        created_at=datetime.datetime.now(datetime.UTC),
    )
    service = make_test_model_metadata_service(snapshot=snapshot)
    captured = await service.capture()
    match = service.lookup(
        captured, provider=LLMProvider.OPENAI, model_identifier="alias"
    )
    assert captured is snapshot
    assert match is not None
    assert match.source_model_key == "openai/alias"
    assert match.metadata["max_input_tokens"] == 256_000
