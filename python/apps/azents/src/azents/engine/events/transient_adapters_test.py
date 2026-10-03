"""Real provider parsers/lowerers support RAM messages without durable identities."""

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.usage import RequestUsage

from azents.core.enums import EventKind, LLMProvider
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesOutputNormalizer,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    NativeModelProtocol,
    PydanticAIStreamEvent,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
    UserMessagePayload,
)


@pytest.mark.parametrize(
    "provider,protocol",
    [
        (LLMProvider.ANTHROPIC, "anthropic"),
        (LLMProvider.GOOGLE_GEMINI, "google"),
        (LLMProvider.GOOGLE_VERTEX_AI, "google"),
        (LLMProvider.AWS_BEDROCK, "bedrock"),
        (LLMProvider.OPENROUTER, "chat_completions"),
        (LLMProvider.XAI, "responses"),
    ],
)
def test_common_provider_semantics_round_trip_through_ram_transcript(
    provider: LLMProvider, protocol: NativeModelProtocol
) -> None:
    normalizer = PydanticAIOutputNormalizer(
        provider=provider.value,
        model="selected-model",
        pricing=None,
        operation="historical_memory",
        integration=None,
    )
    stream = normalizer.start_transient()
    stream.process_event(
        PydanticAIStreamEvent(
            event=None,
            response=ModelResponse(
                parts=[
                    TextPart("Read the scoped source."),
                    ToolCallPart(
                        "read",
                        {"path": "azents://memory/inventory/README.md"},
                        tool_call_id="read-1",
                    ),
                ],
                usage=RequestUsage(input_tokens=20, output_tokens=5),
            ),
            observation=NativeModelObservation(
                protocol=protocol,
                event_type="completed",
                parsed_activity=True,
                terminal="success",
                end_turn=False,
                native_usage={
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "total_tokens": 25,
                },
                reported_cost_usd=None,
                service_tier=None,
                native_items=(),
                annotations=(),
                error=None,
            ),
        )
    )
    output = stream.complete()
    assert output.needs_follow_up
    assert all(isinstance(message, TransientModelMessage) for message in output.events)
    assert all(
        set(message.model_dump()) == {"kind", "payload"} for message in output.events
    )
    calls = [
        message.payload
        for message in output.events
        if isinstance(message.payload, ClientToolCallPayload)
    ]
    assert len(calls) == 1 and calls[0].call_id == "read-1"
    transcript = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Scoped job input"),
        ),
        *output.events,
    ]
    transcript.append(
        transient_model_message(
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="read-1",
                name="read",
                wire_dialect="json_function",
                status="completed",
                output=[OutputTextPart(text="Scoped source metadata")],
            ),
        )
    )
    request = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model="selected-model",
        tools=[],
        model_capabilities=None,
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower(
        transcript, model="selected-model", system_prompt="Independent internal task"
    )
    assert request.messages and request.native_request_input_chars() > 0
    assert "Scoped source metadata" in str(request.messages)
    assert "session_id" not in str(request.messages)


def test_native_openai_completed_stream_and_lowerer_have_no_session_fiction() -> None:
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="selected-model",
        pricing=None,
        operation="historical_memory",
        integration=None,
        requested_service_tier=None,
    )
    response = Response(
        id="response-synthetic",
        created_at=1.0,
        model="selected-model",
        object="response",
        output=[
            ResponseOutputMessage(
                id="message-synthetic",
                content=[
                    ResponseOutputText(
                        annotations=[], text="Completed", type="output_text"
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
    )
    stream = normalizer.start_transient()
    stream.process_event(
        ResponseCompletedEvent(
            response=response, sequence_number=1, type="response.completed"
        )
    )
    output = stream.complete()
    assert len(output.events) == 1 and isinstance(
        output.events[0], TransientModelMessage
    )
    assert isinstance(output.events[0].payload, AssistantMessagePayload)
    request = OpenAIResponsesLowerer(
        top_k=None,
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="selected-model",
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower(output.events, model="selected-model", system_prompt="Independent task")
    assert request.native_request_input_chars() > 0
    assert "Completed" in str(request)
    assert "session_id" not in str(request)


def test_interrupted_native_text_is_a_transient_partial_not_a_public_event() -> None:
    normalizer = OpenAIResponsesOutputNormalizer(
        provider="openai",
        model="selected-model",
        pricing=None,
        operation="historical_memory",
        integration=None,
        requested_service_tier=None,
    )
    stream = normalizer.start_transient()
    stream.process_event(
        ResponseTextDeltaEvent(
            content_index=0,
            delta="Partial",
            item_id="message",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        )
    )
    interrupted = stream.interrupt()
    assert not interrupted.needs_follow_up
    assert len(interrupted.events) == 1
    assert isinstance(interrupted.events[0], TransientModelMessage)
    assert isinstance(interrupted.events[0].payload, AssistantMessagePayload)
