"""Official OpenAI SDK Responses adapter tests."""

import datetime
import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from litellm.types.llms.openai import ResponsesAPIResponse
from openai import AsyncOpenAI, AuthenticationError, BadRequestError, omit
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from azents.core.enums import EventKind, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelCompatibilityCapabilities,
)
from azents.engine.events.litellm_responses import LiteLLMResponsesLowerer
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
    OpenAISDKResponsesClient,
    openai_responses_client_config,
)
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    NativeArtifact,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.run.errors import ModelCallError
from azents.testing.model_stream import make_test_model_stream_watchdog


def _event(content: str = "hello") -> Event:
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content=content),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _response(*, text: str = "done") -> Response:
    return Response(
        id="resp_synthetic",
        created_at=1.0,
        model="gpt-5.1-codex",
        object="response",
        output=[
            ResponseOutputMessage(
                id="msg_synthetic",
                content=[
                    ResponseOutputText(
                        annotations=[],
                        text=text,
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        status="completed",
        usage=ResponseUsage(
            input_tokens=10,
            input_tokens_details=InputTokensDetails(
                cache_write_tokens=3,
                cached_tokens=2,
            ),
            output_tokens=5,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=1),
            total_tokens=15,
        ),
    )


def _completed_event(response: Response | None = None) -> ResponseCompletedEvent:
    return ResponseCompletedEvent(
        response=response or _response(),
        sequence_number=2,
        type="response.completed",
    )


class _FakeStream:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.closed = False

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self.events:
            yield event

    async def close(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, stream: _FakeStream) -> None:
        self.stream = stream
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def create_response(self, **kwargs: object) -> _FakeStream:
        self.calls.append(kwargs)
        return self.stream

    async def close(self) -> None:
        self.closed = True


class _SequencedFakeClient:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def create_response(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self) -> None:
        self.closed = True


def test_openai_lowerer_omits_endpoint_credentials_and_store() -> None:
    """API-key logical requests retain semantics without client credentials."""
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        prompt_cache_scope="session-1",
    )

    request = lowerer.lower([_event()], model="gpt-5.1-codex")

    assert request.input == [{"role": "user", "content": "hello"}]
    assert "store" not in request.options
    assert "api_key" not in request.options
    assert "base_url" not in request.options
    assert request.options.get("instructions") == "You are a helpful assistant."
    assert request.options.get("prompt_cache_key") != "session-1"


def test_chatgpt_lowerer_uses_full_context_store_false() -> None:
    """Standard ChatGPT sampling is stateless and requests encrypted reasoning."""
    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
    )

    request = lowerer.lower([_event()], model="gpt-5.1-codex")

    assert request.input == [{"role": "user", "content": "hello"}]
    assert request.options.get("store") is False
    assert request.options.get("include") == ["reasoning.encrypted_content"]
    assert request.continuation_store_enabled() is False


def test_chatgpt_responses_lite_is_sampling_capability_driven() -> None:
    """Responses Lite retains its extension prefix and required physical fields."""
    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
        prompt_cache_scope="session-1",
        tools=[
            {
                "type": "function",
                "name": "lookup",
                "description": "Look up a value",
                "parameters": {"type": "object"},
            }
        ],
        model_capabilities=ModelCapabilities(
            compatibility=ModelCompatibilityCapabilities(responses_lite=True)
        ),
    )

    request = lowerer.lower(
        [_event()],
        model="gpt-5.1-codex",
        system_prompt="Be useful.",
    )

    assert request.responses_lite is True
    assert request.tools == []
    assert request.options.get("parallel_tool_calls") is False
    assert request.options.get("prompt_cache_key") == "session-1"
    assert request.input[0]["type"] == "additional_tools"
    assert request.input[1] == {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "Be useful."}],
    }


