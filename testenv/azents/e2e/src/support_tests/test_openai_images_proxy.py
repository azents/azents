"""Deterministic client-executed OpenAI Images proxy tests."""

from support.image_generation_openai_proxy import has_current_tool_output


def test_previous_image_result_does_not_complete_new_turn() -> None:
    """An earlier image result must not skip a subsequent generation request."""
    call_id = "call_openai_image_generation"
    previous = {"type": "function_call_output", "call_id": call_id, "output": "ok"}
    inputs: list[dict[str, object]] = [
        {"role": "user", "content": "first image"},
        previous,
        {"role": "user", "content": "second image"},
    ]

    assert not has_current_tool_output({"input": inputs}, call_id)
    assert has_current_tool_output(
        {"input": [*inputs, previous]},
        call_id,
    )
