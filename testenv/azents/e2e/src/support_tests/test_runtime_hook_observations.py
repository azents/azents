"""Pure regressions for Runtime Hook ingress and adjacent native live decoding."""

import json

import azentspublicclient
import pytest
import requests
from pydantic import ValidationError

from tests.required.public import external_channel_scenarios as channels
from tests.required.public import test_agent_execution_persistence as persistence
from tests.required.public import test_runtime_hooks as hooks


class _Clock:
    """Advance on controlled polling only, without wall-clock waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, interval: float) -> None:
        self.now += interval
        self.waits += 1


def _install_clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(hooks.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(hooks.time, "sleep", clock.sleep)
    return clock


def _response(payload: object, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "http://fixture.invalid/observation"
    response.encoding = "utf-8"
    response._content = json.dumps(payload).encode()
    return response


def _session(run_state: str) -> dict[str, object]:
    return {
        "id": "session",
        "agent_id": "agent",
        "status": "active",
        "run_state": run_state,
        "pinned": False,
        "current_enabled_execution_options": [],
        "current_model_target_label": None,
        "current_reasoning_effort": None,
        "title": None,
        "title_source": None,
        "product_mode": None,
        "unread_terminal_run_id": None,
        "auto_archive_after": None,
        "archived_at": None,
        "purge_after": None,
        "archive_retention_days_snapshot": None,
        "created_at": "2026-10-04T00:00:00Z",
        "updated_at": "2026-10-04T00:00:00Z",
        "future_session": {"opaque": [None, True, "retained"]},
    }


def _live() -> dict[str, object]:
    return {
        "partial_history": {"items": [], "future_history": True},
        "mailbox_items": [],
        "run": None,
        "session_run_state": "idle",
        "future_live": {"opaque": [None, "retained"]},
        "action_executions": [
            {
                "execution": {
                    "id": "execution",
                    "source_mailbox_item_id": "mailbox",
                    "sender_user_id": None,
                    "action_type": "create_session_working_folder",
                    "action": {
                        "type": "create_session_working_folder",
                        "future_context": {"opaque": [None, "retained"]},
                    },
                    "result": {
                        "phase": "completed",
                        "outcome": "ready",
                        "reason_code": None,
                    },
                    "status": "completed",
                    "owner_generation": 1,
                    "updated_at": "2026-10-04T00:00:00Z",
                    "future_execution": True,
                },
                "events": [],
                "future_projection": True,
            }
        ],
    }


def _write() -> dict[str, object]:
    live = _live()
    return {
        "session_id": "session",
        "client_request_id": "request",
        "accepted": {"type": "mailbox_item", "id": "mailbox", "future": True},
        "snapshot": {
            "partial_history_events": [],
            "mailbox_items": [],
            "run": None,
            "session_run_state": "idle",
            "action_executions": live["action_executions"],
            "future_snapshot": True,
        },
        "history_reload_required": False,
        "future_write": {"opaque": [None, "retained"]},
    }


def test_journal_compiles_chat_and_responses_fields_and_retains_extensions() -> None:
    wire = [
        {
            "body": {
                "instructions": "instructions",
                "messages": [
                    {"content": [{"text": "chat message"}]},
                    {"output": ["chat output"]},
                ],
                "input": [
                    {"content": [{"text": "responses message"}]},
                    {"input": ["responses input"]},
                ],
                "tools": [
                    {"name": "responses_tool", "future_tool": True},
                    {"function": {"name": "chat_tool", "future_function": None}},
                    {"name": "primary", "function": {"name": "not-selected"}},
                    {"type": "provider-owned-tool"},
                ],
                "future_body": {"opaque": [None, False]},
            },
            "future_journal": "retained",
        }
    ]
    observation = hooks._decode_hook_journal(wire)[0]
    assert hooks._message_texts(observation) == [
        "instructions",
        "chat message",
        "chat output",
        "responses message",
        "responses input",
    ]
    assert hooks._request_tool_names(observation) == [
        "responses_tool",
        "chat_tool",
        "primary",
    ]
    assert json.loads(observation.wire_json) == wire[0]


def test_journal_missing_and_null_remain_distinct_opaque_snapshots() -> None:
    missing = hooks._decode_hook_journal([{"future": True}])[0]
    nullable = hooks._decode_hook_journal([{"body": None, "future": True}])[0]
    empty = hooks._decode_hook_journal(
        [
            {
                "body": {
                    "instructions": None,
                    "messages": None,
                    "input": None,
                    "tools": None,
                }
            }
        ]
    )[0]
    assert missing.message_texts == nullable.message_texts == empty.message_texts == ()
    assert missing.tool_names == nullable.tool_names == empty.tool_names == ()
    assert "body" not in json.loads(missing.wire_json)
    assert json.loads(nullable.wire_json)["body"] is None
    assert json.loads(empty.wire_json)["body"]["input"] is None


@pytest.mark.parametrize(
    "wire",
    [
        None,
        {},
        [None],
        [{"body": False}],
        [{"body": {"instructions": 1}}],
        [{"body": {"messages": "not-a-list"}}],
        [{"body": {"tools": {}}}],
        [{"body": {"tools": [False]}}],
        [{"body": {"tools": [{"name": 1}]}}],
        [{"body": {"tools": [{"function": {"name": True}}]}}],
    ],
)
def test_journal_rejects_malformed_consumed_values(wire: object) -> None:
    with pytest.raises(ValidationError):
        hooks._decode_hook_journal(wire)


def test_journal_projection_is_independent_of_later_raw_mutation() -> None:
    body: dict[str, object] = {
        "input": "original",
        "tools": [{"name": "original-tool"}],
    }
    wire = [{"body": body}]
    observation = hooks._decode_hook_journal(wire)[0]
    body["input"] = "mutated"
    body["tools"] = []
    assert observation.message_texts == ("original",)
    assert observation.tool_names == ("original-tool",)
    assert json.loads(observation.wire_json)["body"]["input"] == "original"


def test_actual_tool_snapshot_poll_uses_controlled_journal_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_clock(monkeypatch)
    first = {"body": {"input": "user message", "tools": [{"name": "tool_search"}]}}
    second = {"body": {"input": "user message", "tools": [{"name": "probe"}]}}
    responses = [_response([first]), _response([first, second])]
    monkeypatch.setattr(hooks.requests, "get", lambda *args, **kwargs: responses.pop(0))
    snapshots = hooks._wait_for_tool_request_snapshots(
        "http://fixture.invalid", "user message", minimum_count=2, required_tool="probe"
    )
    assert snapshots == [["tool_search"], ["probe"]]
    assert clock.waits == 1
    assert not responses


def test_actual_journal_text_poll_uses_decoded_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_clock(monkeypatch)
    response = _response([{"body": {"instructions": "visible", "input": "hidden"}}])
    monkeypatch.setattr(hooks.requests, "get", lambda *args, **kwargs: response)
    assert hooks._wait_for_journal_text(
        "http://fixture.invalid", ("visible", "hidden")
    ) == ("visible\nhidden")
    assert clock.waits == 0


@pytest.mark.parametrize("status", [401, 500])
def test_journal_http_error_is_not_empty_readiness(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    response = _response([], status)
    monkeypatch.setattr(hooks.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(requests.HTTPError):
        hooks._journal_items("http://fixture.invalid")


def test_native_session_and_write_projections_keep_known_fields_and_extensions() -> (
    None
):
    session = hooks._decode_hook_session(_session("idle"))
    assert session.id == "session"
    assert session.run_state == "idle"
    assert session.additional_properties["future_session"] == {
        "opaque": [None, True, "retained"]
    }
    write = hooks._decode_hook_write(_write())
    assert write.session_id == "session"
    assert write.accepted.id == "mailbox"
    assert write.accepted.additional_properties["future"] is True
    assert write.snapshot.additional_properties["future_snapshot"] is True
    assert write.snapshot.action_executions is not None
    result = write.snapshot.action_executions[0].execution.result
    assert result is not None
    assert result["phase"].to_dict() == "completed"
    assert result["reason_code"].to_dict() is None
    assert write.additional_properties["future_write"] == {"opaque": [None, "retained"]}


@pytest.mark.parametrize(
    "field",
    [
        "current_model_target_label",
        "current_reasoning_effort",
        "title",
        "title_source",
        "product_mode",
        "unread_terminal_run_id",
        "auto_archive_after",
        "archived_at",
        "purge_after",
        "archive_retention_days_snapshot",
    ],
)
def test_native_session_requires_nullable_response_fields_to_be_present(
    field: str,
) -> None:
    """Required nullable response fields allow null, not wire-key omission."""
    wire = _session("idle")
    assert wire[field] is None
    session = hooks._decode_hook_session(wire)
    assert session.id == "session" and session.run_state == "idle"
    assert field in session.model_fields_set
    assert session.to_dict()[field] is None
    assert "primary_kind" not in session.model_fields_set

    del wire[field]
    with pytest.raises(ValidationError) as captured:
        hooks._decode_hook_session(wire)
    assert any(
        error["type"] == "missing" and error["loc"] == (field,)
        for error in captured.value.errors()
    )


@pytest.mark.parametrize("field", ["id", "run_state", "pinned"])
def test_native_session_rejects_invalid_known_fields(field: str) -> None:
    wire = _session("idle")
    wire[field] = 4
    with pytest.raises(ValidationError):
        hooks._decode_hook_session(wire)


def test_actual_run_message_decodes_primary_session_and_accepted_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def get(url: str, **kwargs: object) -> requests.Response:
        calls.append(url)
        return _response(_session("idle"))

    def post(url: str, **kwargs: object) -> requests.Response:
        calls.append(url)
        return _response(_write(), 202)

    monkeypatch.setattr(hooks.requests, "get", get)
    monkeypatch.setattr(hooks.requests, "post", post)
    with azentspublicclient.ApiClient() as client:
        assert (
            hooks._run_message(
                public_api_client=client,
                public_url="http://fixture.invalid",
                access_token="synthetic-token",
                agent_id="agent",
                message="user message",
            )
            == "session"
        )
    assert calls == [
        "http://fixture.invalid/chat/v1/agents/agent/team-primary-session",
        "http://fixture.invalid/chat/v1/sessions/session/inputs",
    ]


def test_existing_rest_write_error_diagnostics_preserve_actual_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response({"detail": "conflict"}, 409)
    monkeypatch.setattr(hooks.requests, "post", lambda *args, **kwargs: response)
    with azentspublicclient.ApiClient() as client:
        with pytest.raises(AssertionError, match="REST write failed") as captured:
            hooks._run_message(
                public_api_client=client,
                public_url="http://fixture.invalid",
                access_token="synthetic-token",
                agent_id="agent",
                message="user message",
                session_id="session",
            )
    cause = captured.value.__cause__
    assert isinstance(cause, requests.HTTPError)
    assert cause.response is response and cause.response.status_code == 409


def test_actual_idle_poll_uses_generated_session_state_and_fake_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_clock(monkeypatch)
    responses = [_response(_session("running")), _response(_session("idle"))]
    monkeypatch.setattr(hooks.requests, "get", lambda *args, **kwargs: responses.pop(0))
    hooks._wait_for_session_idle(
        public_url="http://fixture.invalid",
        access_token="synthetic-token",
        agent_id="agent",
        session_id="session",
    )
    assert not responses
    assert clock.waits == 1


def test_adjacent_live_helper_uses_actual_native_ingress_and_primitive_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(_live())
    monkeypatch.setattr(persistence.requests, "get", lambda *args, **kwargs: response)
    live = channels.list_live(
        server_url="http://fixture.invalid",
        token="synthetic-token",
        session_id="session",
    )
    assert live.session_run_state == "idle"
    assert live.partial_history.additional_properties["future_history"] is True
    assert live.additional_properties["future_live"] == {"opaque": [None, "retained"]}
    assert live.action_executions is not None
    projection = live.action_executions[0]
    assert projection.additional_properties["future_projection"] is True
    execution = projection.execution
    assert execution.additional_properties["future_execution"] is True
    assert execution.result is not None
    assert execution.result["phase"].to_dict() == "completed"
    assert execution.result["outcome"].to_dict() == "ready"
    assert execution.result["reason_code"].to_dict() is None
    action_wire = execution.action.to_dict()
    assert isinstance(action_wire, dict)
    assert action_wire["future_context"] == {"opaque": [None, "retained"]}


@pytest.mark.parametrize("status", [403, 500])
def test_adjacent_live_helper_does_not_hide_http_errors(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    response = _response({}, status)
    monkeypatch.setattr(persistence.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(requests.HTTPError):
        channels.list_live(
            server_url="http://fixture.invalid",
            token="synthetic-token",
            session_id="session",
        )


def test_adjacent_live_helper_rejects_null_native_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(channels, "_wire_live", lambda **kwargs: None)
    with pytest.raises(AssertionError, match="non-null"):
        channels.list_live(
            server_url="http://fixture.invalid",
            token="synthetic-token",
            session_id="session",
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("session_run_state", "invalid-state"), ("mailbox_items", [None])],
)
def test_adjacent_native_decoder_rejects_invalid_known_wire_fields(
    monkeypatch: pytest.MonkeyPatch, field: str, invalid: object
) -> None:
    wire = _live()
    wire[field] = invalid
    monkeypatch.setattr(channels, "_wire_live", lambda **kwargs: wire)
    with pytest.raises(ValidationError):
        channels.list_live(
            server_url="http://fixture.invalid",
            token="synthetic-token",
            session_id="session",
        )
