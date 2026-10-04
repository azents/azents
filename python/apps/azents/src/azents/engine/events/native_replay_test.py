"""Opaque native replay binds actual prepared text and exact admitted selection."""

import base64
import dataclasses
import datetime
import json
from collections.abc import Sequence

import pytest
from openai.types.responses import Response, ResponseCompletedEvent
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from azents.core.enums import EventKind, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.model_messages import (
    TransientModelMessage,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    NativeModelProtocol,
    PydanticAIStreamEvent,
)
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.types import (
    ClientToolResultPayload,
    Event,
    ReasoningPayload,
)

_INSTRUCTIONS = "Synthetic authorized automatic Memory and ordinary guidance."
_OLD_SELECTION = "synthetic-authorized-unit/revision-original"
_NEW_SELECTION = "synthetic-authorized-unit/revision-clean"
_OPAQUE = "synthetic-opaque-state-never-visible"
_SIGNATURE = base64.b64encode(_OPAQUE.encode()).decode()
_TOOL: dict[str, object] = {
    "type": "function",
    "name": "probe",
    "description": "Synthetic fixture tool",
    "parameters": {"type": "object", "properties": {}},
}


@dataclasses.dataclass(frozen=True)
class _Family:
    provider: LLMProvider
    sdk_provider: str
    protocol: NativeModelProtocol
    redacted_id: str | None


_FAMILIES = (
    _Family(LLMProvider.GOOGLE_GEMINI, "google-gla", "google", None),
    _Family(LLMProvider.GOOGLE_VERTEX_AI, "google-vertex", "google", None),
    _Family(LLMProvider.ANTHROPIC, "anthropic", "anthropic", "redacted_thinking"),
    _Family(LLMProvider.AWS_BEDROCK, "bedrock", "bedrock", "redacted_content"),
)


def _result(*, transient: bool) -> Event | TransientModelMessage:
    payload = ClientToolResultPayload(
        call_id="call-fixture",
        name="probe",
        wire_dialect="json_function",
        status="completed",
        output="Visible tool result retained",
        metadata={},
    )
    if transient:
        return TransientModelMessage(kind=EventKind.CLIENT_TOOL_RESULT, payload=payload)
    return Event(
        id="f" * 32,
        session_id="synthetic-session",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=payload,
        created_at=datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC),
    )


def _restart(
    messages: Sequence[Event | TransientModelMessage],
) -> list[Event | TransientModelMessage]:
    """Decode persisted canonical envelopes without any prior adapter RAM."""
    return [
        Event.model_validate(message.model_dump(mode="json"))
        if isinstance(message, Event)
        else TransientModelMessage.model_validate(message.model_dump(mode="json"))
        for message in messages
    ]


@dataclasses.dataclass(frozen=True)
class _CurrentPrefix:
    instructions: str
    context: str | None


