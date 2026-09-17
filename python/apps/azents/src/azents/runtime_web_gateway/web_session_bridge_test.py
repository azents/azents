"""Tests for the inactive persistent Gateway browser stream bridge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import unused_port
from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_flow import AbsoluteCreditWindow, QueueLane
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_ENVELOPE_BYTES,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
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

from azents.runtime_web_gateway import (
    web_session_bridge as web_session_bridge_module,
)
from azents.runtime_web_gateway.operations import (
    RuntimeWebDrainCoordinator,
    RuntimeWebDrainPolicy,
    RuntimeWebDrainStreamKind,
    RuntimeWebGatewayHardLimits,
    RuntimeWebGatewayResourceTracker,
)
from azents.runtime_web_gateway.server import create_runtime_web_gateway_public_runner
from azents.runtime_web_gateway.web_session_bridge import (
    PersistentGatewaySessionTransport,
    RuntimeWebBrowserStreamBridge,
    RuntimeWebGatewayResourceExhausted,
    RuntimeWebOpenRejected,
    _outbound_lane,
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
        service_id="endpoint",
        service_revision=3,
        identity_id="identity",
        authentication_session_id="authentication",
        user_id="user",
        agent_id="agent-session",
        runtime_id="runtime",
        desired_generation=5,
        runner_generation=6,
        port=6006,
        open_deadline_at=now + timedelta(seconds=10),
        transport_deadline_at=now + timedelta(minutes=1),
        exposure_deadline_at=now + timedelta(hours=1),
    )


def _head(protocol: StreamProtocol = StreamProtocol.HTTP) -> RequestHead:
    return RequestHead(
        protocol=protocol,
        method=b"GET",
        target=b"/raw?value=%ff",
        headers=(Header(b"x-raw", b"\xff"),),
    )


def _response() -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    return runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="control-boot",
        stream_id=1,
    )


def _accepted_response(
    *,
    session_id: str = "gateway-session",
    stream_id: int = 1,
    route_path: runtime_stream_session_pb2.RuntimeStreamSessionRoutePath.ValueType = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL
    ),
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    envelope = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=session_id,
        peer_boot_id="control-boot",
        stream_id=stream_id,
    )
    envelope.open_accepted.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            route_path=route_path,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        )
    )
    return envelope


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_path", "expected"),
    [
        (runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL, "local"),
        (runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_RELAY, "relay"),
    ],
)
async def test_bridge_records_only_bounded_accepted_route(
    route_path: runtime_stream_session_pb2.RuntimeStreamSessionRoutePath.ValueType,
    expected: str,
) -> None:
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
    await bridge.receive(_accepted_response(route_path=route_path))
    await bridge.wait_accepted(timeout_seconds=1)
    assert bridge.route == expected


@pytest.mark.asyncio
async def test_bridge_rejects_unspecified_accepted_route() -> None:
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
    with pytest.raises(ValueError, match="open route"):
        await bridge.receive(
            _accepted_response(
                route_path=(
                    runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_UNSPECIFIED
                )
            )
        )


class _ObservedResources(RuntimeWebGatewayResourceTracker):
    def __init__(
        self,
        *,
        maximum_active_exchanges: int = 32,
        maximum_application_buffer_bytes: int = 64 * 1024 * 1024,
        maximum_scheduler_waiters: int = 32,
    ) -> None:
        super().__init__(
            RuntimeWebGatewayHardLimits(
                maximum_active_exchanges=maximum_active_exchanges,
                maximum_application_buffer_bytes=maximum_application_buffer_bytes,
                maximum_control_buffer_bytes=16 * 1024 * 1024,
                maximum_pending_tasks=128,
                maximum_scheduler_waiters=maximum_scheduler_waiters,
                maximum_event_loop_lag_milliseconds=250,
                maximum_resident_memory_bytes=1024 * 1024 * 1024,
            )
        )
        self.waiter_added = asyncio.Event()

    def try_add_scheduler_waiter(self) -> bool:
        reserved = super().try_add_scheduler_waiter()
        if reserved:
            self.waiter_added.set()
        return reserved


class _CaptureTransport(PersistentGatewaySessionTransport):
    def __init__(self, resources: _ObservedResources | None = None) -> None:
        self.sent: list[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope] = []
        self.handlers = {}
        self.observed_resources = resources or _ObservedResources()
        self.resources: RuntimeWebGatewayResourceTracker = self.observed_resources
        self.credit_condition = asyncio.Condition()
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
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        copied = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
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
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        if self.block_send:
            self.blocked.set()
            await self.release_block.wait()
        await super().send(envelope)


class _DisconnectTransport(_CaptureTransport):
    def __init__(self) -> None:
        super().__init__()
        self.unbound = asyncio.Event()

    async def unbind(self, stream_id: int) -> None:
        await super().unbind(stream_id)
        self.unbound.set()


class _BlockedCancelDisconnectTransport(_DisconnectTransport):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_started = asyncio.Event()
        self.cancel_interrupted = asyncio.Event()
        self.release_cancel = asyncio.Event()
        self.cancel_completed = asyncio.Event()

    async def send(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        if envelope.WhichOneof("payload") != "cancel":
            await super().send(envelope)
            return
        self.cancel_started.set()
        try:
            await self.release_cancel.wait()
        except asyncio.CancelledError:
            self.cancel_interrupted.set()
            await self.release_cancel.wait()
        await super().send(envelope)
        self.cancel_completed.set()


class _FailingCancelTransport(_DisconnectTransport):
    async def send(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        if envelope.WhichOneof("payload") == "cancel":
            raise RuntimeError("sensitive-transport-detail")
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
    assert terminal.terminal_reason is (
        CloseReason.TRANSPORT_UNAVAILABLE if operation == "data" else CloseReason.CALLER
    )


@pytest.mark.asyncio
async def test_preaccept_cancel_wakes_waiter_and_allows_sequential_open() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    first = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    waiting = asyncio.create_task(first.wait_accepted(timeout_seconds=10))

    await first.cancel(CloseReason.CALLER)

    with pytest.raises(RuntimeWebOpenRejected) as rejected:
        await waiting
    assert rejected.value.reason is CloseReason.CALLER
    assert pool.sessions["gateway-session"].state.streams == {}
    assert transport.handlers == {}

    second = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=2,
        authority=_authority(),
        request_head=_head(),
    )
    assert transport.sent[-1].stream_id == 2
    assert transport.sent[-1].WhichOneof("payload") == "open"
    await second.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["direction_end", "stream_end"])
async def test_bridge_ignores_response_terminal_frame_after_local_cancel(
    payload: str,
) -> None:
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
    await bridge.cancel(CloseReason.CALLER)
    late = _response()
    if payload == "direction_end":
        late.direction_end.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        )
        late.direction_end.final_sequence = 0
    else:
        late.stream_end.SetInParent()

    await bridge.receive(late)

    terminal = bridge.events.get_nowait()
    assert terminal.terminal_reason is CloseReason.CALLER
    assert bridge.events.empty()
    assert pool.sessions["gateway-session"].state.streams == {}
    assert transport.handlers == {}


@pytest.mark.asyncio
async def test_public_runner_disconnect_releases_when_cancel_delivery_blocks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _BlockedCancelDisconnectTransport()
    resources = transport.resources
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )

    async def ignore_close(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN

    drain = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=1,
            long_lived_grace_seconds=0.5,
            termination_grace_seconds=2,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=ignore_close,
    )
    request_started = asyncio.Event()
    request_released = asyncio.Event()
    bridge_box: list[RuntimeWebBrowserStreamBridge | None] = [None]
    handler_cancellations = 0

    async def stream(request: web.Request) -> web.StreamResponse:
        nonlocal handler_cancellations
        del request
        registration = await drain.register(
            kind=RuntimeWebDrainStreamKind.LONG_LIVED,
            request_graceful_close=ignore_close,
            force_close=ignore_close,
        )
        assert registration is not None
        bridge: RuntimeWebBrowserStreamBridge | None = None
        try:
            bridge = await RuntimeWebBrowserStreamBridge.open(
                pool=pool,
                stream_id=1,
                authority=_authority(),
                request_head=_head(),
            )
            bridge_box[0] = bridge
            request_started.set()
            await bridge.wait_accepted(timeout_seconds=10)
            raise AssertionError("Disconnected request must not be accepted")
        except asyncio.CancelledError:
            handler_cancellations += 1
            raise
        finally:
            try:
                if bridge is not None and not bridge.released:
                    await bridge.cancel(CloseReason.CALLER)
            finally:
                assert await drain.release(registration)
                request_released.set()

    async def state(request: web.Request) -> web.Response:
        del request
        return web.json_response({"active": resources.active_exchanges})

    application = web.Application()
    application.router.add_get("/stream", stream)
    application.router.add_get("/state", state)
    runner = create_runtime_web_gateway_public_runner(application)
    await runner.setup()
    port = unused_port()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"GET /stream HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{port}\r\n".encode()
            + b"\r\n"
        )
        await writer.drain()
        await request_started.wait()
        assert resources.active_exchanges == 1

        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(transport.cancel_started.wait(), timeout=1)
        await asyncio.wait_for(request_released.wait(), timeout=1)

        bridge = bridge_box[0]
        assert bridge is not None
        assert bridge.released
        assert bridge.request_credit.closed
        assert bridge.response_credit.closed
        assert bridge.request_credit.available_bytes == 0
        assert bridge.response_credit.available_bytes == 0
        assert resources.active_exchanges == 0
        assert drain.active == {}
        assert handler_cancellations == 1
        assert pool.sessions["gateway-session"].state.streams == {}
        assert transport.handlers == {}
        assert transport.cancel_interrupted.is_set()
        assert not transport.cancel_completed.is_set()
        terminal = bridge.events.get_nowait()
        assert terminal.payload == "terminal"
        assert terminal.terminal_reason is CloseReason.CALLER
        assert any(
            record.message == "Runtime Web Gateway CANCEL delivery timed out"
            and record.__dict__.get("error_type") == "TimeoutError"
            for record in caplog.records
        )
        async with ClientSession() as client:
            response = await client.get(f"http://127.0.0.1:{port}/state")
            assert response.status == 200
            assert await response.json() == {"active": 0}

        transport.release_cancel.set()
        await asyncio.wait_for(transport.cancel_completed.wait(), timeout=1)
        assert resources.active_exchanges == 0
        assert drain.active == {}
        assert handler_cancellations == 1
        assert pool.sessions["gateway-session"].state.streams == {}
        assert transport.handlers == {}
        assert bridge.request_credit.closed
        assert bridge.response_credit.closed
        assert [envelope.WhichOneof("payload") for envelope in transport.sent] == [
            "open",
            "cancel",
        ]
    finally:
        transport.release_cancel.set()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_cancel_delivery_failure_is_content_free_and_releases(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _FailingCancelTransport()
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

    await bridge.cancel()

    assert bridge.released
    assert pool.sessions["gateway-session"].state.streams == {}
    assert transport.handlers == {}
    assert any(
        record.message == "Runtime Web Gateway CANCEL delivery failed"
        and record.__dict__.get("error_type") == "RuntimeError"
        for record in caplog.records
    )
    assert "sensitive-transport-detail" not in caplog.text


@pytest.mark.asyncio
async def test_sse_and_websocket_open_concurrently_after_capacity_release() -> None:
    resources = _ObservedResources(maximum_active_exchanges=2)
    transport = _CaptureTransport(resources)
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    await pool.register(
        identity=_identity(),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )

    async def ignore_close(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN

    drain = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=1,
            long_lived_grace_seconds=0.5,
            termination_grace_seconds=2,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=ignore_close,
    )
    sse_registration = await drain.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=ignore_close,
        force_close=ignore_close,
    )
    websocket_registration = await drain.register(
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
        request_graceful_close=ignore_close,
        force_close=ignore_close,
    )
    assert sse_registration is not None
    assert websocket_registration is not None
    assert resources.active_exchanges == 2

    sse, websocket = await asyncio.gather(
        RuntimeWebBrowserStreamBridge.open(
            pool=pool,
            stream_id=1,
            authority=_authority(),
            request_head=_head(StreamProtocol.HTTP),
        ),
        RuntimeWebBrowserStreamBridge.open(
            pool=pool,
            stream_id=2,
            authority=_authority(),
            request_head=_head(StreamProtocol.WEBSOCKET),
        ),
    )
    await asyncio.gather(
        sse.receive(_accepted_response(stream_id=1)),
        websocket.receive(_accepted_response(stream_id=2)),
    )
    await asyncio.gather(
        sse.wait_accepted(timeout_seconds=1),
        websocket.wait_accepted(timeout_seconds=1),
    )
    sse_head = _response()
    sse_head.stream_id = 1
    sse_head.response_head.status = 200
    sse_head.response_head.headers.append(
        runtime_stream_session_pb2.RuntimeStreamSessionHeader(
            name=b"content-type",
            value=b"text/event-stream",
        )
    )
    websocket_head = _response()
    websocket_head.stream_id = 2
    websocket_head.response_head.status = 101
    await asyncio.gather(
        sse.receive(sse_head),
        websocket.receive(websocket_head),
    )
    sse_event, websocket_event = await asyncio.gather(
        sse.next_event(),
        websocket.next_event(),
    )
    assert sse_event.status == 200
    assert websocket_event.status == 101
    assert await drain.reclassify(
        sse_registration,
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
    )
    opened = {envelope.stream_id: envelope for envelope in transport.sent}
    assert (
        opened[1].open.request_head.protocol
        == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_HTTP
    )
    assert (
        opened[2].open.request_head.protocol
        == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET
    )
    assert (
        await drain.register(
            kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
            request_graceful_close=ignore_close,
            force_close=ignore_close,
        )
        is None
    )

    await asyncio.gather(
        sse.release_event(sse_event),
        websocket.release_event(websocket_event),
    )
    await asyncio.gather(
        sse.cancel(),
        websocket.cancel(),
    )
    assert await drain.release(sse_registration)
    assert await drain.release(websocket_registration)
    assert resources.active_exchanges == 0
    recovered = await drain.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=ignore_close,
        force_close=ignore_close,
    )
    assert recovered is not None
    assert await drain.release(recovered)


@pytest.mark.asyncio
async def test_preaccept_go_away_rejection_wakes_acceptance_waiter() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    transport = _CaptureTransport()
    registration = await pool.register(
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
    waiting = asyncio.create_task(bridge.wait_accepted(timeout_seconds=10))
    terminated = await pool.start_draining(
        registration,
        last_accepted_stream_id=0,
    )
    assert terminated == (1,)

    await bridge.fail_go_away(CloseReason.SERVICE_DRAIN)

    with pytest.raises(RuntimeWebOpenRejected) as rejected:
        await waiting
    assert rejected.value.reason is CloseReason.SERVICE_DRAIN
    assert bridge.released
    assert bridge.accepted.is_set()
    assert bridge.acceptance_error is CloseReason.SERVICE_DRAIN
    assert transport.handlers == {}


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
    blocked = asyncio.create_task(bridges[8].send_request_data(frame))
    await transport.observed_resources.waiter_added.wait()
    assert not blocked.done()
    assert bridges[8].binding.state.snapshot().request_sequence == 0

    update = _response()
    update.window_update.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    update.window_update.stream_consumed_total = MANDATORY_DATA_FRAME_BYTES
    update.window_update.session_consumed_total = MANDATORY_DATA_FRAME_BYTES
    await bridges[0].receive(update)
    await blocked
    assert bridges[8].binding.state.snapshot().request_sequence == 1
    assert transport.resources.scheduler_waiters == 0
    await bridges[0].receive(update)
    with pytest.raises(ValueError, match="must not decrease"):
        update.window_update.stream_consumed_total = 0
        await bridges[0].receive(update)


@pytest.mark.asyncio
async def test_websocket_send_waits_for_stream_credit_update() -> None:
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
    await bridge.receive(_accepted_response())
    frame = b"x" * MANDATORY_DATA_FRAME_BYTES
    for _ in range(4):
        await bridge.send_websocket(
            opcode=WebSocketOpcode.BINARY,
            final=True,
            data=frame,
        )

    blocked = asyncio.create_task(
        bridge.send_websocket(
            opcode=WebSocketOpcode.BINARY,
            final=True,
            data=frame,
        )
    )
    await transport.observed_resources.waiter_added.wait()
    assert not blocked.done()

    update = _response()
    update.window_update.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    update.window_update.stream_consumed_total = MANDATORY_DATA_FRAME_BYTES
    update.window_update.session_consumed_total = MANDATORY_DATA_FRAME_BYTES
    await bridge.receive(update)
    await blocked

    assert bridge.binding.state.snapshot().request_sequence == 5
    assert transport.sent[-1].websocket.data == frame
    assert transport.resources.scheduler_waiters == 0


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
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
    )
    response_data.data.data = b"x" * MANDATORY_DATA_FRAME_BYTES
    await bridge.receive(response_data)

    head_event = await bridge.next_event()
    assert head_event.payload == "response_head"
    buffered_control = transport.resources.control_buffer_bytes
    assert buffered_control > head_event.control_buffer_bytes
    await bridge.release_event(head_event)
    assert transport.resources.control_buffer_bytes == (
        buffered_control - head_event.control_buffer_bytes
    )
    event = await bridge.next_event()
    assert event.data == response_data.data.data
    assert transport.resources.application_buffer_bytes == len(event.data)
    await bridge.release_event(event)
    update = transport.sent[-1].window_update
    assert update.stream_consumed_total == MANDATORY_DATA_FRAME_BYTES
    assert update.session_consumed_total == MANDATORY_DATA_FRAME_BYTES
    assert transport.resources.application_buffer_bytes == 0
    assert transport.resources.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_websocket_control_payload_does_not_return_application_credit() -> None:
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
    await bridge.receive(_accepted_response())
    response_head = _response()
    response_head.response_head.status = 101
    await bridge.receive(response_head)
    ping = _response()
    ping.frame_sequence = 1
    ping.websocket.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
    )
    ping.websocket.opcode = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PING
    )
    ping.websocket.final = True
    ping.websocket.data = b"ping"
    await bridge.receive(ping)
    sent_before = len(transport.sent)

    head_event = await bridge.next_event()
    await bridge.release_event(head_event)
    ping_event = await bridge.next_event()
    await bridge.release_event(ping_event)

    assert head_event.payload == "response_head"
    assert ping_event.websocket_opcode is WebSocketOpcode.PING
    assert len(transport.sent) == sent_before
    assert bridge.response_credit.session.sent_total == 0
    assert transport.resources.application_buffer_bytes == 0
    assert transport.resources.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_discarded_browser_event_releases_buffers_without_credit() -> None:
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
    head_event = await bridge.next_event()
    await bridge.release_event(head_event)
    response_data = _response()
    response_data.frame_sequence = 1
    response_data.data.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
    )
    response_data.data.data = b"unwritten"
    await bridge.receive(response_data)
    sent_before_discard = len(transport.sent)

    event = await bridge.next_event()
    await bridge.discard_event(event)

    assert len(transport.sent) == sent_before_discard
    assert transport.resources.application_buffer_bytes == 0
    assert transport.resources.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_terminal_uses_reserved_slot_when_browser_queue_is_full() -> None:
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
    for sequence in range(1, 8):
        response_data = _response()
        response_data.frame_sequence = sequence
        response_data.data.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        )
        response_data.data.data = b"x"
        await bridge.receive(response_data)
    assert bridge.events.qsize() == 8

    async with asyncio.timeout(1):
        await bridge.cancel(CloseReason.SERVICE_DRAIN)

    assert bridge.released
    assert bridge.terminal_published
    assert bridge.events.qsize() == 9
    events = [await bridge.next_event() for _ in range(9)]
    assert events[-1].payload == "terminal"
    assert events[-1].terminal_reason is CloseReason.SERVICE_DRAIN
    for event in events:
        await bridge.discard_event(event)
    assert transport.resources.application_buffer_bytes == 0
    assert transport.resources.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_control_event_queue_wait_charges_scheduler_waiter() -> None:
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
    for sequence in range(1, 8):
        response_data = _response()
        response_data.frame_sequence = sequence
        response_data.data.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        )
        response_data.data.data = b"x"
        await bridge.receive(response_data)
    direction_end = _response()
    direction_end.direction_end.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
    )
    direction_end.direction_end.final_sequence = 7

    receiving_end = asyncio.create_task(bridge.receive(direction_end))
    await transport.observed_resources.waiter_added.wait()
    assert transport.resources.scheduler_waiters == 1
    assert not receiving_end.done()

    event = await bridge.next_event()
    await bridge.release_event(event)
    await receiving_end

    assert transport.resources.scheduler_waiters == 0
    assert bridge.events.qsize() == 8
    await bridge.discard_buffered_events()
    assert transport.resources.application_buffer_bytes == 0
    assert transport.resources.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_control_event_cannot_bypass_scheduler_waiter_ceiling() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    resources = _ObservedResources(maximum_scheduler_waiters=1)
    transport = _CaptureTransport(resources)
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
    for sequence in range(1, 8):
        response_data = _response()
        response_data.frame_sequence = sequence
        response_data.data.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        )
        response_data.data.data = b"x"
        await bridge.receive(response_data)
    assert resources.try_add_scheduler_waiter()
    direction_end = _response()
    direction_end.direction_end.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
    )
    direction_end.direction_end.final_sequence = 7

    await bridge.receive(direction_end)

    assert bridge.released
    assert bridge.events.qsize() == 9
    assert resources.scheduler_waiters == 1
    resources.remove_scheduler_waiter()
    events = [await bridge.next_event() for _ in range(9)]
    assert events[-1].payload == "terminal"
    assert events[-1].terminal_reason is CloseReason.RESOURCE_EXHAUSTED
    for event in events:
        await bridge.discard_event(event)
    assert resources.application_buffer_bytes == 0
    assert resources.control_buffer_bytes == 0
    assert resources.scheduler_waiters == 0


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
        runtime_stream_session_pb2.RuntimeStreamSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            route_path=(
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL
            ),
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
        runtime_stream_session_pb2.RuntimeStreamSessionResponseHead(
            status=200,
            headers=[
                runtime_stream_session_pb2.RuntimeStreamSessionHeader(
                    name=b"x-response", value=b"\xfe"
                )
            ],
        )
    )
    await bridge.receive(response_head)
    data = _response()
    data.frame_sequence = 1
    data.data.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionData(
            direction=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
            data=b"\xffresponse",
        )
    )
    await bridge.receive(data)
    direction_end = _response()
    direction_end.direction_end.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionDirectionEnd(
            direction=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
            final_sequence=1,
        )
    )
    await bridge.receive(direction_end)
    stream_end = _response()
    stream_end.stream_end.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionStreamEnd()
    )
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
        runtime_stream_session_pb2.RuntimeStreamSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            route_path=(
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL
            ),
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        )
    )
    await bridge.receive(accepted)
    response_head = _response()
    response_head.response_head.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionResponseHead(status=101)
    )
    await bridge.receive(response_head)
    await bridge.send_websocket(
        opcode=WebSocketOpcode.BINARY,
        final=True,
        data=b"\x00\xff",
    )
    assert transport.sent[-1].websocket.data == b"\x00\xff"
    assert transport.sent[-1].websocket.opcode == (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY
    )
    websocket = _response()
    websocket.frame_sequence = 1
    websocket.websocket.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionWebSocketFrame(
            direction=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
            opcode=(
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY
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
        self.sent: asyncio.Queue[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ] = asyncio.Queue()
        self.responses: asyncio.Queue[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ] = asyncio.Queue()
        self.response_yielded = asyncio.Event()

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        assert metadata is None

        async def exchange() -> AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            await self.sent.put(hello)
            yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                protocol_fingerprint=hello.protocol_fingerprint,
                session_id=hello.session_id,
                peer_boot_id="control-boot",
                session_accepted=(
                    runtime_stream_session_pb2.RuntimeStreamSessionAccepted()
                ),
            )
            async for request in request_iterator:
                await self.sent.put(request)
                yield await self.responses.get()
                self.response_yielded.set()

        return exchange()


class _PausedDuplexStream:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ] = asyncio.Queue()
        self.release_requests = asyncio.Event()

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        assert metadata is None

        async def exchange() -> AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            await self.sent.put(hello)
            yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                protocol_fingerprint=hello.protocol_fingerprint,
                session_id=hello.session_id,
                peer_boot_id="control-boot",
                session_accepted=runtime_stream_session_pb2.RuntimeStreamSessionAccepted(),
            )
            await self.release_requests.wait()
            async for request in request_iterator:
                await self.sent.put(request)

        return exchange()


def _gateway_hello() -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    return runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )


def _data_envelope_with_size(
    size_bytes: int,
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    payload_bytes = size_bytes
    while True:
        envelope = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
        envelope.data.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
        )
        envelope.data.data = b"x" * payload_bytes
        difference = envelope.ByteSize() - size_bytes
        if difference == 0:
            return envelope
        payload_bytes -= difference
        if payload_bytes <= 0:
            raise AssertionError("Requested envelope size is too small")


class _IndependentDuplexStream:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ] = asyncio.Queue()
        self.responses: asyncio.Queue[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ] = asyncio.Queue()
        self.response_yielded = asyncio.Event()

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        assert metadata is None

        async def consume_requests() -> None:
            async for request in request_iterator:
                await self.sent.put(request)

        async def exchange() -> AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            await self.sent.put(hello)
            consumer = asyncio.create_task(consume_requests())
            try:
                yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                    protocol_fingerprint=hello.protocol_fingerprint,
                    session_id=hello.session_id,
                    peer_boot_id="control-boot",
                    session_accepted=(
                        runtime_stream_session_pb2.RuntimeStreamSessionAccepted()
                    ),
                )
                while True:
                    yield await self.responses.get()
                    self.response_yielded.set()
            finally:
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)

        return exchange()


@pytest.mark.asyncio
async def test_gateway_session_heartbeat_ack_is_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_session_bridge_module,
        "_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    stream = _IndependentDuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    await stream.sent.get()

    heartbeat = await asyncio.wait_for(stream.sent.get(), timeout=1)
    acknowledgement = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id="control-boot",
    )
    acknowledgement.heartbeat_ack.monotonic_sequence = (
        heartbeat.heartbeat.monotonic_sequence
    )
    await stream.responses.put(acknowledgement)
    await asyncio.wait_for(stream.response_yielded.wait(), timeout=1)

    assert resources.transport_heartbeats_sent == 1
    assert resources.transport_heartbeat_acknowledgements == 1
    await transport.close()


@pytest.mark.asyncio
async def test_gateway_session_two_missed_heartbeats_fail_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_session_bridge_module,
        "_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        web_session_bridge_module,
        "_MAX_MISSED_HEARTBEATS",
        2,
    )
    stream = _IndependentDuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    await stream.sent.get()
    await asyncio.wait_for(stream.sent.get(), timeout=1)
    await asyncio.wait_for(stream.sent.get(), timeout=1)
    assert transport.heartbeat_task is not None
    await asyncio.wait_for(transport.heartbeat_task, timeout=1)
    assert transport.receiver is not None
    await asyncio.gather(transport.receiver, return_exceptions=True)

    assert resources.transport_missed_heartbeats == 1
    assert not transport.active
    await transport.close()


@pytest.mark.asyncio
async def test_persistent_session_sends_next_open_after_preaccept_cancel() -> None:
    stream = _IndependentDuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    assert (await stream.sent.get()).WhichOneof("payload") == "hello"
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    await pool.register(
        identity=identity,
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )

    first = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    assert (await asyncio.wait_for(stream.sent.get(), timeout=1)).stream_id == 1
    waiting = asyncio.create_task(first.wait_accepted(timeout_seconds=10))
    await first.cancel()
    cancel = await asyncio.wait_for(stream.sent.get(), timeout=1)
    assert cancel.stream_id == 1
    assert cancel.WhichOneof("payload") == "cancel"
    with pytest.raises(RuntimeWebOpenRejected):
        await waiting

    second = await RuntimeWebBrowserStreamBridge.open(
        pool=pool,
        stream_id=2,
        authority=_authority(),
        request_head=_head(),
    )
    second_open = await asyncio.wait_for(stream.sent.get(), timeout=1)
    assert second_open.stream_id == 2
    assert second_open.WhichOneof("payload") == "open"
    await stream.responses.put(_accepted_response(stream_id=2))
    await second.wait_accepted(timeout_seconds=1)

    assert transport.active
    assert transport.failure is None
    await second.cancel()
    await transport.close()


class _GoAwayHandler:
    def __init__(self) -> None:
        self.stream_frames = 0
        self.transport_failed = asyncio.Event()
        self.go_away = asyncio.Event()
        self.go_away_reason: CloseReason | None = None

    async def __call__(
        self,
        envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
    ) -> None:
        del envelope
        self.stream_frames += 1

    async def fail_transport(self) -> None:
        self.transport_failed.set()

    async def fail_go_away(self, reason: CloseReason) -> None:
        self.go_away_reason = reason
        self.go_away.set()


@pytest.mark.asyncio
async def test_transport_consumes_go_away_and_fences_only_above_boundary() -> None:
    stream = _DuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    await stream.sent.get()
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    registration = await pool.register(
        identity=identity,
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    await pool.open(stream_id=1, authority=_authority(), request_head=_head())
    await pool.open(stream_id=2, authority=_authority(), request_head=_head())
    first = _GoAwayHandler()
    second = _GoAwayHandler()
    await transport.bind(1, first)
    await transport.bind(2, second)

    async def start_draining(
        boundary: int,
        reason: CloseReason,
        deadline: datetime,
    ) -> tuple[int, ...]:
        assert reason is CloseReason.SERVICE_DRAIN
        assert deadline > datetime.now(UTC)
        return await pool.start_draining(
            registration,
            last_accepted_stream_id=boundary,
        )

    transport.set_go_away_handler(start_draining)
    await transport.send(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            heartbeat=runtime_stream_session_pb2.RuntimeStreamSessionHeartbeat(
                monotonic_sequence=1
            )
        )
    )
    await stream.sent.get()
    go_away = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id="control-boot",
        go_away=runtime_stream_session_pb2.RuntimeStreamSessionGoAway(
            last_accepted_stream_id=1,
            reason=(
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_SERVICE_DRAIN
            ),
        ),
    )
    deadline = datetime.now(UTC) + timedelta(seconds=1)
    go_away.go_away.drain_deadline_at.FromDatetime(deadline)
    await stream.responses.put(go_away)

    await asyncio.wait_for(transport.go_away_received.wait(), timeout=1)

    assert transport.go_away_boundary == 1
    assert transport.go_away_reason is CloseReason.SERVICE_DRAIN
    assert transport.go_away_deadline == deadline
    assert transport.failure is None
    assert transport.active
    assert first.go_away_reason is None
    assert second.go_away_reason is CloseReason.SERVICE_DRAIN
    assert first.stream_frames == 0
    assert second.stream_frames == 0
    assert not first.transport_failed.is_set()
    assert not second.transport_failed.is_set()
    with pytest.raises(RuntimeError, match="no active"):
        await pool.open(stream_id=3, authority=_authority(), request_head=_head())
    await transport.close()


@pytest.mark.asyncio
async def test_transport_go_away_deadline_terminates_allowed_stream() -> None:
    stream = _DuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)
    await stream.sent.get()
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    registration = await pool.register(
        identity=identity,
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    await pool.open(stream_id=1, authority=_authority(), request_head=_head())
    handler = _GoAwayHandler()
    await transport.bind(1, handler)

    async def start_draining(
        boundary: int,
        reason: CloseReason,
        deadline: datetime,
    ) -> tuple[int, ...]:
        del reason, deadline
        return await pool.start_draining(
            registration,
            last_accepted_stream_id=boundary,
        )

    transport.set_go_away_handler(start_draining)
    await transport.send(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            heartbeat=runtime_stream_session_pb2.RuntimeStreamSessionHeartbeat(
                monotonic_sequence=1
            )
        )
    )
    await stream.sent.get()
    go_away = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id="control-boot",
        go_away=runtime_stream_session_pb2.RuntimeStreamSessionGoAway(
            last_accepted_stream_id=1,
            reason=(
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_SERVICE_DRAIN
            ),
        ),
    )
    go_away.go_away.drain_deadline_at.FromDatetime(
        datetime.now(UTC) + timedelta(milliseconds=50)
    )
    await stream.responses.put(go_away)

    await asyncio.wait_for(transport.go_away_received.wait(), timeout=1)
    assert not handler.go_away.is_set()
    await asyncio.wait_for(handler.go_away.wait(), timeout=1)

    assert handler.go_away_reason is CloseReason.SERVICE_DRAIN
    assert handler.stream_frames == 0
    assert not handler.transport_failed.is_set()
    assert transport.failure is None
    assert transport.active
    await transport.close()


@pytest.mark.asyncio
async def test_transport_copy_fails_fast_when_original_owns_buffer_ceiling() -> None:
    resources = _ObservedResources(maximum_application_buffer_bytes=10)
    assert await resources.reserve_application_buffer(10)
    transport = PersistentGatewaySessionTransport(
        _DuplexStream(),
        resources=resources,
    )

    async with asyncio.timeout(1):
        with pytest.raises(
            RuntimeWebGatewayResourceExhausted,
            match="application buffer",
        ):
            await transport.send(
                runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                    stream_id=1,
                    data=runtime_stream_session_pb2.RuntimeStreamSessionData(data=b"x"),
                )
            )

    assert resources.application_buffer_bytes == 10
    await resources.release_application_buffer(10)
    assert resources.application_buffer_bytes == 0


@pytest.mark.asyncio
async def test_persistent_transport_accounts_queued_application_and_control_bytes() -> (
    None
):
    permit_requests = asyncio.Event()

    def stream(
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        assert metadata is None

        async def exchange() -> AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                protocol_fingerprint=hello.protocol_fingerprint,
                session_id=hello.session_id,
                peer_boot_id="control-boot",
                session_accepted=(
                    runtime_stream_session_pb2.RuntimeStreamSessionAccepted()
                ),
            )
            await permit_requests.wait()

        return exchange()

    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    await transport.start(hello, timeout_seconds=1)

    data = b"buffered"
    await transport.send(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            stream_id=1,
            data=runtime_stream_session_pb2.RuntimeStreamSessionData(data=data),
        )
    )
    snapshot = resources.snapshot()
    assert snapshot.application_buffer_bytes == len(data)
    assert snapshot.control_buffer_bytes > 0

    await transport.close()
    snapshot = resources.snapshot()
    assert snapshot.application_buffer_bytes == 0
    assert snapshot.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_persistent_transport_multiplexes_without_replay() -> None:
    stream = _DuplexStream()
    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )
    accepted = await transport.start(hello, timeout_seconds=1)
    assert accepted.WhichOneof("payload") == "session_accepted"
    assert (await stream.sent.get()).hello.role == (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
    )
    oversized = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        data=runtime_stream_session_pb2.RuntimeStreamSessionData(
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
            self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ) -> None:
            assert envelope.stream_id == 7
            self.delivered.set()

        async def fail_transport(self) -> None:
            self.failed.set()

        async def fail_go_away(self, reason: CloseReason) -> None:
            del reason
            self.failed.set()

    handler = _Handler()
    await transport.bind(7, handler)
    await transport.send(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            stream_id=7,
            cancel=runtime_stream_session_pb2.RuntimeStreamSessionCancel(
                reason=(
                    runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER
                )
            ),
        )
    )
    assert (await stream.sent.get()).stream_id == 7
    await stream.responses.put(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="control-boot",
            stream_id=7,
            reset=runtime_stream_session_pb2.RuntimeStreamSessionReset(
                reason=(
                    runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER
                )
            ),
        )
    )
    await asyncio.wait_for(handler.delivered.wait(), timeout=1)
    await transport.unbind(7)
    await asyncio.wait_for(stream.response_yielded.wait(), timeout=1)
    assert transport.active
    assert await transport.close() == ()


@pytest.mark.asyncio
async def test_persistent_transport_prioritizes_control_over_queued_data() -> None:
    stream = _PausedDuplexStream()
    resources = _ObservedResources()
    transport = PersistentGatewaySessionTransport(stream, resources=resources)
    await transport.start(_gateway_hello(), timeout_seconds=1)
    await stream.sent.get()

    data = _data_envelope_with_size(SESSION_WINDOW_BYTES // 32)
    cancel = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
    cancel.cancel.reason = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER
    )
    for _ in range(32):
        await transport.send(data)
    latency = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
    latency.direction_end.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    latency_task = asyncio.create_task(transport.send(latency))
    await resources.waiter_added.wait()
    assert not latency_task.done()
    await transport.send(cancel)

    assert transport.outbound_bytes == SESSION_WINDOW_BYTES + cancel.ByteSize()
    assert transport.outbound_items[QueueLane.DATA] == 32
    assert transport.outbound_items[QueueLane.LATENCY] == 0
    assert transport.outbound_items[QueueLane.CONTROL] == 1
    stream.release_requests.set()

    assert (await stream.sent.get()).WhichOneof("payload") == "cancel"
    assert (await stream.sent.get()).WhichOneof("payload") == "data"
    latency_task.cancel()
    await asyncio.gather(latency_task, return_exceptions=True)
    await transport.close()


def test_persistent_transport_routes_websocket_controls_to_data_lane() -> None:
    ping = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
    ping.websocket.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    ping.websocket.opcode = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PING
    )
    ping.websocket.final = True
    ping.websocket.data = b"ping"

    assert _outbound_lane(ping) is QueueLane.DATA


@pytest.mark.asyncio
async def test_persistent_transport_preserves_stream_order_across_priority_lanes() -> (
    None
):
    stream = _PausedDuplexStream()
    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    await transport.start(_gateway_hello(), timeout_seconds=1)
    await stream.sent.get()
    data = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
    data.frame_sequence = 1
    data.data.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    data.data.data = b"data"
    direction_end = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(stream_id=7)
    direction_end.direction_end.direction = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    )
    direction_end.direction_end.final_sequence = 1
    session_control = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
    session_control.heartbeat_ack.monotonic_sequence = 1

    await transport.send(data)
    await transport.send(direction_end)
    await transport.send(session_control)
    stream.release_requests.set()

    assert (await stream.sent.get()).WhichOneof("payload") == "heartbeat_ack"
    assert (await stream.sent.get()).WhichOneof("payload") == "data"
    assert (await stream.sent.get()).WhichOneof("payload") == "direction_end"
    await transport.close()


@pytest.mark.asyncio
async def test_persistent_transport_handles_session_frames_before_stream_lookup() -> (
    None
):
    stream = _IndependentDuplexStream()
    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    await transport.start(_gateway_hello(), timeout_seconds=1)
    await stream.sent.get()
    await stream.responses.put(
        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="control-boot",
            heartbeat=runtime_stream_session_pb2.RuntimeStreamSessionHeartbeat(
                monotonic_sequence=9
            ),
        )
    )

    acknowledgement = await asyncio.wait_for(stream.sent.get(), timeout=1)
    assert acknowledgement.stream_id == 0
    assert acknowledgement.heartbeat_ack.monotonic_sequence == 9
    await transport.close()


@pytest.mark.asyncio
async def test_persistent_transport_session_error_closes_without_stream_lookup() -> (
    None
):
    stream = _IndependentDuplexStream()
    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    await transport.start(_gateway_hello(), timeout_seconds=1)
    await stream.sent.get()
    session_error = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="control-boot",
    )
    stream_pb2 = runtime_stream_session_pb2
    protocol_violation_reason = (
        stream_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
    )
    session_error.session_error.reason = protocol_violation_reason
    await stream.responses.put(session_error)
    assert transport.receiver is not None
    with pytest.raises(RuntimeError, match="session error"):
        await asyncio.wait_for(transport.receiver, timeout=1)

    assert not transport.active
    assert isinstance(transport.failure, RuntimeError)
    assert "session error" in str(transport.failure)
    await transport.close()


@pytest.mark.asyncio
async def test_persistent_transport_rejects_stream_scoped_session_acceptance() -> None:
    async def stream(
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        assert metadata is None
        hello = await anext(request_iterator)
        yield runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=hello.protocol_fingerprint,
            session_id=hello.session_id,
            peer_boot_id="control-boot",
            stream_id=7,
            session_accepted=runtime_stream_session_pb2.RuntimeStreamSessionAccepted(),
        )

    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        ),
    )

    with pytest.raises(RuntimeError, match="session-scoped"):
        await transport.start(hello, timeout_seconds=1)

    assert isinstance(transport.failure, RuntimeError)
    assert not transport.active


@pytest.mark.asyncio
async def test_receiver_identity_failure_retires_pool_session_automatically() -> None:
    stream = _DuplexStream()
    transport = PersistentGatewaySessionTransport(
        stream,
        resources=_ObservedResources(),
    )
    identity = _identity()
    hello = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=identity.session_id,
        peer_boot_id=identity.peer_boot_id,
        hello=runtime_stream_session_pb2.RuntimeStreamSessionHello(
            role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
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
    stream_pb2 = runtime_stream_session_pb2
    transport_unavailable_reason = (
        stream_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
    )
    stale.reset.reason = transport_unavailable_reason
    await stream.responses.put(stale)
    terminal = await asyncio.wait_for(bridge.events.get(), timeout=1)
    assert terminal.terminal_reason is CloseReason.TRANSPORT_UNAVAILABLE
    assert "gateway-session" not in pool.sessions
    assert await transport.close() == ()
