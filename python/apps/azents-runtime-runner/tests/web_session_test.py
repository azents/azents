"""Inactive persistent Runtime Web Runner session tests."""

import asyncio
import base64
import datetime
import hashlib
from collections.abc import AsyncIterator

import pytest
from azents_runtime_control.grpc_runner_web_session_client import (
    EnvelopeHandler,
    FailureHandler,
    GrpcRunnerWebSessionClient,
)
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
)

from azents_runtime_runner.web_session import (
    RunnerWebLoopbackPool,
    RunnerWebLoopbackProtocolError,
    RunnerWebSessionManager,
    _hello,
)


def _offer(*, runner_generation: int = 4) -> RunnerSessionOffer:
    return RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id="boot-a",
            session_lease_id="lease-a",
            lease_generation=1,
            runtime_id="runtime-a",
            desired_generation=3,
            runner_generation=runner_generation,
        ),
        owner_replica_id="control-a",
        connect_address=(
            "runtime-control-pod-a.runtime-control-headless.azents.svc:8030"
        ),
        tls_server_name="runtime-control.internal",
        session_nonce="nonce-a",
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        deadline_at=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=10),
    )


def _accepted(
    offer: RunnerSessionOffer,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=offer.protocol_fingerprint,
        session_id=offer.owner.session_lease_id,
        peer_boot_id=offer.owner.owner_boot_id,
        owner_boot_id=offer.owner.owner_boot_id,
        session_lease_id=offer.owner.session_lease_id,
        lease_generation=offer.owner.lease_generation,
    )
    envelope.session_accepted.data_frame_bytes = 256 * 1024
    envelope.session_accepted.request_stream_window_bytes = 1024 * 1024
    envelope.session_accepted.response_stream_window_bytes = 1024 * 1024
    envelope.session_accepted.request_session_window_bytes = 8 * 1024 * 1024
    envelope.session_accepted.response_session_window_bytes = 8 * 1024 * 1024
    return envelope


async def _failure_handler() -> None:
    pass


def test_runner_hello_binds_exact_owner_generation_and_profile() -> None:
    offer = _offer()

    envelope = _hello(offer, "runner-boot-a")

    assert envelope.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
    assert envelope.owner_boot_id == "boot-a"
    assert envelope.session_lease_id == "lease-a"
    assert envelope.lease_generation == 1
    assert envelope.peer_boot_id == "runner-boot-a"
    assert envelope.hello.runtime_id == "runtime-a"
    assert envelope.hello.desired_generation == 3
    assert envelope.hello.runner_generation == 4
    assert envelope.hello.maximum_data_frame_bytes == 256 * 1024


async def test_loopback_pool_reuses_one_generation_scoped_session() -> None:
    pool = RunnerWebLoopbackPool(maximum_connections=8)
    await pool.start()
    http_pool = pool.http_pool
    await pool.start()
    assert pool.http_pool is http_pool

    await pool.close()
    assert pool.http_pool is None


async def test_loopback_websocket_rejects_registration_after_generation_close() -> None:
    handshake_received = asyncio.Event()
    permit_accept = asyncio.Event()

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_head = await reader.readuntil(b"\r\n\r\n")
        websocket_key = next(
            line.split(b":", 1)[1].strip()
            for line in request_head.split(b"\r\n")
            if line.lower().startswith(b"sec-websocket-key:")
        )
        accept = base64.b64encode(
            hashlib.sha1(
                websocket_key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
                usedforsecurity=False,
            ).digest()
        )
        handshake_received.set()
        await permit_accept.wait()
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = RunnerWebLoopbackPool(maximum_connections=8)
    try:
        await pool.start()
        opening = asyncio.create_task(
            pool.websocket(
                target=b"/socket",
                headers=(),
                port=port,
                timeout_seconds=1,
            )
        )
        await handshake_received.wait()
        await pool.close()
        permit_accept.set()
        with pytest.raises(RuntimeError, match="generation changed"):
            await opening
        assert not pool.websockets
    finally:
        permit_accept.set()
        await pool.close()
        server.close()
        await server.wait_closed()


async def test_loopback_http_preserves_raw_target_headers_and_connection() -> None:
    requests: list[bytes] = []
    connections = 0

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal connections
        connections += 1
        try:
            while True:
                try:
                    head = await reader.readuntil(b"\r\n\r\n")
                except asyncio.IncompleteReadError:
                    return
                requests.append(head)
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nX-Raw: \xff\r\n\r\nok"
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = RunnerWebLoopbackPool(maximum_connections=8)
    try:
        await pool.start()
        for _ in range(2):
            async with pool.request(
                method=b"GET",
                target=b"/%7euser?x=a%2fb",
                headers=(
                    (b"X-Order", b"first"),
                    (b"X-Raw", b"\xff"),
                    (b"X-Order", b"second"),
                ),
                port=port,
                body=None,
                timeout_seconds=1,
            ) as response:
                assert response.status == 200
                assert (b"X-Raw", b"\xff") in response.headers
                assert b"".join([chunk async for chunk in response.body]) == b"ok"
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()

    assert connections == 1
    assert len(requests) == 2
    for request in requests:
        assert request.startswith(b"GET /%7euser?x=a%2fb HTTP/1.1\r\n")
        assert b"\r\nHost: 127.0.0.1:" in request
        assert (b"\r\nX-Order: first\r\nX-Raw: \xff\r\nX-Order: second\r\n") in request


