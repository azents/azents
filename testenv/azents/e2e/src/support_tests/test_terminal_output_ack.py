"""Value-free, deterministic cumulative ACK and idle-flush boundary checks."""

import json
from unittest.mock import Mock

import pytest
from websockets.sync.client import ClientConnection

from support.terminal_output_ack import TerminalOutputAcknowledgements
from tests.required.public import test_runtime_terminal as terminal


def test_tiny_output_burst_flushes_one_cumulative_ack() -> None:
    acks = TerminalOutputAcknowledgements(0, lambda: 10.0)
    for sequence in range(1, 201):
        assert acks.observe(sequence, 1) is None
    assert acks.deadline == 10.05
    assert acks.flush() == 200
    assert acks.flush() is None
    assert acks.deadline is None


def test_large_output_flushes_below_live_window_and_keeps_sequence() -> None:
    acks = TerminalOutputAcknowledgements(20, lambda: 10.0)
    for sequence in range(21, 28):
        assert acks.observe(sequence, 16 * 1024) is None
    assert acks.observe(28, 16 * 1024) == 28
    assert acks.pending_bytes == 0
    assert acks.observe(29, 1) is None
    assert acks.flush() == 29
    with pytest.raises(AssertionError):
        acks.observe(29, 1)


def _socket(connection: ClientConnection) -> terminal._TerminalSocket:
    return terminal._TerminalSocket(
        connection,
        terminal._AcceptedTerminal(
            terminal_id="terminal",
            attachment_generation=1,
            working_directory="/workspace/synthetic",
            next_input_sequence=1,
            replay_maximum_sequence=0,
        ),
        output_sequence=0,
    )


def test_idle_read_flushes_small_output_without_a_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [10.0]
    monkeypatch.setattr(terminal.time, "monotonic", lambda: clock[0])
    connection = Mock(spec=ClientConnection)
    socket = _socket(connection)
    socket._accept_output(terminal._FRAME_HEADER.pack(1, 2, 1) + b"partial")
    timeouts: list[float] = []

    def receive(*, timeout: float) -> str:
        timeouts.append(timeout)
        if len(timeouts) == 1:
            clock[0] += timeout
            raise TimeoutError
        return "control"

    connection.recv.side_effect = receive
    assert socket._receive(timeout=2) == "control"
    assert timeouts == pytest.approx([0.05, 1.95])
    connection.send.assert_called_once_with(
        json.dumps({"type": "output_ack", "sequence": 1})
    )
    assert socket.output == b"partial"


def test_logical_output_completion_flushes_without_ack_per_frame() -> None:
    connection = Mock(spec=ClientConnection)
    socket = _socket(connection)
    connection.recv.side_effect = [
        terminal._FRAME_HEADER.pack(1, 2, sequence) + data
        for sequence, data in enumerate([b"a"] * 50 + [b"DONE"], 1)
    ]
    assert socket.wait_for_output(b"DONE") == b"a" * 50 + b"DONE"
    connection.send.assert_called_once_with(
        json.dumps({"type": "output_ack", "sequence": 51})
    )
    assert socket.output_sequence == 51
