"""Listener-free tests for the Terminal journey's typed ingress observations."""

import json
from unittest.mock import Mock

import pytest
import requests
from azentspublicclient.models.agent_workspace_stat_response import (
    AgentWorkspaceStatResponse,
)
from azentspublicclient.models.runtime_terminal_ticket_status import (
    RuntimeTerminalTicketStatus,
)
from websockets.sync.client import ClientConnection

from tests.required.public import test_runtime_terminal as terminal

_ACCEPTED = {
    "type": "accepted",
    "terminal_id": "terminal-1",
    "lifecycle": "attached",
    "attachment_generation": 1,
    "desired_generation": 2,
    "runner_generation": "00000000000000000003",
    "shell_label": "sh",
    "working_directory_display": "/fixture/session",
    "next_input_sequence": 1,
    "replay_min_sequence": 0,
    "replay_max_sequence": 1,
    "replay_truncated": False,
}

_CONTROLS = [
    _ACCEPTED,
    {"type": "replay_begin", "minimum_sequence": 0, "maximum_sequence": 1},
    {"type": "replay_truncated", "minimum_sequence": 0},
    {"type": "replay_end", "maximum_sequence": 1},
    {"type": "input_ack", "sequence": 1},
    {"type": "status", "lifecycle": "attached", "reason": None},
    {"type": "exit", "reason": "caller", "exit_code": None},
    {"type": "revoked", "reason_code": "runtime_stopped"},
    {"type": "error", "code": "protocol_error"},
    {"type": "heartbeat_ack", "sequence": 1},
]


@pytest.mark.parametrize("payload", _CONTROLS)
def test_all_canonical_controls_decode_and_preserve_fields(
    payload: dict[str, object],
) -> None:
    observation = terminal._control(json.dumps(payload))
    assert observation.model_dump(mode="json") == payload


@pytest.mark.parametrize("payload", _CONTROLS)
def test_controls_reject_omitted_required_fields_and_unknown_fields(
    payload: dict[str, object],
) -> None:
    for field in payload:
        malformed = dict(payload)
        del malformed[field]
        with pytest.raises(AssertionError, match="Invalid Terminal control payload"):
            terminal._control(json.dumps(malformed))
    with pytest.raises(AssertionError, match="Invalid Terminal control payload"):
        terminal._control(json.dumps({**payload, "future_unknown": True}))


@pytest.mark.parametrize("value", [True, False, "1", 1.5, None, -1, 0])
@pytest.mark.parametrize(
    "field", ["attachment_generation", "desired_generation", "next_input_sequence"]
)
def test_accepted_required_positive_integers_are_not_coerced(
    field: str, value: object
) -> None:
    with pytest.raises(AssertionError, match="Invalid Terminal control payload"):
        terminal._control(json.dumps({**_ACCEPTED, field: value}))


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        True,
        {"type": "unsupported"},
        {"type": "input_ack", "sequence": True},
        {"type": "replay_end", "maximum_sequence": False},
        {"type": "exit", "reason": "caller", "exit_code": True},
        {"type": "status", "lifecycle": "invalid", "reason": None},
        {**_ACCEPTED, "replay_truncated": 0},
    ],
)
def test_malformed_control_variants_are_rejected(payload: object) -> None:
    with pytest.raises(AssertionError, match="Invalid Terminal control payload"):
        terminal._control(json.dumps(payload))


def test_fake_wire_handshake_preserves_replay_and_binary_acknowledgements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock(spec=ClientConnection)
    frame = terminal._FRAME_HEADER.pack(1, 2, 1) + b"replay"
    connection.recv.side_effect = [
        json.dumps(_ACCEPTED),
        json.dumps(_CONTROLS[1]),
        json.dumps(_CONTROLS[2]),
        json.dumps(_CONTROLS[4]),
        json.dumps(_CONTROLS[5]),
        json.dumps(_CONTROLS[9]),
        frame,
        json.dumps(_CONTROLS[3]),
    ]
    monkeypatch.setattr(terminal, "ws_connect", Mock(return_value=connection))
    issued = Mock(status=RuntimeTerminalTicketStatus.ISSUED, ticket="fixture-ticket")
    api = Mock()
    api.terminal_v1_issue_terminal_ticket.return_value = issued
    monkeypatch.setattr(terminal, "TerminalV1Api", Mock(return_value=api))
    socket = terminal._TerminalSocket.connect(
        public_api_client=Mock(),
        workspace=terminal._TerminalWorkspace("token", "handle", "agent", "session"),
        server_url="http://fixture.invalid",
        origin="https://fixture.invalid",
    )
    assert socket.accepted.terminal_id == "terminal-1"
    assert socket.accepted.attachment_generation == 1
    assert socket.accepted.working_directory == "/fixture/session"
    assert socket.output_sequence == 1
    sends = [json.loads(call.args[0]) for call in connection.send.call_args_list]
    assert sends == [
        {"type": "attach", "columns": 80, "rows": 24, "last_output_sequence": None},
        {"type": "output_ack", "sequence": 1},
        {"type": "output_ack", "sequence": 1},
    ]


def test_fake_wire_consumers_use_typed_exit_and_ack_output() -> None:
    connection = Mock(spec=ClientConnection)
    accepted = terminal._AcceptedTerminal("terminal", 1, "/fixture", 1, 0)
    socket = terminal._TerminalSocket(connection, accepted, output_sequence=0)
    connection.recv.side_effect = [
        json.dumps(_CONTROLS[9]),
        terminal._FRAME_HEADER.pack(1, 2, 1) + b"marker",
        json.dumps(_CONTROLS[6]),
    ]
    exited = socket.terminate()
    assert isinstance(exited, terminal._ExitControl)
    assert exited.reason == "caller" and exited.exit_code is None
    assert socket.output == b"marker"
    assert socket.output_sequence == 1
    connection.recv.side_effect = [json.dumps(_CONTROLS[5]), json.dumps(_CONTROLS[7])]
    revoked = socket.wait_for_invalidation(timeout=1)
    assert isinstance(revoked, terminal._RevokedControl)
    assert revoked.reason_code.value == "runtime_stopped"


def test_rest_stat_uses_generated_model_with_required_typed_fields() -> None:
    response = requests.Response()
    response._content = (
        b'{"path":"/fixture","name":"fixture","kind":"directory","symlink":false}'
    )
    stat = terminal._response_payload(
        response, AgentWorkspaceStatResponse, label="stat"
    )
    assert (
        stat.path == "/fixture" and stat.kind == "directory" and stat.symlink is False
    )
    response._content = (
        b'{"path":"/fixture","name":"fixture","kind":"directory","symlink":0}'
    )
    with pytest.raises(AssertionError, match="stat payload is invalid"):
        terminal._response_payload(response, AgentWorkspaceStatResponse, label="stat")
