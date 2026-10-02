"""Historical Memory preparation service tests."""

import datetime
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.openai_responses import OpenAIResponsesTextResult
from azents.engine.events.types import TokenUsagePayload
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_text import ProviderTextResult
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.preparation import (
    HistoricalMemoryOutputError,
    HistoricalMemoryPreparationService,
    _guard_summary,
    generate_historical_memory_with_model,
)
from azents.testing.model_stream import make_test_model_stream_watchdog

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_TEST_WATCHDOG = make_test_model_stream_watchdog()
_SDK_FACTORIES = ModelSDKFactories(
    openai_responses=AsyncMock(),
    provider_model=AsyncMock(),
)
_ASSEMBLY_METADATA = ModelAssemblyMetadata(
    model_developer=LLMModelDeveloper.ANTHROPIC,
    model_family="claude",
    capabilities=ModelCapabilities(),
)


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        source_session_id="s" * 32,
        agent_id="a" * 32,
        workspace_id="w" * 32,
        source_activity_at=_NOW - datetime.timedelta(hours=8),
        source_tail_event_id="e" * 32,
        source_title="Prior work",
        model_operation_state=SimpleNamespace(),
    )


@pytest.mark.parametrize(
    "sampled_at",
    [None, datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)],
)
async def test_prepare_agent_publishes_bounded_batch_result(
    monkeypatch: pytest.MonkeyPatch,
    sampled_at: datetime.datetime | None,
) -> None:
    """Successful model output publishes source markers and summary atomically."""
    preparation_repository = AsyncMock()
    preparation_repository.begin_next.side_effect = [_source(), None]
    historical_repository = AsyncMock()
    historical_repository.publish_completed.return_value = SimpleNamespace(
        summary="Useful summary"
    )
    service = HistoricalMemoryPreparationService(
        preparation_repository=preparation_repository,
        historical_repository=historical_repository,
        message_repository=AsyncMock(),
        model_stream_watchdog=AsyncMock(),
        model_metadata_service=AsyncMock(),
        sdk_factories=_SDK_FACTORIES,
        session_manager=AsyncMock(),
        model_read_repository=EngineModelReadRepository(
            session_manager=(AsyncMock()).session_manager,
            integration_repository=(AsyncMock()).integration_repository,
        ),
        runtime_token_resolver=EngineRuntimeTokenResolver(
            chatgpt_repository=AsyncMock(),
            xai_repository=XaiOAuthRuntimeRepository(
                session_manager=(AsyncMock()).session_manager,
                integration_repository=(AsyncMock()).integration_repository,
            ),
            kimi_repository=KimiOAuthRuntimeRepository(
                session_manager=(AsyncMock()).session_manager,
                integration_repository=(AsyncMock()).integration_repository,
            ),
        ),
    )
    prepare_source = AsyncMock(return_value="Useful summary")
    monkeypatch.setattr(service, "_prepare_source", prepare_source)

    summary = await service.prepare_agent(
        agent_id="a" * 32,
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
        now=sampled_at,
    )

    assert summary.attempted == 1
    assert summary.prepared == 1
    assert summary.empty == 0
    assert summary.failed == 0
    historical_repository.publish_completed.assert_awaited_once()
    completion = historical_repository.publish_completed.await_args.kwargs["completion"]
    assert completion.source_activity_at == _NOW - datetime.timedelta(hours=8)
    assert completion.source_tail_event_id == "e" * 32
    assert completion.summary == "Useful summary"
    if sampled_at is not None:
        assert completion.prepared_at == sampled_at
        assert all(
            call.kwargs["attempted_at"] == sampled_at
            and call.kwargs["inactive_before"]
            == sampled_at - datetime.timedelta(hours=6)
            for call in preparation_repository.begin_next.await_args_list
        )


async def test_explicit_sampling_does_not_extend_real_execution_deadline() -> None:
    """An old domain sample cannot run work after a wallclock deadline."""
    repository = AsyncMock()
    service = HistoricalMemoryPreparationService(
        preparation_repository=repository,
        historical_repository=AsyncMock(),
        message_repository=AsyncMock(),
        model_stream_watchdog=AsyncMock(),
        model_metadata_service=AsyncMock(),
        sdk_factories=_SDK_FACTORIES,
        session_manager=AsyncMock(),
        model_read_repository=EngineModelReadRepository(
            session_manager=(AsyncMock()).session_manager,
            integration_repository=(AsyncMock()).integration_repository,
        ),
        runtime_token_resolver=EngineRuntimeTokenResolver(
            chatgpt_repository=AsyncMock(),
            xai_repository=XaiOAuthRuntimeRepository(
                session_manager=(AsyncMock()).session_manager,
                integration_repository=(AsyncMock()).integration_repository,
            ),
            kimi_repository=KimiOAuthRuntimeRepository(
                session_manager=(AsyncMock()).session_manager,
                integration_repository=(AsyncMock()).integration_repository,
            ),
        ),
    )
    summary = await service.prepare_agent(
        agent_id="a" * 32,
        deadline=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1),
        now=datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
    )
    assert summary.attempted == 0
    repository.begin_next.assert_not_awaited()
    with pytest.raises(ValueError, match="aware"):
        await service.prepare_agent(
            agent_id="a" * 32,
            deadline=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=1),
            now=datetime.datetime(2099, 1, 1),
        )
    repository.begin_next.assert_not_awaited()