async def test_loopback_http_does_not_follow_redirects() -> None:
    requests = 0

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal requests
        await reader.readuntil(b"\r\n\r\n")
        requests += 1
        writer.write(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: /followed\r\n\r\n"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = RunnerWebLoopbackPool(maximum_connections=8)
    try:
        await pool.start()
        async with pool.request(
            method=b"GET",
            target=b"/redirect",
            headers=(),
            port=port,
            body=None,
            timeout_seconds=1,
        ) as response:
            assert response.status == 302
            assert b"".join([chunk async for chunk in response.body]) == b""
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()

    assert requests == 1


async def test_loopback_websocket_preserves_target_and_rejects_fragment() -> None:
    request_head = b""

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal request_head
        request_head = await reader.readuntil(b"\r\n\r\n")
        websocket_key = next(
            line.split(b":", 1)[1].strip()
            for line in request_head.split(b"\r\n")
            if line.lower().startswith(b"sec-websocket-key:")
        )
        accept = base64.b64encode(
            hashlib.sha1(
                websocket_key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
                usedforsecurity=False,
            ).digest()
        )
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: "
            + accept
            + b"\r\nSec-WebSocket-Protocol: Chat.V2\r\n\r\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = RunnerWebLoopbackPool(maximum_connections=8)
    try:
        await pool.start()
        websocket = await pool.websocket(
            target=b"/%7euser?x=a%2fb",
            headers=(
                (b"host", f"localhost:{port}".encode()),
                (b"sec-websocket-protocol", b"chat.v1, Chat.V2"),
                (b"X-Raw", b"\xff"),
            ),
            port=port,
            timeout_seconds=1,
        )
        assert (
            b"sec-websocket-protocol",
            b"Chat.V2",
        ) in websocket.response_headers
        await websocket.close()
        with pytest.raises(ValueError, match="origin form"):
            await pool.websocket(
                target=b"/path#fragment",
                headers=(),
                port=port,
                timeout_seconds=1,
            )
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()

    assert request_head.startswith(b"GET /%7euser?x=a%2fb HTTP/1.1\r\n")
    assert request_head.lower().count(b"\r\nhost:") == 1
    assert f"\r\nHost: 127.0.0.1:{port}\r\n".encode() in request_head
    assert request_head.lower().count(b"\r\nsec-websocket-protocol:") == 1
    assert b"\r\nSec-WebSocket-Protocol: chat.v1, Chat.V2\r\n" in request_head
    assert b"\r\nX-Raw: \xff\r\n" in request_head


async def test_loopback_websocket_rejects_unoffered_selected_subprotocol() -> None:
    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_head = await reader.readuntil(b"\r\n\r\n")
        websocket_key = next(
            line.split(b":", 1)[1].strip()
            for line in request_head.split(b"\r\n")
            if line.lower().startswith(b"sec-websocket-key:")
        )
        accept = base64.b64encode(
            hashlib.sha1(
                websocket_key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11",
                usedforsecurity=False,
            ).digest()
        )
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: "
            + accept
            + b"\r\nSec-WebSocket-Protocol: other\r\n\r\n"
        )
        await writer.drain()
        await reader.read()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = RunnerWebLoopbackPool(maximum_connections=1)
    try:
        await pool.start()
        with pytest.raises(RunnerWebLoopbackProtocolError, match="handshake"):
            await pool.websocket(
                target=b"/socket",
                headers=((b"sec-websocket-protocol", b"chat.v1"),),
                port=port,
                timeout_seconds=1,
            )
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()


async def test_runner_manager_rejects_obsolete_generation_without_connecting() -> None:
    calls = 0

    def client_factory(
        endpoint: str,
        offer: RunnerSessionOffer,
    ) -> GrpcRunnerWebSessionClient:
        nonlocal calls
        del endpoint, offer
        calls += 1
        raise AssertionError("obsolete offer must not create a client")

    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 5,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=8),
        client_factory=client_factory,
        outbound_resources=None,
    )

    async def handler(envelope: object) -> None:
        del envelope

    await manager.accept_offer(
        _offer(runner_generation=4),
        handler,
        _failure_handler,
    )

    assert calls == 0
    assert manager.client is None


@pytest.mark.parametrize("invalidate", (True, False))
async def test_runner_manager_closes_loopback_when_client_shutdown_fails(
    invalidate: bool,
) -> None:
    class FailingCloseClient(GrpcRunnerWebSessionClient):
        def __init__(self) -> None:
            pass

        async def close(self) -> None:
            raise RuntimeError("client shutdown failed")

    loopback = RunnerWebLoopbackPool(maximum_connections=8)
    await loopback.start()
    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 4,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=loopback,
        client_factory=None,
        outbound_resources=None,
    )
    manager.client = FailingCloseClient()

    with pytest.raises(RuntimeError, match="client shutdown failed"):
        if invalidate:
            await manager.invalidate_generation()
        else:
            await manager.close()

    assert loopback.http_pool is None
    assert loopback.active_generation is None


