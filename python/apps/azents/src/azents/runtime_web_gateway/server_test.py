"""Gateway HTTP security boundary tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import WSMessage, WSMsgType, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer
from azcommon.logging import RuntimeEnvironment
from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_flow import AbsoluteCreditWindow
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    SESSION_WINDOW_BYTES,
    CloseReason,
    Header,
    SessionIdentity,
    SessionPeerRole,
    StreamProtocol,
    WebSocketOpcode,
)
from multidict import CIMultiDict

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebServiceRecord
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAuthBinding,
    RuntimeWebBrokerBinding,
    RuntimeWebGatewayAuthority,
    RuntimeWebGatewayIdentity,
    RuntimeWebRedeemedIdentity,
)
from azents.runtime_web_gateway.operations import (
    RuntimeWebCapacityBackend,
    RuntimeWebDrainCoordinator,
    RuntimeWebDrainPolicy,
    RuntimeWebDrainStreamKind,
    RuntimeWebGatewayHardLimits,
    RuntimeWebGatewayHealth,
    RuntimeWebGatewayOperationalState,
    RuntimeWebGatewayOperationsCoordinator,
    RuntimeWebGatewayPressure,
    RuntimeWebGatewayResourceTracker,
)
from azents.runtime_web_gateway.server import (
    LinuxProcResidentMemorySampler,
    _assemble_websocket_response_event,
    _completion_document,
    _response_is_sse,
    _selected_websocket_subprotocol,
    _send_websocket_frames,
    _websocket_data,
    _websocket_subprotocol_tokens,
    _WebSocketResponseAssembler,
    create_runtime_web_gateway_application,
    create_runtime_web_resident_memory_sampler,
)
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.web_session_bridge import (
    BrowserStreamEvent,
    RuntimeWebBrowserStreamBridge,
    RuntimeWebGatewayResourceExhausted,
)
from azents.runtime_web_gateway.web_session_pool import (
    GatewayStreamHandler,
    RuntimeWebGatewaySessionPool,
)
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityCode,
    RuntimeWebGatewayAuthorityError,
)

_CONFIG = RuntimeWebGatewayConfig(
    enabled=True,
    auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
    main_web_origin="https://app.example.com",
    broker_origin="https://auth.services.example.net",
    service_suffix="services.example.net",
    cookie_domain="services.example.net",
    identity_cookie_name="__Http-Azents-Runtime-Web",
    identity_lifetime_seconds=1_800,
    request_header_bytes=32 * 1024,
    request_body_bytes=64 * 1024 * 1024,
    permissions_policy="camera=()",
)
_SETTINGS = RuntimeWebGatewaySettings.model_validate(
    {
        "runtime_env": RuntimeEnvironment.LOCAL,
        "runtime_web_gateway_enabled": True,
        "runtime_web_gateway_auth_mode": RuntimeWebAuthMode.SEPARATE_DOMAIN,
        "runtime_web_gateway_main_web_origin": "http://app.localhost",
        "runtime_web_gateway_broker_origin": "http://auth.services.localhost",
        "runtime_web_gateway_service_suffix": "services.localhost",
        "runtime_web_gateway_cookie_domain": "services.localhost",
        "runtime_web_gateway_control_endpoint": "localhost:8032",
        "runtime_web_gateway_control_allow_insecure": True,
    }
)
_NOW = datetime.now(UTC)


def test_completion_replaces_history_with_fixed_script() -> None:
    document = _completion_document(
        "https://endpoint.services.example.net/catalog?tag=one&tag=two#details"
    )
    assert (
        'href="https://endpoint.services.example.net/catalog?tag=one&amp;tag=two#details"'
        in document
    )
    assert (
        'window.location.replace(document.getElementById("continue").href)' in document
    )
    assert ".click()" not in document
    assert ">Continue</a>" in document


def test_completion_escapes_attribute_content_and_keeps_inline_script_fixed() -> None:
    document = _completion_document('https://endpoint.test/?q="</script><script>bad')
    assert (
        'href="https://endpoint.test/?q=&quot;&lt;/script&gt;&lt;script&gt;bad"'
        in document
    )
    assert document.count("<script") == 1


_SERVICE = RuntimeWebServiceRecord(
    id="e" * 32,
    workspace_id="w" * 32,
    agent_id="a" * 32,
    port=8080,
    hostname_key="endpoint",
    label="Preview",
    selected_duration_seconds=3600,
    exposure_deadline_at=_NOW + timedelta(minutes=5),
    revision=1,
    created_at=_NOW,
    updated_at=_NOW,
)


class _Auth:
    async def bind_broker(
        self,
        *,
        initiation_id: str,
        now: datetime,
    ) -> RuntimeWebBrokerBinding:
        return RuntimeWebBrokerBinding(
            binding=RuntimeWebAuthBinding(
                id="b" * 32,
                initiation_id=initiation_id,
                user_id="u" * 32,
                auth_session_id="s" * 32,
                service_id=_SERVICE.id,
                expires_at=now + timedelta(seconds=120),
                broker_bound=True,
                settled=False,
            ),
            broker_binding_secret="broker-secret",
        )

    async def redeem_ticket(
        self,
        *,
        ticket_secret: str,
        broker_binding_secret: str,
        now: datetime,
    ) -> RuntimeWebRedeemedIdentity:
        del ticket_secret, broker_binding_secret, now
        raise AssertionError("Broker authentication is not expected")


class _Authority:
    async def resolve_service(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebServiceRecord | None:
        return _SERVICE if hostname_key == "endpoint" else None

    async def resolve_service_by_id(
        self,
        *,
        service_id: str,
    ) -> RuntimeWebServiceRecord | None:
        del service_id
        raise AssertionError("Broker authentication is not expected")

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthority:
        del hostname_key, identity_secret, protocol
        raise AssertionError("Gateway admission is not expected")

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        del authority
        raise AssertionError("Gateway admission is not expected")


class _ControlSessions:
    def __init__(self) -> None:
        self.opened = False
        self.pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)


class _WebSocketAuthority(_Authority):
    def __init__(self) -> None:
        self.value = RuntimeWebGatewayAuthority(
            identity=RuntimeWebGatewayIdentity(
                id="i" * 32,
                user_id="u" * 32,
                auth_session_id="h" * 32,
                mode=RuntimeWebAuthMode.SHARED_COOKIE,
                issued_at=_NOW,
                expires_at=_NOW + timedelta(minutes=5),
            ),
            service=_SERVICE,
            runtime_id="t" * 32,
            desired_generation=1,
            runner_generation=1,
            exposure_deadline_at=_NOW + timedelta(minutes=5),
        )

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthority:
        assert hostname_key == "endpoint"
        assert identity_secret == "opaque-secret"
        assert protocol is StreamProtocol.WEBSOCKET
        return self.value

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        assert authority is self.value
        return True


class _HttpAuthority(_WebSocketAuthority):
    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthority:
        assert hostname_key == "endpoint"
        assert identity_secret == "opaque-secret"
        assert protocol is StreamProtocol.HTTP
        return self.value


class _WebSocketTransport:
    def __init__(
        self,
        *,
        resources: RuntimeWebGatewayResourceTracker,
        response_headers: tuple[tuple[bytes, bytes], ...],
        response_frames: tuple[tuple[WebSocketOpcode, bool, bytes], ...],
    ) -> None:
        self.resources = resources
        self.response_headers = response_headers
        self.response_frames = response_frames
        self.handlers: dict[int, RuntimeWebBrowserStreamBridge] = {}
        self.sent: list[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope] = []
        self.credit_condition = asyncio.Condition()
        self.request_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )
        self.unbound = asyncio.Event()

    async def bind(self, stream_id: int, handler: GatewayStreamHandler) -> None:
        if not isinstance(handler, RuntimeWebBrowserStreamBridge):
            raise TypeError("Runtime Web test transport requires a browser bridge")
        self.handlers[stream_id] = handler

    async def unbind(self, stream_id: int) -> None:
        self.handlers.pop(stream_id, None)
        self.unbound.set()

    async def send(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        copied = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
        copied.CopyFrom(envelope)
        self.sent.append(copied)
        handler = self.handlers.get(envelope.stream_id)
        if handler is None:
            return
        payload = envelope.WhichOneof("payload")
        if payload == "open":
            await handler.receive(self._accepted(envelope.stream_id))
            await handler.receive(self._response_head(envelope.stream_id))
            for sequence, (opcode, final, data) in enumerate(
                self.response_frames,
                start=1,
            ):
                await handler.receive(
                    self._websocket_frame(
                        envelope.stream_id,
                        sequence=sequence,
                        opcode=opcode,
                        final=final,
                        data=data,
                    )
                )
        elif payload == "direction_end" and not self.response_frames:
            await handler.receive(self._reset(envelope.stream_id))

    @staticmethod
    def _base(
        stream_id: int,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        return runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="control-boot",
            stream_id=stream_id,
        )

    @classmethod
    def _accepted(
        cls,
        stream_id: int,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        envelope = cls._base(stream_id)
        envelope.open_accepted.data_frame_bytes = (
            APPROVED_SESSION_PROFILE.data_frame_bytes
        )
        envelope.open_accepted.request_credit_bytes = (
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        )
        envelope.open_accepted.response_credit_bytes = (
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        )
        envelope.open_accepted.route_path = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL
        )
        return envelope

    def _response_head(
        self,
        stream_id: int,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        envelope = self._base(stream_id)
        envelope.response_head.status = 101
        envelope.response_head.headers.extend(
            runtime_stream_session_pb2.RuntimeStreamSessionHeader(
                name=name, value=value
            )
            for name, value in self.response_headers
        )
        return envelope

    @classmethod
    def _reset(
        cls,
        stream_id: int,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        envelope = cls._base(stream_id)
        proto = runtime_stream_session_pb2
        reason = proto.RUNTIME_STREAM_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE
        envelope.reset.reason = reason
        return envelope

    @classmethod
    def _websocket_frame(
        cls,
        stream_id: int,
        *,
        sequence: int,
        opcode: WebSocketOpcode,
        final: bool,
        data: bytes,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        envelope = cls._base(stream_id)
        envelope.frame_sequence = sequence
        envelope.websocket.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        )
        envelope.websocket.opcode = {
            WebSocketOpcode.TEXT: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_TEXT
            ),
            WebSocketOpcode.BINARY: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY
            ),
            WebSocketOpcode.CONTINUATION: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CONTINUATION
            ),
            WebSocketOpcode.PING: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PING
            ),
            WebSocketOpcode.PONG: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PONG
            ),
            WebSocketOpcode.CLOSE: (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CLOSE
            ),
        }[opcode]
        envelope.websocket.final = final
        envelope.websocket.data = data
        return envelope


@dataclasses.dataclass(frozen=True)
class _WebSocketHarness:
    client: TestClient
    control_sessions: _ControlSessions
    transport: _WebSocketTransport
    operations: RuntimeWebGatewayOperationsCoordinator
    operational_state: RuntimeWebGatewayOperationalState


async def _websocket_harness(
    response_headers: tuple[tuple[bytes, bytes], ...],
    *,
    response_frames: tuple[tuple[WebSocketOpcode, bool, bytes], ...],
) -> _WebSocketHarness:
    operations, operational_state = _operations()
    control_sessions = _ControlSessions()
    transport = _WebSocketTransport(
        resources=operational_state.resources,
        response_headers=response_headers,
        response_frames=response_frames,
    )
    await control_sessions.pool.register(
        identity=SessionIdentity(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            role=SessionPeerRole.GATEWAY,
            owner=None,
            session_nonce="nonce",
            deadline_at=_NOW + timedelta(minutes=5),
        ),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=_WebSocketAuthority(),
        control_sessions=control_sessions,
        operations=operations,
        operational_state=operational_state,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    return _WebSocketHarness(
        client=client,
        control_sessions=control_sessions,
        transport=transport,
        operations=operations,
        operational_state=operational_state,
    )


class _BrowserNeutralAuthority(_Authority):
    def __init__(self) -> None:
        self.authorize_calls: list[tuple[str, str, StreamProtocol]] = []

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthority:
        self.authorize_calls.append((hostname_key, identity_secret, protocol))
        raise RuntimeWebGatewayAuthorityError(RuntimeWebGatewayAuthorityCode.GONE)


async def _ignore_drain(reason: CloseReason) -> None:
    assert reason is CloseReason.SERVICE_DRAIN


class _Operations(NamedTuple):
    coordinator: RuntimeWebGatewayOperationsCoordinator
    state: RuntimeWebGatewayOperationalState


def _operations() -> _Operations:
    resources = RuntimeWebGatewayResourceTracker(
        RuntimeWebGatewayHardLimits(
            maximum_active_exchanges=4,
            maximum_application_buffer_bytes=1024 * 1024,
            maximum_control_buffer_bytes=1024 * 1024,
            maximum_pending_tasks=16,
            maximum_scheduler_waiters=4,
            maximum_event_loop_lag_milliseconds=250,
            maximum_resident_memory_bytes=1024 * 1024 * 1024,
        )
    )
    state = RuntimeWebGatewayOperationalState(
        health=RuntimeWebGatewayHealth(
            configuration_valid=True,
            maintenance=False,
            draining=False,
            authority_query_available=True,
            replacement_protocol_compatible=True,
            local_pressure_acceptable=True,
            event_loop_responsive=True,
            redis_available=False,
        ),
        pressure=RuntimeWebGatewayPressure(0, 0, 0, 0, 0),
        backend=RuntimeWebCapacityBackend.MEMORY,
        capacity_degraded=False,
        resources=resources,
        local_open_count=0,
        relay_open_count=0,
        event_loop_lag_milliseconds=0,
        resident_memory_bytes=0,
    )
    drain = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=0.01,
            long_lived_grace_seconds=0.001,
            termination_grace_seconds=1,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=_ignore_drain,
    )
    return _Operations(
        coordinator=RuntimeWebGatewayOperationsCoordinator(state=state, drain=drain),
        state=state,
    )


async def _client(
    control_sessions: _ControlSessions,
    *,
    authority: _Authority | None = None,
    resident_memory_bytes: int = 0,
) -> TestClient:
    operations, operational_state = _operations()
    operational_state.resident_memory_bytes = resident_memory_bytes
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=authority or _Authority(),
        control_sessions=control_sessions,
        operations=operations,
        operational_state=operational_state,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    return client


async def test_local_hard_pressure_rejects_before_authority_lookup() -> None:
    proxy = _ControlSessions()
    client = await _client(proxy, resident_memory_bytes=1024 * 1024 * 1024)
    try:
        response = await client.get(
            "/",
            headers={"Host": "endpoint.services.example.net"},
        )
        assert response.status == 429
        assert (await response.json())["code"] == CloseReason.RESOURCE_EXHAUSTED.value
    finally:
        await client.close()


async def test_active_exchange_limit_rejects_before_request_body_admission() -> None:
    control_sessions = _ControlSessions()
    operations, operational_state = _operations()
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=_HttpAuthority(),
        control_sessions=control_sessions,
        operations=operations,
        operational_state=operational_state,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    registrations = []
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        for _ in range(4):
            registration = await operations.drain_coordinator.register(
                kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
                request_graceful_close=_ignore_drain,
                force_close=_ignore_drain,
            )
            assert registration is not None
            registrations.append(registration)

        server_port = client.server.port
        assert server_port is not None
        reader, writer = await asyncio.open_connection("127.0.0.1", server_port)
        writer.write(
            b"POST /upload HTTP/1.1\r\n"
            b"Host: endpoint.services.example.net\r\n"
            b"Cookie: __Http-Azents-Runtime-Web=opaque-secret\r\n"
            b"Content-Length: 1048576\r\n"
            b"Content-Type: application/octet-stream\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        await writer.drain()

        response_head = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"),
            timeout=1,
        )
        assert response_head.startswith(b"HTTP/1.1 429")
        content_length_line = next(
            line
            for line in response_head.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        content_length = int(content_length_line.split(b":", maxsplit=1)[1])
        response_body = await asyncio.wait_for(
            reader.readexactly(content_length),
            timeout=1,
        )
        assert b"resource_exhausted" in response_body
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        for registration in registrations:
            await operations.drain_coordinator.release(registration)
        await client.close()


async def test_stale_pressure_snapshot_does_not_delay_released_capacity() -> None:
    proxy = _ControlSessions()
    authority = _BrowserNeutralAuthority()
    operations, operational_state = _operations()
    operational_state.health = dataclasses.replace(
        operational_state.health,
        local_pressure_acceptable=False,
    )
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=authority,
        control_sessions=proxy,
        operations=operations,
        operational_state=operational_state,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    try:
        response = await client.get(
            "/api",
            headers={
                "Host": "endpoint.services.example.net",
                "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
            },
        )
        assert response.status == 410
        assert authority.authorize_calls == [
            ("endpoint", "opaque-secret", StreamProtocol.HTTP)
        ]
    finally:
        await client.close()


def test_linux_current_rss_sampler_reads_injected_resident_pages(
    tmp_path: Path,
) -> None:
    statm_path = tmp_path / "statm"
    statm_path.write_text("100 25 0 0 0 0 0\n", encoding="ascii")
    sampler = LinuxProcResidentMemorySampler(
        statm_path=statm_path,
        page_size_bytes=4096,
    )

    assert sampler.current_bytes() == 25 * 4096


def test_linux_current_rss_sample_recovers_pressure_after_memory_release(
    tmp_path: Path,
) -> None:
    statm_path = tmp_path / "statm"
    sampler = LinuxProcResidentMemorySampler(
        statm_path=statm_path,
        page_size_bytes=4096,
    )
    _, state = _operations()
    statm_path.write_text(f"300000 {1024 * 1024 * 1024 // 4096}\n", encoding="ascii")
    state.update_process_pressure(
        event_loop_lag_milliseconds=0,
        resident_memory_bytes=sampler.current_bytes(),
    )
    assert not state.health.ready
    assert state.pressure.resident_memory_ratio == 1

    statm_path.write_text("3000 2500\n", encoding="ascii")
    state.update_process_pressure(
        event_loop_lag_milliseconds=0,
        resident_memory_bytes=sampler.current_bytes(),
    )

    assert state.health.ready
    assert state.pressure.resident_memory_ratio < 1


def test_current_rss_sampler_selects_linux_and_rejects_unsupported_platform() -> None:
    sampler = create_runtime_web_resident_memory_sampler(platform="linux")
    assert sampler.current_bytes() > 0
    with pytest.raises(RuntimeError, match="unsupported"):
        create_runtime_web_resident_memory_sampler(platform="future-os")


def test_sse_response_classification_is_long_lived() -> None:
    assert _response_is_sse(
        (Header(b"content-type", b"text/event-stream; charset=utf-8"),)
    )
    assert not _response_is_sse((Header(b"content-type", b"text/plain"),))


def test_websocket_subprotocol_selection_preserves_order_and_case() -> None:
    offered = _websocket_subprotocol_tokens(
        ((b"Sec-WebSocket-Protocol", b"chat.v1, Chat.V2"),)
    )

    assert offered == ("chat.v1", "Chat.V2")
    assert (
        _selected_websocket_subprotocol(
            offered=offered,
            response_headers=(Header(b"sec-websocket-protocol", b"Chat.V2"),),
        )
        == "Chat.V2"
    )
    assert (
        _selected_websocket_subprotocol(
            offered=offered,
            response_headers=(),
        )
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [bytearray(b"ping"), memoryview(b"ping")],
)
def test_websocket_control_payload_normalizes_buffer_views(
    payload: bytearray | memoryview,
) -> None:
    assert (
        _websocket_data(
            WSMessage(WSMsgType.PING, payload, ""),
            WebSocketOpcode.PING,
        )
        == b"ping"
    )


def test_websocket_response_assembler_preserves_fragmented_message_and_controls() -> (
    None
):
    assembler = _WebSocketResponseAssembler()
    first = BrowserStreamEvent(
        payload="websocket",
        status=None,
        headers=(),
        data=b"hello ",
        websocket_opcode=WebSocketOpcode.TEXT,
        websocket_final=False,
        terminal_reason=None,
        control_buffer_bytes=1,
    )
    ping = dataclasses.replace(
        first,
        data=b"ping",
        websocket_opcode=WebSocketOpcode.PING,
        websocket_final=True,
    )
    continuation = dataclasses.replace(
        first,
        data=b"world",
        websocket_opcode=WebSocketOpcode.CONTINUATION,
        websocket_final=True,
    )

    assert assembler.feed(first) is None
    control = assembler.feed(ping)
    assert control is not None
    assert control.event is ping
    assert control.release_events == (ping,)
    assembled = assembler.feed(continuation)
    assert assembled is not None
    assert assembled.event.websocket_opcode is WebSocketOpcode.TEXT
    assert assembled.event.websocket_final is True
    assert assembled.event.data == b"hello world"
    assert assembled.release_events == (first, continuation)
    assert assembler.discard_pending() == ()


class _DiscardingBridge(RuntimeWebBrowserStreamBridge):
    def __init__(self) -> None:
        self.discarded: list[BrowserStreamEvent] = []

    async def discard_event(self, event: BrowserStreamEvent) -> None:
        self.discarded.append(event)


@pytest.mark.asyncio
async def test_websocket_response_assembly_discards_rejected_current_event() -> None:
    assembler = _WebSocketResponseAssembler()
    first = BrowserStreamEvent(
        payload="websocket",
        status=None,
        headers=(),
        data=b"partial",
        websocket_opcode=WebSocketOpcode.TEXT,
        websocket_final=False,
        terminal_reason=None,
        control_buffer_bytes=1,
    )
    invalid = dataclasses.replace(first, websocket_final=True)
    assert assembler.feed(first) is None
    bridge = _DiscardingBridge()

    with pytest.raises(RuntimeError, match="changed mid-message"):
        await _assemble_websocket_response_event(assembler, bridge, invalid)

    assert bridge.discarded == [invalid]
    assert assembler.discard_pending() == (first,)


@pytest.mark.parametrize(
    ("offered_headers", "response_headers"),
    [
        (
            ((b"sec-websocket-protocol", b"chat.v1, Chat.V2"),),
            (
                Header(b"sec-websocket-protocol", b"Chat.V2"),
                Header(b"Sec-WebSocket-Protocol", b"Chat.V2"),
            ),
        ),
        (
            ((b"sec-websocket-protocol", b"chat.v1, Chat.V2"),),
            (Header(b"sec-websocket-protocol", b"Chat.V2, chat.v1"),),
        ),
        (
            ((b"sec-websocket-protocol", b"chat.v1, Chat.V2"),),
            (Header(b"sec-websocket-protocol", b"bad protocol"),),
        ),
        (
            ((b"sec-websocket-protocol", b"chat.v1, Chat.V2"),),
            (Header(b"sec-websocket-protocol", b"other"),),
        ),
        (
            ((b"sec-websocket-protocol", b"chat.v1, bad protocol"),),
            (),
        ),
        (
            (
                (b"sec-websocket-protocol", b"chat.v1"),
                (b"Sec-WebSocket-Protocol", b"Chat.V2"),
            ),
            (),
        ),
        (
            ((b"sec-websocket-protocol", b"chat.v1, chat.v1"),),
            (),
        ),
    ],
)
def test_websocket_subprotocol_selection_rejects_ambiguity(
    offered_headers: tuple[tuple[bytes, bytes], ...],
    response_headers: tuple[Header, ...],
) -> None:
    with pytest.raises(ValueError, match="subprotocol"):
        offered = _websocket_subprotocol_tokens(offered_headers)
        _selected_websocket_subprotocol(
            offered=offered,
            response_headers=response_headers,
        )


@pytest.mark.parametrize(
    ("selected", "protocols"),
    [
        ("Chat.V2", ("chat.v1", "Chat.V2")),
        (None, ()),
    ],
)
async def test_public_websocket_handshake_returns_exact_selected_subprotocol(
    selected: str | None,
    protocols: tuple[str, ...],
) -> None:
    response_headers = (
        ((b"Sec-WebSocket-Protocol", selected.encode()),)
        if selected is not None
        else ()
    ) + (
        (b"Sec-WebSocket-Extensions", b"permessage-deflate"),
        (b"Set-Cookie", b"upstream=application"),
        (b"X-Upstream-Handshake", b"application"),
    )
    harness = await _websocket_harness(response_headers, response_frames=())
    try:
        websocket = await harness.client.ws_connect(
            "/socket",
            headers={
                "Host": "endpoint.services.example.net",
                "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
                "Origin": "https://endpoint.services.example.net",
            },
            protocols=protocols,
        )
        assert websocket.protocol == selected
        if selected is None:
            assert "Sec-WebSocket-Protocol" not in websocket._response.headers
        else:
            assert websocket._response.headers["Sec-WebSocket-Protocol"] == selected
        assert "Sec-WebSocket-Extensions" not in websocket._response.headers
        assert websocket._response.headers["Set-Cookie"] == "upstream=application"
        assert websocket._response.headers["X-Upstream-Handshake"] == "application"

        await websocket.close()
        await asyncio.wait_for(harness.transport.unbound.wait(), timeout=1)
        async with harness.operations.drain_coordinator.condition:
            await asyncio.wait_for(
                harness.operations.drain_coordinator.condition.wait_for(
                    lambda: not harness.operations.drain_coordinator.active
                ),
                timeout=1,
            )
        assert harness.operational_state.resources.active_exchanges == 0
        assert harness.operations.drain_coordinator.active == {}
        assert (
            harness.control_sessions.pool.sessions["gateway-session"].state.streams
            == {}
        )
        assert harness.transport.handlers == {}
    finally:
        await harness.client.close()


@pytest.mark.asyncio
async def test_public_websocket_preserves_application_headers_and_cookies() -> None:
    harness = await _websocket_harness(
        (
            (b"Sec-WebSocket-Protocol", b"chat.v1"),
            (b"Sec-WebSocket-Accept", b"upstream-hop-key"),
            (b"Content-Length", b"123"),
            (b"Set-Cookie", b"__Http-Azents-Runtime-Web=replace-platform"),
            (b"Set-Cookie", b"session=app; HttpOnly; Path=/"),
            (b"Set-Cookie", b"second=app; Path=/"),
            (b"X-App", b"first"),
            (b"X-App", b"second"),
            (b"Connection", b"Upgrade, X-Transport"),
            (b"X-Transport", b"hop-only"),
        ),
        response_frames=((WebSocketOpcode.TEXT, True, b"app-ready"),),
    )
    try:
        websocket = await harness.client.ws_connect(
            "/socket",
            headers={
                "Host": "endpoint.services.example.net",
                "Cookie": "__Http-Azents-Runtime-Web=opaque-secret; session=app",
                "Origin": "https://external.example.com",
                "Authorization": "Bearer app",
            },
            protocols=("chat.v1",),
        )
        assert websocket.protocol == "chat.v1"
        response = websocket._response
        assert response.headers.getall("Set-Cookie") == [
            "session=app; HttpOnly; Path=/",
            "second=app; Path=/",
        ]
        assert response.headers.getall("X-App") == ["first", "second"]
        assert response.headers["Sec-WebSocket-Accept"] != "upstream-hop-key"
        assert "Content-Length" not in response.headers
        assert "X-Transport" not in response.headers
        opened = next(
            item.open for item in harness.transport.sent if item.HasField("open")
        )
        forwarded = {
            item.name.lower(): item.value for item in opened.request_head.headers
        }
        assert forwarded[b"cookie"] == b"session=app"
        assert forwarded[b"origin"] == b"https://external.example.com"
        assert forwarded[b"authorization"] == b"Bearer app"
        assert b"sec-websocket-key" not in forwarded
        message = await asyncio.wait_for(websocket.receive(), timeout=1)
        assert message.data == "app-ready"
        await websocket.close()
    finally:
        await harness.client.close()


async def test_public_websocket_close_discards_incomplete_response_message() -> None:
    harness = await _websocket_harness(
        (),
        response_frames=(
            (WebSocketOpcode.TEXT, False, b"partial"),
            (WebSocketOpcode.CLOSE, True, b"\x03\xe8application close"),
        ),
    )
    try:
        websocket = await harness.client.ws_connect(
            "/socket",
            headers={
                "Host": "endpoint.services.example.net",
                "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
                "Origin": "https://endpoint.services.example.net",
            },
        )
        message = await asyncio.wait_for(websocket.receive(), timeout=1)
        assert message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}
        await asyncio.wait_for(harness.transport.unbound.wait(), timeout=1)

        payloads = [
            envelope.WhichOneof("payload") for envelope in harness.transport.sent
        ]
        assert "cancel" in payloads
        assert harness.operational_state.resources.application_buffer_bytes == 0
        assert harness.operational_state.resources.control_buffer_bytes == 0
        assert harness.transport.handlers == {}
    finally:
        await harness.client.close()


@pytest.mark.parametrize(
    "offered_headers",
    [
        (
            (b"Sec-WebSocket-Protocol", b"chat.v1"),
            (b"sec-websocket-protocol", b"Chat.V2"),
        ),
        ((b"Sec-WebSocket-Protocol", b"chat.v1, chat.v1"),),
    ],
)
async def test_public_websocket_rejects_ambiguous_offered_subprotocol_before_101(
    offered_headers: tuple[tuple[bytes, bytes], ...],
) -> None:
    harness = await _websocket_harness(
        ((b"Sec-WebSocket-Protocol", b"Chat.V2"),),
        response_frames=(),
    )
    server_port = harness.client.server.port
    assert server_port is not None
    reader, writer = await asyncio.open_connection("127.0.0.1", server_port)
    request_lines = [
        b"GET /socket HTTP/1.1",
        b"Host: endpoint.services.example.net",
        b"Cookie: __Http-Azents-Runtime-Web=opaque-secret",
        b"Origin: https://endpoint.services.example.net",
        b"Connection: Upgrade",
        b"Upgrade: websocket",
        b"Sec-WebSocket-Version: 13",
        b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
        *(name + b": " + value for name, value in offered_headers),
        b"",
        b"",
    ]
    try:
        writer.write(b"\r\n".join(request_lines))
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout=1)
        assert status_line.startswith(b"HTTP/1.1 409 ")
        await asyncio.wait_for(harness.transport.unbound.wait(), timeout=1)
        async with harness.operations.drain_coordinator.condition:
            await asyncio.wait_for(
                harness.operations.drain_coordinator.condition.wait_for(
                    lambda: not harness.operations.drain_coordinator.active
                ),
                timeout=1,
            )
        payloads = [
            envelope.WhichOneof("payload") for envelope in harness.transport.sent
        ]
        assert payloads == ["open", "cancel"]
        cancel = harness.transport.sent[-1]
        assert cancel.cancel.reason == (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
        )
        assert harness.operational_state.resources.active_exchanges == 0
        assert harness.operations.drain_coordinator.active == {}
        assert (
            harness.control_sessions.pool.sessions["gateway-session"].state.streams
            == {}
        )
        assert harness.transport.handlers == {}
    finally:
        writer.close()
        await writer.wait_closed()
        await harness.client.close()


@pytest.mark.parametrize(
    "response_headers",
    [
        (
            (b"Sec-WebSocket-Protocol", b"Chat.V2"),
            (b"sec-websocket-protocol", b"Chat.V2"),
        ),
        ((b"Sec-WebSocket-Protocol", b"bad protocol"),),
        ((b"Sec-WebSocket-Protocol", b"other"),),
    ],
)
async def test_public_websocket_rejects_invalid_selected_subprotocol_before_101(
    response_headers: tuple[tuple[bytes, bytes], ...],
) -> None:
    harness = await _websocket_harness(response_headers, response_frames=())
    try:
        with pytest.raises(WSServerHandshakeError) as rejected:
            await harness.client.ws_connect(
                "/socket",
                headers={
                    "Host": "endpoint.services.example.net",
                    "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
                    "Origin": "https://endpoint.services.example.net",
                },
                protocols=("chat.v1", "Chat.V2"),
            )
        assert rejected.value.status == 409
        await asyncio.wait_for(harness.transport.unbound.wait(), timeout=1)
        async with harness.operations.drain_coordinator.condition:
            await asyncio.wait_for(
                harness.operations.drain_coordinator.condition.wait_for(
                    lambda: not harness.operations.drain_coordinator.active
                ),
                timeout=1,
            )
        cancel = next(
            envelope
            for envelope in harness.transport.sent
            if envelope.WhichOneof("payload") == "cancel"
        )
        assert cancel.cancel.reason == (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
        )
        assert harness.operational_state.resources.active_exchanges == 0
        assert harness.operations.drain_coordinator.active == {}
        assert (
            harness.control_sessions.pool.sessions["gateway-session"].state.streams
            == {}
        )
        assert harness.transport.handlers == {}
    finally:
        await harness.client.close()


class _InputWebSocket(web.WebSocketResponse):
    def __init__(self, message: WSMessage) -> None:
        super().__init__()
        self.message: WSMessage | None = message

    def __aiter__(self) -> _InputWebSocket:
        return self

    async def __anext__(self) -> WSMessage:
        message = self.message
        if message is None:
            raise StopAsyncIteration
        self.message = None
        return message


class _BufferedInputBridge(RuntimeWebBrowserStreamBridge):
    def __init__(self, resources: RuntimeWebGatewayResourceTracker) -> None:
        self.resources = resources
        self.send_started = asyncio.Event()
        self.allow_send = asyncio.Event()
        self.frames: list[tuple[WebSocketOpcode, bool, bytes]] = []
        self.cancelled_reason: CloseReason | None = None
        self.finished = False

    async def send_websocket(
        self,
        *,
        opcode: WebSocketOpcode,
        final: bool,
        data: bytes,
    ) -> None:
        self.frames.append((opcode, final, data))
        self.send_started.set()
        await self.allow_send.wait()

    async def cancel(self, reason: CloseReason = CloseReason.CALLER) -> None:
        self.cancelled_reason = reason

    async def finish_request(self) -> None:
        self.finished = True


async def test_websocket_input_message_is_accounted_while_send_waits() -> None:
    resources = _operations()[1].resources
    data = b"x" * (512 * 1024)
    websocket = _InputWebSocket(WSMessage(WSMsgType.BINARY, data, ""))
    bridge = _BufferedInputBridge(resources)

    sending = asyncio.create_task(_send_websocket_frames(websocket, bridge))
    await bridge.send_started.wait()

    assert resources.application_buffer_bytes == len(data)
    bridge.allow_send.set()
    await sending
    assert bridge.frames == [
        (WebSocketOpcode.BINARY, False, data[: 256 * 1024]),
        (WebSocketOpcode.CONTINUATION, True, data[256 * 1024 :]),
    ]
    assert bridge.finished
    assert resources.application_buffer_bytes == 0


async def test_websocket_input_rejects_application_buffer_ceiling_without_leak() -> (
    None
):
    resources = RuntimeWebGatewayResourceTracker(
        RuntimeWebGatewayHardLimits(
            maximum_active_exchanges=1,
            maximum_application_buffer_bytes=10,
            maximum_control_buffer_bytes=1024,
            maximum_pending_tasks=4,
            maximum_scheduler_waiters=1,
            maximum_event_loop_lag_milliseconds=250,
            maximum_resident_memory_bytes=1024 * 1024 * 1024,
        )
    )
    websocket = _InputWebSocket(WSMessage(WSMsgType.BINARY, b"x" * 11, ""))
    bridge = _BufferedInputBridge(resources)

    with pytest.raises(
        RuntimeWebGatewayResourceExhausted,
        match="browser input buffer",
    ):
        await _send_websocket_frames(websocket, bridge)

    assert bridge.cancelled_reason is CloseReason.RESOURCE_EXHAUSTED
    assert bridge.frames == []
    assert not bridge.finished
    assert resources.application_buffer_bytes == 0
    assert resources.scheduler_waiters == 0


class _HttpTransport(_WebSocketTransport):
    async def send(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        copied = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
        copied.CopyFrom(envelope)
        self.sent.append(copied)
        handler = self.handlers.get(envelope.stream_id)
        if handler is None:
            return
        payload = envelope.WhichOneof("payload")
        if payload == "open":
            await handler.receive(self._accepted(envelope.stream_id))
        elif payload == "direction_end":
            head = self._response_head(envelope.stream_id)
            head.response_head.status = 200
            await handler.receive(head)
            end = self._base(envelope.stream_id)
            end.direction_end.direction = (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
            )
            end.direction_end.final_sequence = 0
            await handler.receive(end)
            terminal = self._base(envelope.stream_id)
            terminal.stream_end.SetInParent()
            await handler.receive(terminal)


@pytest.mark.parametrize(
    "method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
@pytest.mark.parametrize("body_mode", ["absent", "fixed", "chunked"])
@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://external.example.com",
        "https://endpoint.services.example.net",
    ],
)
@pytest.mark.parametrize(
    "destination_headers",
    [
        {},
        {"Service-Worker": "script"},
        {"Sec-Fetch-Dest": "serviceworker"},
        {"Sec-Fetch-Dest": "sharedworker"},
    ],
)
async def test_authenticated_application_methods_reach_transport(
    method: str,
    origin: str | None,
    destination_headers: dict[str, str],
    body_mode: str,
) -> None:
    operations, operational_state = _operations()
    proxy = _ControlSessions()
    transport = _HttpTransport(
        resources=operational_state.resources,
        response_headers=(
            (b"Access-Control-Allow-Origin", b"https://external.example.com"),
            (b"Access-Control-Allow-Headers", b"X-App-Token"),
            (b"Referrer-Policy", b"strict-origin-when-cross-origin"),
            (b"Cache-Control", b"private, max-age=60"),
            (b"Permissions-Policy", b"camera=(self)"),
            (b"Cross-Origin-Opener-Policy", b"unsafe-none"),
        ),
        response_frames=(),
    )
    await proxy.pool.register(
        identity=SessionIdentity(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            role=SessionPeerRole.GATEWAY,
            owner=None,
            session_nonce="nonce",
            deadline_at=_NOW + timedelta(minutes=5),
        ),
        profile=APPROVED_SESSION_PROFILE,
        transport=transport,
    )
    application = create_runtime_web_gateway_application(
        config=_CONFIG,
        settings=_SETTINGS,
        auth=_Auth(),
        authority=_HttpAuthority(),
        control_sessions=proxy,
        operations=operations,
        operational_state=operational_state,
    )
    client = TestClient(TestServer(application))
    await client.start_server()
    headers = {
        "Host": "endpoint.services.example.net",
        "Cookie": (
            "__Http-Azents-Runtime-Web=opaque-secret; session=application-session"
        ),
        "Sec-Fetch-Site": "cross-site",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-App-Token",
        "X-App-Token": "application-value",
    }
    if origin is not None:
        headers["Origin"] = origin
    headers.update(destination_headers)
    body = b"value=example"

    async def chunks() -> AsyncIterator[bytes]:
        yield body[:5]
        yield body[5:]

    try:
        response = await client.request(
            method,
            "/create",
            headers=headers,
            data=(
                chunks()
                if body_mode == "chunked"
                else body
                if body_mode == "fixed"
                else None
            ),
        )
        assert response.status == 200
        await response.read()
        for name, value in transport.response_headers:
            assert response.headers.getall(name.decode()) == [value.decode()]
        opened = next(item.open for item in transport.sent if item.HasField("open"))
        assert opened.request_head.method == method.encode()
        forwarded = {
            item.name.lower(): item.value for item in opened.request_head.headers
        }
        assert forwarded[b"x-app-token"] == b"application-value"
        assert forwarded[b"cookie"] == b"session=application-session"
        assert b"transfer-encoding" not in forwarded
        if body_mode == "chunked":
            assert b"content-length" not in forwarded
        else:
            assert forwarded[b"content-length"] == (
                str(len(body)).encode() if body_mode == "fixed" else b"0"
            )
        for name, value in destination_headers.items():
            assert forwarded[name.lower().encode()] == value.encode()
        if origin is None:
            assert b"origin" not in forwarded
        else:
            assert forwarded[b"origin"] == origin.encode()
        assert b"".join(
            item.data.data for item in transport.sent if item.HasField("data")
        ) == (b"" if body_mode == "absent" else body)
    finally:
        await client.close()


async def test_broker_auto_post_preserves_only_its_origin() -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    try:
        response = await client.post(
            "/bind",
            headers={
                "Host": "auth.services.example.net",
                "Origin": "https://app.example.com",
            },
            data={
                "initiation_id": "i" * 32,
                "return_target": "/catalog/item?tag=one&tag=two#details",
            },
        )
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "strict-origin"
        content_security_policy = response.headers["Content-Security-Policy"]
        assert "form-action https://app.example.com" in content_security_policy
        assert "frame-ancestors 'none'" in content_security_policy
        assert "script-src 'nonce-runtime-web'" in content_security_policy
        assert "https://app.example.com/runtime-web/auth/bound" in await response.text()
        assert (
            'name="return_target" value="/catalog/item?tag=one&amp;tag=two#details"'
            in await response.text()
        )
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "origin",
    [
        "https://source.attacker.example",
        "http://source.services.example.net",
        "https://nested.source.services.example.net",
        "https://source.services.example.net:8443",
        "https://source.services.example.net:80",
        "http://source.services.example.net:443",
    ],
)
async def test_application_preflight_requires_platform_identity(
    origin: str,
) -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    try:
        response = await client.options(
            "/api",
            headers={
                "Host": "endpoint.services.example.net",
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status == 401
        assert "Access-Control-Allow-Origin" not in response.headers
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        (
            {
                "Host": "endpoint.services.example.net",
                "Service-Worker": "script",
            },
            401,
        ),
        (
            {
                "Host": "endpoint.services.example.net",
                "User-Agent": "Mozilla/5.0 Firefox/143.0",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            401,
        ),
        (
            {
                "Host": "endpoint.services.example.net",
                "User-Agent": "Mozilla/5.0 Version/26.0 Safari/605.1.15",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            401,
        ),
    ],
)
async def test_rejected_requests_never_open_trusted_transport(
    headers: dict[str, str],
    expected_status: int,
) -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == expected_status
        assert response.headers["Cache-Control"] == "no-store"
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("user_agent", "upgrade", "expected_protocol"),
    [
        ("Mozilla/5.0 Firefox/143.0", None, StreamProtocol.HTTP),
        (
            "Mozilla/5.0 Version/26.0 Safari/605.1.15",
            "websocket",
            StreamProtocol.WEBSOCKET,
        ),
    ],
)
async def test_identity_reaches_authority_without_vendor_signals(
    user_agent: str,
    upgrade: str | None,
    expected_protocol: StreamProtocol,
) -> None:
    proxy = _ControlSessions()
    authority = _BrowserNeutralAuthority()
    client = await _client(proxy, authority=authority)
    headers = {
        "Host": "endpoint.services.example.net",
        "Cookie": "__Http-Azents-Runtime-Web=opaque-secret",
        "User-Agent": user_agent,
    }
    if upgrade is not None:
        headers["Upgrade"] = upgrade
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == 410
        assert authority.authorize_calls == [
            ("endpoint", "opaque-secret", expected_protocol)
        ]
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "cookies",
    [
        [
            (
                "Cookie",
                "__Http-Azents-Runtime-Web=first; __Http-Azents-Runtime-Web=second",
            )
        ],
        [
            (
                "Cookie",
                "__Http-Azents-Runtime-Web=same; __Http-Azents-Runtime-Web=same",
            )
        ],
        [
            ("Cookie", "__Http-Azents-Runtime-Web=first"),
            ("Cookie", "__Http-Azents-Runtime-Web=second"),
        ],
        [
            ("Cookie", "__Http-Azents-Runtime-Web=same"),
            ("Cookie", "__Http-Azents-Runtime-Web=same"),
        ],
    ],
)
async def test_duplicate_identity_cookie_is_rejected_before_authority_lookup(
    cookies: list[tuple[str, str]],
) -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    headers = CIMultiDict(cookies)
    headers["Host"] = "endpoint.services.example.net"
    try:
        response = await client.get("/api", headers=headers)
        assert response.status == 400
        assert not proxy.opened
    finally:
        await client.close()


@pytest.mark.parametrize(
    "cookies",
    [
        [
            (
                "Cookie",
                "__Host-Azents-Runtime-Web-Broker-Binding=first; "
                "__Host-Azents-Runtime-Web-Broker-Binding=second",
            )
        ],
        [
            (
                "Cookie",
                "__Host-Azents-Runtime-Web-Broker-Binding=same; "
                "__Host-Azents-Runtime-Web-Broker-Binding=same",
            )
        ],
        [
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=first"),
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=second"),
        ],
        [
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=same"),
            ("Cookie", "__Host-Azents-Runtime-Web-Broker-Binding=same"),
        ],
    ],
)
async def test_duplicate_broker_binding_cookie_is_rejected_before_ticket_redeem(
    cookies: list[tuple[str, str]],
) -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    headers = CIMultiDict(cookies)
    headers["Host"] = "auth.services.example.net"
    headers["Origin"] = "https://app.example.com"
    try:
        response = await client.post(
            "/redeem",
            headers=headers,
            data={"ticket": "ticket-secret", "return_target": "/"},
        )
        assert response.status == 400
        assert not proxy.opened
    finally:
        await client.close()


async def test_authentication_navigation_preserves_original_path_and_query() -> None:
    client = await _client(_ControlSessions())
    target = "/catalog/item?tag=one&tag=two"
    try:
        response = await client.get(
            target,
            headers={
                "Host": "endpoint.services.example.net",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
            allow_redirects=False,
        )
        assert response.status == 303
        location = urlsplit(response.headers["Location"])
        assert location.scheme == "https"
        assert location.netloc == "app.example.com"
        assert location.path == "/runtime-web/auth"
        assert parse_qs(location.query) == {
            "service_id": [_SERVICE.id],
            "return_to": [target],
        }
        assert location.fragment == ""
    finally:
        await client.close()


@pytest.mark.parametrize(
    "target", ["https://evil.test/", "//evil.test/", "/\\evil.test/", "/\nfoo"]
)
async def test_broker_rejects_unsafe_target_before_ticket_redemption(
    target: str,
) -> None:
    client = await _client(_ControlSessions())
    try:
        response = await client.post(
            "/redeem",
            headers={
                "Host": "auth.services.example.net",
                "Origin": "https://app.example.com",
                "Cookie": "__Host-Azents-Runtime-Web-Broker-Binding=broker-secret",
            },
            data={"ticket": "ticket-secret", "return_target": target},
        )
        assert response.status == 400
    finally:
        await client.close()