def _current(change: str) -> _CurrentPrefix:
    if change == "instructions":
        return _CurrentPrefix("New authorized Memory text", _OLD_SELECTION)
    if change == "denial":
        return _CurrentPrefix(
            "Ordinary guidance without denied Memory", "empty-authorized-selection"
        )
    if change == "revision":
        return _CurrentPrefix(_INSTRUCTIONS, _NEW_SELECTION)
    return _CurrentPrefix(_INSTRUCTIONS, _OLD_SELECTION)


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize("transient", [False, True])
@pytest.mark.parametrize(
    "change", ["unchanged", "instructions", "denial", "revision", "unbound"]
)
def test_responses_restart_never_replays_incompatible_encrypted_reasoning(
    provider: LLMProvider, transient: bool, change: str
) -> None:
    lowerer = OpenAIResponsesLowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model="synthetic-model",
        tools=[_TOOL],
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    origin = lowerer.lower(
        [],
        model="synthetic-model",
        system_prompt=_INSTRUCTIONS,
        native_replay_context=_OLD_SELECTION,
    )
    normalizer = OpenAIResponsesOutputNormalizer(
        provider=provider.value,
        model="synthetic-model",
        pricing=None,
        operation="sampling",
        integration=None,
        requested_service_tier=None,
    )
    selected = (
        normalizer
        if change == "unbound"
        else normalizer.for_native_replay(origin.native_replay_schema_version())
    )
    stream = (
        selected.start_transient() if transient else selected.start("synthetic-session")
    )
    response = Response.model_validate(
        {
            "id": "native-opaque-response",
            "created_at": 1,
            "model": "synthetic-model",
            "object": "response",
            "status": "completed",
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "output": [
                {
                    "id": "reasoning-fixture",
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "Synthetic reasoning"}
                    ],
                    "encrypted_content": _OPAQUE,
                },
                {
                    "id": "visible-fixture",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Visible answer retained",
                            "annotations": [],
                        }
                    ],
                },
                {
                    "type": "function_call",
                    "id": "tool-fixture",
                    "call_id": "call-fixture",
                    "name": "probe",
                    "arguments": "{}",
                    "status": "completed",
                },
            ],
        }
    )
    stream.process_event(
        ResponseCompletedEvent(
            response=response, sequence_number=1, type="response.completed"
        )
    )
    completed = stream.complete()
    assert normalizer.schema_version == "1"
    assert any(
        isinstance(message.payload, ReasoningPayload) for message in completed.events
    )
    history = _restart([*completed.events, _result(transient=transient)])
    before = [message.model_dump(mode="json") for message in history]
    prefix = _current(change)
    instructions, context = prefix.instructions, prefix.context
    # A newly constructed lowerer cannot use RAM history to prove old authority.
    fresh = OpenAIResponsesLowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model="synthetic-model",
        tools=[_TOOL],
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    request = fresh.lower(
        history,
        model="synthetic-model",
        system_prompt=instructions,
        native_replay_context=context,
    )
    wire = json.dumps(request.input)
    assert (_OPAQUE in wire) == (change == "unchanged")
    assert "Visible answer retained" in wire and "Visible tool result retained" in wire
    calls = [item for item in request.input if item.get("type") == "function_call"]
    results = [
        item for item in request.input if item.get("type") == "function_call_output"
    ]
    assert [item["call_id"] for item in calls] == ["call-fixture"]
    assert [item["call_id"] for item in results] == ["call-fixture"]
    assert "native_replay_context" not in request.model_dump(mode="json")
    assert [message.model_dump(mode="json") for message in history] == before
    if change == "revision":
        assert request.options == origin.options
        assert (
            request.native_replay_schema_version()
            != origin.native_replay_schema_version()
        )