def test_client_config_keeps_endpoint_identity_outside_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client configuration preserves base URL and common identity headers."""
    monkeypatch.setenv("AZ_OPENAI_BASE_URL", "https://openai.example/v1")
    openai_config = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={"api_key": "key"},
    )
    chatgpt_config = openai_responses_client_config(
        provider=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={
            "api_key": "token",
            "base_url": "https://chatgpt.example/codex",
            "extra_headers": {
                "originator": "azents",
                "ChatGPT-Account-Id": "account",
            },
        },
    )

    assert openai_config.base_url == "https://openai.example/v1"
    assert chatgpt_config.base_url == "https://chatgpt.example/codex"
    assert chatgpt_config.default_headers == {
        "originator": "azents",
        "ChatGPT-Account-Id": "account",
    }


async def test_adapter_preserves_omission_null_and_stop_extension() -> None:
    """Dispatch sends SDK omission sentinels and preserves explicit null."""
    stream = _FakeStream([_completed_event()])
    client = _FakeClient(stream)
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model="gpt-5.1-codex",
        inference_profile=None,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={
            "instructions": None,
            "stop": ["END"],
        },
    )

    received = [
        event
        async for event in adapter.stream(
            request,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=ModelStreamCallContext(
                call_kind="sampling",
                provider="openai",
                model=request.model,
                session_id="session-1",
                run_id="run-1",
                attempt_number=None,
                check_stop=None,
            ),
        )
    ]

    assert received == [_completed_event()]
    call = client.calls[0]
    assert call["instructions"] is None
    assert call["store"] is omit
    assert call["tools"] is omit
    assert call["previous_response_id"] is omit
    assert call["extra_body"] == {"stop": ["END"]}
    assert stream.closed is True
    await adapter.close()
    assert client.closed is True


async def test_official_sdk_wire_request_preserves_presence_and_stop() -> None:
    """Public SDK serialization omits absent fields and merges the stop extension."""
    captured_body: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads((await request.aread()).decode())
        assert isinstance(body, dict)
        captured_body.update(body)
        event = _completed_event().model_dump_json(exclude_unset=True)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {event}\n\ndata: [DONE]\n\n",
            request=request,
        )

    sdk_client = AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url="https://provider.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    adapter = OpenAIResponsesModelAdapter(
        client=OpenAISDKResponsesClient(sdk_client),
        continuation_planner=None,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "synthetic input"}],
        tools=[],
        options={"instructions": None, "stop": ["END"]},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )
    try:
        events = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=ModelStreamCallContext(
                    call_kind="sampling",
                    provider="openai",
                    model=request.model,
                    session_id="session-1",
                    run_id="run-1",
                    attempt_number=None,
                    check_stop=None,
                ),
            )
        ]
    finally:
        await adapter.close()

    assert len(events) == 1
    assert isinstance(events[0], ResponseCompletedEvent)
    assert captured_body["instructions"] is None
    assert captured_body["stop"] == ["END"]
    assert "store" not in captured_body
    assert "tools" not in captured_body
    assert "previous_response_id" not in captured_body


def test_typed_normalizer_requires_exact_completed_wire_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incidental completed class cannot promote an unknown discriminator."""
    monkeypatch.setattr(
        "azents.engine.events.openai_responses.completion_cost",
        lambda **kwargs: 0.25,
    )
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
    )
    output = normalizer.start("session-1")
    mismatched = ResponseCompletedEvent.model_construct(
        response=_response(),
        sequence_number=1,
        type="response.error",
    )

    output.process_event(mismatched)

    with pytest.raises(ModelCallError, match="ended before completion"):
        output.complete()


def test_typed_normalizer_builds_openai_artifact_usage_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed completion produces canonical output with SDK usage provenance."""
    captured: dict[str, object] = {}

    def fake_completion_cost(**kwargs: object) -> float:
        captured.update(kwargs)
        return 0.25

    monkeypatch.setattr(
        "azents.engine.events.openai_responses.completion_cost",
        fake_completion_cost,
    )
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
    )
    output = normalizer.start("session-1")
    output.process_event(
        ResponseTextDeltaEvent(
            content_index=0,
            delta="done",
            item_id="msg_synthetic",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        )
    )
    output.process_event(_completed_event())

    completed = output.complete()

    assert len(completed.events) == 1
    payload = completed.events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.content == "done"
    assert payload.native_artifact is not None
    assert payload.native_artifact.adapter == "openai"
    assert payload.native_artifact.compat_key.startswith("openai:responses:openai:")
    assert completed.usage is not None
    assert completed.usage.prompt_tokens == 10
    assert completed.usage.completion_tokens == 5
    assert completed.usage.cached_tokens == 2
    assert completed.usage.cache_creation_tokens == 3
    assert completed.usage.reasoning_tokens == 1
    assert completed.usage.cost_usd == 0.25
    assert completed.usage.raw_hidden_params is None
    minimal_response = captured["completion_response"]
    assert isinstance(minimal_response, ResponsesAPIResponse)
    assert [getattr(item, "type", None) for item in minimal_response.output] == [
        "message"
    ]
    assert "done" not in str(minimal_response)
    assert "resp_synthetic" not in str(minimal_response)


def test_typed_terminal_error_fails_without_provider_body() -> None:
    """Typed error events expose a fixed safe failure message."""
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
    )
    output = normalizer.start("session-1")
    output.process_event(
        ResponseErrorEvent(
            code="synthetic_error",
            message="provider body must not be surfaced",
            param=None,
            sequence_number=1,
            type="error",
        )
    )

    with pytest.raises(ModelCallError, match="^Model call failed\\.$"):
        output.complete()


def test_cross_adapter_artifacts_use_canonical_fallback() -> None:
    """OpenAI and LiteLLM artifacts never cross their exact compat boundary."""
    openai_artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="openai",
            native_format="responses",
            provider="openai",
            model="gpt-5.1-codex",
            schema_version="1",
        ),
        adapter="openai",
        native_format="responses",
        provider="openai",
        model="gpt-5.1-codex",
        schema_version="1",
        item={"type": "message", "id": "sdk-only", "content": []},
    )
    event = Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content="canonical text",
            attachments=[],
            native_artifact=openai_artifact,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    lite_request = LiteLLMResponsesLowerer(
        provider="openai",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.OPENAI,
    ).lower([event], model="gpt-5.1-codex")

    assert lite_request.input == [{"role": "assistant", "content": "canonical text"}]


def test_pricing_failure_preserves_successful_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pricing-map failure does not fail completed provider output."""

    def fail_pricing(**kwargs: object) -> float:
        del kwargs
        raise ValueError("synthetic pricing failure")

    monkeypatch.setattr(
        "azents.engine.events.openai_responses.completion_cost",
        fail_pricing,
    )
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
    ).start("session-1")
    output.process_event(_completed_event())

    completed = output.complete()

    assert completed.usage is not None
    assert completed.usage.total_tokens == 15
    assert completed.usage.cost_usd is None


