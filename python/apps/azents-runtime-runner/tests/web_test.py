"""Runtime Runner loopback Web transport tests."""

import asyncio
import gzip
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from azents_runtime_control.runner_web import (
    RunnerWebBodyChunk,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebHeader,
    RunnerWebIdentity,
    RunnerWebOpenIntent,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebSocketFrame,
    RunnerWebSocketOpcode,
    RunnerWebStreamEnd,
    RunnerWebStreamError,
    RunnerWebStreamErrorCode,
)

from azents_runtime_runner.web import RunnerWebTransportManager


class _Client:
    def __init__(self, frames: list[RunnerWebControlFrame]) -> None:
        self.frames = frames
        self.handler: Callable[[RunnerWebControlFrame], Awaitable[None]] | None = None
        self.sent: list[RunnerWebEventFrame] = []
        self.closed = False

    def set_control_handler(
        self,
        handler: Callable[[RunnerWebControlFrame], Awaitable[None]],
    ) -> None:
        self.handler = handler

    async def start(self, identity: RunnerWebIdentity) -> object:
        del identity
        assert self.handler is not None
        for frame in self.frames:
            await self.handler(frame)
        return object()

    async def send(self, frame: RunnerWebEventFrame) -> None:
        self.sent.append(frame)

    async def finish(self, frame: RunnerWebEventFrame) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True


async def test_http_transport_streams_request_and_response_without_redirects() -> None:
    """The Runner targets numeric loopback and preserves bounded stream order."""
    observed: list[tuple[str, bytes]] = []
    encoded_response = gzip.compress(b"firstsecond")

    async def handler(request: web.Request) -> web.StreamResponse:
        observed.append((request.path_qs, await request.read()))
        response = web.StreamResponse(
            status=201,
            headers={"content-encoding": "gzip", "x-app": "ok"},
        )
        await response.prepare(request)
        midpoint = len(encoded_response) // 2
        await response.write(encoded_response[:midpoint])
        await response.write(encoded_response[midpoint:])
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/events", handler)
    server = TestServer(app)
    await server.start_server()
    assert server.port is not None
    identity = _identity(server.port)
    client = _Client(
        [
            RunnerWebRequestHead(
                identity=identity,
                protocol=RunnerWebProtocol.HTTP,
                method=b"POST",
                target=b"/events?source=test",
                headers=(RunnerWebHeader(b"content-type", b"text/plain"),),
            ),
            RunnerWebBodyChunk(1, b"payload"),
            RunnerWebStreamEnd(1),
        ]
    )
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 7,
        client_factory=lambda: client,
    )

    try:
        await manager.handle_open(RunnerWebOpenIntent(identity))
        tunnel = manager.tunnels[identity.tunnel_id]
        assert tunnel.task is not None
        await asyncio.wait_for(tunnel.task, timeout=2)
    finally:
        await manager.close()
        await server.close()

    assert observed == [("/events?source=test", b"payload")]
    assert isinstance(client.sent[0], RunnerWebResponseHead)
    assert client.sent[0].status == 201
    body = b"".join(
        frame.data for frame in client.sent if isinstance(frame, RunnerWebBodyChunk)
    )
    assert body == encoded_response
    assert client.sent[-1] == RunnerWebStreamEnd(
        sum(isinstance(frame, RunnerWebBodyChunk) for frame in client.sent)
    )
    assert client.closed


