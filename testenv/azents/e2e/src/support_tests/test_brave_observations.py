"""Docker-free typed-boundary regressions for Brave product E2E evidence."""

import json

import pytest
import requests
from pydantic import ValidationError

from support.image_watchdog_observations import (
    ContentObservation,
    decode_image_requests,
)
from support.observations import ToolCallObservation, ToolResultObservation
from tests.required.public import test_brave_runtime as runtime_flow
from tests.required.public import test_brave_search as search_flow
from tests.required.public.test_provider_image_generation import _count_typed_items


def _event(kind: str, payload: object) -> dict[str, object]:
    return {
        "id": "event-1",
        "session_id": "session-1",
        "kind": kind,
        "payload": payload,
        "schema_version": "1",
        "created_at": "2026-10-13T00:00:00Z",
        "provider": None,
        "future_event_evidence": {"opaque": True},
    }


def _history(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "items": items,
        "has_more": False,
        "has_newer": False,
        "next_cursor": None,
        "previous_cursor": None,
    }


def _response(payload: object) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    return response


@pytest.mark.parametrize("kind", ["web", "context", "news", "images", "videos"])
def test_brave_history_retains_typed_calls_results_and_event_extensions(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    history = _history(
        [
            _event(
                "client_tool_call",
                {
                    "call_id": "call-1",
                    "name": f"brave__search_{kind}",
                    "arguments": {"q": "query"},
                },
            ),
            _event(
                "client_tool_result",
                {
                    "call_id": "call-1",
                    "name": f"brave__search_{kind}",
                    "status": "completed",
                    "output": "https://source.example/",
                },
            ),
        ]
    )
    monkeypatch.setattr(search_flow, "list_history", lambda **kwargs: history)
    events = search_flow._tool_events(
        server_url="https://api.test", token="token", session_id="session-1"
    )
    call = ToolCallObservation.model_validate(events[0].payload)
    result = ToolResultObservation.model_validate(events[1].payload)
    assert call.name == result.name == f"brave__search_{kind}"
    assert call.call_id == result.call_id == "call-1"
    assert result.status == "completed"
    assert events[0].additional_properties["future_event_evidence"] == {"opaque": True}


def test_brave_history_malformed_event_fails_before_state_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = _event("client_tool_result", {"call_id": "call-1"})
    malformed["id"] = 1
    monkeypatch.setattr(
        search_flow, "list_history", lambda **kwargs: _history([malformed])
    )
    with pytest.raises(ValidationError):
        search_flow._tool_events(
            server_url="https://api.test", token="token", session_id="session-1"
        )


@pytest.mark.parametrize("output", [None, "text", ["opaque", None], {"opaque": True}])
def test_nullable_result_metadata_and_opaque_outputs_remain_canonical(
    output: object,
) -> None:
    result = ToolResultObservation.model_validate(
        {"call_id": "call-1", "name": None, "status": None, "output": output}
    )
    assert result.name is None
    assert result.status is None
    assert result.output == output


@pytest.mark.parametrize(
    "content", [None, "text", [{"type": "text", "text": "bounded"}]]
)
def test_brave_assistant_content_is_opaque_until_the_text_assertion(
    content: object,
) -> None:
    assert ContentObservation.model_validate({"content": content}).content == content


def test_brave_request_journal_preserves_typed_input_and_opaque_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [
        {
            "model": "fixture-model",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_brave_e2e_images",
                    "output": "opaque-output",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "https://image.test/1"},
                        {"type": "input_image", "image_url": "https://image.test/2"},
                    ],
                },
            ],
            "native_extension": {"provider": [None, True, "value"]},
        }
    ]
    monkeypatch.setattr(
        search_flow.requests, "get", lambda *args, **kwargs: _response(payload)
    )
    journal = search_flow._request_journal("https://proxy.test")
    assert len(journal) == 1
    request = journal[0]
    assert "call_brave_e2e_images" in request.serialized()
    assert "function_call_output" in request.serialized()
    assert (
        json.loads(request.serialized())["native_extension"]
        == payload[0]["native_extension"]
    )
    assert (
        _count_typed_items(search_flow._request_input_wire(request), "input_image") == 2
    )


@pytest.mark.parametrize("input_value", [None, "transparent text", []])
def test_brave_request_preserves_nullable_string_and_empty_input(
    input_value: object,
) -> None:
    request = decode_image_requests([{"input": input_value}])[0]
    assert search_flow._request_input_wire(request) == input_value
    assert (
        _count_typed_items(search_flow._request_input_wire(request), "input_image") == 0
    )


@pytest.mark.parametrize("invalid", [1, True, {"role": "user"}])
def test_brave_request_rejects_malformed_input_contract(invalid: object) -> None:
    with pytest.raises(ValidationError):
        decode_image_requests([{"input": invalid}])


def test_brave_attachment_projection_retains_all_parts_and_nullable_fields() -> None:
    payload = [
        {"type": "text", "text": "source link", "kind": None},
        {
            "type": "attachment",
            "kind": "image",
            "uri": "exchange://one",
            "attachment_id": "one",
            "availability": "available",
        },
        {
            "type": "attachment",
            "kind": "image",
            "uri": "exchange://two",
            "attachment_id": "two",
            "availability": "available",
        },
    ]
    parts = search_flow._IMAGE_PARTS.validate_python(payload)
    managed_parts = runtime_flow._IMAGE_PARTS.validate_python(payload)
    assert sum(part.type == "attachment" for part in parts) == 2
    assert sum(part.kind == "image" for part in parts) == 2
    assert parts[0].kind is None
    assert [part.uri for part in managed_parts] == [
        None,
        "exchange://one",
        "exchange://two",
    ]
    assert parts[0].model_extra == {"text": "source link"}


@pytest.mark.parametrize(
    "field", ["type", "kind", "uri", "attachment_id", "availability"]
)
def test_brave_attachment_rejects_coercible_interpreted_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        search_flow._IMAGE_PARTS.validate_python([{field: 1}])


def test_brave_terminal_marker_drain_retains_the_idle_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _event("run_marker", {"run_id": "run-1", "status": "completed"})
    monkeypatch.setattr(
        search_flow, "list_history", lambda **kwargs: _history([marker])
    )
    idle_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        search_flow, "_wait_for_idle", lambda **kwargs: idle_calls.append(kwargs)
    )
    search_flow._wait_for_terminal_session(
        server_url="https://api.test",
        token="token",
        agent_id="agent-1",
        session_id="session-1",
    )
    assert idle_calls == [
        {
            "server_url": "https://api.test",
            "token": "token",
            "agent_id": "agent-1",
            "session_id": "session-1",
        }
    ]


def test_brave_connection_response_retains_extensions_for_redaction() -> None:
    observed = search_flow._ConnectionTestObservation.model_validate(
        {
            "success": False,
            "message": "Invalid credentials",
            "provider_extension": {"private_value": "redaction-canary"},
        }
    )
    assert observed.success is False
    assert observed.message == "Invalid credentials"
    assert "redaction-canary" in str(observed)
    assert observed.discovered_auth_url is None


@pytest.mark.parametrize("success", [1, "true", None])
def test_brave_connection_response_rejects_malformed_success(success: object) -> None:
    with pytest.raises(ValidationError):
        search_flow._ConnectionTestObservation.model_validate(
            {"success": success, "message": "Result"}
        )
