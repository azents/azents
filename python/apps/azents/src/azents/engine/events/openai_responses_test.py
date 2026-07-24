"""Official OpenAI SDK Responses adapter tests."""

import asyncio
import datetime
import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from litellm.types.llms.openai import ResponsesAPIResponse
from openai import AsyncOpenAI, AuthenticationError, BadRequestError, OpenAIError, omit
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseCustomToolCall,
    ResponseCustomToolCallInputDeltaEvent,
    ResponseCustomToolCallInputDoneEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFileSearchToolCall,
    ResponseFunctionWebSearch,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    ResponseUsage,
    ResponseWebSearchCallCompletedEvent,
    ResponseWebSearchCallInProgressEvent,
)
from openai.types.responses.response_error import ResponseError
from openai.types.responses.response_function_web_search import ActionSearch
from openai.types.responses.response_output_item import ImageGenerationCall
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)
from pydantic import ValidationError
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response as WebSocketHTTPResponse

from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.file_parts import ModelFileLoweringContent
from azents.engine.events.litellm_responses import LiteLLMResponsesLowerer
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOptions,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
    OpenAIResponsesWebSocketConnection,
    OpenAISDKResponsesClient,
    create_openai_responses_client,
    openai_responses_client_config,
    openai_responses_websocket_endpoint_eligible,
)
from azents.engine.events.protocols import (
    ProviderToolActivityProjection,
    ReasoningDeltaProjection,
)
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    FileOutputPart,
    NativeArtifact,
    ProviderToolCallPayload,
    ProviderToolSemanticContent,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    close_stream_response,
)
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.model_transport import (
    InMemoryModelTransportState,
    ModelTransportKey,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    UnclassifiedModelProviderError,
)
from azents.engine.run.types import BuiltinToolSpec
from azents.testing.model_stream import make_test_model_stream_watchdog

_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
)


class _StaticModelFileResolver:
    """Return fixed request-local ModelFile content."""

    def resolve(self, part: FileOutputPart) -> ModelFileLoweringContent:
        """Resolve one generated image FilePart."""
        del part
        return ModelFileLoweringContent(
            data_url="data:image/jpeg;base64,cmVoeWRyYXRlZA=="
        )


def _event(content: str = "hello") -> Event:
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content=content),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _external_payload(
    message_id: str,
    batch_id: str,
    *,
    attachment_metadata: dict[str, object] | None = None,
) -> ExternalChannelMessagePayload:
    """Create one deterministic external message payload."""
    return ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id=batch_id,
        external_message_id=message_id,
        revision_id=f"revision-{message_id}",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        projection_root_id=f"external-channel:binding-1:{message_id}",
        provider_message_key=f"slack:tenant-1:C1:{message_id}",
        provider_position=f"000000000000000000{message_id}.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        body=f"message-{message_id}",
        attachment_metadata=attachment_metadata or {},
        provider_created_at=datetime.datetime(2026, 7, 22, 12, 0, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
        correction_of_revision_id=None,
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


def _failed_event(*, code: str, message: str) -> ResponseFailedEvent:
    error = ResponseError.model_construct(code=code, message=message)
    response = _response().model_copy(
        update={
            "error": error,
            "output": [],
            "status": "failed",
            "usage": None,
        }
    )
    return ResponseFailedEvent(
        response=response,
        sequence_number=2,
        type="response.failed",
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

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        raise AssertionError("WebSocket was not expected")

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

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        raise AssertionError("WebSocket was not expected")

    async def close(self) -> None:
        self.closed = True


class _FakeWebSocketConnection:
    def __init__(
        self,
        events: list[ResponseStreamEvent | Exception],
        *,
        create_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.create_error = create_error
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def create_response(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error

    async def receive_event(self) -> ResponseStreamEvent:
        result = self.events.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self) -> None:
        self.closed = True


class _BlockingWebSocketConnection(_FakeWebSocketConnection):
    def __init__(self) -> None:
        super().__init__([])
        self.receive_started = asyncio.Event()

    async def receive_event(self) -> ResponseStreamEvent:
        self.receive_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _TransportFakeClient:
    def __init__(
        self,
        *,
        connection_result: OpenAIResponsesWebSocketConnection | Exception,
        http_results: list[object],
    ) -> None:
        self.connection_result = connection_result
        self.http_results = http_results
        self.http_calls: list[dict[str, object]] = []
        self.connect_count = 0
        self.closed = False

    async def create_response(self, **kwargs: object) -> object:
        self.http_calls.append(kwargs)
        if not self.http_results:
            raise AssertionError("HTTP was not expected")
        result = self.http_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        self.connect_count += 1
        if isinstance(self.connection_result, Exception):
            raise self.connection_result
        return self.connection_result

    async def close(self) -> None:
        self.closed = True


def _transport_key() -> ModelTransportKey:
    return ModelTransportKey(
        family="openai_responses",
        provider="openai",
        provider_integration_id="integration-1",
    )


def _sampling_context(model: str = "gpt-5.1-codex") -> ModelStreamCallContext:
    return ModelStreamCallContext(
        call_kind="sampling",
        provider="openai",
        provider_integration_id=None,
        model=model,
        session_id="session-1",
        run_id="run-1",
        attempt_number=None,
        check_stop=None,
    )


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


def test_openai_lowerer_renders_agent_result_terminal_envelope() -> None:
    """Official SDK lowering shares terminal mailbox envelope semantics."""
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
    )
    event = Event(
        id="3" * 32,
        session_id="session-1",
        kind=EventKind.AGENT_MESSAGE,
        payload=AgentMessagePayload(
            message_kind="agent_result",
            source_session_agent_id="source-agent",
            source_path="/root/reviewer",
            target_session_agent_id="target-agent",
            target_path="/root",
            source_run_id="1" * 32,
            source_run_index=2,
            run_status=AgentRunStatus.FAILED,
            source_terminal_result_event_id=None,
            content="Review failed safely.",
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )

    request = lowerer.lower([event], model="gpt-5.1-codex")

    assert request.input == [
        {
            "role": "user",
            "content": (
                "Message Type: AGENT_RESULT\n"
                "Task name: /root\n"
                "Sender: /root/reviewer\n"
                "Run status: failed\n"
                "Payload:\n"
                "Review failed safely."
            ),
        }
    ]


def test_chatgpt_lowerer_uses_standard_full_context_request() -> None:
    """ChatGPT sampling uses standard tools and stateless encrypted replay."""
    tool: dict[str, object] = {
        "type": "function",
        "name": "lookup",
        "description": "Look up a value",
        "parameters": {"type": "object"},
    }
    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.6-luna",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={
            "api_key": "synthetic-token",
            "base_url": "https://chatgpt.example/backend-api/codex",
            "extra_headers": {
                "originator": "azents",
                "ChatGPT-Account-Id": "synthetic-account",
            },
        },
        tools=[tool],
    )

    request = lowerer.lower(
        [_event()],
        model="gpt-5.6-luna",
        system_prompt="Be useful.",
    )

    assert request.input == [{"role": "user", "content": "hello"}]
    assert request.tools == [tool]
    assert request.options.get("instructions") == "Be useful."
    assert request.options.get("store") is False
    assert request.options.get("include") == ["reasoning.encrypted_content"]
    assert "extra_headers" not in request.options
    assert request.continuation_store_enabled() is False


def test_openai_sdk_lowerer_accepts_plaintext_custom_apply_patch_tool() -> None:
    """Validate the reviewed plaintext custom declaration through the pinned SDK."""
    tool: dict[str, object] = {
        "type": "custom",
        "name": "apply_patch",
        "description": "Apply one strict V4A patch.",
        "format": {"type": "text"},
    }
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        tools=[tool],
    )

    request = lowerer.lower([_event()], model="gpt-5.1")

    assert request.tools == [tool]


