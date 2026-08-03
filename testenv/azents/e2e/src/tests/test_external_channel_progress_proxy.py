"""Deterministic External Channel progress proxy tests."""

from support import image_generation_openai_proxy as proxy


def _request() -> dict[str, object]:
    return {
        "instructions": (
            "For a current input explicitly marked as an External Channel turn, "
            "invoke `channel_action`."
        ),
        "input": [
            {
                "role": "user",
                "content": (
                    "Message Type: EXTERNAL_CHANNEL_TURN\n"
                    "Provider: slack\n"
                    "Resource: #e2e\n"
                    "Binding: binding-dynamic-123\n\n"
                    "Provider-native Channel Work progress E2E. "
                    "Ask @User UREVIEWER in #e2e."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "tool_search",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "unrelated_active_tool",
                "parameters": {"type": "object"},
            },
        ],
    }


def test_progress_proxy_recognizes_resolved_external_turn_and_dynamic_binding() -> None:
    """The fixture activates only after visible Slack references are resolved."""
    request = _request()

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.external_channel_binding(request) == "binding-dynamic-123"
    assert proxy.external_channel_progress_evidence(request) == {
        "binding": "binding-dynamic-123",
        "marker_present": True,
        "resolved_user_reference": True,
        "resolved_channel_reference": True,
        "search_tool_available": True,
        "progress_tool_available": False,
    }


def test_progress_proxy_extracts_binding_from_compacted_channel_work() -> None:
    """A continuation can recover its handle from compacted Channel Work."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "## Channel Work Snapshot\n\n"
                "### Binding `binding-compacted-456`\n"
                "- Current work title: Continue"
            ),
        }
    ]

    assert proxy.external_channel_binding(request) == "binding-compacted-456"


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


def test_progress_proxy_ignores_non_string_nested_type_values() -> None:
    """Nested schema objects cannot be mistaken for tool-output item types."""
    request = _request()
    request["tools"] = [
        {
            "type": "function",
            "name": "channel_action",
            "parameters": {
                "type": {
                    "unexpected": "object",
                }
            },
        }
    ]

    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_progress",
        )
        is False
    )


def test_progress_proxy_records_unresolved_provider_references() -> None:
    """Raw provider IDs remain visible as precise projection evidence."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                "Binding: binding-dynamic-123\n\n"
                "Provider-native Channel Work progress E2E. "
                "Ask <@UREVIEWER> in <#CRELATED>."
            ),
        }
    ]

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.external_channel_progress_evidence(request) == {
        "binding": "binding-dynamic-123",
        "marker_present": True,
        "resolved_user_reference": False,
        "resolved_channel_reference": False,
        "search_tool_available": True,
        "progress_tool_available": False,
    }


def test_p0_continuation_proxy_stage_a_uses_rendered_active_binding() -> None:
    """Rendered continuation reminder produces the first dynamic tool call."""
    request: dict[str, object] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "E2E_P0_DISCORD_GATEWAY_AGENT_MARKER\n"
                    '<system_reminder type="external_channel_continuation">'
                    '<data>\n<item name="active_bindings">binding-discord-123'
                    "</item>\n</data>"
                ),
            },
            {"role": "assistant", "content": None},
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "channel_action"},
            }
        ],
    }
    assert proxy.external_channel_p0_continuation(request) == (
        "discord",
        "binding-discord-123",
        "DISCORD_GATEWAY_P0_AGENT_RESPONSE",
    )


def test_p0_continuation_proxy_stage_b_requires_our_tool_call_output() -> None:
    """Captured Chat tool-result shape completes only after our exact call ID."""
    request: dict[str, object] = {
        "messages": [
            {"role": "system", "content": "E2E_P0_SLACK_ACCESS_ALLOW_AGENT_MARKER"},
            {"role": "assistant", "content": None},
            {
                "role": "tool",
                "tool_call_id": "call_external_channel_p0_slack_finish",
                "content": '{"binding":"binding-slack-456"}',
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "channel_action"},
            }
        ],
    }
    assert proxy.external_channel_p0_continuation(request) == (
        "slack",
        "binding-slack-456",
        "SLACK_ACCESS_ALLOW_P0_AGENT_RESPONSE",
    )
    request["messages"] = [
        {"role": "system", "content": "E2E_P0_SLACK_ACCESS_ALLOW_AGENT_MARKER"},
        {
            "role": "tool",
            "tool_call_id": "call_unrelated",
            "content": '{"binding":"binding-wrong"}',
        },
        {
            "role": "tool",
            "tool_call_id": "call_external_channel_p0_slack_finish",
            "content": '{"status":"completed"}',
        },
    ]
    assert proxy.external_channel_p0_continuation(request) is None


def test_p0_continuation_proxy_excludes_initial_request_without_stage_inputs() -> None:
    """The initial Agent request has neither a continuation nor tool result."""
    request: dict[str, object] = {
        "messages": [
            {"role": "system", "content": "E2E_P0_DISCORD_GATEWAY_AGENT_MARKER"},
            {"role": "user", "content": "Private Discord Gateway invocation"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "channel_action"},
            }
        ],
    }
    assert proxy.external_channel_p0_continuation(request) is None