async def test_generate_historical_memory_decodes_strict_json(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The model boundary accepts only the strict summary object."""
    usage = TokenUsagePayload(
        prompt_tokens=40,
        completion_tokens=10,
        total_tokens=50,
        raw={},
        cached_tokens=5,
        cost_usd=0.01,
    )
    call = AsyncMock(
        return_value=OpenAIResponsesTextResult(
            text='{"summary":"Useful history"}',
            usage=usage,
        )
    )
    monkeypatch.setattr(
        (
            "azents.services.historical_memory.preparation."
            "call_openai_responses_text_with_usage"
        ),
        call,
    )
    with caplog.at_level(logging.INFO):
        summary = await generate_historical_memory_with_model(
            sdk_factories=_SDK_FACTORIES,
            provider=LLMProvider.OPENAI,
            provider_integration_id="i" * 32,
            model="gpt-test",
            credential_kwargs={},
            assembly_metadata=None,
            source_text="[User]\nKeep the decision.",
            source_session_id="s" * 32,
            watchdog=_TEST_WATCHDOG,
        )

    assert summary == "Useful history"
    call.assert_awaited_once()
    usage_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Historical Memory model usage"
    )
    usage_fields = vars(usage_record)
    assert usage_fields["call_kind"] == "historical_memory"
    assert usage_fields["prompt_tokens"] == 40
    assert usage_fields["completion_tokens"] == 10
    assert usage_fields["cost_usd"] == 0.01
    assert "raw" not in usage_fields
    assert "source_text" not in usage_fields

    call.return_value = OpenAIResponsesTextResult(
        text='{"summary":"ok","extra":true}',
        usage=None,
    )
    with pytest.raises(HistoricalMemoryOutputError, match="invalid_output"):
        await generate_historical_memory_with_model(
            sdk_factories=_SDK_FACTORIES,
            provider=LLMProvider.OPENAI,
            provider_integration_id="i" * 32,
            model="gpt-test",
            credential_kwargs={},
            assembly_metadata=None,
            source_text="[User]\nKeep the decision.",
            source_session_id="s" * 32,
            watchdog=_TEST_WATCHDOG,
        )


async def test_generate_historical_memory_attributes_litellm_stream_usage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LiteLLM terminal usage is attributed to the Historical Memory call."""
    usage = TokenUsagePayload(
        prompt_tokens=60,
        completion_tokens=15,
        total_tokens=75,
        raw={},
        reasoning_tokens=4,
        cost_usd=0.02,
    )
    call = AsyncMock(
        return_value=ProviderTextResult(
            text='{"summary":"LiteLLM history"}',
            usage=usage,
        )
    )
    monkeypatch.setattr(
        "azents.services.historical_memory.preparation.call_provider_text_with_usage",
        call,
    )
    with caplog.at_level(logging.INFO):
        summary = await generate_historical_memory_with_model(
            sdk_factories=_SDK_FACTORIES,
            provider=LLMProvider.ANTHROPIC,
            provider_integration_id="i" * 32,
            model="anthropic/test",
            credential_kwargs={},
            assembly_metadata=_ASSEMBLY_METADATA,
            source_text="[User]\nKeep the decision.",
            source_session_id="s" * 32,
            watchdog=_TEST_WATCHDOG,
        )

    assert summary == "LiteLLM history"
    call.assert_awaited_once()
    usage_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Historical Memory model usage"
    )
    usage_fields = vars(usage_record)
    assert usage_fields["call_kind"] == "historical_memory"
    assert usage_fields["provider"] == LLMProvider.ANTHROPIC.value
    assert usage_fields["reasoning_tokens"] == 4


def test_summary_guard_truncates_at_valid_utf8_boundary() -> None:
    """Oversized summaries stay within 9,000 bytes with a visible note."""
    guarded = _guard_summary("가" * 4_000)

    assert len(guarded.encode()) <= 9_000
    assert guarded.endswith("[Truncated by Azents Historical Memory guard.]")
