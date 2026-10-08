"""Historical Memory preparation publication and native model boundary contracts."""

import datetime
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Success
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseStreamEvent,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)
from pydantic import TypeAdapter

from azents.core.config import Config
from azents.core.enums import EventKind, LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.events.model_messages import transient_model_message
from azents.engine.events.openai_responses import OpenAIResponsesWebSocketConnection
from azents.engine.events.types import Event, UserMessagePayload
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.provider_model_operation import prepare_model_operation_request
from azents.engine.run.resolve import ResolvedModelCandidateRuntime
from azents.repos.engine_read import EngineModelReadRepository
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.preparation import (
    _HISTORICAL_MEMORY_PROMPT,
    HistoricalMemoryOutputError,
    HistoricalMemoryPreparationService,
    _guard_summary,
    generate_historical_memory_with_model,
)
from azents.testing.model_selection import (
    make_test_model_candidate,
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_TEST_WATCHDOG = make_test_model_stream_watchdog()
_SDK_FACTORIES = ModelSDKFactories(
    openai_responses=AsyncMock(), provider_model=AsyncMock()
)
_CONFIG = MagicMock(spec=Config)
_CONFIG.openai_responses_websocket_enabled = False


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


def _service(
    repository: AsyncMock, historical: AsyncMock
) -> HistoricalMemoryPreparationService:
    return HistoricalMemoryPreparationService(
        preparation_repository=repository,
        historical_repository=historical,
        source_events_repository=AsyncMock(),
        model_read_repository=AsyncMock(spec=EngineModelReadRepository),
        runtime_token_resolver=AsyncMock(spec=EngineRuntimeTokenResolver),
        model_stream_watchdog=AsyncMock(),
        model_metadata_service=AsyncMock(),
        sdk_factories=_SDK_FACTORIES,
        config=_CONFIG,
    )


@pytest.mark.parametrize(
    "sampled_at", [None, datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)]
)
async def test_prepare_agent_publishes_bounded_batch_result(
    monkeypatch: pytest.MonkeyPatch,
    sampled_at: datetime.datetime | None,
) -> None:
    repository = AsyncMock()
    repository.begin_next.side_effect = [_source(), None]
    historical = AsyncMock()
    historical.publish_completed.return_value = SimpleNamespace(
        summary="Useful summary"
    )
    service = _service(repository, historical)
    monkeypatch.setattr(
        service, "_prepare_source", AsyncMock(return_value="Useful summary")
    )
    summary = await service.prepare_agent(
        agent_id="a" * 32,
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
        now=sampled_at,
    )
    assert summary.attempted == summary.prepared == 1
    assert summary.empty == summary.failed == 0
    historical.publish_completed.assert_awaited_once()
    completion = historical.publish_completed.await_args.kwargs["completion"]
    assert completion.source_activity_at == _NOW - datetime.timedelta(hours=8)
    assert completion.source_tail_event_id == "e" * 32
    assert completion.summary == "Useful summary"
    if sampled_at is not None:
        assert completion.prepared_at == sampled_at
        assert all(
            call.kwargs["attempted_at"] == sampled_at
            and call.kwargs["inactive_before"]
            == sampled_at - datetime.timedelta(hours=6)
            for call in repository.begin_next.await_args_list
        )


async def test_explicit_sampling_does_not_extend_real_execution_deadline() -> None:
    repository = AsyncMock()
    service = _service(repository, AsyncMock())
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


@dataclass
class _Stream:
    event: ResponseStreamEvent

    async def __aiter__(self) -> AsyncIterator[ResponseStreamEvent]:
        yield self.event

    async def aclose(self) -> None:
        pass


