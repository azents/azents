"""Gateway HTTP security boundary tests."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import WSMessage, WSMsgType, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer
from azcommon.logging import RuntimeEnvironment
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import AbsoluteCreditWindow
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
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
from azents.repos.runtime_web.data import RuntimeWebCycle, RuntimeWebEndpoint
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
    RuntimeWebGatewayHardLimits,
    RuntimeWebGatewayHealth,
    RuntimeWebGatewayOperationalState,
    RuntimeWebGatewayOperationsCoordinator,
    RuntimeWebGatewayPressure,
    RuntimeWebGatewayResourceTracker,
)
from azents.runtime_web_gateway.server import (
    LinuxProcResidentMemorySampler,
    _response_is_sse,
    _selected_websocket_subprotocol,
    _send_websocket_frames,
    _websocket_data,
    _websocket_subprotocol_tokens,
    create_runtime_web_gateway_application,
    create_runtime_web_resident_memory_sampler,
)
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.web_session_bridge import (
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
_ENDPOINT = RuntimeWebEndpoint(
    id="e" * 32,
    workspace_id="w" * 32,
    agent_id="a" * 32,
    agent_session_id="s" * 32,
    port=8080,
    hostname_key="endpoint",
    label="Preview",
    authority_revision=1,
    close_barrier=0,
    current_pending_request_id=None,
    current_cycle_id=None,
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
                endpoint_id=_ENDPOINT.id,
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
    async def resolve_endpoint(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebEndpoint | None:
        return _ENDPOINT if hostname_key == "endpoint" else None

    async def source_endpoint_matches_root(
        self,
        *,
        source_hostname_key: str,
        target_endpoint: RuntimeWebEndpoint,
    ) -> bool:
        return source_hostname_key == "source" and target_endpoint.id == _ENDPOINT.id

    async def resolve_endpoint_by_id(
        self,
        *,
        endpoint_id: str,
    ) -> RuntimeWebEndpoint | None:
        del endpoint_id
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
            endpoint=_ENDPOINT,
            request=None,
            cycle=RuntimeWebCycle(
                id="c" * 32,
                endpoint_id=_ENDPOINT.id,
                request_id="r" * 32,
                approver_user_id="u" * 32,
                duration_seconds=300,
                approved_at=_NOW,
                expires_at=_NOW + timedelta(minutes=5),
                close_barrier=0,
                ended_at=None,
                end_reason=None,
                created_at=_NOW,
            ),
            runtime_id="t" * 32,
            desired_generation=1,
            runner_generation=1,
            active=True,
            runtime_ready=True,
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


class _WebSocketTransport:
    def __init__(
        self,
        *,
        resources: RuntimeWebGatewayResourceTracker,
        response_headers: tuple[tuple[bytes, bytes], ...],
    ) -> None:
        self.resources = resources
        self.response_headers = response_headers
        self.handlers: dict[int, RuntimeWebBrowserStreamBridge] = {}
        self.sent: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
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
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
        copied.CopyFrom(envelope)
        self.sent.append(copied)
        handler = self.handlers.get(envelope.stream_id)
        if handler is None:
            return
        payload = envelope.WhichOneof("payload")
        if payload == "open":
            await handler.receive(self._accepted(envelope.stream_id))
            await handler.receive(self._response_head(envelope.stream_id))
        elif payload == "direction_end":
            await handler.receive(self._reset(envelope.stream_id))

    @staticmethod
    def _base(stream_id: int) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="control-boot",
            stream_id=stream_id,
        )

    @classmethod
    def _accepted(
        cls,
        stream_id: int,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
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
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL
        )
        return envelope

    def _response_head(
        self,
        stream_id: int,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        envelope = self._base(stream_id)
        envelope.response_head.status = 101
        envelope.response_head.headers.extend(
            runtime_web_session_pb2.RuntimeWebSessionHeader(name=name, value=value)
            for name, value in self.response_headers
        )
        return envelope

    @classmethod
    def _reset(
        cls,
        stream_id: int,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        envelope = cls._base(stream_id)
        proto = runtime_web_session_pb2
        reason = proto.RUNTIME_WEB_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE
        envelope.reset.reason = reason
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
) -> _WebSocketHarness:
    operations, operational_state = _operations()
    control_sessions = _ControlSessions()
    transport = _WebSocketTransport(
        resources=operational_state.resources,
        response_headers=response_headers,
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


def _operations() -> tuple[
    RuntimeWebGatewayOperationsCoordinator,
    RuntimeWebGatewayOperationalState,
]:
    resources = RuntimeWebGatewayResourceTracker(
        RuntimeWebGatewayHardLimits(
            maximum_active_exchanges=4,
            maximum_application_buffer_bytes=1024 * 1024,
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
    return RuntimeWebGatewayOperationsCoordinator(state=state, drain=drain), state


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
        (b"Set-Cookie", b"upstream=forbidden"),
        (b"X-Upstream-Handshake", b"forbidden"),
    )
    harness = await _websocket_harness(response_headers)
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
        assert "Set-Cookie" not in websocket._response.headers
        assert "X-Upstream-Handshake" not in websocket._response.headers

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
    harness = await _websocket_harness(((b"Sec-WebSocket-Protocol", b"Chat.V2"),))
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
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
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
    harness = await _websocket_harness(response_headers)
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
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
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


async def test_valid_same_root_preflight_is_local_and_credentialed() -> None:
    proxy = _ControlSessions()
    client = await _client(proxy)
    try:
        response = await client.options(
            "/api",
            headers={
                "Host": "endpoint.services.example.net",
                "Origin": "https://source.services.example.net",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            },
        )
        assert response.status == 204
        assert (
            response.headers["Access-Control-Allow-Origin"]
            == "https://source.services.example.net"
        )
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert not proxy.opened
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
            data={"initiation_id": "i" * 32},
        )
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "strict-origin"
        content_security_policy = response.headers["Content-Security-Policy"]
        assert "form-action https://app.example.com" in content_security_policy
        assert "frame-ancestors 'none'" in content_security_policy
        assert "script-src 'nonce-runtime-web'" in content_security_policy
        assert "https://app.example.com/runtime-web/auth/bound" in await response.text()
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
async def test_preflight_rejects_origin_aliases_before_authority_lookup(
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
        assert response.status == 403
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
            403,
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
            data={"ticket": "ticket-secret"},
        )
        assert response.status == 400
        assert not proxy.opened
    finally:
        await client.close()
