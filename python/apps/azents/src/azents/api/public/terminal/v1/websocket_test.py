"""Public Runtime Terminal WebSocket boundary tests."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from azents.api.public.terminal.v1 import (
    _CLOSE_PROTOCOL,
    _CLOSE_REVOKED,
    _receive_attach,
    _receive_loop,
    _run_terminal_socket,
    _send_initial_state,
    _SocketProgress,
    _TerminalSocketProtocolError,
    terminal_websocket,
)
from azents.api.public.terminal.v1.wire import TERMINAL_WEBSOCKET_SUBPROTOCOL
from azents.services.runtime_terminal.data import (
    RuntimeTerminalAttachmentAccepted,
    RuntimeTerminalExited,
    RuntimeTerminalLifecycle,
    RuntimeTerminalOutput,
    RuntimeTerminalReasonCode,
    RuntimeTerminalServerEvent,
)


class _WebSocket:
    def __init__(self, messages: list[dict[str, object]] | None = None) -> None:
        self.messages = list(messages or [])
        self.texts: list[str] = []
        self.bytes: list[bytes] = []
        self.accepted_subprotocol: str | None = None
        self.closed: tuple[int, str | None] | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason)

    async def receive(self) -> dict[str, object]:
        if not self.messages:
            raise AssertionError("No WebSocket message is available")
        return self.messages.pop(0)

    async def send_text(self, data: str) -> None:
        self.texts.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.bytes.append(data)


class _RouteWebSocket(_WebSocket):
    def __init__(self, *, origin: str) -> None:
        super().__init__()
        self.query_params = {"ticket": "secret-ticket"}
        self.headers = {"origin": origin}
        self.scope: dict[str, object] = {
            "query_string": b"ticket=secret-ticket",
            "subprotocols": [TERMINAL_WEBSOCKET_SUBPROTOCOL],
        }


class _Attachment:
    def __init__(self) -> None:
        self.accepted = RuntimeTerminalAttachmentAccepted(
            terminal_id="terminal-1",
            lifecycle=RuntimeTerminalLifecycle.ATTACHED,
            attachment_generation=2,
            desired_generation=3,
            runner_generation=4,
            shell_label="bash",
            working_directory_display="~/session",
            next_input_sequence=2,
            replay_min_sequence=5,
            replay_max_sequence=6,
            replay_truncated=True,
        )
        self.inputs: list[tuple[int, bytes]] = []
        self.resizes: list[tuple[int, int, int]] = []
        self.acks: list[int] = []
        self.heartbeats: list[int] = []
        self.terminated = False
        self.terminated_event = asyncio.Event()

    def replay(self) -> tuple[RuntimeTerminalOutput, ...]:
        return (RuntimeTerminalOutput(sequence=6, data=b"\xffreplay"),)

    async def input(self, *, sequence: int, data: bytes) -> None:
        self.inputs.append((sequence, data))

    async def resize(self, *, sequence: int, columns: int, rows: int) -> None:
        self.resizes.append((sequence, columns, rows))

    async def acknowledge_output(self, *, sequence: int) -> None:
        self.acks.append(sequence)

    async def heartbeat(self, *, sequence: int) -> None:
        self.heartbeats.append(sequence)

    async def terminate(self) -> None:
        self.terminated = True
        self.terminated_event.set()

    async def revoke(self, reason_code: RuntimeTerminalReasonCode) -> None:
        del reason_code
        self.terminated = True

    async def close(self) -> None:
        return None

    async def events(self) -> AsyncIterator[RuntimeTerminalServerEvent]:
        await asyncio.Future()
        if False:
            yield RuntimeTerminalOutput(sequence=1, data=b"x")


@pytest.mark.asyncio
async def test_initial_state_sends_replay_controls_and_opaque_output() -> None:
    websocket = _WebSocket()
    attachment = _Attachment()

    await _send_initial_state(websocket, attachment)

    controls = [json.loads(item) for item in websocket.texts]
    assert [item["type"] for item in controls] == [
        "accepted",
        "replay_begin",
        "replay_truncated",
        "replay_end",
    ]
    assert websocket.bytes[0][10:] == b"\xffreplay"


@pytest.mark.asyncio
async def test_receive_loop_routes_typed_controls_and_binary_input() -> None:
    input_frame = bytes((1, 1)) + (1).to_bytes(8, "big") + b"pwd\n"
    websocket = _WebSocket(
        [
            {"type": "websocket.receive", "bytes": input_frame},
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "resize",
                        "sequence": 1,
                        "columns": 120,
                        "rows": 40,
                    }
                ),
            },
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "output_ack", "sequence": 6}),
            },
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "heartbeat", "sequence": 2}),
            },
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "terminate"}),
            },
        ]
    )
    attachment = _Attachment()
    progress = _SocketProgress(
        highest_output_sent=6,
        highest_output_acknowledged=0,
        output_acknowledged_at=time.monotonic(),
        changed=asyncio.Event(),
    )

    task = asyncio.create_task(_receive_loop(websocket, attachment, progress))
    await asyncio.wait_for(attachment.terminated_event.wait(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert attachment.inputs == [(1, b"pwd\n")]
    assert attachment.resizes == [(1, 120, 40)]
    assert attachment.acks == [6]
    assert attachment.heartbeats == [2]
    assert attachment.terminated is True
    assert json.loads(websocket.texts[0]) == {
        "type": "heartbeat_ack",
        "sequence": 2,
    }


@pytest.mark.asyncio
async def test_terminate_keeps_send_loop_alive_until_exit_is_delivered() -> None:
    websocket = _WebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "terminate"}),
            }
        ]
    )

    class _TerminatingAttachment(_Attachment):
        async def events(self) -> AsyncIterator[RuntimeTerminalServerEvent]:
            await self.terminated_event.wait()
            yield RuntimeTerminalExited(reason="caller", exit_code=None)

    attachment = _TerminatingAttachment()
    service = AsyncMock()
    progress = _SocketProgress(
        highest_output_sent=6,
        highest_output_acknowledged=6,
        output_acknowledged_at=time.monotonic(),
        changed=asyncio.Event(),
    )
    del progress

    await asyncio.wait_for(
        _run_terminal_socket(
            websocket,
            service,
            AsyncMock(),
            attachment,
        ),
        timeout=1,
    )

    assert attachment.terminated is True
    assert {"type": "exit", "reason": "caller", "exit_code": None} in [
        json.loads(item) for item in websocket.texts
    ]


@pytest.mark.asyncio
async def test_attach_rejects_oversized_or_open_control() -> None:
    oversized = _WebSocket(
        [{"type": "websocket.receive", "text": "x" * (4 * 1024 + 1)}]
    )
    with pytest.raises(_TerminalSocketProtocolError) as error:
        await _receive_attach(oversized)
    assert error.value.code == _CLOSE_PROTOCOL

    unknown = _WebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "attach",
                        "columns": 80,
                        "rows": 24,
                        "unknown": True,
                    }
                ),
            }
        ]
    )
    with pytest.raises(_TerminalSocketProtocolError):
        await _receive_attach(unknown)


@pytest.mark.asyncio
async def test_websocket_scrubs_query_ticket_before_rejecting_origin() -> None:
    websocket = _RouteWebSocket(origin="https://untrusted.example")
    service = AsyncMock()

    await terminal_websocket(
        cast(WebSocket, websocket),
        handle="workspace",
        agent_id="agent-1",
        session_id="session-1",
        service=service,
        expected_origin="https://app.example",
    )

    assert websocket.scope["query_string"] == b""
    assert websocket.closed == (
        _CLOSE_REVOKED,
        "Terminal WebSocket origin is not allowed",
    )
    service.consume_ticket.assert_not_awaited()
