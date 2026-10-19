"""Structured canonical-history lowering and judgment usage isolation."""

import datetime
import json

import pytest
from azcommon.uuid import uuid7
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.output import OutputObjectDefinition

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.core.routine_judgment import (
    RoutineActionDecision,
    RoutineJudgmentConsidered,
    RoutineJudgmentDecision,
)
from azents.engine.events.filters import _compaction_input_tokens
from azents.engine.events.model_support_contract import ModelRequestFeatureError
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.types import (
    Event,
    EventPayload,
    RoutineJudgmentPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    public_event_payload,
    validate_event_payload,
)
from azents.services.chat.context import _latest_usage


def _event(kind: EventKind, payload: EventPayload) -> Event:
    return Event(
        id=uuid7().hex,
        session_id="routine-session",
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _observation() -> Event:
    return _event(
        EventKind.ROUTINE_JUDGMENT,
        RoutineJudgmentPayload(
            judgment_id="judgment-1",
            considered=(
                RoutineJudgmentConsidered(
                    routine_id="routine-a", slug="routine-a", title="Traffic anomalies"
                ),
            ),
            status="completed",
            decision=RoutineJudgmentDecision(
                decisions=(RoutineActionDecision(routine_id="routine-a", act=False),)
            ),
            error=None,
            usage=TokenUsagePayload(
                prompt_tokens=9999, completion_tokens=77, total_tokens=10076
            ),
        ),
    )


def _history() -> list[Event]:
    return [
        _event(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Keep watching traffic."),
        ),
        _event(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Only alert on anomalies."),
        ),
    ]


def _schema() -> OutputObjectDefinition:
    return OutputObjectDefinition(
        json_schema=RoutineJudgmentDecision.model_json_schema(),
        name="routine_judgment",
        description="Joint action selection for the supplied Session Routines.",
        strict=True,
    )


def _caps(*, structured: bool) -> ModelCapabilities:
    return ModelCapabilities(
        structured_response=structured,
        tool_calling=ModelToolCallingCapabilities(supported=True),
    )


def _pydantic(provider: LLMProvider, *, structured: bool) -> PydanticAILowerer:
    return PydanticAILowerer(
        provider=provider.value,
        provider_id=provider,
        model="exact-selected-model",
        tools=None,
        hosted_tools=None,
        top_k=None,
        model_capabilities=_caps(structured=structured),
        model_developer=(
            LLMModelDeveloper.ANTHROPIC if provider is LLMProvider.AWS_BEDROCK else None
        ),
        supported_execution_options=[],
        enabled_execution_options=[],
    )


def _responses(*, structured: bool) -> OpenAIResponsesLowerer:
    return OpenAIResponsesLowerer(
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="exact-selected-model",
        tools=None,
        hosted_tools=None,
        top_k=None,
        model_capabilities=_caps(structured=structured),
        supported_execution_options=[],
        enabled_execution_options=[],
    )


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_VERTEX_AI,
        LLMProvider.OPENROUTER,
        LLMProvider.XAI,
        LLMProvider.KIMI_OAUTH,
        LLMProvider.AWS_BEDROCK,
    ],
)
def test_pydantic_structured_judgment_retains_history_without_executable_tools(
    provider: LLMProvider,
) -> None:
    request = _pydantic(provider, structured=True).lower_structured(
        [*_history(), _observation()],
        model="exact-selected-model",
        system_prompt="Ordinary Session system context with judgment instructions.",
        native_replay_context="same-canonical-context",
        output=_schema(),
    )
    contents = [
        str(part.content)
        for message in request.messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, (SystemPromptPart, UserPromptPart))
    ]
    assert len(request.messages) == len(contents) == 3
    rendered = "\n".join(contents)
    assert "Keep watching traffic." in rendered
    assert "Only alert on anomalies." in rendered
    assert "Ordinary Session system context" in rendered
    assert "judgment-1" not in rendered
    assert "9999" not in rendered
    assert not request.parameters.function_tools
    assert not request.parameters.native_tools
    assert request.parameters.output_mode == "native"
    assert request.parameters.output_object == _schema()