async def test_runner_manager_revalidates_generation_after_handshake() -> None:
    offer = _offer()
    generation = 4
    hello_seen = asyncio.Event()
    permit_accept = asyncio.Event()
    handled = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        hello_seen.set()
        await permit_accept.wait()
        yield _accepted(offer)

    def client_factory(
        endpoint: str,
        candidate: RunnerSessionOffer,
    ) -> GrpcRunnerWebSessionClient:
        assert endpoint == "runtime-control.internal:8030"
        assert candidate == offer
        return GrpcRunnerWebSessionClient(
            stream,
            runner_auth_token="runner-token",
            channel=None,
            outbound_resources=None,
        )

    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: generation,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=8),
        client_factory=client_factory,
        outbound_resources=None,
    )

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope
        handled.set()

    accepting = asyncio.create_task(
        manager.accept_offer(offer, handler, _failure_handler)
    )
    await hello_seen.wait()
    generation = 5
    permit_accept.set()

    with pytest.raises(ValueError, match="generation changed"):
        await accepting
    assert manager.client is None
    assert not handled.is_set()
    await manager.close()


async def test_runner_manager_rejects_stream_scoped_session_acceptance() -> None:
    offer = _offer()

    class _StreamScopedClient(GrpcRunnerWebSessionClient):
        def __init__(self) -> None:
            self.activated_flag = False
            self.closed = False

        async def start(
            self,
            hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
            handler: EnvelopeHandler,
            failure_handler: FailureHandler,
            *,
            timeout_seconds: float,
        ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
            del hello, handler, failure_handler, timeout_seconds
            accepted = _accepted(offer)
            accepted.stream_id = 7
            return accepted

        def activate(self) -> None:
            self.activated_flag = True

        async def close(self) -> None:
            self.closed = True

    client: _StreamScopedClient | None = None

    def client_factory(
        endpoint: str,
        candidate: RunnerSessionOffer,
    ) -> GrpcRunnerWebSessionClient:
        nonlocal client
        assert endpoint == "runtime-control.internal:8030"
        assert candidate == offer
        client = _StreamScopedClient()
        return client

    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 4,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=8),
        client_factory=client_factory,
        outbound_resources=None,
    )

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    with pytest.raises(ValueError, match="authority changed"):
        await manager.accept_offer(offer, handler, _failure_handler)
    assert manager.client is None
    assert manager.offer is None
    assert client is not None
    assert not client.activated_flag
    assert client.closed
    await manager.close()


async def test_runner_manager_ignores_consumed_offer_replay() -> None:
    offer = _offer()
    clients = 0

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _accepted(offer)
        await asyncio.Event().wait()

    def client_factory(
        endpoint: str,
        candidate: RunnerSessionOffer,
    ) -> GrpcRunnerWebSessionClient:
        nonlocal clients
        assert endpoint == "runtime-control.internal:8030"
        assert candidate == offer
        clients += 1
        return GrpcRunnerWebSessionClient(
            stream,
            runner_auth_token="runner-token",
            channel=None,
            outbound_resources=None,
        )

    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 4,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=8),
        client_factory=client_factory,
        outbound_resources=None,
    )

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    await manager.accept_offer(offer, handler, _failure_handler)
    accepted_client = manager.client
    await manager.accept_offer(offer, handler, _failure_handler)

    assert clients == 1
    assert manager.client is accepted_client
    await manager.close()


@pytest.mark.parametrize(
    "field",
    (
        "data_frame_bytes",
        "request_stream_window_bytes",
        "response_stream_window_bytes",
        "request_session_window_bytes",
        "response_session_window_bytes",
    ),
)
async def test_runner_manager_rejects_invalid_accepted_profile(field: str) -> None:
    offer = _offer()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        accepted = _accepted(offer)
        match field:
            case "data_frame_bytes":
                accepted.session_accepted.data_frame_bytes = 512 * 1024
            case "request_stream_window_bytes":
                accepted.session_accepted.request_stream_window_bytes = 0
            case "response_stream_window_bytes":
                accepted.session_accepted.response_stream_window_bytes = 0
            case "request_session_window_bytes":
                accepted.session_accepted.request_session_window_bytes = 0
            case "response_session_window_bytes":
                accepted.session_accepted.response_session_window_bytes = 0
        yield accepted

    def client_factory(
        endpoint: str,
        candidate: RunnerSessionOffer,
    ) -> GrpcRunnerWebSessionClient:
        assert endpoint == "runtime-control.internal:8030"
        assert candidate == offer
        return GrpcRunnerWebSessionClient(
            stream,
            runner_auth_token="runner-token",
            channel=None,
            outbound_resources=None,
        )

    manager = RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-boot-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 4,
        control_endpoint="runtime-control.internal:8030",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=8),
        client_factory=client_factory,
        outbound_resources=None,
    )

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    with pytest.raises(ValueError):
        await manager.accept_offer(offer, handler, _failure_handler)
    assert manager.client is None
    await manager.close()
