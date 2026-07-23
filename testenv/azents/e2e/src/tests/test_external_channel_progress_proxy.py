"""Deterministic External Channel progress proxy tests."""

from support import image_generation_openai_proxy as proxy


def _request() -> dict[str, object]:
    return {
        "instructions": (
            "### External Channel Work\n\n"
            "### Binding `binding-dynamic-123`\n"
            "- Current work title: Not declared yet"
        ),
        "input": [
            {
                "role": "user",
                "content": (
                    "Provider-native Channel Work progress E2E. "
                    "Ask @User UREVIEWER in #e2e."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "channel_action",
                "parameters": {"type": "object"},
            }
        ],
    }


def test_progress_proxy_recognizes_resolved_external_turn_and_dynamic_binding() -> None:
    """The fixture activates only after visible Slack references are resolved."""
    request = _request()

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.external_channel_binding(request) == "binding-dynamic-123"


def test_progress_proxy_distinguishes_continue_and_finish_tool_outputs() -> None:
    """Responses and Chat tool-result shapes advance the deterministic sequence."""
    request = _request()
    initial_input = request["input"]
    assert isinstance(initial_input, list)
    request["input"] = [
        *initial_input,
        {
            "type": "function_call_output",
            "call_id": "call_external_channel_progress",
            "output": "{}",
        },
        {
            "role": "tool",
            "tool_call_id": "call_external_channel_finish",
            "content": "{}",
        },
    ]

    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_progress",
        )
        is True
    )
    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_finish",
        )
        is True
    )
    assert proxy.request_has_tool_output(request, "call_missing") is False


def test_progress_proxy_requires_provider_resolved_names() -> None:
    """Raw provider IDs do not activate the name-resolution E2E response."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Provider-native Channel Work progress E2E. "
                "Ask <@UREVIEWER> in <#CRELATED>."
            ),
        }
    ]

    assert proxy.is_external_channel_progress_request(request) is False