def test_openai_sdk_lowerer_projects_incompatible_custom_history() -> None:
    """Do not emit a historical custom call on a function-only SDK request."""
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        historical_plaintext_custom_supported=True,
        tools=[
            {
                "type": "function",
                "name": "apply_patch",
                "description": "Apply a patch.",
                "parameters": {"type": "object"},
            }
        ],
    )
    historical_call = Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-custom",
            name="apply_patch",
            arguments="opaque-custom-input",
            wire_dialect="plaintext_custom",
            native_artifact=NativeArtifact(
                compat_key=build_native_compat_key(
                    adapter="litellm",
                    native_format="responses",
                    provider="openai",
                    model="gpt-5.1",
                    schema_version="1",
                ),
                adapter="litellm",
                native_format="responses",
                provider="openai",
                model="gpt-5.1",
                schema_version="1",
                item={
                    "type": "custom_tool_call",
                    "call_id": "call-custom",
                    "name": "apply_patch",
                    "input": "opaque-custom-input",
                },
            ),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )

    request = lowerer.lower([historical_call], model="gpt-5.1")

    assert request.input == [
        {
            "role": "assistant",
            "content": (
                "[Historical custom tool call: apply_patch. "
                "Input omitted; non-executable history.]"
            ),
        }
    ]
    assert "opaque-custom-input" not in str(request.input)


def test_chatgpt_lowerer_uses_standard_hosted_web_search_tool() -> None:
    """ChatGPT hosted web search remains in the standard tools field."""
    capabilities = ModelCapabilities()
    capabilities.built_in_tools.supported = ["web_search"]
    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.6-luna",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
        hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
        model_capabilities=capabilities,
    )

    request = lowerer.lower([_event()], model="gpt-5.6-luna")

    assert request.tools == [{"type": "web_search"}]
    assert request.options.get("instructions") == "You are a helpful assistant."
    assert request.options.get("store") is False


@pytest.mark.parametrize(
    ("provider", "provider_id"),
    [
        ("openai", LLMProvider.OPENAI),
        ("chatgpt_oauth", LLMProvider.CHATGPT_OAUTH),
    ],
)
def test_openai_sdk_lowerer_uses_standard_image_generation_tool(
    provider: str,
    provider_id: LLMProvider,
) -> None:
    """Validate image generation through the official SDK tool contract."""
    capabilities = ModelCapabilities()
    capabilities.built_in_tools.supported = ["image_generation"]
    lowerer = OpenAIResponsesLowerer(
        provider=provider,
        model="gpt-5.6-luna",
        provider_id=provider_id,
        credential_kwargs={},
        hosted_tools=[
            BuiltinToolSpec(
                name="image_generation",
                config={"quality": "high", "size": "1024x1024"},
            )
        ],
        model_capabilities=capabilities,
    )

    request = lowerer.lower([_event()], model="gpt-5.6-luna")

    assert request.tools == [
        {
            "type": "image_generation",
            "quality": "high",
            "size": "1024x1024",
        }
    ]
    assert request.options.get("store") is (
        False if provider_id == LLMProvider.CHATGPT_OAUTH else None
    )


def test_chatgpt_oauth_rehydrates_image_generation_with_store_false() -> None:
    """Replay only valid generated-image fields for stateless ChatGPT."""
    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.1",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
        model_file_resolver=_StaticModelFileResolver(),
    )
    artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="openai",
            native_format="responses",
            provider="chatgpt_oauth",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="openai",
        native_format="responses",
        provider="chatgpt_oauth",
        model="gpt-5.1",
        schema_version="1",
        item={
            "type": "image_generation_call",
            "id": "image-call-1",
            "status": "completed",
            "action": "generate",
            "revised_prompt": "output-only prompt",
            "provider_extension": "output-only value",
        },
    )
    event = Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=ProviderToolCallPayload(
            call_id="image-call-1",
            name="image_generation",
            status="completed",
            semantic=ProviderToolSemanticContent(
                input=None,
                output=[
                    FileOutputPart(
                        model_file_id="model-file-1",
                        media_type="image/jpeg",
                        name="generated.jpg",
                        size=123,
                        kind="image",
                    )
                ],
                references=[],
            ),
            native_artifact=artifact,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )

    request = lowerer.lower([event], model="gpt-5.1")

    assert request.options.get("store") is False
    assert request.input == [
        {
            "type": "image_generation_call",
            "status": "completed",
            "result": "cmVoeWRyYXRlZA==",
        }
    ]


