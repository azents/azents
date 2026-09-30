"""Fail-closed native terminal evidence independently of common assembly."""

from typing import NamedTuple

import pytest

from azents.engine.events.pydantic_ai_adapter_test import context_for_test
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    NativeModelProtocol,
    PydanticAIStreamEvent,
)
from azents.engine.model_stream import ModelStreamTimeoutPolicy
from azents.engine.provider_errors import map_model_provider_error
from azents.engine.providers.native_observation import observe_native_payload
from azents.engine.providers.observation_state import NativeObservationState
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)


@pytest.mark.parametrize(
    ("protocol", "payload", "code"),
    [
        (
            "responses",
            {
                "type": "response.incomplete",
                "response": {"incomplete_details": {"reason": "max_output_tokens"}},
            },
            "max_output_tokens",
        ),
        (
            "anthropic",
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
            "max_output_tokens",
        ),
        (
            "google",
            {"candidates": [{"finishReason": "MAX_TOKENS"}]},
            "max_output_tokens",
        ),
        ("bedrock", {"messageStop": {"stopReason": "max_tokens"}}, "max_output_tokens"),
        (
            "chat_completions",
            {"choices": [{"finish_reason": "length"}]},
            "max_output_tokens",
        ),
        (
            "responses",
            {
                "type": "response.incomplete",
                "response": {"incomplete_details": {"reason": "content_filter"}},
            },
            "content_filter",
        ),
        (
            "anthropic",
            {"type": "message_delta", "delta": {"stop_reason": "refusal"}},
            "refusal",
        ),
        ("google", {"candidates": [{"finishReason": "SAFETY"}]}, "SAFETY"),
        (
            "google",
            {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}},
            "PROHIBITED_CONTENT",
        ),
        (
            "bedrock",
            {"messageStop": {"stopReason": "guardrail_intervened"}},
            "guardrail_intervened",
        ),
        (
            "bedrock",
            {"messageStop": {"stopReason": "content_filtered"}},
            "content_filtered",
        ),
        (
            "chat_completions",
            {"choices": [{"finish_reason": "content_filter"}]},
            "content_filter",
        ),
    ],
)
async def test_limits_and_policy_refusals_preserve_first_failure_and_late_usage(
    protocol: NativeModelProtocol,
    payload: dict[str, object],
    code: str,
) -> None:
    state = NativeObservationState(
        protocol=protocol,
        call_context=context_for_test(),
        timeout_policy=ModelStreamTimeoutPolicy(
            connect_timeout_seconds=2,
            parsed_event_idle_timeout_seconds=5,
            absolute_attempt_timeout_seconds=30,
        ),
        sdk_failure_mapper=map_model_provider_error,
    )
    output = PydanticAIOutputNormalizer(
        provider="synthetic",
        model="exact/saved-model",
        pricing=None,
        operation="sampling",
        integration="synthetic-integration",
    ).start("synthetic-session")
    await state.observe(payload)
    first = await state.queue.get()
    assert isinstance(first, PydanticAIStreamEvent)
    assert first.observation is not None
    assert first.observation.terminal in {"incomplete", "failed"}
    assert first.observation.error is not None
    assert first.observation.error.code == code
    output.process_event(first)
    if code == "max_output_tokens":
        assert (
            first.observation.error.message
            == "The model response reached its output token limit."
        )
    # Native usage is still visible after a failing terminal; it is not success.
    trailing = trailing_events(protocol)
    await state.observe(trailing.usage)
    late = await state.queue.get()
    assert isinstance(late, PydanticAIStreamEvent)
    assert late.observation is not None and late.observation.native_usage is not None
    output.process_event(late)
    assert output.native_usage == late.observation.native_usage
    await state.observe(trailing.success)
    contradictory = await state.queue.get()
    assert isinstance(contradictory, PydanticAIStreamEvent)
    assert contradictory.observation is not None
    assert contradictory.observation.terminal == first.observation.terminal
    assert contradictory.observation.error == first.observation.error
    output.process_event(contradictory)
    with pytest.raises(ModelProviderFailure) as raised:
        output.complete()
    assert raised.value.provider_code == code
    assert raised.value.model == "exact/saved-model"
    assert raised.value.category == (
        ModelProviderFailureCategory.INVALID_REQUEST
        if code == "max_output_tokens"
        else ModelProviderFailureCategory.CONTENT_POLICY
    )


class NativeTrailingEvents(NamedTuple):
    usage: dict[str, object]
    success: dict[str, object]


def trailing_events(protocol: NativeModelProtocol) -> NativeTrailingEvents:
    # Each payload is provider-native evidence; no synthetic ModelResponse exists.
    match protocol:
        case "responses":
            return NativeTrailingEvents(
                {
                    "type": "response.in_progress",
                    "response": {"usage": {"input_tokens": 3, "output_tokens": 2}},
                },
                {"type": "response.completed", "response": {"status": "completed"}},
            )
        case "anthropic":
            return NativeTrailingEvents(
                {
                    "type": "message_delta",
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
                {"type": "message_stop"},
            )
        case "google":
            return NativeTrailingEvents(
                {"usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}},
                {"candidates": [{"finishReason": "STOP"}]},
            )
        case "bedrock":
            return NativeTrailingEvents(
                {"metadata": {"usage": {"inputTokens": 3, "outputTokens": 2}}},
                {"messageStop": {"stopReason": "end_turn"}},
            )
        case "chat_completions":
            return NativeTrailingEvents(
                {"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
                {"choices": [{"finish_reason": "stop"}]},
            )


@pytest.mark.parametrize(
    ("protocol", "payload"),
    [
        (
            "google",
            {"candidates": [{"finishReason": "MAX_TOKENS"}, {"finishReason": "STOP"}]},
        ),
        (
            "chat_completions",
            {"choices": [{"finish_reason": "length"}, {"finish_reason": "stop"}]},
        ),
    ],
)
def test_same_frame_success_cannot_erase_output_limit(
    protocol: NativeModelProtocol, payload: dict[str, object]
) -> None:
    observed = observe_native_payload(protocol, payload)
    assert observed.terminal == "incomplete"
    assert observed.error is not None
    assert observed.error.code == "max_output_tokens"
