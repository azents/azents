"""Tests for the inactive persistent Gateway browser stream bridge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import AbsoluteCreditWindow
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_ENVELOPE_BYTES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    SESSION_WINDOW_BYTES,
    CloseReason,
    Header,
    RequestHead,
    SessionIdentity,
    SessionPeerRole,
    StreamAuthority,
    StreamProtocol,
    WebSocketOpcode,
)

from azents.runtime_web_gateway.web_session_bridge import (
    PersistentGatewaySessionTransport,
    RuntimeWebBrowserStreamBridge,
)
from azents.runtime_web_gateway.web_session_pool import (
    GatewayStreamHandler,
    RuntimeWebGatewaySessionPool,
)


def _identity(session_id: str = "gateway-session") -> SessionIdentity:
    return SessionIdentity(
        session_id=session_id,
        peer_boot_id=f"{session_id}-boot",
        role=SessionPeerRole.GATEWAY,
        owner=None,
        session_nonce="nonce",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _authority() -> StreamAuthority:
    now = datetime.now(UTC)
    return StreamAuthority(
        correlation_id="correlation",
        endpoint_id="endpoint",
        cycle_id="cycle",
        endpoint_authority_revision=3,
        close_barrier=4,
        identity_id="identity",
        authentication_session_id="authentication",
        user_id="user",
        agent_session_id="agent-session",
        runtime_id="runtime",
        desired_generation=5,
        runner_generation=6,
        port=6006,
        open_deadline_at=now + timedelta(seconds=10),
        transport_deadline_at=now + timedelta(minutes=1),
        approval_deadline_at=now + timedelta(hours=1),
    )


def _head(protocol: StreamProtocol = StreamProtocol.HTTP) -> RequestHead:
    return RequestHead(
        protocol=protocol,
        method=b"GET",
        target=b"/raw?value=%ff",
        headers=(Header(b"x-raw", b"\xff"),),
    )


def _response() -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="control-boot",
        stream_id=1,
    )


def _accepted_response(
    *,
    session_id: str = "gateway-session",
    stream_id: int = 1,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=session_id,
        peer_boot_id="control-boot",
        stream_id=stream_id,
    )
    envelope.open_accepted.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        )
    )
    return envelope


class _CaptureTransport(PersistentGatewaySessionTransport):
    def __init__(self) -> None:
        self.sent: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
        self.handlers = {}
        self.request_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )

    async def bind(self, stream_id: int, handler: GatewayStreamHandler) -> None:
        self.handlers[stream_id] = handler

    async def unbind(self, stream_id: int) -> None:
        self.handlers.pop(stream_id, None)

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
        copied.CopyFrom(envelope)
        self.sent.append(copied)


class _BlockingTransport(_CaptureTransport):
    def __init__(self, *, block_bind: bool, block_send: bool) -> None:
        super().__init__()
        self.block_bind = block_bind
        self.block_send = block_send
        self.blocked = asyncio.Event()
        self.release_block = asyncio.Event()

    async def bind(self, stream_id: int, handler: GatewayStreamHandler) -> None:
        if self.block_bind:
            self.blocked.set()
            await self.release_block.wait()
        await super().bind(stream_id, handler)

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        if self.block_send:
            self.blocked.set()
            await self.release_block.wait()
        await super().send(envelope)


@pytest.mark.asyncio
async def test_pool_selected_transport_carries_its_own_session_identity() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=2)
    first_transport = _CaptureTransport()
    second_transport = _CaptureTransport()
    await pool.register(
        identity=_identity("gateway-a"),
        profile=APPROVED_SESSION_PROFILE,
        transport=first_transport,
    )
    await pool.register(
        identity=_identity("gateway-b"),
        profile=APPROVED_SESSION_PROFILE,
        transport=second_transport,
    )

    await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=2,
        authority=_authority(),
        request_head=_head(),
    )

    assert first_transport.sent[0].session_id == "gateway-a"
    assert second_transport.sent[0].session_id == "gateway-b"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("block_bind", "block_send"),
    [(True, False), (False, True)],
)
async def test_bridge_open_cancellation_releases_binding_and_handler(
    block_bind: bool,
    block_send: bool,
) -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _BlockingTransport(
        block_bind=block_bind,
        block_send=block_send,
    )
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    opening = asyncio.create_task(
        RuntimeWebBrowserStreamBridge.open(
            pool=pool,
            stream_id=1,
            authority=_authority(),
            request_head=_head(),
        )
    )
    await transport.blocked.wait()
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert pool.sessions["gateway-session"].state.streams == {}
    assert transport.handlers == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["data", "cancel"])
async def test_bridge_active_send_cancellation_is_terminal(operation: str) -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _BlockingTransport(block_bind=False, block_send=False)
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridge = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    await bridge.receive(_accepted_response())
    transport.block_send = True
    transport.blocked.clear()
    operation_task = asyncio.create_task(
        bridge.send_request_data(b"body") if operation == "data" else bridge.cancel()
    )
    await transport.blocked.wait()
    operation_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation_task
    assert pool.sessions["gateway-session"].state.streams == {}
    assert transport.handlers == {}
    terminal = await bridge.events.get()
    assert terminal.terminal_reason is CloseReason.TRANSPORT_UNAVAILABLE


@pytest.mark.asyncio
async def test_bridge_enforces_absolute_stream_and_shared_session_credit() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridges = [
        await RuntimeWebBrowserStreamBridge.open(
            pool=pool,
            stream_id=stream_id,
            authority=_authority(),
            request_head=_head(),
        )
        for stream_id in range(1, 10)
    ]
    for stream_id, bridge in enumerate(bridges, start=1):
        await bridge.receive(_accepted_response(stream_id=stream_id))
    frame = b"x" * MANDATORY_DATA_FRAME_BYTES
    for bridge in bridges[:8]:
        for _ in range(4):
            await bridge.send_request_data(frame)
    with pytest.raises(ValueError, match="credit is exhausted"):
        await bridges[8].send_request_data(frame)
    assert bridges[8].binding.state.snapshot().request_sequence == 0

    update = _response()
    update.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    )
    update.window_update.stream_consumed_total = MANDATORY_DATA_FRAME_BYTES
    update.window_update.session_consumed_total = MANDATORY_DATA_FRAME_BYTES
    await bridges[0].receive(update)
    await bridges[0].receive(update)
    with pytest.raises(ValueError, match="must not decrease"):
        update.window_update.stream_consumed_total = 0
        await bridges[0].receive(update)


@pytest.mark.asyncio
async def test_browser_consumption_returns_absolute_response_credit() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridge = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    await bridge.receive(_accepted_response())
    response_head = _response()
    response_head.response_head.status = 200
    await bridge.receive(response_head)
    response_data = _response()
    response_data.frame_sequence = 1
    response_data.data.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
    )
    response_data.data.data = b"x" * MANDATORY_DATA_FRAME_BYTES
    await bridge.receive(response_data)

    assert (await bridge.next_event()).payload == "response_head"
    assert (await bridge.next_event()).data == response_data.data.data
    update = transport.sent[-1].window_update
    assert update.stream_consumed_total == MANDATORY_DATA_FRAME_BYTES
    assert update.session_consumed_total == MANDATORY_DATA_FRAME_BYTES


@pytest.mark.asyncio
async def test_bridge_preserves_raw_http_head_and_releases_terminal_stream() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridge = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )

    opened = transport.sent[0]
    assert opened.open.authority.runtime_id == "runtime"
    assert opened.open.authority.desired_generation == 5
    assert opened.open.authority.runner_generation == 6
    assert opened.open.request_head.target == b"/raw?value=%ff"
    assert opened.open.request_head.headers[0].value == b"\xff"

    accepted = _response()
    accepted.open_accepted.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        )
    )
    await bridge.receive(accepted)
    await bridge.send_request_data(b"\x00request")
    await bridge.finish_request()
    assert transport.sent[1].data.data == b"\x00request"

    response_head = _response()
    response_head.response_head.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionResponseHead(
            status=200,
            headers=[
                runtime_web_session_pb2.RuntimeWebSessionHeader(
                    name=b"x-response", value=b"\xfe"
                )
            ],
        )
    )
    await bridge.receive(response_head)
    data = _response()
    data.frame_sequence = 1
    data.data.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionData(
            direction=runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE,
            data=b"\xffresponse",
        )
    )
    await bridge.receive(data)
    direction_end = _response()
    direction_end.direction_end.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionDirectionEnd(
            direction=runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE,
            final_sequence=1,
        )
    )
    await bridge.receive(direction_end)
    stream_end = _response()
    stream_end.stream_end.CopyFrom(runtime_web_session_pb2.RuntimeWebSessionStreamEnd())
    await bridge.receive(stream_end)
    assert transport.handlers == {}
    assert pool.sessions["gateway-session"].state.streams == {}
    events = [await bridge.events.get() for _ in range(4)]
    assert [event.payload for event in events] == [
        "response_head",
        "data",
        "direction_end",
        "terminal",
    ]
    assert events[-1].terminal_reason is None


@pytest.mark.asyncio
async def test_bridge_preserves_typed_websocket_frames() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridge = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(StreamProtocol.WEBSOCKET),
    )
    accepted = _response()
    accepted.open_accepted.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        )
    )
    await bridge.receive(accepted)
    response_head = _response()
    response_head.response_head.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionResponseHead(status=101)
    )
    await bridge.receive(response_head)
    await bridge.send_websocket(
        opcode=WebSocketOpcode.BINARY,
        final=True,
        data=b"\x00\xff",
    )
    assert transport.sent[-1].websocket.data == b"\x00\xff"
    assert transport.sent[-1].websocket.opcode == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY
    )
    websocket = _response()
    websocket.frame_sequence = 1
    websocket.websocket.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionWebSocketFrame(
            direction=runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE,
            opcode=(
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY
            ),
            final=True,
            data=b"\xfe\x01",
        )
    )
    await bridge.receive(websocket)
    event = await bridge.events.get()
    assert event.payload == "response_head"
    event = await bridge.events.get()
    assert event.websocket_opcode is WebSocketOpcode.BINARY
    assert event.data == b"\xfe\x01"


class _DuplexStream:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = (
            asyncio.Queue()
        )
        self.responses: asyncio.Queue[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ] = asyncio.Queue()
        self.response_yielded = asyncio.Event()

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        assert metadata is None

        async def exchange() -> AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            await self.sent.put(hello)
            yield runtime_web_session_pb2.RuntimeWebSessionEnvelope(
                protocol_fingerprint=hello.protocol_fingerprint,
                session_id=hello.session_id,
                peer_boot_id="control-boot",
                session_accepted=(runtime_web_session_pb2.RuntimeWebSessionAccepted()),
            )
            async for request in request_iterator:
                await self.sent.put(request)
                yield await self.responses.get()
                self.response_yielded.set()

        return exchange()


@pytest.mark.asyncio
async def test_persistent_transport_multiplexes_without_replay() -> None:
    stream = _DuplexStream()
    transport = PersistentGatewaySessionTransport(stream)
    hello = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=runtime_web_session_pb2.RuntimeWebSessionHello(
            role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    accepted = await transport.start(hello, timeout_seconds=1)
    assert accepted.WhichOneof("payload") == "session_accepted"
    assert (await stream.sent.get()).hello.role == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY
    )
    oversized = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        data=runtime_web_session_pb2.RuntimeWebSessionData(
            data=b"x" * MAX_ENVELOPE_BYTES
        )
    )
    with pytest.raises(ValueError, match="envelope size"):
        await transport.send(oversized)

    class _Handler:
        def __init__(self) -> None:
            self.delivered = asyncio.Event()
            self.failed = asyncio.Event()

        async def __call__(
            self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ) -> None:
            assert envelope.stream_id == 7
            self.delivered.set()

        async def fail_transport(self) -> None:
            self.failed.set()

    handler = _Handler()
    await transport.bind(7, handler)
    await transport.send(
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            stream_id=7,
            cancel=runtime_web_session_pb2.RuntimeWebSessionCancel(
                reason=(runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER)
            ),
        )
    )
    assert (await stream.sent.get()).stream_id == 7
    await stream.responses.put(
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="control-boot",
            stream_id=7,
            reset=runtime_web_session_pb2.RuntimeWebSessionReset(
                reason=(runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER)
            ),
        )
    )
    await asyncio.wait_for(handler.delivered.wait(), timeout=1)
    await transport.unbind(7)
    await asyncio.wait_for(stream.response_yielded.wait(), timeout=1)
    assert transport.active
    assert await transport.close() == ()


@pytest.mark.asyncio
async def test_receiver_identity_failure_retires_pool_session_automatically() -> None:
    stream = _DuplexStream()
    transport = PersistentGatewaySessionTransport(stream)
    identity = _identity()
    hello = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_web_session_pb2.RuntimeWebSessionHello(
            role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    await stream.sent.get()
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    await pool.register(
        identity=identity,
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    bridge = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    await stream.sent.get()
    await stream.responses.put(_accepted_response())
    await asyncio.wait_for(stream.response_yielded.wait(), timeout=1)
    stream.response_yielded.clear()
    await bridge.send_request_data(b"body")
    await stream.sent.get()
    stale = _response()
    stale.peer_boot_id = "replacement-control"
    stale.reset.reason = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
    )
    await stream.responses.put(stale)
    terminal = await asyncio.wait_for(bridge.events.get(), timeout=1)
    assert terminal.terminal_reason is CloseReason.TRANSPORT_UNAVAILABLE
    assert "gateway-session" not in pool.sessions
    assert await transport.close() == ()