def test_openai_sdk_rehydrates_image_generation_call() -> None:
    """Replay a generated-image call through the SDK lowerer."""
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        model_file_resolver=_StaticModelFileResolver(),
    )
    artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="openai",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="openai",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={
            "type": "image_generation_call",
            "id": "image-call-1",
            "status": "completed",
            "action": "generate",
            "revised_prompt": "output-only prompt",
            "provider_extension": "output-only value",
        },
    )
    event = Event(
        id="3" * 32,
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=ProviderToolCallPayload(
            call_id="image-call-1",
            name="image_generation",
            status="completed",
            semantic=ProviderToolSemanticContent(
                input=None,
                output=[
                    FileOutputPart(
                        model_file_id="model-file-1",
                        media_type="image/jpeg",
                        name="generated.jpg",
                        size=123,
                        kind="image",
                    )
                ],
                references=[],
            ),
            native_artifact=artifact,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )

    request = lowerer.lower([event], model="gpt-5.1")

    assert request.continuation_store_enabled()
    assert request.input == [
        {
            "type": "image_generation_call",
            "id": "image-call-1",
            "status": "completed",
            "result": "cmVoeWRyYXRlZA==",
        }
    ]


def test_openai_sdk_lowerer_rejects_invalid_image_generation_config() -> None:
    """Reject invalid provider configuration before dispatch."""
    capabilities = ModelCapabilities()
    capabilities.built_in_tools.supported = ["image_generation"]
    lowerer = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.6-luna",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        hosted_tools=[
            BuiltinToolSpec(
                name="image_generation",
                config={"quality": "ultra"},
            )
        ],
        model_capabilities=capabilities,
    )

    with pytest.raises(ValidationError):
        lowerer.lower([_event()], model="gpt-5.6-luna")


def test_client_config_keeps_endpoint_identity_outside_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client configuration preserves base URL and common identity headers."""
    for name in (
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_CUSTOM_HEADERS",
    ):
        monkeypatch.delenv(name, raising=False)
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
    assert (
        openai_responses_websocket_endpoint_eligible(
            provider=LLMProvider.OPENAI,
            config=openai_config,
        )
        is False
    )
    assert (
        openai_responses_websocket_endpoint_eligible(
            provider=LLMProvider.CHATGPT_OAUTH,
            config=chatgpt_config,
        )
        is False
    )

    monkeypatch.delenv("AZ_OPENAI_BASE_URL")
    official_openai_config = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={"api_key": "key"},
    )
    official_chatgpt_config = openai_responses_client_config(
        provider=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={
            "api_key": "token",
            "base_url": CHATGPT_OAUTH_BACKEND_BASE_URL,
        },
    )

    assert openai_responses_websocket_endpoint_eligible(
        provider=LLMProvider.OPENAI,
        config=official_openai_config,
    )
    assert openai_responses_websocket_endpoint_eligible(
        provider=LLMProvider.CHATGPT_OAUTH,
        config=official_chatgpt_config,
    )


async def test_client_config_resolves_sdk_environment_for_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK environment routing is included in eligibility and handshake state."""
    monkeypatch.delenv("AZ_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.example/v1")
    monkeypatch.setenv("OPENAI_ORG_ID", "synthetic-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "synthetic-project")
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS",
        "X-Environment: environment\nX-Override: environment",
    )
    config = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={
            "api_key": "synthetic-test-key",
            "extra_headers": {"X-Override": "credential"},
        },
    )

    assert config.base_url == "https://environment.example/v1"
    assert config.organization == "synthetic-organization"
    assert config.project == "synthetic-project"
    assert config.default_headers == {
        "X-Environment": "environment",
        "X-Override": "credential",
    }
    assert not openai_responses_websocket_endpoint_eligible(
        provider=LLMProvider.OPENAI,
        config=config,
    )

    client = create_openai_responses_client(config=config)
    assert isinstance(client, OpenAISDKResponsesClient)
    assert client.sdk_client.max_retries == 0
    assert client.websocket_headers == {
        "OpenAI-Organization": "synthetic-organization",
        "OpenAI-Project": "synthetic-project",
        "X-Environment": "environment",
        "X-Override": "credential",
    }
    await client.close()