def test_responses_structured_judgment_retains_same_history_and_schema() -> None:
    request = _responses(structured=True).lower_structured(
        [*_history(), _observation()],
        model="exact-selected-model",
        system_prompt="Ordinary Session context.",
        native_replay_context="same-canonical-context",
        output=_schema(),
    )
    rendered = json.dumps(request.input)
    assert "Keep watching traffic." in rendered
    assert "Only alert on anomalies." in rendered
    assert "judgment-1" not in rendered
    assert request.tools == []
    assert request.options["text"] == {
        "format": {
            "type": "json_schema",
            "name": "routine_judgment",
            "schema": _schema().json_schema,
            "strict": True,
            "description": _schema().description,
        }
    }


@pytest.mark.parametrize("kind", ["pydantic", "responses"])
def test_unsupported_structured_output_does_not_silently_become_text(kind: str) -> None:
    lowerer = (
        _pydantic(LLMProvider.ANTHROPIC, structured=False)
        if kind == "pydantic"
        else _responses(structured=False)
    )
    with pytest.raises(ModelRequestFeatureError):
        lowerer.lower_structured(
            _history(),
            model="exact-selected-model",
            system_prompt="Session context.",
            native_replay_context=None,
            output=_schema(),
        )


def test_judgment_usage_never_replaces_normal_context_or_compaction_baseline() -> None:
    normal_usage = TokenUsagePayload(
        prompt_tokens=100, completion_tokens=20, total_tokens=120
    )
    normal = _event(
        EventKind.TURN_MARKER,
        TurnMarkerPayload(run_id="ordinary-run", usage=normal_usage),
    )
    judgment = _observation()
    assert _latest_usage([normal, judgment]) is normal_usage
    assert _latest_usage([judgment]) is None
    assert _compaction_input_tokens([normal, judgment]) == 100
    assert _compaction_input_tokens([judgment]) == 0
    assert isinstance(judgment.payload, RoutineJudgmentPayload)
    assert judgment.payload.usage is not None
    assert judgment.payload.usage.prompt_tokens == 9999
    assert "run_id" not in judgment.payload.model_dump()


def test_observation_roundtrip_preserves_unknown_usage_and_failure() -> None:
    observed = _observation()
    assert isinstance(observed.payload, RoutineJudgmentPayload)
    failed = observed.payload.model_copy(
        update={
            "status": "failed",
            "decision": None,
            "error": "Provider did not produce a valid Structured response.",
            "usage": None,
        }
    )
    decoded = validate_event_payload(
        EventKind.ROUTINE_JUDGMENT, failed.model_dump(mode="json")
    )
    assert decoded == failed
    assert isinstance(decoded, RoutineJudgmentPayload)
    assert decoded.usage is None
    assert decoded.decision is None


def test_failure_cannot_be_recorded_as_successful_no_action() -> None:
    observed = _observation()
    assert isinstance(observed.payload, RoutineJudgmentPayload)
    values = observed.payload.model_dump()
    values["decision"] = None
    with pytest.raises(ValidationError, match="requires a decision"):
        RoutineJudgmentPayload.model_validate(values)
    values["status"] = "failed"
    with pytest.raises(ValidationError, match="requires an error"):
        RoutineJudgmentPayload.model_validate(values)


@pytest.mark.parametrize("failed", [False, True])
def test_public_judgment_round_trip_preserves_explicit_unknown_usage(
    failed: bool,
) -> None:
    payload = _observation().payload.model_dump()
    payload["usage"] = None
    if failed:
        payload.update(status="failed", decision=None, error="Synthetic failure.")
    validated = RoutineJudgmentPayload.model_validate(payload)
    projected = public_event_payload(EventKind.ROUTINE_JUDGMENT, validated)
    assert projected["usage"] is None
    assert validate_event_payload(EventKind.ROUTINE_JUDGMENT, projected) == validated