async def test_authentication_error_is_mapped_without_raw_provider_text() -> None:
    """Final SDK status failures expose only fixed user-safe messages."""
    request_handle = httpx.Request("POST", "https://provider.example/responses")
    error = AuthenticationError(
        "provider body with credential-shaped text",
        response=httpx.Response(401, request=request_handle),
        body={"error": {"code": "invalid_api_key", "message": "raw body"}},
    )
    client = _SequencedFakeClient([error])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
    )
    logical_request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=logical_request.model,
        inference_profile=None,
    )

    with pytest.raises(ModelCallError, match="^Model authentication failed\\.$"):
        _ = [
            event
            async for event in adapter.stream(
                logical_request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=ModelStreamCallContext(
                    call_kind="sampling",
                    provider="openai",
                    model=logical_request.model,
                    session_id="session-1",
                    run_id="run-1",
                    attempt_number=None,
                    check_stop=None,
                ),
            )
        ]


async def test_missing_previous_response_retries_full_input_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing stored state retries in full and logs only response-id presence."""
    caplog.set_level(logging.INFO)
    planner = ResponsesContinuationPlanner()
    base = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "first"}],
        tools=[],
        options={},
    )
    output_item = (
        _response()
        .output[0]
        .model_dump(
            mode="json",
            exclude_unset=True,
            warnings=False,
        )
    )
    planner.record_completion(
        base,
        response_id="resp_previous",
        output_items=[output_item],
    )
    follow_up = base.model_copy(
        update={
            "input": [
                *base.input,
                output_item,
                {"role": "user", "content": "second"},
            ]
        }
    )
    request_handle = httpx.Request("POST", "https://provider.example/responses")
    missing = BadRequestError(
        "stored response missing",
        response=httpx.Response(400, request=request_handle),
        body={"error": {"code": "previous_response_not_found"}},
    )
    completed_stream = _FakeStream([_completed_event()])
    client = _SequencedFakeClient([missing, completed_stream])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=planner,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=follow_up.model,
        inference_profile=None,
    )

    _ = [
        event
        async for event in adapter.stream(
            follow_up,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=ModelStreamCallContext(
                call_kind="sampling",
                provider="openai",
                model=follow_up.model,
                session_id="session-1",
                run_id="run-1",
                attempt_number=None,
                check_stop=None,
            ),
        )
    ]

    assert len(client.calls) == 2
    assert client.calls[0]["previous_response_id"] == "resp_previous"
    assert client.calls[0]["input"] == [{"role": "user", "content": "second"}]
    assert client.calls[1]["previous_response_id"] is omit
    assert client.calls[1]["input"] == follow_up.input
    records = [
        record
        for record in caplog.records
        if record.message == "Dispatching OpenAI Responses request"
    ]
    assert [record.__dict__["previous_response_id_supplied"] for record in records] == [
        True,
        False,
    ]
    assert "resp_previous" not in caplog.text