async def test_sdk_websocket_connect_forwards_bounded_receive_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK WebSocket receives identity headers and a bounded 32 MiB limit."""
    captured: dict[str, object] = {}
    connection = _FakeWebSocketConnection([_completed_event()])

    class Manager:
        async def enter(self) -> _FakeWebSocketConnection:
            return connection

    sdk_client = AsyncOpenAI(api_key="synthetic-test-key")

    def connect(**kwargs: object) -> Manager:
        captured.update(kwargs)
        return Manager()

    monkeypatch.setattr(sdk_client.responses, "connect", connect)
    client = OpenAISDKResponsesClient(
        sdk_client,
        websocket_headers={
            "originator": "azents",
            "ChatGPT-Account-Id": "synthetic-account",
        },
    )

    opened = await client.connect_websocket()

    assert captured["extra_headers"] == {
        "originator": "azents",
        "ChatGPT-Account-Id": "synthetic-account",
    }
    assert captured["websocket_connection_options"] == {
        "open_timeout": None,
        "max_size": 32 * 1024 * 1024,
    }
    await opened.close()
    assert connection.closed is True
    await client.close()


async def test_adapter_preserves_omission_null_and_stop_extension() -> None:
    """Dispatch sends SDK omission sentinels and preserves explicit null."""
    stream = _FakeStream([_completed_event()])
    client = _FakeClient(stream)
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
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
                provider_integration_id=None,
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


async def test_unclassified_sdk_error_is_safely_normalized() -> None:
    """Preserve safe provider diagnostics without raw SDK serialization."""
    original = OpenAIError("synthetic unclassified SDK failure")
    client = _SequencedFakeClient([original])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )

    with pytest.raises(UnclassifiedModelProviderError) as raised:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=_sampling_context(),
            )
        ]

    assert raised.value.provider_message == "synthetic unclassified SDK failure"
    assert raised.value.provider_error_type == "OpenAIError"
    assert raised.value.fingerprint
    await adapter.close()


async def test_websocket_reuses_one_connection_for_sequential_responses() -> None:
    """Eligible sequential turns reuse one execution-owned WebSocket."""
    connection = _FakeWebSocketConnection(
        [_completed_event(_response(text="first")), _completed_event()]
    )
    client = _TransportFakeClient(
        connection_result=connection,
        http_results=[],
    )
    state = InMemoryModelTransportState(websocket_enabled=True)
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=state,
        transport_key=_transport_key(),
        websocket_endpoint_eligible=True,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model="gpt-5.1-codex",
        inference_profile=None,
    )
    first = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "first"}],
        tools=[],
        options={"store": False},
    )
    second = first.model_copy(update={"input": [{"role": "user", "content": "second"}]})

    first_events = [
        event
        async for event in adapter.stream(
            first,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]
    second_events = [
        event
        async for event in adapter.stream(
            second,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]

    assert len(first_events) == 1
    assert len(second_events) == 1
    assert client.connect_count == 1
    assert client.http_calls == []
    assert len(connection.calls) == 2
    assert connection.calls[0]["input"] == first.input
    assert connection.calls[1]["input"] == second.input
    assert connection.calls[0]["store"] is False
    assert connection.calls[0]["previous_response_id"] is omit
    assert "extra_headers" not in connection.calls[0]
    assert connection.closed is False

    await adapter.close()

    assert connection.closed is True
    assert client.closed is True


async def test_websocket_reuse_preserves_strict_openai_continuation() -> None:
    """A healthy socket may use the existing exact continuation planner."""
    first_response = _response(text="first")
    connection = _FakeWebSocketConnection(
        [_completed_event(first_response), _completed_event()]
    )
    client = _TransportFakeClient(connection_result=connection, http_results=[])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=ResponsesContinuationPlanner(),
        transport_state=InMemoryModelTransportState(websocket_enabled=True),
        transport_key=_transport_key(),
        websocket_endpoint_eligible=True,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model="gpt-5.1-codex",
        inference_profile=None,
    )
    first = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "first"}],
        tools=[],
        options={},
    )
    output_item = first_response.output[0].model_dump(
        mode="json",
        exclude_unset=True,
        warnings=False,
    )
    second = first.model_copy(
        update={
            "input": [
                *first.input,
                output_item,
                {"role": "user", "content": "second"},
            ]
        }
    )

    _ = [
        event
        async for event in adapter.stream(
            first,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]
    _ = [
        event
        async for event in adapter.stream(
            second,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]

    assert client.connect_count == 1
    assert connection.calls[1]["previous_response_id"] == first_response.id
    assert connection.calls[1]["input"] == [{"role": "user", "content": "second"}]
    await adapter.close()


@pytest.mark.parametrize(
    ("websocket_enabled", "endpoint_eligible", "options"),
    [
        (False, True, {}),
        (True, False, {}),
        (True, True, {"stop": ["END"]}),
        (True, True, {"extra_headers": {"X-Request": "value"}}),
    ],
    ids=["deployment-disabled", "custom-endpoint", "stop", "request-headers"],
)
async def test_http_only_conditions_preserve_existing_streaming_path(
    websocket_enabled: bool,
    endpoint_eligible: bool,
    options: OpenAIResponsesOptions,
) -> None:
    """Deployment, endpoint, and request restrictions select HTTP."""
    http_stream = _FakeStream([_completed_event()])
    client = _TransportFakeClient(
        connection_result=AssertionError("WebSocket was not expected"),
        http_results=[http_stream],
    )
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=InMemoryModelTransportState(
            websocket_enabled=websocket_enabled
        ),
        transport_key=_transport_key(),
        websocket_endpoint_eligible=endpoint_eligible,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options=options,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )

    events = [
        event
        async for event in adapter.stream(
            request,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]

    assert len(events) == 1
    assert client.connect_count == 0
    assert len(client.http_calls) == 1
    assert http_stream.closed is True
    await adapter.close()


@pytest.mark.parametrize("failure_stage", ["connect", "send", "decode"])
async def test_websocket_transport_failure_stages_activate_http_fallback(
    failure_stage: str,
) -> None:
    """Connect, send, and decode failures consume the WebSocket attempt."""
    connection: _FakeWebSocketConnection | None
    if failure_stage == "connect":
        connection = None
        connection_result: OpenAIResponsesWebSocketConnection | Exception = (
            InvalidStatus(
                WebSocketHTTPResponse(
                    status_code=404,
                    reason_phrase="Not Found",
                    headers=Headers(),
                )
            )
        )
    elif failure_stage == "send":
        connection = _FakeWebSocketConnection(
            [],
            create_error=OSError("synthetic-send-failure"),
        )
        connection_result = connection
    else:
        connection = _FakeWebSocketConnection(
            [json.JSONDecodeError("synthetic-decode-failure", "", 0)]
        )
        connection_result = connection

    state = InMemoryModelTransportState(websocket_enabled=True)
    key = _transport_key()
    client = _TransportFakeClient(
        connection_result=connection_result,
        http_results=[],
    )
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )

    with pytest.raises(
        ModelProviderFailure,
        match="^Model provider error: The model WebSocket transport failed\\.$",
    ) as raised:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=_sampling_context(),
            )
        ]

    assert raised.value.category is ModelProviderFailureCategory.TRANSPORT
    assert raised.value.provider_code == f"websocket_{failure_stage}"
    assert raised.value.status_code == (404 if failure_stage == "connect" else None)
    assert state.websocket_allowed(key) is False
    if connection is not None:
        assert connection.closed is True
    await adapter.close()


async def test_websocket_transport_failure_marks_sticky_http_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A classified socket failure consumes the attempt and sticks to HTTP."""
    caplog.set_level(logging.INFO)
    forbidden_detail = "synthetic-provider-payload-must-not-log"
    connection = _FakeWebSocketConnection([OSError(forbidden_detail)])
    state = InMemoryModelTransportState(websocket_enabled=True)
    key = _transport_key()
    websocket_client = _TransportFakeClient(
        connection_result=connection,
        http_results=[],
    )
    adapter = OpenAIResponsesModelAdapter(
        client=websocket_client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )

    with pytest.raises(
        ModelProviderFailure,
        match="^Model provider error: The model WebSocket transport failed\\.$",
    ) as raised:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=_sampling_context(),
            )
        ]

    assert raised.value.category is ModelProviderFailureCategory.TRANSPORT
    assert raised.value.provider_code == "websocket_receive"
    assert state.websocket_allowed(key) is False
    assert connection.closed is True
    assert forbidden_detail not in caplog.text
    await adapter.close()

    http_stream = _FakeStream([_completed_event()])
    fallback_client = _TransportFakeClient(
        connection_result=AssertionError("sticky state must select HTTP"),
        http_results=[http_stream],
    )
    fallback_adapter = OpenAIResponsesModelAdapter(
        client=fallback_client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )

    events = [
        event
        async for event in fallback_adapter.stream(
            request,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=_sampling_context(),
        )
    ]

    assert len(events) == 1
    assert fallback_client.connect_count == 0
    assert len(fallback_client.http_calls) == 1
    await fallback_adapter.close()


