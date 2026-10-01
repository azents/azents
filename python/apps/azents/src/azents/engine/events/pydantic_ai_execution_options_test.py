"""Saved speed authority through public model settings and native SDK wire."""

from typing import Literal

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai.messages import TextPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.testing.provider_native_envelopes import core_native_response

_MODEL = "gpt-6-astra"
_OBJECT = TypeAdapter(dict[str, JsonValue])
_SPEEDS = [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST]


class _CompletedEnvelope(BaseModel):
    """Extract a fixture's native response without replacing SDK parsing."""

    type: Literal["response.completed"]
    response: dict[str, JsonValue]


def _lowerer(
    *,
    provider: LLMProvider,
    supported: list[ModelExecutionOptionId],
    enabled: list[ModelExecutionOptionId],
    reasoning: bool,
    kwargs: dict[str, object] | None,
) -> PydanticAILowerer:
    return PydanticAILowerer(
        provider=provider.value,
        provider_id=provider,
        model=_MODEL,
        tools=None,
        model_capabilities=ModelCapabilities(
            reasoning=ModelReasoningCapabilities(
                supported=reasoning,
                effort_levels=[ModelReasoningEffort.HIGH] if reasoning else [],
            )
        ),
        supported_execution_options=supported,
        enabled_execution_options=enabled,
        reasoning_effort="high" if reasoning else None,
        kwargs=kwargs,
    )


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize("speed", ["normal", "fast", "ultrafast"])
@pytest.mark.parametrize("reasoning", [False, True])
async def test_saved_speed_survives_public_settings_and_real_sdk_serialization(
    provider: LLMProvider,
    speed: Literal["normal", "fast", "ultrafast"],
    reasoning: bool,
) -> None:
    """Preserve exclusive intent and reasoning together, without profile grants."""
    enabled = (
        []
        if speed == "normal"
        else [
            ModelExecutionOptionId.FAST
            if speed == "fast"
            else ModelExecutionOptionId.ULTRAFAST
        ]
    )
    request = _lowerer(
        provider=provider,
        supported=_SPEEDS,
        enabled=enabled,
        reasoning=reasoning,
        kwargs=None,
    ).lower([], model=_MODEL, system_prompt="Synthetic speed contract")
    envelope = core_native_response(
        protocol="responses", model=_MODEL, text="Synthetic speed output"
    )
    frame = next(
        frame
        for frame in envelope.body.split(b"\n\n")
        if b'"response.completed"' in frame
    )
    reply = _CompletedEnvelope.model_validate_json(
        frame.split(b"data: ", 1)[1]
    ).response
    captured: list[dict[str, JsonValue]] = []

    def handle(native_request: httpx2.Request) -> httpx2.Response:
        captured.append(_OBJECT.validate_json(native_request.content))
        return httpx2.Response(200, request=native_request, json=reply)

    sdk = AsyncOpenAI(
        api_key="synthetic-speed-contract-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        model = OpenAIResponsesModel(_MODEL, provider=OpenAIProvider(openai_client=sdk))
        output = await model.request(
            request.messages, request.settings, request.parameters
        )
        assert len(captured) == 1
        wire = captured[0]
        assert wire["model"] == _MODEL
        expected = (
            "priority"
            if speed == "fast"
            else "ultrafast"
            if speed == "ultrafast"
            else "default"
            if provider == LLMProvider.OPENAI
            else None
        )
        if expected is None:
            assert "service_tier" not in wire
        else:
            assert wire["service_tier"] == expected
        if reasoning:
            assert wire["reasoning"] == {"effort": "high", "summary": "auto"}
        assert any(
            isinstance(part, TextPart) and part.content == "Synthetic speed output"
            for part in output.parts
        )
    finally:
        await sdk.close()


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
def test_conflicting_speed_preferences_fail_before_model_dispatch(
    provider: LLMProvider,
) -> None:
    lowerer = _lowerer(
        provider=provider,
        supported=_SPEEDS,
        enabled=_SPEEDS,
        reasoning=False,
        kwargs=None,
    )
    with pytest.raises(ValueError, match="exclusive"):
        lowerer.lower([], model=_MODEL)


@pytest.mark.parametrize("option", _SPEEDS)
def test_non_openai_provider_rejects_saved_speed_options(
    option: ModelExecutionOptionId,
) -> None:
    lowerer = _lowerer(
        provider=LLMProvider.ANTHROPIC,
        supported=[option],
        enabled=[option],
        reasoning=False,
        kwargs=None,
    )
    with pytest.raises(ValueError, match="not supported by this provider"):
        lowerer.lower([], model=_MODEL)


@pytest.mark.parametrize("option", _SPEEDS)
def test_unsupported_speed_does_not_acquire_authority_from_model_name(
    option: ModelExecutionOptionId,
) -> None:
    lowerer = _lowerer(
        provider=LLMProvider.OPENAI,
        supported=[],
        enabled=[option],
        reasoning=False,
        kwargs=None,
    )
    with pytest.raises(ValueError, match="not supported by the model"):
        lowerer.lower([], model=_MODEL)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"service_tier": "ultrafast"},
        {"openai_service_tier": "priority"},
        {"extra_body": {"service_tier": "ultrafast"}},
    ],
)
def test_raw_sdk_options_cannot_override_saved_speed_authority(
    kwargs: dict[str, object],
) -> None:
    lowerer = _lowerer(
        provider=LLMProvider.OPENAI,
        supported=_SPEEDS,
        enabled=[],
        reasoning=False,
        kwargs=kwargs,
    )
    with pytest.raises(ValueError, match="authorized execution options"):
        lowerer.lower([], model=_MODEL)