@dataclass
class _SummaryClient:
    text: str
    requests: list[dict[str, object]] = field(default_factory=list)
    closed: bool = False

    async def create_response(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return _Stream(
            ResponseCompletedEvent(
                type="response.completed",
                sequence_number=1,
                response=Response(
                    id="fixture-summary",
                    created_at=1,
                    model="fixture",
                    object="response",
                    status="completed",
                    parallel_tool_calls=True,
                    tool_choice="auto",
                    tools=[],
                    output=[
                        ResponseOutputMessage(
                            id="fixture-message",
                            type="message",
                            role="assistant",
                            status="completed",
                            content=[
                                ResponseOutputText(
                                    type="output_text", text=self.text, annotations=[]
                                )
                            ],
                        )
                    ],
                    usage=ResponseUsage(
                        input_tokens=40,
                        output_tokens=10,
                        total_tokens=50,
                        input_tokens_details=InputTokensDetails(
                            cached_tokens=5, cache_write_tokens=0
                        ),
                        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                    ),
                ),
            )
        )

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        raise AssertionError("This fixture uses HTTP streaming.")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize(
    "text,expected",
    [('{"summary":"Useful history"}', "Useful history"), ('{"summary":""}', "")],
)
async def test_preparation_stream_decodes_summary_and_attributes_usage(
    provider: LLMProvider,
    text: str,
    expected: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shared native lowerer, adapter and parser deliver the source result."""
    client = _SummaryClient(text)

    def factory(*, config: OpenAIResponsesClientConfig) -> _SummaryClient:
        return client

    with caplog.at_level(logging.INFO):
        summary = await generate_historical_memory_with_model(
            sdk_factories=ModelSDKFactories(factory, _SDK_FACTORIES.provider_model),
            selection=make_test_model_selection(provider=provider),
            settings=make_test_model_settings(),
            credential_kwargs={"api_key": "synthetic-unused"},
            effective_input_tokens=128000,
            source_text="[User]\nKeep the decision.",
            source_session_id="s" * 32,
            watchdog=_TEST_WATCHDOG,
            websocket_enabled=False,
        )
    assert summary == expected
    assert client.closed and len(client.requests) == 1
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Historical Memory model usage"
    )
    fields = vars(record)
    assert fields["call_kind"] == "historical_memory"
    assert fields["prompt_tokens"] == 40
    assert fields["completion_tokens"] == 10
    assert fields["cached_tokens"] == 5


@pytest.mark.parametrize("text", ['{"summary":"ok","extra":true}', '{"summary":2}', ""])
async def test_preparation_validates_terminal_summary_shape(text: str) -> None:
    client = _SummaryClient(text)

    def factory(*, config: OpenAIResponsesClientConfig) -> _SummaryClient:
        return client

    with pytest.raises(HistoricalMemoryOutputError):
        await generate_historical_memory_with_model(
            sdk_factories=ModelSDKFactories(factory, _SDK_FACTORIES.provider_model),
            selection=make_test_model_selection(),
            settings=make_test_model_settings(),
            credential_kwargs={"api_key": "synthetic-unused"},
            effective_input_tokens=128000,
            source_text="Source",
            source_session_id="s" * 32,
            watchdog=_TEST_WATCHDOG,
            websocket_enabled=False,
        )
    assert client.closed


def test_summary_guard_truncates_at_valid_utf8_boundary() -> None:
    guarded = _guard_summary("가" * 4_000)
    assert len(guarded.encode()) <= 9_000
    assert guarded.endswith("[Truncated by Azents Historical Memory guard.]")


async def test_preparation_keeps_prior_result_when_source_cannot_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = make_test_model_candidate()
    candidate.settings.max_output_tokens = 7860
    candidate.model_selection.normalized_capabilities.parameters.max_output_tokens = (
        True
    )
    source = _source()
    source.model_operation_state = SimpleNamespace(current_candidate=candidate)
    preparation_repository = AsyncMock()
    preparation_repository.begin_next.side_effect = [source, None]
    historical_repository = AsyncMock()
    service = _service(preparation_repository, historical_repository)
    source_events_repository = AsyncMock()
    source_events_repository.capture.return_value = [
        Event(
            id="e" * 32,
            session_id=source.source_session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                sender_user_id=None, content="Meaningful source evidence." * 100
            ),
            created_at=_NOW,
        )
    ]
    service.source_events_repository = source_events_repository
    monkeypatch.setattr(
        "azents.services.historical_memory.preparation.resolve_model_candidate_runtime",
        AsyncMock(
            return_value=Success(
                ResolvedModelCandidateRuntime(
                    provider=LLMProvider.OPENAI,
                    provider_integration_id=candidate.model_selection.llm_provider_integration_id,
                    model=candidate.model_selection.model_identifier,
                    credential_kwargs={"api_key": "synthetic-unused"},
                    effective_input_tokens=8192,
                )
            )
        ),
    )
    result = await service.prepare_agent(
        agent_id=source.agent_id,
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1),
        now=_NOW,
    )
    assert result.attempted == result.failed == 1
    assert result.prepared == result.empty == 0
    historical_repository.publish_completed.assert_not_awaited()
    preparation_repository.record_failure.assert_awaited_once()
    assert (
        preparation_repository.record_failure.await_args.kwargs["failure_code"]
        == "runtime_unavailable"
    )


@pytest.mark.parametrize("selected_output", [None, 2048])
@pytest.mark.parametrize(
    "source_row", [" foo" * 2500, " 한글🙂" * 2000], ids=["ascii", "unicode"]
)
async def test_source_service_fits_complete_native_request_before_summary(
    monkeypatch: pytest.MonkeyPatch,
    selected_output: int | None,
    source_row: str,
) -> None:
    """Semantic source projection, instructions and framing share the chosen window."""
    candidate = make_test_model_candidate()
    candidate.settings.max_output_tokens = selected_output
    candidate.model_selection.normalized_capabilities.parameters.max_output_tokens = (
        selected_output is not None
    )
    source = _source()
    source.model_operation_state = SimpleNamespace(current_candidate=candidate)
    events = [
        Event(
            id=f"{number:032x}",
            session_id=source.source_session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(sender_user_id=None, content=source_row),
            created_at=_NOW,
        )
        for number in range(1, 8)
    ]
    preparation_repository = AsyncMock()
    preparation_repository.begin_next.side_effect = [source, None]
    historical_repository = AsyncMock()
    historical_repository.publish_completed.return_value = SimpleNamespace(
        summary="Observed source continuation"
    )
    service = _service(preparation_repository, historical_repository)
    source_events_repository = AsyncMock()
    source_events_repository.capture.return_value = events
    service.source_events_repository = source_events_repository
    client = _SummaryClient('{"summary":"Observed source continuation"}')

    def factory(*, config: OpenAIResponsesClientConfig) -> _SummaryClient:
        return client

    service.sdk_factories = ModelSDKFactories(factory, _SDK_FACTORIES.provider_model)
    service.model_stream_watchdog = _TEST_WATCHDOG
    monkeypatch.setattr(
        "azents.services.historical_memory.preparation.resolve_model_candidate_runtime",
        AsyncMock(
            return_value=Success(
                ResolvedModelCandidateRuntime(
                    provider=LLMProvider.OPENAI,
                    provider_integration_id=candidate.model_selection.llm_provider_integration_id,
                    model=candidate.model_selection.model_identifier,
                    credential_kwargs={"api_key": "synthetic-unused"},
                    effective_input_tokens=8192,
                )
            )
        ),
    )
    result = await service.prepare_agent(
        agent_id=source.agent_id,
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1),
        now=_NOW,
    )
    assert result.prepared == result.attempted == 1
    assert result.failed == 0
    assert (
        historical_repository.publish_completed.await_args.kwargs["completion"].summary
        == "Observed source continuation"
    )
    assert client.closed and len(client.requests) == 1
    items = TypeAdapter(list[dict[str, object]]).validate_python(
        client.requests[0]["input"]
    )
    content = items[0]["content"]
    assert isinstance(content, str) and content
    prepared = prepare_model_operation_request(
        selection=candidate.model_selection,
        messages=[
            transient_model_message(
                EventKind.USER_MESSAGE,
                UserMessagePayload(sender_user_id=None, content=content),
            )
        ],
        catalog=None,
        system_prompt=_HISTORICAL_MEMORY_PROMPT,
        output_tokens=selected_output,
    )
    assert (
        prepared.request.native_request_input_bytes()
        <= (8192 - (selected_output or 0)) * 4
    )
