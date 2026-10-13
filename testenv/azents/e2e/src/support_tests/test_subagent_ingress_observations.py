"""Pure subagent observation contracts without product or network listeners."""

import json

import pytest
from azentspublicclient.models.chat_event_response import ChatEventResponse
from pydantic import ValidationError

from tests.required.public import test_subagents as subagents
from tests.required.public.test_subagents import (
    _AgentMessageObservation,
    _ListedAgentsObservation,
    _TreeObservation,
    _WaitOutcomeObservation,
)


def _tree() -> dict[str, object]:
    """Represent the current public API tree shape with opaque extensions."""
    return {
        "root_session_agent_id": "root-agent",
        "root_agent_session_id": "root-session",
        "current_session_agent_id": "child-agent",
        "opaque_tree_extension": {"future": True},
        "nodes": [
            {
                "session_agent_id": "child-agent",
                "agent_session_id": "child-session",
                "parent_session_agent_id": "root-agent",
                "name": "child",
                "path": "/root/child",
                "agent_type": "default",
                "status": "completed",
                "unread_result": True,
                "latest_run_status": "completed",
                "terminal_result_event_id": None,
                "terminal_result_message": None,
                "children": [],
                "opaque_node_extension": {"future": "value"},
            }
        ],
    }


def test_tree_preserves_generated_null_defaults_and_opaque_extensions() -> None:
    tree = _TreeObservation.model_validate(_tree())
    assert tree.root_agent_session_id == "root-session"
    assert tree.current_session_agent_id == "child-agent"
    child = tree.nodes[0]
    assert child.agent_session_id == "child-session"
    assert child.latest_run_status == "completed"
    assert child.terminal_result_event_id is None
    assert child.terminal_result_message is None
    assert child.latest_run_id is None
    assert child.children == []
    assert tree.model_extra == {"opaque_tree_extension": {"future": True}}
    assert child.model_extra == {"opaque_node_extension": {"future": "value"}}


@pytest.mark.parametrize("value", [None, {}, "true", 1])
def test_tree_rejects_malformed_children_at_http_ingress(value: object) -> None:
    payload = _tree()
    node = {
        "session_agent_id": "child-agent",
        "agent_session_id": "child-session",
        "name": "child",
        "path": "/root/child",
        "agent_type": "default",
        "status": "completed",
        "unread_result": True,
        "children": value,
    }
    payload["nodes"] = [node]
    with pytest.raises(ValidationError):
        _TreeObservation.model_validate(payload)


@pytest.mark.parametrize("unread", ["true", 1, None])
def test_tree_retains_strict_boolean_authoritative_state(unread: object) -> None:
    payload = _tree()
    payload["nodes"] = [
        {
            "session_agent_id": "child-agent",
            "agent_session_id": "child-session",
            "name": "child",
            "path": "/root/child",
            "agent_type": "default",
            "status": "completed",
            "unread_result": unread,
            "children": [],
        }
    ]
    with pytest.raises(ValidationError):
        _TreeObservation.model_validate(payload)


def test_list_waiter_decodes_matching_embedded_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = {
        "agents": [
            {"agent_name": "/root", "agent_status": "running"},
            {"agent_name": "/root/child", "agent_status": "completed"},
        ]
    }
    event = ChatEventResponse.model_validate(
        {
            "id": "event-1",
            "session_id": "session-1",
            "kind": "client_tool_result",
            "payload": {"call_id": "selected", "output": json.dumps(result)},
            "schema_version": "1",
            "created_at": "2026-10-14T00:00:00Z",
        }
    )
    monkeypatch.setattr(subagents, "_history", lambda **kwargs: [event])
    agents = subagents._wait_for_listed_agents(
        public_url="unused",
        token="unused",
        session_id="session-1",
        call_id="selected",
    )
    assert agents[0].agent_name == "/root"
    assert agents[1].agent_status == "completed"
    assert [agent.model_dump() for agent in agents] == result["agents"]


@pytest.mark.parametrize(
    "status", ["running", "idle", "completed", "errored", "interrupted"]
)
def test_native_list_result_retains_bounded_order_and_exact_items(status: str) -> None:
    observed = _ListedAgentsObservation.model_validate_json(
        '{"agents":[{"agent_name":"/root","agent_status":"'
        + status
        + '"},{"agent_name":"/root/child","agent_status":"idle"}]}'
    )
    assert [item.agent_name for item in observed.agents] == ["/root", "/root/child"]
    assert observed.agents[0].agent_status == status
    assert observed.agents[1].model_dump() == {
        "agent_name": "/root/child",
        "agent_status": "idle",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"agents": None},
        {"agents": [{"agent_name": "/root", "agent_status": True}]},
        {"agents": [{"agent_name": "/root", "agent_status": "idle", "extra": None}]},
    ],
)
def test_native_list_result_rejects_malformed_or_unknown_fields(
    payload: object,
) -> None:
    with pytest.raises(ValidationError):
        _ListedAgentsObservation.model_validate(payload)


@pytest.mark.parametrize("reason", [None, "no_descendants", "all_descendants_idle"])
def test_native_wait_result_retains_omitted_and_nullable_reason(
    reason: str | None,
) -> None:
    observed = _WaitOutcomeObservation.model_validate(
        {"outcome": "not_waitable", "reason": reason}
    )
    assert observed.reason == reason
    assert (
        _WaitOutcomeObservation.model_validate({"outcome": "timed_out"}).reason is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": True},
        {"outcome": "activity", "reason": False},
    ],
)
def test_native_wait_result_rejects_malformed_or_unknown_fields(
    payload: object,
) -> None:
    with pytest.raises(ValidationError):
        _WaitOutcomeObservation.model_validate(payload)


def test_tool_envelopes_preserve_opaque_extensions() -> None:
    listed = _ListedAgentsObservation.model_validate(
        {"agents": [], "future": {"opaque": True}}
    )
    assert listed.agents == []
    assert listed.model_extra == {"future": {"opaque": True}}
    waiting = _WaitOutcomeObservation.model_validate(
        {"outcome": "activity", "reason": None, "future": [1, 2]}
    )
    assert waiting.reason is None
    assert waiting.model_extra == {"future": [1, 2]}


def test_terminal_message_retains_semantic_text_and_opaque_event_extensions() -> None:
    observed = _AgentMessageObservation.model_validate(
        {
            "message_kind": "agent_result",
            "source_path": "/root/child",
            "run_status": "failed",
            "content": "A bounded failure message.",
            "opaque_event_extension": {"future": True},
        }
    )
    assert observed.content == "A bounded failure message."
    assert observed.source_path == "/root/child"
    assert observed.run_status == "failed"
    assert observed.model_extra == {"opaque_event_extension": {"future": True}}
