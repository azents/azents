"""Known Responses projections preserve permissive wire compatibility."""

import pytest

from azents.engine.events.responses_wire import (
    CompletedResponse,
    ResponseOutputItem,
    ResponseStreamFrame,
)


@pytest.mark.parametrize("value", [None, [], 4, "opaque"])
def test_non_object_items_have_no_semantic_type(value: object) -> None:
    item = ResponseOutputItem.decode(value)
    assert not item.has_type
    assert item.type == item.call_id == item.name == item.arguments == ""


def test_function_coercion_and_custom_validation_are_distinct() -> None:
    raw = {"type": "function_call", "id": 7, "name": 8, "arguments": False}
    item = ResponseOutputItem.decode(raw)
    assert (item.call_id, item.name, item.arguments) == ("7", "8", "")
    assert item.custom_call_id is None
    assert item.custom_name is None
    assert item.raw is raw


def test_content_filters_invalid_parts_without_losing_unknown_artifacts() -> None:
    raw = {
        "type": "reasoning",
        "content": [{"text": "one"}, {"text": 8}, None, {"text": "two"}],
        "summary": [{"text": "summary"}],
        "extension": {"future": True},
    }
    item = ResponseOutputItem.decode(raw)
    assert item.reasoning_text == "one\ntwo"
    assert item.reasoning_summary == "summary"
    assert item.raw["extension"] == {"future": True}


@pytest.mark.parametrize("value", [None, "true", 1, {}, []])
def test_completion_does_not_coerce_end_turn(value: object) -> None:
    response = CompletedResponse.decode({"end_turn": value, "output": "invalid"})
    assert response.end_turn is None
    assert response.output == ()


def test_stream_preserves_explicit_null_delta_and_strict_counter() -> None:
    frame = ResponseStreamFrame.decode(
        {"delta": None, "output_index": True, "summary_index": "2", "item_id": 4}
    )
    assert frame.delta == "None"
    assert frame.output_index is frame.summary_index is frame.item_id is None