async def test_abandoned_websocket_response_invalidates_without_sticky_fallback() -> (
    None
):
    """Caller abandonment closes unread events without disabling WebSocket."""
    delta = ResponseTextDeltaEvent(
        content_index=0,
        delta="partial",
        item_id="msg_synthetic",
        logprobs=[],
        output_index=0,
        sequence_number=1,
        type="response.output_text.delta",
    )
    connection = _FakeWebSocketConnection([delta])
    state = InMemoryModelTransportState(websocket_enabled=True)
    key = _transport_key()
    client = _TransportFakeClient(connection_result=connection, http_results=[])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )
    stream = adapter.stream(
        request,
        watchdog=watchdog,
        timeout_policy=policy,
        call_context=_sampling_context(),
    )

    received = await anext(stream)
    await close_stream_response(stream)

    assert received is delta
    assert connection.closed is True
    assert state.websocket_allowed(key) is True
    await adapter.close()


async def test_websocket_watchdog_timeout_invalidates_without_http_fallback() -> None:
    """Application timeout closes the active socket without proving incompatibility."""
    connection = _BlockingWebSocketConnection()
    state = InMemoryModelTransportState(websocket_enabled=True)
    key = _transport_key()
    client = _TransportFakeClient(connection_result=connection, http_results=[])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    timeout_policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=1,
        parsed_event_idle_timeout_seconds=0.05,
        absolute_attempt_timeout_seconds=1,
    )
    watchdog = make_test_model_stream_watchdog(policy=timeout_policy)

    with pytest.raises(ModelStreamTimeoutError) as raised:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=_sampling_context(),
            )
        ]

    assert raised.value.timeout_kind == "parsed_event_idle"
    assert connection.receive_started.is_set()
    assert connection.closed is True
    assert state.websocket_allowed(key) is True
    await adapter.close()


async def test_authentication_handshake_failure_does_not_activate_http_fallback() -> (
    None
):
    """Authentication status remains a provider failure instead of fallback proof."""
    handshake_error = InvalidStatus(
        WebSocketHTTPResponse(
            status_code=401,
            reason_phrase="Unauthorized",
            headers=Headers(),
        )
    )
    state = InMemoryModelTransportState(websocket_enabled=True)
    key = _transport_key()
    client = _TransportFakeClient(
        connection_result=handshake_error,
        http_results=[],
    )
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=state,
        transport_key=key,
        websocket_endpoint_eligible=True,
    )
    request = OpenAIResponsesRequest(
        model="gpt-5.1-codex",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
        options={},
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openai",
        model=request.model,
        inference_profile=None,
    )

    with pytest.raises(
        ModelProviderFailure,
        match="^Model provider error: Model authentication failed\\.$",
    ) as raised:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=_sampling_context(),
            )
        ]

    assert raised.value.category is ModelProviderFailureCategory.AUTHENTICATION
    assert raised.value.failure_code == "model_provider_authentication"
    assert raised.value.provider_code == "websocket_connect"
    assert raised.value.status_code == 401
    assert raised.value.integration == "integration-1"
    assert state.websocket_allowed(key) is True
    await adapter.close()


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
        client=OpenAISDKResponsesClient(sdk_client, websocket_headers=None),
        continuation_planner=None,
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
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
                    provider_integration_id=None,
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


