"""Listener-free current-contract tests for the public live Chat helpers."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple
from unittest.mock import Mock

import pytest
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.chat_input_write_request import ChatInputWriteRequest
from azentspublicclient.models.ws_ticket_response import WsTicketResponse
from pydantic import ValidationError

from testenv.live.chat import Chat
from testenv.live.errors import ChatConnectionError, ChatTimeout
from testenv.live.events import ChatAction, OpaquePayload, ToolResultPayload
from testenv.live.matchers import (
    function_call_count,
    function_call_output_contains,
    function_call_succeeded,
    has_function_call,
    has_text_content,
    ordered,
    run_completed,
)
from testenv.live.tools import Tools
from testenv.live.types import Session
from testenv.runtime_config import TestenvConfig as Config
from testenv.seed.types import Agent, Integration, User, Workspace


def _action(kind: str, payload: object, *, live: bool = False) -> dict[str, object]:
    """Build the current public Event envelope, including wire metadata."""
    return {
        "type": "live_event_upserted" if live else "history_event_appended",
        "session_id": "session",
        "event": {
            "id": "e" * 32,
            "session_id": "session",
            "kind": kind,
            "payload": payload,
            "schema_version": "1",
            "created_at": "2026-10-14T00:00:00Z",
        },
    }


def _typed(kind: str, payload: object, *, live: bool = False) -> ChatAction:
    """Decode a public action exactly as WebSocket ingress does."""
    return ChatAction.model_validate_json(json.dumps(_action(kind, payload, live=live)))


def _session() -> Session:
    """Prepare trusted immutable seed values without any network resources."""
    user = User(email="test@example.com", access_token="private-token", refresh_token="refresh")
    workspace = Workspace(handle="workspace", name="Workspace", owner=user)
    integration = Integration(id="integration", workspace=workspace, provider="openai", name="LLM")
    agent = Agent(
        id="agent", workspace=workspace, integration=integration, name="Agent", model_slug="m"
    )
    return Session(id="session", user=user, agent=agent, public_url="http://public.invalid")


@pytest.mark.parametrize("text_type", ["text", "output_text"])
def test_canonical_payloads_and_matchers(text_type: str) -> None:
    """Live/history duplicates correlate by call_id, with structured outputs."""
    call = {"call_id": "call", "name": "exec", "arguments": "{}", "extension": None}
    result = {
        "call_id": "call",
        "status": "completed",
        "output": [{"type": text_type, "text": "ok"}],
    }
    events = [
        _typed("client_tool_call", call, live=True),
        _typed("client_tool_call", call),
        _typed("client_tool_result", result),
        _typed("assistant_message", {"content": [{"type": text_type, "text": "hello"}]}),
        _typed("run_marker", {"run_id": "run", "status": "completed"}),
    ]
    has_function_call(events, name="exec")
    function_call_count(events, name="exec", expected=1)
    function_call_succeeded(events)
    function_call_output_contains(events, name="exec", substring="ok")
    has_text_content(events)
    ordered(events, ["client_tool_call", "assistant_message", "run_marker"])
    run_completed(events)
    assert events[0].event is not None
    assert events[0].event.payload.model_extra == {"arguments": "{}", "extension": None}


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted", "stopped"])
def test_run_completion_preserves_terminal_status(status: str) -> None:
    """Completion includes dummy-key failures rather than claiming model success."""
    run_completed([_typed("run_marker", {"run_id": "run", "status": status})])


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
def test_failed_tool_output_is_not_success(status: str) -> None:
    """A result body alone never disguises a failed client call as success."""
    events = [
        _typed("client_tool_call", {"call_id": "call", "name": "exec"}),
        _typed("client_tool_result", {"call_id": "call", "status": status, "output": "error"}),
    ]
    with pytest.raises(AssertionError, match="successful output"):
        function_call_succeeded(events)


def test_optional_null_and_opaque_extensions() -> None:
    """Public null result names and unrelated native content retain wire meaning."""
    event = _typed("client_tool_result", {"call_id": "call", "name": None, "status": "completed"})
    assert event.event is not None
    assert isinstance(event.event.payload, ToolResultPayload)
    assert event.event.payload.name is None
    assert "name" in event.event.payload.model_fields_set
    opaque = _typed("unknown_adapter_output", {"native": {"arbitrary": [None, 1, True]}})
    assert opaque.event is not None
    assert isinstance(opaque.event.payload, OpaquePayload)
    assert opaque.event.payload.value == {"native": {"arbitrary": [None, 1, True]}}


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "history_event_appended", "session_id": "session"},
        _action("client_tool_call", {"call_id": "call", "name": 123}),
        _action("client_tool_result", {"call_id": "call", "status": "running"}),
        _action("assistant_message", {"content": [{"type": "text", "text": None}]}),
        _action("run_marker", {"run_id": "run", "status": "running"}),
    ],
)
def test_malformed_decision_fields_rejected(payload: object) -> None:
    """Malformed interpreted protocol fields fail once at ingress."""
    with pytest.raises(ValidationError):
        ChatAction.model_validate_json(json.dumps(payload))


class _Transport(NamedTuple):
    """Controlled REST collaborator and deterministic operation order."""

    api: Mock
    order: list[str]


def _install_transport(monkeypatch: pytest.MonkeyPatch, frames: list[object]) -> _Transport:
    """Install typed SDK collaborators and an in-memory WebSocket context."""
    order: list[str] = []
    api = Mock()
    # Trusted collaborator responses: fields unrelated to these operations are
    # intentionally absent rather than fabricating a complete product fixture.
    api.chat_v1_get_team_primary_agent_session.return_value = AgentSessionResponse.model_construct(
        id="session"
    )
    api.chat_v1_issue_ws_ticket.return_value = WsTicketResponse.model_construct(
        ticket="private-ticket"
    )
    agent_api = Mock()
    agent_api.agent_v1_get_agent.return_value = AgentResponse.model_construct(
        main_model_label="Current label"
    )
    api.chat_v1_create_input.side_effect = lambda *args, **kwargs: order.append("write")
    monkeypatch.setattr("testenv.live.chat.public_client", lambda config: Mock())
    monkeypatch.setattr("testenv.live.chat.ChatV1Api", lambda client: api)
    monkeypatch.setattr("testenv.live.chat.AgentV1Api", lambda client: agent_api)

    class Socket:
        """Receive deterministic queued frames, never opening a listener."""

        def recv(self, *, timeout: float) -> str:
            assert timeout > 0
            if not frames:
                raise TimeoutError
            order.append("recv")
            return json.dumps(frames.pop(0))

    @contextmanager
    def connect(uri: str, *, open_timeout: float) -> Iterator[Socket]:
        assert uri.endswith("/chat/v1/sessions/session?ticket=private-ticket")
        assert open_timeout > 0
        yield Socket()

    monkeypatch.setattr("testenv.live.chat.ws_connect", connect)
    return _Transport(api=api, order=order)


def test_live_chat_uses_current_profile_and_subscribes_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise public helpers end to end with typed REST and actual wire frames."""
    session = _session()
    api, order = _install_transport(
        monkeypatch,
        [
            {"type": "subscribed", "session_id": "session"},
            _action("run_marker", {"run_id": "run", "status": "failed"}),
        ],
    )
    chat = Chat(
        Config(
            public_url=session.public_url,
            admin_url="http://admin.invalid",
            testenv_api_url="http://testenv.invalid",
        )
    )
    assert chat.start_session(session.user, session.agent).id == "session"
    tools = Tools(config=chat.config, chat=chat)
    events = tools.run_and_collect(session, "hello")
    run_completed(events)
    assert tools.types_only(events) == ["subscribed", "run_marker"]
    assert order == ["recv", "write", "recv"]
    args, kwargs = api.chat_v1_create_input.call_args
    assert args[0] == session.id
    request = args[1]
    assert isinstance(request, ChatInputWriteRequest)
    assert request.message == "hello"
    assert request.agent_id == session.agent.id
    assert request.inference_profile is not None
    assert request.inference_profile.model_target_label == "Current label"
    assert request.inference_profile.reasoning_effort is None
    assert request.inference_profile.enabled_execution_options == []
    assert kwargs["_headers"] == {"Authorization": "Bearer private-token"}


def test_timeout_exposes_only_typed_collected_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listener-free receive timeout preserves observed typed actions."""
    session = _session()
    _install_transport(monkeypatch, [{"type": "subscribed", "session_id": "session"}])
    chat = Chat(
        Config(
            public_url=session.public_url,
            admin_url="http://admin.invalid",
            testenv_api_url="http://testenv.invalid",
        )
    )
    with pytest.raises(ChatTimeout) as caught:
        chat.collect(session, "hello")
    assert [action.type for action in caught.value.collected_events] == ["subscribed"]


def test_malformed_stream_error_redacts_ticket_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Protocol errors have a safe high-level message without raw credentials."""
    session = _session()
    _install_transport(monkeypatch, [{"type": "subscribed", "session_id": 3}])
    chat = Chat(
        Config(
            public_url=session.public_url,
            admin_url="http://admin.invalid",
            testenv_api_url="http://testenv.invalid",
        )
    )
    with pytest.raises(ChatConnectionError) as caught:
        chat.collect(session, "hello")
    assert "private-ticket" not in str(caught.value)
    assert "private-token" not in str(caught.value)
