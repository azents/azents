"""Docker-free observation regressions for subagent and scheduled-result flows."""

import json

import pytest
import requests
from azentspublicclient.models.chat_event_response import ChatEventResponse
from pydantic import ValidationError

from support.observations import decode_history_page
from tests.required.public import test_run_tool_to_file as materialization
from tests.required.public import test_scheduled_tasks as scheduled
from tests.required.public import test_subagents as subagents


def _event(
    kind: str, payload: dict[str, object], *, event_id: str = "event-1"
) -> ChatEventResponse:
    return ChatEventResponse.model_validate(
        {
            "id": event_id,
            "session_id": "session-1",
            "kind": kind,
            "payload": payload,
            "schema_version": "1",
            "created_at": "2026-10-13T00:00:00Z",
        }
    )


def _response(value: object) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(value).encode()
    return response


def test_agent_results_keep_nullable_nonterminal_status_and_extensions() -> None:
    message = subagents._AgentMessageObservation.model_validate(
        {
            "message_kind": "send_message",
            "source_path": "/root/child",
            "content": "working",
            "run_status": None,
            "future": {"opaque": True},
        }
    )
    assert message.run_status is None
    assert message.message_kind != "agent_result"
    assert message.model_extra == {"future": {"opaque": True}}
    with pytest.raises(ValidationError):
        subagents._AgentMessageObservation.model_validate(
            {"message_kind": "agent_result", "source_path": True, "content": "done"}
        )


def test_agent_result_wait_matches_source_status_and_detects_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        subagents._AgentMessageObservation.model_validate(
            {
                "message_kind": "agent_result",
                "source_path": "/root/child",
                "run_status": "completed",
                "content": "done",
            }
        )
    ]
    monkeypatch.setattr(subagents, "_agent_message_payloads", lambda **kwargs: messages)
    result = subagents._wait_for_agent_result(
        public_url="unused",
        token="unused",
        session_id="session-1",
        source_path="/root/child",
        run_status="completed",
    )
    assert result["content"] == "done"
    messages.append(messages[0])
    with pytest.raises(AssertionError, match="duplicate terminal"):
        subagents._wait_for_agent_result(
            public_url="unused",
            token="unused",
            session_id="session-1",
            source_path="/root/child",
            run_status="completed",
        )


@pytest.mark.parametrize(
    "output,expected",
    [
        ("plain", "plain"),
        (
            [
                {"type": "text", "text": "first"},
                {"type": "attachment", "uri": "exchange://file"},
                {"type": "output_text", "text": "second"},
            ],
            "first\nsecond",
        ),
        (None, None),
    ],
)
def test_tool_output_preserves_text_structured_parts_and_nullable_observation(
    output: object, expected: str | None
) -> None:
    event = _event(
        "client_tool_result",
        {"call_id": "call-1", "status": "completed", "output": output},
    )
    assert subagents._tool_result_output_text(event) == expected
    assert (
        subagents._tool_result_output_text(
            _event("reasoning", {"native": {"opaque": True}})
        )
        is None
    )


def test_wait_outcome_matches_declared_fields_without_ignoring_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event(
        "client_tool_result",
        {
            "call_id": "call-1",
            "output": json.dumps(
                {
                    "outcome": "timeout",
                    "reason": "active_descendants",
                    "future": True,
                }
            ),
        },
    )
    monkeypatch.setattr(subagents, "_history", lambda **kwargs: [event])
    result = subagents._wait_for_tool_result_outcome(
        public_url="unused",
        token="unused",
        session_id="session-1",
        call_id="call-1",
        outcome="timeout",
        reason="active_descendants",
    )
    assert result["id"] == "event-1"
    assert (
        subagents._WaitOutcomeObservation.model_validate(
            {"outcome": "all_idle", "reason": None}
        ).reason
        is None
    )
    with pytest.raises(ValidationError):
        subagents._WaitOutcomeObservation.model_validate({"outcome": True})


def test_list_agents_rejects_extra_item_fields_and_nonstring_status() -> None:
    valid = {"agents": [{"agent_name": "/root/child", "agent_status": "idle"}]}
    assert subagents._listed_agents(valid) == valid["agents"]
    for invalid in [
        {"agent_name": "/root/child", "agent_status": False},
        {"agent_name": "/root/child", "agent_status": "idle", "private": True},
    ]:
        with pytest.raises(ValidationError):
            subagents._listed_agents({"agents": [invalid]})


def test_run_markers_ignore_unrelated_payload_and_require_typed_status() -> None:
    assert subagents._run_marker_completed(
        _event("run_marker", {"status": "completed"})
    )
    assert not subagents._run_marker_completed(
        _event("run_marker", {"status": "failed"})
    )
    assert not subagents._run_marker_completed(_event("reasoning", {"status": True}))
    with pytest.raises(ValidationError):
        subagents._run_marker_completed(_event("run_marker", {"status": True}))


def test_materialization_history_selects_only_target_text_result() -> None:
    events = [
        _event("reasoning", {"opaque": True}),
        _event("client_tool_result", {"call_id": "different", "output": []}),
        _event("client_tool_result", {"call_id": "target", "output": "stored"}),
    ]
    page = decode_history_page(
        {
            "items": [event.model_dump(mode="json") for event in events],
            "has_more": False,
            "next_cursor": None,
        }
    )
    assert materialization._tool_result_output(page, call_id="target") == "stored"
    with pytest.raises(AssertionError, match="not text"):
        materialization._tool_result_output(page, call_id="different")


def test_scheduled_result_uses_event_kind_and_typed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event(
        "scheduled_task_result",
        {
            "title": "Scheduled",
            "scheduled_for": "2099-01-02T03:04:05Z",
            "status": "finished",
            "result": "done",
        },
    )
    monkeypatch.setattr(
        scheduled.requests,
        "get",
        lambda *args, **kwargs: _response(
            {
                "items": [event.model_dump(mode="json")],
                "has_more": False,
                "next_cursor": None,
            }
        ),
    )
    result = scheduled._scheduled_result(
        public_server_url="unused",
        token="unused",
        session_id="session-1",
        expected_result="done",
    )
    assert result is not None and result["scheduled_for"] == "2099-01-02T03:04:05Z"
    assert (
        scheduled._scheduled_result(
            public_server_url="unused",
            token="unused",
            session_id="session-1",
            expected_result="other",
        )
        is None
    )
    with pytest.raises(ValidationError):
        scheduled._ScheduledResultObservation.model_validate(
            {
                "title": "Scheduled",
                "scheduled_for": "2099-01-02T03:04:05Z",
                "status": "idle",
                "result": "done",
            }
        )


def test_dispatch_counter_validation_rejects_boolean_coercion() -> None:
    payload = {
        "now": "2099-01-02T03:04:05Z",
        "claimed": 1,
        "admitted": 1,
        "coalesced": 0,
        "skipped": 0,
        "wake_failed": 0,
    }
    assert scheduled._DispatchObservation.model_validate(payload).claimed == 1
    with pytest.raises(ValidationError):
        scheduled._DispatchObservation.model_validate({**payload, "claimed": True})