async def test_application_unavailable_logs_safe_failure_classification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Loopback failures emit bounded diagnostics without request target data."""
    identity = _identity(1)
    client = _Client(
        [
            RunnerWebRequestHead(
                identity=identity,
                protocol=RunnerWebProtocol.HTTP,
                method=b"GET",
                target=b"/private?ticket=do-not-log",
                headers=(),
            ),
            RunnerWebStreamEnd(0),
        ]
    )
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 7,
        client_factory=lambda: client,
    )
    caplog.set_level(logging.WARNING, logger="azents_runtime_runner.web")

    await manager.handle_open(RunnerWebOpenIntent(identity))
    tunnel = manager.tunnels[identity.tunnel_id]
    assert tunnel.task is not None
    await asyncio.wait_for(tunnel.task, timeout=2)

    assert client.sent[-1] == RunnerWebStreamError(
        RunnerWebStreamErrorCode.APPLICATION_UNAVAILABLE
    )
    record = next(
        record
        for record in caplog.records
        if record.message == "Runtime Web loopback application unavailable"
    )
    assert record.__dict__["runtime_id"] == identity.runtime_id
    assert record.__dict__["tunnel_id"] == identity.tunnel_id
    assert record.__dict__["port"] == identity.port
    assert record.__dict__["error_type"] == "ClientConnectorError"
    assert isinstance(record.__dict__["error_number"], int)
    assert "do-not-log" not in caplog.text


async def test_stale_generation_does_not_open_transport() -> None:
    """A replaced Runner generation cannot admit a loopback request."""
    identity = _identity(3000)
    client = _Client([])
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 8,
        client_factory=lambda: client,
    )

    await manager.handle_open(RunnerWebOpenIntent(identity))

    assert manager.tunnels == {}
    assert not client.closed


async def test_websocket_transport_streams_messages_in_both_directions() -> None:
    """WebSocket messages use the same bounded dedicated tunnel stream."""
    observed: list[str] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(autoping=False)
        await websocket.prepare(request)
        message = await websocket.receive()
        observed.append(message.data)
        await websocket.send_str("world")
        await websocket.close()
        return websocket

    app = web.Application()
    app.router.add_get("/socket", handler)
    server = TestServer(app)
    await server.start_server()
    assert server.port is not None
    identity = _identity(server.port)
    client = _Client(
        [
            RunnerWebRequestHead(
                identity=identity,
                protocol=RunnerWebProtocol.WEBSOCKET,
                method=b"GET",
                target=b"/socket",
                headers=(),
            ),
            RunnerWebSocketFrame(
                sequence=1,
                opcode=RunnerWebSocketOpcode.TEXT,
                final=True,
                data=b"hello",
            ),
        ]
    )
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 7,
        client_factory=lambda: client,
    )

    try:
        await manager.handle_open(RunnerWebOpenIntent(identity))
        tunnel = manager.tunnels[identity.tunnel_id]
        assert tunnel.task is not None
        await asyncio.wait_for(tunnel.task, timeout=2)
    finally:
        await manager.close()
        await server.close()

    assert observed == ["hello"]
    output = [frame for frame in client.sent if isinstance(frame, RunnerWebSocketFrame)]
    assert output[0].opcode is RunnerWebSocketOpcode.TEXT
    assert output[0].data == b"world"
    assert isinstance(client.sent[-1], RunnerWebStreamEnd)
    assert client.closed


async def test_websocket_client_close_waits_for_application_close_response() -> None:
    """A Gateway close frame is relayed back before the tunnel finishes."""
    observed: list[int] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(autoping=False)
        await websocket.prepare(request)
        message = await websocket.receive()
        assert message.type is web.WSMsgType.CLOSE
        observed.append(message.data)
        return websocket

    app = web.Application()
    app.router.add_get("/socket", handler)
    server = TestServer(app)
    await server.start_server()
    assert server.port is not None
    identity = _identity(server.port)
    client = _Client(
        [
            RunnerWebRequestHead(
                identity=identity,
                protocol=RunnerWebProtocol.WEBSOCKET,
                method=b"GET",
                target=b"/socket",
                headers=(),
            ),
            RunnerWebSocketFrame(
                sequence=1,
                opcode=RunnerWebSocketOpcode.CLOSE,
                final=True,
                data=(1000).to_bytes(2, "big"),
            ),
        ]
    )
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 7,
        client_factory=lambda: client,
    )

    try:
        await manager.handle_open(RunnerWebOpenIntent(identity))
        tunnel = manager.tunnels[identity.tunnel_id]
        assert tunnel.task is not None
        await asyncio.wait_for(tunnel.task, timeout=2)
    finally:
        await manager.close()
        await server.close()

    assert observed == [1000]
    output = [frame for frame in client.sent if isinstance(frame, RunnerWebSocketFrame)]
    assert output[-1].opcode is RunnerWebSocketOpcode.CLOSE
    assert int.from_bytes(output[-1].data[:2], "big") == 1000
    assert isinstance(client.sent[-1], RunnerWebStreamEnd)


async def test_websocket_messages_are_fragmented_into_bounded_frames() -> None:
    """Messages above one frame remain one application message in both directions."""
    payload = b"x" * (64 * 1024 + 17)
    observed: list[bytes] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(autoping=False)
        await websocket.prepare(request)
        message = await websocket.receive()
        observed.append(message.data)
        await websocket.send_bytes(payload)
        await websocket.close()
        return websocket

    app = web.Application()
    app.router.add_get("/socket", handler)
    server = TestServer(app)
    await server.start_server()
    assert server.port is not None
    identity = _identity(server.port)
    client = _Client(
        [
            RunnerWebRequestHead(
                identity=identity,
                protocol=RunnerWebProtocol.WEBSOCKET,
                method=b"GET",
                target=b"/socket",
                headers=(),
            ),
            RunnerWebSocketFrame(
                sequence=1,
                opcode=RunnerWebSocketOpcode.BINARY,
                final=False,
                data=payload[: 64 * 1024],
            ),
            RunnerWebSocketFrame(
                sequence=2,
                opcode=RunnerWebSocketOpcode.BINARY,
                final=True,
                data=payload[64 * 1024 :],
            ),
        ]
    )
    manager = RunnerWebTransportManager(
        runtime_id="runtime-1",
        accepted_generation=lambda: 7,
        client_factory=lambda: client,
    )

    try:
        await manager.handle_open(RunnerWebOpenIntent(identity))
        tunnel = manager.tunnels[identity.tunnel_id]
        assert tunnel.task is not None
        await asyncio.wait_for(tunnel.task, timeout=2)
    finally:
        await manager.close()
        await server.close()

    assert observed == [payload]
    output = [
        frame
        for frame in client.sent
        if isinstance(frame, RunnerWebSocketFrame)
        and frame.opcode is RunnerWebSocketOpcode.BINARY
    ]
    assert [frame.final for frame in output] == [False, True]
    assert b"".join(frame.data for frame in output) == payload


def _identity(port: int) -> RunnerWebIdentity:
    now = datetime.now(UTC)
    return RunnerWebIdentity(
        tunnel_id="tunnel-1",
        endpoint_id="endpoint-1",
        cycle_id="cycle-1",
        endpoint_authority_revision=4,
        close_barrier=1,
        runtime_id="runtime-1",
        desired_generation=5,
        runner_generation=7,
        port=port,
        join_nonce="nonce-1",
        registration_deadline_at=now + timedelta(seconds=5),
        approval_deadline_at=now + timedelta(minutes=30),
        transport_deadline_at=now + timedelta(minutes=30),
    )
