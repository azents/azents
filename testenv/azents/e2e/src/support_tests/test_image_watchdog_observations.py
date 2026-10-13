"""Docker-free typed image request and watchdog boundary regression coverage."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from websockets.sync.connection import Connection

from support.image_watchdog_observations import (
    ContentObservation,
    ImageRequestObservation,
    ImageResultObservation,
    RequestNodeObservation,
    WatchdogActionObservation,
    WatchdogLiveObservation,
    WatchdogRetryObservation,
    decode_image_requests,
)
from tests.required.public.test_model_stream_watchdog import (
    _live_event_ids_containing,
    _live_partial_contents,
    _wait_for_ws_clean_retry,
)
from tests.required.public.test_provider_image_generation import (
    _assistant_content,
    _client_result,
    _count_typed_items,
    _image_tool,
    _last_user_text,
    _request_for_prompt,
)


def _event(kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "event-1",
        "session_id": "session-1",
        "kind": kind,
        "payload": payload,
        "schema_version": "1",
        "created_at": "2026-10-13T00:00:00Z",
    }


def _live(events: list[dict[str, object]]) -> dict[str, object]:
    return {"partial_history": {"items": events}, "session_run_state": "idle"}


def test_image_request_selection_preserves_native_extensions() -> None:
    wire = {
        "model": "gpt-5.5",
        "input": [
            {"type": "function_call_output", "call_id": "call", "output": "opaque"},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Generate ", "extension": 3},
                    {"type": "input_image", "image_url": "exchange://fixture"},
                    {"type": "input_text", "text": "an image"},
                ],
            },
        ],
        "tools": [{"type": "function", "name": "image_generation"}],
        "opaque_provider_field": {"nested": [1, None]},
    }
    request = decode_image_requests([wire])[0]
    assert _last_user_text(request) == "Generate an image"
    assert _request_for_prompt([request], "Generate an image") is request
    assert _image_tool(request).name == "image_generation"
    assert json.loads(request.serialized()) == wire
    assert _count_typed_items(wire["input"], "function_call_output") == 1


@pytest.mark.parametrize("bad", [1, True, {}, [1]])
def test_image_request_rejects_invalid_input_shapes(bad: object) -> None:
    with pytest.raises(ValidationError):
        ImageRequestObservation.model_validate({"input": bad})


@pytest.mark.parametrize("bad", [1, True, [], {}])
def test_image_request_rejects_non_string_decision_fields(bad: object) -> None:
    with pytest.raises(ValidationError):
        ImageRequestObservation.model_validate({"model": bad})
    with pytest.raises(ValidationError):
        RequestNodeObservation.model_validate({"type": bad})


def test_image_requests_omitted_and_null_optional_fields_are_preserved() -> None:
    omitted = ImageRequestObservation.model_validate({"model": "image-model"})
    explicit = ImageRequestObservation.model_validate({"input": None, "tools": None})
    assert "input" not in omitted.model_fields_set
    assert {"input", "tools"} <= explicit.model_fields_set
    assert _last_user_text(omitted) is None
    assert _last_user_text(explicit) is None


def test_typed_history_selection_keeps_valid_nonmatching_variants() -> None:
    structured = _event(
        "assistant_message", {"content": [{"type": "text", "text": "structured"}]}
    )
    unrelated = _event(
        "client_tool_result",
        {"call_id": "other", "name": "read", "status": "completed", "output": "text"},
    )
    image = _event(
        "client_tool_result",
        {
            "call_id": "image-call",
            "name": "image_generation",
            "status": "completed",
            "output": [{"type": "attachment", "uri": "exchange://image"}],
        },
    )
    assert _assistant_content(structured) is None
    assert _client_result([unrelated]) is None
    assert _client_result([image]) == image
    assert ImageResultObservation.model_validate(image["payload"]).output[0].uri == (
        "exchange://image"
    )


def test_watchdog_live_content_uses_typed_event_identity() -> None:
    payload = _live(
        [
            _event("assistant_message", {"content": "visible marker"}),
            _event(
                "client_tool_result", {"content": [{"type": "text", "text": "opaque"}]}
            ),
        ]
    )
    assert _live_partial_contents(payload) == ["visible marker"]
    assert _live_event_ids_containing(payload, "marker") == {"event-1"}
    assert WatchdogLiveObservation.model_validate(payload).run is None
    assert ContentObservation.model_validate({"content": None}).content is None


@pytest.mark.parametrize(
    "wire",
    [
        {"type": "live_event_upserted", "session_id": "s"},
        {"type": "live_event_removed", "session_id": "s"},
        {"type": "live_run_updated", "session_id": "s"},
        {"type": "live_event_removed", "session_id": "s", "event_id": True},
    ],
)
def test_watchdog_actions_reject_missing_or_malformed_variant_fields(
    wire: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WatchdogActionObservation.model_validate(wire)


def test_watchdog_retry_preserves_omitted_null_failure_code() -> None:
    retry = WatchdogRetryObservation.model_validate(
        {
            "error_kind": "model_provider",
            "failed_attempt_count": 1,
            "attempts": [
                {"attempt_number": 1, "user_message": "safe", "retryability": "unknown"}
            ],
        }
    )
    assert retry.attempts[0].failure_code is None
    with pytest.raises(ValidationError):
        WatchdogRetryObservation.model_validate(
            {
                "error_kind": "model_provider",
                "failed_attempt_count": True,
                "attempts": [],
            }
        )


@pytest.mark.parametrize("content", [True, 1, None])
def test_selected_assistant_content_rejects_invalid_scalar(content: object) -> None:
    with pytest.raises(ValidationError):
        _assistant_content(_event("assistant_message", {"content": content}))


def test_watchdog_websocket_cleanup_precedes_retry_and_preserves_extensions() -> None:
    wire = {
        "type": "live_run_updated",
        "session_id": "session-1",
        "run": {
            "retry": {
                "error_kind": "model_provider",
                "failed_attempt_count": 1,
                "attempts": [],
            },
            "extension": {"opaque": True},
        },
    }
    websocket = Mock(spec=Connection)
    websocket.recv.side_effect = [
        json.dumps(
            {
                "type": "live_event_removed",
                "session_id": "session-1",
                "event_id": "event-1",
            }
        ),
        json.dumps(wire),
    ]
    assert (
        _wait_for_ws_clean_retry(
            websocket,
            session_id="session-1",
            failed_event_ids={"event-1"},
            failed_attempt_count=1,
        )
        == wire
    )
    assert websocket.recv.call_count == 2


def test_watchdog_websocket_retry_cannot_precede_failed_event_cleanup() -> None:
    websocket = Mock(spec=Connection)
    websocket.recv.return_value = json.dumps(
        {
            "type": "live_run_updated",
            "session_id": "session-1",
            "run": {
                "retry": {
                    "error_kind": "model_provider",
                    "failed_attempt_count": 1,
                    "attempts": [],
                }
            },
        }
    )
    with pytest.raises(AssertionError):
        _wait_for_ws_clean_retry(
            websocket,
            session_id="session-1",
            failed_event_ids={"event-1"},
            failed_attempt_count=1,
        )