async def test_official_sdk_wire_request_sanitizes_unstored_generated_image() -> None:
    """Send only the ChatGPT stateless generated-image input contract."""
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

    lowerer = OpenAIResponsesLowerer(
        provider="chatgpt_oauth",
        model="gpt-5.1",
        provider_id=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
        model_file_resolver=_StaticModelFileResolver(),
    )
    artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="openai",
            native_format="responses",
            provider="chatgpt_oauth",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="openai",
        native_format="responses",
        provider="chatgpt_oauth",
        model="gpt-5.1",
        schema_version="1",
        item={
            "type": "image_generation_call",
            "id": "image-call-1",
            "status": "completed",
            "action": "generate",
            "revised_prompt": "output-only prompt",
            "provider_extension": "output-only value",
        },
    )
    event = Event(
        id="4" * 32,
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=ProviderToolCallPayload(
            call_id="image-call-1",
            name="image_generation",
            status="completed",
            semantic=ProviderToolSemanticContent(
                input=None,
                output=[
                    FileOutputPart(
                        model_file_id="model-file-1",
                        media_type="image/jpeg",
                        name="generated.jpg",
                        size=123,
                        kind="image",
                    )
                ],
                references=[],
            ),
            native_artifact=artifact,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    request = lowerer.lower([event], model="gpt-5.1")
    sdk_client = AsyncOpenAI(
        api_key="synthetic-test-key",
        base_url="https://provider.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    adapter = OpenAIResponsesModelAdapter(
        client=OpenAISDKResponsesClient(sdk_client, websocket_headers=None),
        continuation_planner=None,
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
    )
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="chatgpt_oauth",
        model=request.model,
        inference_profile=None,
    )
    try:
        _ = [
            response_event
            async for response_event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=ModelStreamCallContext(
                    call_kind="sampling",
                    provider="chatgpt_oauth",
                    provider_integration_id="integration-chatgpt",
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

    assert captured_body["store"] is False
    assert captured_body["input"] == [
        {
            "type": "image_generation_call",
            "status": "completed",
            "result": "cmVoeWRyYXRlZA==",
        }
    ]


def test_typed_normalizer_admits_completed_custom_tool_call() -> None:
    """Keep custom input private until a completed matching item is received."""
    custom_call = ResponseCustomToolCall(
        call_id="call-custom",
        id="item-custom",
        input="opaque-custom-input",
        name="apply_patch",
        type="custom_tool_call",
    )
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")

    added = output.process_event(
        ResponseOutputItemAddedEvent(
            item=custom_call,
            output_index=0,
            sequence_number=1,
            type="response.output_item.added",
        )
    )
    delta = output.process_event(
        ResponseCustomToolCallInputDeltaEvent(
            delta="opaque-custom-input",
            item_id="item-custom",
            output_index=0,
            sequence_number=2,
            type="response.custom_tool_call_input.delta",
        )
    )
    input_done = output.process_event(
        ResponseCustomToolCallInputDoneEvent(
            input="opaque-custom-input",
            item_id="item-custom",
            output_index=0,
            sequence_number=3,
            type="response.custom_tool_call_input.done",
        )
    )
    item_done = output.process_event(
        ResponseOutputItemDoneEvent(
            item=custom_call,
            output_index=0,
            sequence_number=4,
            type="response.output_item.done",
        )
    )
    output.process_event(
        _completed_event(_response().model_copy(update={"output": [custom_call]}))
    )

    assert added.projections == []
    assert delta.projections == []
    assert input_done.projections == []
    assert item_done.projections == []
    completed = output.complete()
    assert completed.needs_follow_up is True
    assert len(completed.events) == 1
    payload = completed.events[0].payload
    assert isinstance(payload, ClientToolCallPayload)
    assert payload.call_id == "call-custom"
    assert payload.name == "apply_patch"
    assert payload.arguments == "opaque-custom-input"
    assert payload.wire_dialect == "plaintext_custom"

    result = Event(
        id="3" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-custom",
            name="apply_patch",
            wire_dialect="plaintext_custom",
            status="completed",
            output="completed",
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    request = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
        historical_plaintext_custom_supported=True,
    ).lower([*completed.events, result], model="gpt-5.1-codex")

    assert request.input == [
        {
            "type": "custom_tool_call",
            "call_id": "call-custom",
            "id": "item-custom",
            "input": "opaque-custom-input",
            "name": "apply_patch",
        },
        {
            "type": "custom_tool_call_output",
            "call_id": "call-custom",
            "output": "completed",
        },
    ]


def test_typed_normalizer_maps_end_turn_false_to_follow_up() -> None:
    """Preserve the OpenAI dialect continuation hint in normalized output."""
    response = _response().model_copy(update={"end_turn": False, "output": []})
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")

    output.process_event(_completed_event(response))
    completed = output.complete()

    assert completed.needs_follow_up is True
    assert completed.events == []


def test_typed_normalizer_rejects_inconsistent_custom_tool_input() -> None:
    """Do not admit a custom call whose streamed and completed input disagree."""
    custom_call = ResponseCustomToolCall(
        call_id="call-custom",
        id="item-custom",
        input="final-input",
        name="apply_patch",
        type="custom_tool_call",
    )
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")
    output.process_event(
        ResponseCustomToolCallInputDoneEvent(
            input="different-input",
            item_id="item-custom",
            output_index=0,
            sequence_number=1,
            type="response.custom_tool_call_input.done",
        )
    )
    output.process_event(
        ResponseOutputItemDoneEvent(
            item=custom_call,
            output_index=0,
            sequence_number=2,
            type="response.output_item.done",
        )
    )
    output.process_event(
        _completed_event(_response().model_copy(update={"output": [custom_call]}))
    )

    assert output.complete().events == []


def test_typed_normalizer_preserves_reasoning_stream_identity() -> None:
    """Carry reasoning item and summary-part identity into live projection."""
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")

    projected = output.process_event(
        ResponseReasoningSummaryTextDeltaEvent(
            delta="thinking",
            item_id="rs_1",
            output_index=2,
            sequence_number=1,
            summary_index=1,
            type="response.reasoning_summary_text.delta",
        )
    )

    assert projected.projections == [
        ReasoningDeltaProjection(
            delta="thinking",
            item_id="rs_1",
            output_index=2,
            summary_index=1,
        )
    ]


def test_typed_completed_message_does_not_replay_output_index() -> None:
    """Keep reasoning handoff metadata out of non-reasoning replay items."""
    message = ResponseOutputMessage(
        id="msg_1",
        content=[
            ResponseOutputText(
                annotations=[],
                text="done",
                type="output_text",
            )
        ],
        role="assistant",
        status="completed",
        type="message",
    )
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")
    output.process_event(
        ResponseOutputItemDoneEvent(
            item=message,
            output_index=4,
            sequence_number=1,
            type="response.output_item.done",
        )
    )
    output.process_event(
        _completed_event(_response().model_copy(update={"output": []}))
    )

    completed = output.complete()

    assert len(completed.events) == 1
    payload = completed.events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert "output_index" not in payload.native_artifact.item
    request = OpenAIResponsesLowerer(
        provider="openai",
        model="gpt-5.1-codex",
        provider_id=LLMProvider.OPENAI,
        credential_kwargs={},
    ).lower(completed.events, model="gpt-5.1-codex")
    assert "output_index" not in request.input[0]


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
        operation="sampling",
        integration=None,
    )
    output = normalizer.start("session-1")
    mismatched = ResponseCompletedEvent.model_construct(
        response=_response(),
        sequence_number=1,
        type="response.error",
    )

    output.process_event(mismatched)

    with pytest.raises(
        ModelProviderFailure,
        match="ended before completion",
    ) as raised:
        output.complete()

    assert raised.value.category is ModelProviderFailureCategory.TRANSPORT
    assert raised.value.provider_code == "stream_ended_before_completion"


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
        operation="sampling",
        integration=None,
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


def test_typed_normalizer_projects_provider_tool_lifecycle() -> None:
    """Translate SDK-specific hosted-tool stages to canonical snapshots."""
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")

    running = output.process_event(
        ResponseWebSearchCallInProgressEvent(
            item_id="search-1",
            output_index=0,
            sequence_number=1,
            type="response.web_search_call.in_progress",
        )
    )
    completed = output.process_event(
        ResponseWebSearchCallCompletedEvent(
            item_id="search-1",
            output_index=0,
            sequence_number=2,
            type="response.web_search_call.completed",
        )
    )
    regressive = output.process_event(
        ResponseWebSearchCallInProgressEvent(
            item_id="search-1",
            output_index=0,
            sequence_number=3,
            type="response.web_search_call.in_progress",
        )
    )

    assert running.projections == [
        ProviderToolActivityProjection(
            call_id="search-1",
            name="web_search",
            status="running",
            arguments=None,
        )
    ]
    assert completed.projections == [
        ProviderToolActivityProjection(
            call_id="search-1",
            name="web_search",
            status="completed",
            arguments=None,
        )
    ]
    assert regressive.projections == []


def test_typed_normalizer_extracts_transient_generated_image() -> None:
    """Keep official SDK image bytes transient until Engine materialization."""
    completed = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).normalize_completed_output(
        "session-1",
        {
            "output": [
                {
                    "type": "image_generation_call",
                    "id": "image-call-1",
                    "status": "completed",
                    "result": _PNG_BASE64,
                }
            ]
        },
        [],
    )

    assert len(completed.events) == 1
    payload = completed.events[0].payload
    assert isinstance(payload, ProviderToolCallPayload)
    assert payload.output == []
    assert "result" not in payload.native_artifact.item
    assert len(completed.pending_provider_files) == 1
    pending = completed.pending_provider_files[0]
    assert pending.call_id == "image-call-1"
    assert pending.body.startswith(b"\x89PNG")
    assert "body" not in completed.model_dump(mode="json")


def test_typed_stream_extracts_transient_generated_image() -> None:
    """Preserve typed SDK image bytes until transient file extraction."""
    image = ImageGenerationCall(
        id="image-call-1",
        result=_PNG_BASE64,
        status="completed",
        type="image_generation_call",
    )
    response = _response().model_copy(update={"output": [image]})
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")

    output.process_event(
        ResponseOutputItemDoneEvent(
            item=image,
            output_index=0,
            sequence_number=1,
            type="response.output_item.done",
        )
    )
    output.process_event(_completed_event(response))

    completed = output.complete()

    assert len(completed.events) == 1
    payload = completed.events[0].payload
    assert isinstance(payload, ProviderToolCallPayload)
    assert "result" not in payload.native_artifact.item
    assert len(completed.pending_provider_files) == 1
    pending = completed.pending_provider_files[0]
    assert pending.call_id == "image-call-1"
    assert pending.body.startswith(b"\x89PNG")
    serialized = completed.model_dump(mode="json")
    assert "body" not in serialized
    assert _PNG_BASE64 not in str(serialized)


def test_typed_normalizer_projects_generic_provider_tool_output_items() -> None:
    """Treat generic output-item completion as a hosted-tool terminal state."""
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")
    action = ActionSearch(
        type="search",
        query="provider-neutral activity",
        queries=None,
        sources=None,
    )

    running = output.process_event(
        ResponseOutputItemAddedEvent(
            item=ResponseFunctionWebSearch(
                id="search-1",
                action=action,
                status="in_progress",
                type="web_search_call",
            ),
            output_index=0,
            sequence_number=1,
            type="response.output_item.added",
        )
    )
    completed = output.process_event(
        ResponseOutputItemDoneEvent(
            item=ResponseFunctionWebSearch(
                id="search-1",
                action=action,
                status="in_progress",
                type="web_search_call",
            ),
            output_index=0,
            sequence_number=2,
            type="response.output_item.done",
        )
    )
    incomplete = output.process_event(
        ResponseOutputItemDoneEvent(
            item=ResponseFileSearchToolCall(
                id="search-2",
                queries=["provider-neutral activity"],
                status="incomplete",
                type="file_search_call",
                results=None,
            ),
            output_index=1,
            sequence_number=3,
            type="response.output_item.done",
        )
    )

    assert running.projections == [
        ProviderToolActivityProjection(
            call_id="search-1",
            name="web_search",
            status="running",
            arguments=None,
        )
    ]
    assert completed.projections == [
        ProviderToolActivityProjection(
            call_id="search-1",
            name="web_search",
            status="completed",
            arguments=None,
        )
    ]
    assert incomplete.projections == [
        ProviderToolActivityProjection(
            call_id="search-2",
            name="file_search",
            status="failed",
            arguments=None,
        )
    ]


def test_typed_normalizer_accepts_omitted_usage_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Usage totals survive compatible providers that omit detail objects."""
    monkeypatch.setattr(
        "azents.engine.events.openai_responses.completion_cost",
        lambda **kwargs: 0.25,
    )
    usage = ResponseUsage.model_construct(
        input_tokens=10,
        input_tokens_details=None,
        output_tokens=5,
        output_tokens_details=None,
        total_tokens=15,
    )
    response = _response().model_copy(update={"usage": usage})
    output = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    ).start("session-1")
    output.process_event(_completed_event(response))

    completed = output.complete()

    assert completed.usage is not None
    assert completed.usage.prompt_tokens == 10
    assert completed.usage.completion_tokens == 5
    assert completed.usage.total_tokens == 15
    assert completed.usage.cached_tokens is None
    assert completed.usage.cache_creation_tokens is None
    assert completed.usage.reasoning_tokens is None
    assert completed.usage.cost_usd == 0.25


def test_unclassified_typed_terminal_error_is_internal() -> None:
    """Unknown typed errors bypass provider-failure recovery immediately."""
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1-codex",
        operation="sampling",
        integration=None,
    )
    output = normalizer.start("session-1")

    with pytest.raises(
        UnclassifiedModelProviderError,
        match=(
            "provider_code=synthetic_error, provider_error_type=response_error, "
            "provider_message=provider body must not be surfaced"
        ),
    ):
        output.process_event(
            ResponseErrorEvent(
                code="synthetic_error",
                message="provider body must not be surfaced",
                param=None,
                sequence_number=1,
                type="error",
            )
        )


def test_typed_failed_event_classifies_invalid_prompt() -> None:
    """Provider rejection preserves safe text and neutral classification."""
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="chatgpt_oauth",
        model="gpt-5.6-terra",
        operation="sampling",
        integration=None,
    )
    output = normalizer.start("session-1")
    output.process_event(
        _failed_event(
            code="invalid_prompt",
            message="provider body must not be surfaced",
        )
    )

    with pytest.raises(
        ModelProviderFailure,
        match=("^Model provider error: provider body must not be surfaced$"),
    ) as raised:
        output.complete()

    assert raised.value.category is ModelProviderFailureCategory.INVALID_REQUEST
    assert raised.value.failure_code == "model_provider_invalid_request"
    assert raised.value.provider_code == "invalid_prompt"
    assert raised.value.provider_message == "provider body must not be surfaced"


def test_typed_failed_event_classifies_rate_limit() -> None:
    """Rate limits preserve safe text and neutral classification."""
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="chatgpt_oauth",
        model="gpt-5.6-terra",
        operation="sampling",
        integration=None,
    )
    output = normalizer.start("session-1")
    output.process_event(
        _failed_event(
            code="rate_limit_exceeded",
            message="retry after provider-private detail",
        )
    )

    with pytest.raises(
        ModelProviderFailure,
        match=("^Model provider error: retry after provider-private detail$"),
    ) as raised:
        output.complete()

    assert raised.value.category is ModelProviderFailureCategory.RATE_LIMIT
    assert raised.value.failure_code == "model_provider_rate_limit"
    assert raised.value.provider_code == "rate_limit_exceeded"
    assert raised.value.provider_message == "retry after provider-private detail"


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
        operation="sampling",
        integration=None,
    ).start("session-1")
    output.process_event(_completed_event())

    completed = output.complete()

    assert completed.usage is not None
    assert completed.usage.total_tokens == 15
    assert completed.usage.cost_usd is None


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "invalid_api_key", "message": "raw body"}},
        {
            "code": "invalid_api_key",
            "message": "raw body",
            "type": "authentication_error",
        },
    ],
)
async def test_authentication_error_preserves_typed_provider_message(
    body: dict[str, object],
) -> None:
    """Final SDK status failures preserve bounded provider-authored text."""
    request_handle = httpx.Request("POST", "https://provider.example/responses")
    error = AuthenticationError(
        "Error code: 401 - {'error': {'message': 'raw body'}}",
        response=httpx.Response(401, request=request_handle),
        body=body,
    )
    client = _SequencedFakeClient([error])
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
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

    with pytest.raises(
        ModelProviderFailure,
        match="^Model provider error: raw body$",
    ) as raised:
        _ = [
            event
            async for event in adapter.stream(
                logical_request,
                watchdog=watchdog,
                timeout_policy=policy,
                call_context=ModelStreamCallContext(
                    call_kind="sampling",
                    provider="openai",
                    provider_integration_id="integration-openai",
                    model=logical_request.model,
                    session_id="session-1",
                    run_id="run-1",
                    attempt_number=None,
                    check_stop=None,
                ),
            )
        ]

    assert raised.value.category is ModelProviderFailureCategory.AUTHENTICATION
    assert raised.value.failure_code == "model_provider_authentication"
    assert raised.value.provider_message == "raw body"
    assert raised.value.provider_code == "invalid_api_key"
    assert raised.value.status_code == 401


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
        transport_state=None,
        transport_key=None,
        websocket_endpoint_eligible=False,
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
                provider_integration_id=None,
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


def test_openai_lowerer_groups_external_invocation_batch() -> None:
    """OpenAI lowerer uses the same explicit external-turn envelope."""
    lowerer = OpenAIResponsesLowerer(provider="openai", model="gpt-5.1")
    transcript = [
        Event(
            id="1" * 32,
            session_id="session-1",
            kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
            payload=_external_payload(
                "1",
                "batch-1",
                attachment_metadata={
                    "files": [
                        {
                            "name": "report.csv",
                            "title": "Report",
                            "media_type": "text/csv",
                            "declared_size": 1024,
                            "supported": True,
                            "unsupported_reason": None,
                            "file": "external-file:v1:slack:binding-1:F123",
                        }
                    ]
                },
            ),
            created_at=datetime.datetime(2026, 7, 22, tzinfo=datetime.UTC),
        ),
        Event(
            id="2" * 32,
            session_id="session-1",
            kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
            payload=_external_payload("2", "batch-1"),
            created_at=datetime.datetime(2026, 7, 22, tzinfo=datetime.UTC),
        ),
    ]

    request = lowerer.lower(transcript, model="gpt-5.1")
    content = request.input[-1]["content"]
    assert isinstance(content, str)
    assert content.startswith("Message Type: EXTERNAL_CHANNEL_TURN")
    assert "Body: message-1" in content
    assert "Body: message-2" in content
    assert "Files:" in content
    assert "File: external-file:v1:slack:binding-1:F123" in content
