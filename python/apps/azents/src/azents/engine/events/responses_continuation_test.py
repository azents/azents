"""Responses continuation planner tests."""

from collections.abc import Mapping, Sequence

import pytest

from azents.engine.events.protocols import NativeModelRequest
from azents.engine.events.responses_continuation import (
    ResponsesContinuationPlanner,
    sanitize_responses_native_item,
)


def _request(
    input_items: Sequence[Mapping[str, object]],
    *,
    model: str = "gpt-5.1",
    tools: list[dict[str, object]] | None = None,
    kwargs: dict[str, object] | None = None,
) -> NativeModelRequest:
    """Build a full logical request for continuation tests."""
    return NativeModelRequest(
        model=model,
        input=[dict(item) for item in input_items],
        tools=(tools if tools is not None else [{"type": "function", "name": "read"}]),
        kwargs=(
            kwargs if kwargs is not None else {"instructions": "help", "store": True}
        ),
    )


def _seed(
    planner: ResponsesContinuationPlanner,
) -> tuple[NativeModelRequest, dict[str, object]]:
    """Record one completed function-call response."""
    request = _request([{"role": "user", "content": "read file"}])
    output: dict[str, object] = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "read",
        "arguments": "{}",
    }
    planner.record_completion(
        request,
        response_id="resp-1",
        output_items=[output],
    )
    return request, output


def test_first_request_uses_full_input() -> None:
    """A continuation chain starts with a full physical request."""
    planner = ResponsesContinuationPlanner()
    request = _request([{"role": "user", "content": "hello"}])

    plan = planner.plan(request)

    assert plan.previous_response_id is None
    assert plan.input_items == request.input


def test_exact_prefix_sends_only_new_input() -> None:
    """Strip the prior request and response output from an exact continuation."""
    planner = ResponsesContinuationPlanner()
    previous, output = _seed(planner)
    delta = {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "contents",
    }
    current = _request([*previous.input, output, delta])

    plan = planner.plan(current)

    assert plan.previous_response_id == "resp-1"
    assert plan.input_items == [delta]


@pytest.mark.parametrize("changed", ["model", "tools", "kwargs"])
def test_request_property_change_uses_full_input(changed: str) -> None:
    """Do not chain across any request-property change."""
    planner = ResponsesContinuationPlanner()
    previous, output = _seed(planner)
    delta = {"type": "function_call_output", "call_id": "call-1", "output": "x"}
    model = "gpt-5.2" if changed == "model" else previous.model
    tools = [] if changed == "tools" else previous.tools
    kwargs = (
        {**previous.kwargs, "instructions": "changed"}
        if changed == "kwargs"
        else previous.kwargs
    )
    current = _request(
        [*previous.input, output, delta],
        model=model,
        tools=tools,
        kwargs=kwargs,
    )

    plan = planner.plan(current)

    assert plan.previous_response_id is None
    assert plan.input_items == current.input


@pytest.mark.parametrize("mismatch", ["request", "output", "empty_delta"])
def test_prefix_mismatch_or_empty_delta_uses_full_input(mismatch: str) -> None:
    """Fall back when the full logical request cannot prove the exact boundary."""
    planner = ResponsesContinuationPlanner()
    previous, output = _seed(planner)
    delta = {"type": "function_call_output", "call_id": "call-1", "output": "x"}
    input_items = [*previous.input, output, delta]
    if mismatch == "request":
        input_items[0] = {"role": "user", "content": "edited"}
    elif mismatch == "output":
        input_items[1] = {**output, "arguments": '{"path":"other"}'}
    else:
        input_items = [*previous.input, output]
    current = _request(input_items)

    plan = planner.plan(current)

    assert plan.previous_response_id is None
    assert plan.input_items == current.input


def test_store_false_and_disabled_planner_use_full_input() -> None:
    """Require provider storage and stop chaining after stored state is rejected."""
    planner = ResponsesContinuationPlanner()
    previous, output = _seed(planner)
    delta = {"type": "function_call_output", "call_id": "call-1", "output": "x"}
    unstored = _request(
        [*previous.input, output, delta],
        kwargs={**previous.kwargs, "store": False},
    )

    assert planner.plan(unstored).previous_response_id is None

    planner.disable()
    stored = _request([*previous.input, output, delta])
    assert planner.plan(stored).previous_response_id is None


def test_recorded_state_is_deep_copied_and_sanitized() -> None:
    """Keep comparison state isolated and aligned with durable native artifacts."""
    planner = ResponsesContinuationPlanner()
    request_input = [{"role": "user", "content": "generate"}]
    request = _request(request_input)
    output = {
        "type": "image_generation_call",
        "id": "image-1",
        "result": "raw-image",
        "metadata": {
            "provider_payload": "raw-provider-data",
            "kept": [{"base64": "raw", "name": "preview"}],
        },
    }
    planner.record_completion(
        request,
        response_id="resp-image",
        output_items=[output],
    )
    request_input[0]["content"] = "mutated"
    output["id"] = "mutated"
    sanitized_output = {
        "type": "image_generation_call",
        "id": "image-1",
        "metadata": {"kept": [{"name": "preview"}]},
    }
    delta = {"role": "user", "content": "continue"}
    current = _request(
        [
            {"role": "user", "content": "generate"},
            sanitized_output,
            delta,
        ]
    )

    plan = planner.plan(current)

    assert plan.previous_response_id == "resp-image"
    assert plan.input_items == [delta]


def test_request_local_rehydration_does_not_break_continuation() -> None:
    """Compare sanitized items while preserving physical request-local Base64."""
    planner = ResponsesContinuationPlanner()
    previous = _request([{"role": "user", "content": "generate"}])
    output = {
        "type": "image_generation_call",
        "id": "image-1",
        "result": "provider-base64",
    }
    planner.record_completion(
        previous,
        response_id="resp-image",
        output_items=[output],
    )
    rehydrated_output = {
        "type": "image_generation_call",
        "id": "image-1",
        "result": "request-local-base64",
    }
    delta = {"role": "user", "content": "continue"}
    current = _request([*previous.input, rehydrated_output, delta])

    plan = planner.plan(current)

    assert plan.previous_response_id == "resp-image"
    assert plan.input_items == [delta]
    assert rehydrated_output["result"] == "request-local-base64"


def test_sanitizer_removes_nested_blob_fields() -> None:
    """Use the same recursive blob policy for artifacts and continuation state."""
    assert sanitize_responses_native_item(
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "kept",
                    "file_data": "raw",
                    "nested": {"data_base64": "raw", "value": 1},
                }
            ],
        }
    ) == {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": "kept",
                "nested": {"value": 1},
            }
        ],
    }
