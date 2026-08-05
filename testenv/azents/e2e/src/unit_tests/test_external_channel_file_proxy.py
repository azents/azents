"""Deterministic External Channel file-transfer proxy tests."""

from typing import cast

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
                    "Resource: #files\n"
                    "Binding: binding-file-123\n\n"
                    "External Channel file transfer E2E.\n"
                    "Files:\n"
                    "1. Name: first.txt\n"
                    "   Declared size: 32 bytes\n"
                    "   File: external-file:v1:slack:binding-file-123:::F1\n"
                    "2. Name: second.txt\n"
                    "   Declared size: 64 bytes\n"
                    "   File: external-file:v1:slack:binding-file-123:::F2"
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "download_external_file",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "exec_command",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "channel_action",
                "parameters": {"type": "object"},
            },
        ],
    }


def test_file_proxy_recognizes_two_locators_and_required_tools() -> None:
    """The deterministic journey activates only with the complete file contract."""
    request = _request()

    assert proxy.is_external_channel_file_request(request) is True
    assert proxy.external_channel_file_locators(request) == [
        "external-file:v1:slack:binding-file-123:::F1",
        "external-file:v1:slack:binding-file-123:::F2",
    ]
    assert proxy.external_channel_file_declared_sizes(request) == [32, 64]
    assert proxy.external_channel_file_evidence(request) == {
        "matched": True,
        "binding": "binding-file-123",
        "marker_present": True,
        "locator_count": 2,
        "search_tool_available": False,
        "download_tool_available": True,
        "process_tool_available": True,
        "channel_action_tool_available": True,
    }


def test_file_proxy_recognizes_initial_tool_search_surface() -> None:
    """The deterministic journey can activate deferred file and publish tools."""
    request = _request()
    request["tools"] = [
        {
            "type": "function",
            "name": "tool_search",
            "parameters": {"type": "object"},
        }
    ]

    assert proxy.is_external_channel_file_request(request) is True
    assert proxy.external_channel_file_evidence(request) == {
        "matched": True,
        "binding": "binding-file-123",
        "marker_present": True,
        "locator_count": 2,
        "search_tool_available": True,
        "download_tool_available": False,
        "process_tool_available": False,
        "channel_action_tool_available": False,
    }


def test_file_proxy_tracks_each_tool_output_stage() -> None:
    """Download, Runtime processing, and publication outputs remain distinguishable."""
    request = _request()
    initial_input = request["input"]
    assert isinstance(initial_input, list)
    request["input"] = [
        *initial_input,
        {
            "type": "function_call_output",
            "call_id": "call_external_channel_file_tool_search",
            "output": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_external_channel_file_download",
            "output": "{}",
        },
        {
            "role": "tool",
            "tool_call_id": "call_external_channel_file_process",
            "content": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_external_channel_file_finish",
            "output": "{}",
        },
    ]

    assert proxy.request_has_tool_output(
        request,
        "call_external_channel_file_tool_search",
    )
    assert proxy.request_has_tool_output(
        request,
        "call_external_channel_file_download",
    )
    assert proxy.request_has_tool_output(
        request,
        "call_external_channel_file_process",
    )
    assert proxy.request_has_tool_output(
        request,
        "call_external_channel_file_finish",
    )


def test_file_proxy_rejects_incomplete_tool_surface() -> None:
    """A missing Runtime processing tool cannot activate the file scenario."""
    request = _request()
    tools = request["tools"]
    assert isinstance(tools, list)
    typed_tools = [
        cast(dict[str, object], tool)
        for tool in cast(list[object], tools)
        if isinstance(tool, dict)
    ]
    request["tools"] = [
        tool for tool in typed_tools if tool.get("name") != "exec_command"
    ]

    assert proxy.is_external_channel_file_request(request) is False