@pytest.mark.parametrize("family", _FAMILIES, ids=lambda family: family.provider.value)
@pytest.mark.parametrize("transient", [False, True])
@pytest.mark.parametrize(
    "change", ["unchanged", "instructions", "denial", "revision", "unbound"]
)
def test_all_native_families_bind_opaque_reasoning_assistant_and_tool_parts(
    family: _Family, transient: bool, change: str
) -> None:
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=family.provider.value,
        model_capabilities=ModelCapabilities(),
        provider_id=family.provider,
        model="synthetic-model",
        tools=[_TOOL],
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    origin = lowerer.lower(
        [],
        model="synthetic-model",
        system_prompt=_INSTRUCTIONS,
        native_replay_context=_OLD_SELECTION,
    )
    parts: list[ModelResponsePart] = [
        ThinkingPart(
            "Synthetic reasoning",
            signature=_SIGNATURE,
            provider_name=family.sdk_provider,
        ),
        TextPart(
            "Visible answer retained",
            provider_name=family.sdk_provider,
            provider_details={"thought_signature": _SIGNATURE}
            if family.protocol == "google"
            else None,
        ),
        ToolCallPart(
            "probe",
            args={},
            tool_call_id="call-fixture",
            provider_name=family.sdk_provider,
            provider_details={"thought_signature": _SIGNATURE}
            if family.protocol == "google"
            else None,
        ),
    ]
    if family.redacted_id is not None:
        parts.insert(
            1,
            ThinkingPart(
                "",
                id=family.redacted_id,
                signature=_OPAQUE,
                provider_name=family.sdk_provider,
            ),
        )
    normalizer = PydanticAIOutputNormalizer(
        provider=family.provider.value,
        model="synthetic-model",
        pricing=None,
        operation="sampling",
        integration=None,
    )
    selected = (
        normalizer
        if change == "unbound"
        else normalizer.for_native_replay(origin.native_replay_schema_version())
    )
    stream = (
        selected.start_transient() if transient else selected.start("synthetic-session")
    )
    stream.process_event(
        PydanticAIStreamEvent(
            event=None,
            response=ModelResponse(
                parts=parts,
                model_name="synthetic-model",
                provider_name=family.sdk_provider,
                provider_response_id="native-opaque-response",
            ),
            observation=NativeModelObservation(
                protocol=family.protocol,
                event_type="fixture.completed",
                parsed_activity=True,
                terminal="success",
                end_turn=False,
                native_usage=None,
                reported_cost_usd=None,
                service_tier=None,
                native_items=(),
                annotations=(),
                error=None,
            ),
        )
    )
    completed = stream.complete()
    assert normalizer.schema_version == "1"
    history = _restart([*completed.events, _result(transient=transient)])
    before = [message.model_dump(mode="json") for message in history]
    prefix = _current(change)
    instructions, context = prefix.instructions, prefix.context
    fresh = PydanticAILowerer(
        top_k=None,
        provider=family.provider.value,
        model_capabilities=ModelCapabilities(),
        provider_id=family.provider,
        model="synthetic-model",
        tools=[_TOOL],
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    request = fresh.lower(
        history,
        model="synthetic-model",
        system_prompt=instructions,
        native_replay_context=context,
    )
    wire = ModelMessagesTypeAdapter.dump_json(request.messages).decode()
    assert (_SIGNATURE in wire) == (change == "unchanged")
    if family.redacted_id is not None:
        assert (_OPAQUE in wire) == (change == "unchanged")
    assert "Visible answer retained" in wire and "Visible tool result retained" in wire
    calls = [
        part
        for message in request.messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    results = [
        part
        for message in request.messages
        if not isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert [part.tool_call_id for part in calls] == ["call-fixture"]
    assert [part.tool_call_id for part in results] == ["call-fixture"]
    assert [message.model_dump(mode="json") for message in history] == before
    if change == "revision":
        current_prefix, original_prefix = request.messages[0], origin.messages[0]
        assert isinstance(current_prefix, ModelRequest)
        assert isinstance(original_prefix, ModelRequest)
        current_instructions = current_prefix.parts[0]
        original_instructions = original_prefix.parts[0]
        assert isinstance(current_instructions, SystemPromptPart)
        assert isinstance(original_instructions, SystemPromptPart)
        assert current_instructions.content == original_instructions.content
        assert (
            request.native_replay_schema_version()
            != origin.native_replay_schema_version()
        )


def test_equal_text_new_revision_resets_stored_continuation() -> None:
    planner = ResponsesContinuationPlanner()
    original = OpenAIResponsesRequest(
        model="synthetic-model",
        input=[{"role": "user", "content": "Question"}],
        tools=[],
        options={"instructions": _INSTRUCTIONS, "store": True},
        native_replay_context=_OLD_SELECTION,
    )
    answer: dict[str, object] = {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "Visible answer retained"}],
    }
    planner.record_completion(
        original, response_id="old-provider-context", output_items=[answer]
    )
    complete_input = [
        *original.input,
        answer,
        {"role": "user", "content": "Next question"},
    ]
    unchanged = original.model_copy(update={"input": complete_input})
    assert planner.plan(unchanged).previous_response_id == "old-provider-context"
    changed = unchanged.model_copy(update={"native_replay_context": _NEW_SELECTION})
    plan = planner.plan(changed)
    assert plan.previous_response_id is None and plan.input_items == complete_input
    assert changed.options == original.options
    assert changed.continuation_properties() != unchanged.continuation_properties()
