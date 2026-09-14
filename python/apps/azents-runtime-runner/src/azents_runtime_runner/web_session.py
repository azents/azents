"""Inactive persistent Runtime Web Runner session and pooled loopback client."""

import asyncio
import contextlib
import dataclasses
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import h11
import httpcore
from azents_runtime_control.grpc_runner_web_session_client import (
    GrpcRunnerWebSessionClient,
    RunnerWebEnvelopeResources,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
    SessionPeerRole,
    SessionProfile,
)
from wsproto import ConnectionType, WSConnection
from wsproto.events import (
    AcceptConnection,
    BytesMessage,
    Event,
    RejectConnection,
    Request,
    TextMessage,
)
from wsproto.utilities import LocalProtocolError as WsprotoLocalProtocolError
from wsproto.utilities import RemoteProtocolError as WsprotoRemoteProtocolError

_WEBSOCKET_HANDSHAKE_HEADERS = frozenset(
    {
        b"connection",
        b"host",
        b"upgrade",
        b"sec-websocket-accept",
        b"sec-websocket-extensions",
        b"sec-websocket-key",
        b"sec-websocket-protocol",
        b"sec-websocket-version",
    }
)
_WEBSOCKET_SUBPROTOCOL_HEADER = b"sec-websocket-protocol"
_TOKEN_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


@dataclasses.dataclass(frozen=True)
class LoopbackHttpResponse:
    """Byte-preserving loopback HTTP response stream."""

    status: int
    headers: tuple[tuple[bytes, bytes], ...]
    body: AsyncIterator[bytes]


class RunnerWebLoopbackProtocolError(ValueError):
    """Bound a local WebSocket protocol failure without exposing wire details."""


class RunnerWebSocket:
    """One raw-byte-handshaken loopback WebSocket connection."""

    def __init__(
        self,
        *,
        connection: WSConnection,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        response_headers: tuple[tuple[bytes, bytes], ...],
        on_close: Callable[["RunnerWebSocket"], None],
    ) -> None:
        self.connection = connection
        self.reader = reader
        self.writer = writer
        self.response_headers = response_headers
        self.on_close = on_close
        self.closed = False
        self.message_bytes = 0

    async def send(self, event: Event) -> None:
        """Send one typed WebSocket event without implicit control behavior."""
        if self.closed:
            raise RuntimeError("Runner WebSocket is closed")
        self.writer.write(self.connection.send(event))
        await self.writer.drain()

    async def receive(self) -> AsyncIterator[Event]:
        """Yield typed events while enforcing the assembled message limit."""
        while not self.closed:
            data = await self.reader.read(64 * 1024)
            self.connection.receive_data(data or None)
            for event in self.connection.events():
                if isinstance(event, (TextMessage, BytesMessage)):
                    if isinstance(event.data, str):
                        self.message_bytes += len(event.data.encode())
                    else:
                        self.message_bytes += len(event.data)
                    if self.message_bytes > 1024 * 1024:
                        raise ValueError(
                            "Runner WebSocket message exceeds the maximum size"
                        )
                    if event.message_finished:
                        self.message_bytes = 0
                yield event
            if not data:
                return

    async def close(self) -> None:
        """Close the loopback socket and release generation tracking."""
        if self.closed:
            return
        self.closed = True
        self.writer.close()
        await self.writer.wait_closed()
        self.on_close(self)


class RunnerWebLoopbackPool:
    """Own one generation-scoped pooled loopback HTTP client."""

    def __init__(
        self,
        *,
        maximum_connections: int,
    ) -> None:
        if maximum_connections <= 0:
            raise ValueError("Loopback connection limit must be positive")
        self.maximum_connections = maximum_connections
        self.http_pool: httpcore.AsyncConnectionPool | None = None
        self.websockets: set[RunnerWebSocket] = set()
        self.generation = 0
        self.active_generation: int | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the pooled byte HTTP client exactly once."""
        async with self.lock:
            if self.http_pool is not None:
                return
            self.http_pool = httpcore.AsyncConnectionPool(
                max_connections=self.maximum_connections,
                max_keepalive_connections=self.maximum_connections,
                http1=True,
                http2=False,
                retries=0,
            )
            self.generation += 1
            self.active_generation = self.generation

    async def close(self) -> None:
        """Close every pooled loopback connection on generation invalidation."""
        async with self.lock:
            http_pool = self.http_pool
            websockets = tuple(self.websockets)
            self.http_pool = None
            self.active_generation = None
            self.websockets.clear()
        closes: list[Awaitable[None]] = []
        if http_pool is not None:
            closes.append(http_pool.aclose())
        closes.extend(websocket.close() for websocket in websockets)
        if closes:
            await asyncio.gather(*closes)

    @contextlib.asynccontextmanager
    async def request(
        self,
        *,
        method: bytes,
        target: bytes,
        headers: tuple[tuple[bytes, bytes], ...],
        port: int,
        body: AsyncIterable[bytes] | bytes | None,
        timeout_seconds: float,
    ) -> AsyncIterator[LoopbackHttpResponse]:
        """Stream one exact byte-preserving numeric-loopback HTTP exchange."""
        if not 1 <= port <= 65_535:
            raise ValueError("Runtime Web port must be between 1 and 65535")
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web loopback timeout must be positive")
        if not method.isascii() or not target.isascii():
            raise ValueError("Runtime Web method and target must be ASCII")
        if not target.startswith(b"/") or target.startswith(b"//") or b"#" in target:
            raise ValueError("Runtime Web target must use origin form")
        pool = self.http_pool
        if pool is None:
            raise RuntimeError("Runner Web loopback pool is not started")
        content = body if isinstance(body, bytes) or body is None else body.__aiter__()
        url = httpcore.URL(
            scheme=b"http",
            host=b"127.0.0.1",
            port=port,
            target=target,
        )
        timeout = {
            "connect": timeout_seconds,
            "read": timeout_seconds,
            "write": timeout_seconds,
            "pool": timeout_seconds,
        }
        async with asyncio.timeout(timeout_seconds):
            async with pool.stream(
                method=method,
                url=url,
                headers=headers,
                content=content,
                extensions={"timeout": timeout},
            ) as response:
                yield LoopbackHttpResponse(
                    status=response.status,
                    headers=tuple(response.headers),
                    body=response.aiter_stream(),
                )

    async def websocket(
        self,
        *,
        target: bytes,
        headers: tuple[tuple[bytes, bytes], ...],
        port: int,
        timeout_seconds: float,
    ) -> RunnerWebSocket:
        """Open one raw-byte-preserving numeric-loopback WebSocket."""
        if not 1 <= port <= 65_535:
            raise ValueError("Runtime Web port must be between 1 and 65535")
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web loopback timeout must be positive")
        try:
            target_text = target.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Runtime Web target must be ASCII") from error
        if not target.startswith(b"/") or target.startswith(b"//") or b"#" in target:
            raise ValueError("Runtime Web target must use origin form")
        async with self.lock:
            generation = self.active_generation
            if generation is None:
                raise RuntimeError("Runner Web loopback pool is not started")
        normalized_headers = [
            (name, value)
            for name, value in headers
            if name.lower() not in _WEBSOCKET_HANDSHAKE_HEADERS
        ]
        subprotocols = _websocket_subprotocols(headers)
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(timeout_seconds):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                connection = WSConnection(ConnectionType.CLIENT)
                writer.write(
                    connection.send(
                        Request(
                            host=f"127.0.0.1:{port}",
                            target=target_text,
                            extensions=[],
                            subprotocols=subprotocols,
                            extra_headers=normalized_headers,
                        )
                    )
                )
                await writer.drain()
                while True:
                    data = await reader.read(64 * 1024)
                    if not data:
                        raise RuntimeError(
                            "Runner WebSocket closed before handshake acceptance"
                        )
                    connection.receive_data(data)
                    for event in connection.events():
                        if isinstance(event, AcceptConnection):
                            response_headers = tuple(event.extra_headers)
                            if event.subprotocol is not None:
                                if event.subprotocol not in subprotocols:
                                    raise RunnerWebLoopbackProtocolError(
                                        "Runner WebSocket selected protocol is invalid"
                                    )
                                response_headers = (
                                    *response_headers,
                                    (
                                        _WEBSOCKET_SUBPROTOCOL_HEADER,
                                        event.subprotocol.encode("ascii"),
                                    ),
                                )
                            websocket = RunnerWebSocket(
                                connection=connection,
                                reader=reader,
                                writer=writer,
                                response_headers=response_headers,
                                on_close=self.websockets.discard,
                            )
                            async with self.lock:
                                if self.active_generation != generation:
                                    await websocket.close()
                                    writer = None
                                    raise RuntimeError(
                                        "Runner Web loopback generation changed "
                                        "during WebSocket handshake"
                                    )
                                self.websockets.add(websocket)
                            return websocket
                        if isinstance(event, RejectConnection):
                            raise RuntimeError(
                                "Runner WebSocket handshake was rejected"
                            )
        except asyncio.CancelledError:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            raise
        except (
            h11.LocalProtocolError,
            WsprotoLocalProtocolError,
            WsprotoRemoteProtocolError,
        ):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            raise RunnerWebLoopbackProtocolError(
                "Runner WebSocket handshake is invalid"
            ) from None
        except Exception:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            raise


def _websocket_subprotocols(
    headers: tuple[tuple[bytes, bytes], ...],
) -> list[str]:
    """Parse ordered WebSocket subprotocol tokens from normalized headers."""
    protocols: list[str] = []
    seen: set[str] = set()
    for name, value in headers:
        if name.lower() != _WEBSOCKET_SUBPROTOCOL_HEADER:
            continue
        for raw_token in value.split(b","):
            token = raw_token.strip(b" \t")
            if not token or any(byte not in _TOKEN_BYTES for byte in token):
                raise RunnerWebLoopbackProtocolError(
                    "Runner WebSocket subprotocol token is invalid"
                )
            protocol = token.decode("ascii")
            if protocol in seen:
                raise RunnerWebLoopbackProtocolError(
                    "Runner WebSocket subprotocol is duplicated"
                )
            seen.add(protocol)
            protocols.append(protocol)
    return protocols


class RunnerWebSessionManager:
    """Own one inactive persistent Web session for the current Runner generation."""

    def __init__(
        self,
        *,
        runtime_id: str,
        runner_boot_id: str,
        accepted_desired_generation: Callable[[], int | None],
        accepted_generation: Callable[[], int | None],
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
        loopback: RunnerWebLoopbackPool,
        client_factory: Callable[[RunnerSessionOffer], GrpcRunnerWebSessionClient]
        | None,
        outbound_resources: RunnerWebEnvelopeResources | None,
    ) -> None:
        if not runtime_id or not runner_boot_id or not runner_auth_token:
            raise ValueError("Runtime and Runner authentication identity are required")
        self.runtime_id = runtime_id
        self.runner_boot_id = runner_boot_id
        self.accepted_desired_generation = accepted_desired_generation
        self.accepted_generation = accepted_generation
        self.runner_auth_token = runner_auth_token
        self.tls = tls
        self.allow_insecure = allow_insecure
        self.loopback = loopback
        self.client_factory = client_factory
        self.outbound_resources = outbound_resources
        self.client: GrpcRunnerWebSessionClient | None = None
        self.offer: RunnerSessionOffer | None = None
        self.consumed_offers: deque[tuple[OwnerSessionEpoch, str]] = deque(maxlen=64)
        self.consumed_offer_set: set[tuple[OwnerSessionEpoch, str]] = set()
        self.lock = asyncio.Lock()

    async def accept_offer(
        self,
        offer: RunnerSessionOffer,
        handler: Callable[
            [runtime_web_session_pb2.RuntimeWebSessionEnvelope], Awaitable[None]
        ],
        failure_handler: Callable[[], Awaitable[None]],
    ) -> bool:
        """Replace only with an exact current-generation non-expired offer."""
        if not self.offer_is_current(offer):
            return False
        async with self.lock:
            if not self.offer_is_current(offer):
                return False
            offer_key = (offer.owner, offer.session_nonce)
            if (
                offer_key in self.consumed_offer_set
                or self.offer is not None
                and self.offer.owner == offer.owner
            ):
                return False
            self._remember_consumed(offer_key)
            previous = self.client
            self.client = None
            self.offer = None
            client = (
                self.client_factory(offer)
                if self.client_factory is not None
                else GrpcRunnerWebSessionClient.from_endpoint(
                    offer.connect_address,
                    tls_server_name=offer.tls_server_name,
                    runner_auth_token=self.runner_auth_token,
                    tls=self.tls,
                    allow_insecure=self.allow_insecure,
                    outbound_resources=self.outbound_resources,
                )
            )
            if previous is not None:
                await previous.close()
            try:
                await self.loopback.start()
                remaining = (offer.deadline_at - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    raise ValueError("Runner Web session offer expired before connect")
                hello = _hello(offer, self.runner_boot_id)

                async def client_failed() -> None:
                    await failure_handler()
                    await self._detach_failed_client(client)

                accepted = await client.start(
                    hello,
                    handler,
                    client_failed,
                    timeout_seconds=remaining,
                )
                if (
                    accepted.stream_id != 0
                    or accepted.protocol_fingerprint != offer.protocol_fingerprint
                    or accepted.session_id != offer.owner.session_lease_id
                    or accepted.peer_boot_id != offer.owner.owner_boot_id
                    or accepted.owner_boot_id != offer.owner.owner_boot_id
                    or accepted.session_lease_id != offer.owner.session_lease_id
                    or accepted.lease_generation != offer.owner.lease_generation
                ):
                    raise ValueError("Runner Web session acceptance authority changed")
                _accepted_profile(
                    accepted,
                    maximum_data_frame_bytes=hello.hello.maximum_data_frame_bytes,
                )
                if not self.offer_is_current(offer):
                    raise ValueError(
                        "Runner Web session generation changed during acceptance"
                    )
                self.client = client
                self.offer = offer
                client.activate()
            except asyncio.CancelledError:
                self.client = None
                self.offer = None
                await client.close()
                raise
            except Exception:
                self.client = None
                self.offer = None
                await client.close()
                raise
            return True

    async def _detach_failed_client(
        self,
        client: GrpcRunnerWebSessionClient,
    ) -> None:
        """Drop only the exact failed session and its loopback generation."""
        async with self.lock:
            if self.client is not client:
                return
            self.client = None
            self.offer = None
        await self.loopback.close()

    async def invalidate_generation(self) -> None:
        """Close session and pooled loopback state before accepting replacement."""
        async with self.lock:
            client = self.client
            self.client = None
            self.offer = None
            self.consumed_offers.clear()
            self.consumed_offer_set.clear()
        try:
            if client is not None:
                await client.close()
        finally:
            await self.loopback.close()

    async def close(self) -> None:
        """Close the inactive manager without retaining application state."""
        async with self.lock:
            client = self.client
            self.client = None
            self.offer = None
        try:
            if client is not None:
                await client.close()
        finally:
            await self.loopback.close()

    def offer_is_current(self, offer: RunnerSessionOffer) -> bool:
        """Return whether an offer matches current Runtime generation authority."""
        desired_generation = self.accepted_desired_generation()
        generation = self.accepted_generation()
        return (
            offer.owner.runtime_id == self.runtime_id
            and desired_generation is not None
            and offer.owner.desired_generation == desired_generation
            and generation is not None
            and offer.owner.runner_generation == generation
            and offer.deadline_at > datetime.now(UTC)
            and offer.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
        )

    def _remember_consumed(
        self,
        offer_key: tuple[OwnerSessionEpoch, str],
    ) -> None:
        if len(self.consumed_offers) == self.consumed_offers.maxlen:
            expired = self.consumed_offers.popleft()
            self.consumed_offer_set.remove(expired)
        self.consumed_offers.append(offer_key)
        self.consumed_offer_set.add(offer_key)


def _hello(
    offer: RunnerSessionOffer,
    runner_boot_id: str,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    owner = offer.owner
    hello = runtime_web_session_pb2.RuntimeWebSessionHello(
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_RUNNER,
        runtime_id=owner.runtime_id,
        desired_generation=owner.desired_generation,
        runner_generation=owner.runner_generation,
        session_nonce=offer.session_nonce,
        maximum_data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
        request_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        ),
        response_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        ),
        request_session_window_bytes=(
            APPROVED_SESSION_PROFILE.request_session_window_bytes
        ),
        response_session_window_bytes=(
            APPROVED_SESSION_PROFILE.response_session_window_bytes
        ),
    )
    hello.deadline_at.FromDatetime(offer.deadline_at)
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=offer.protocol_fingerprint,
        session_id=owner.session_lease_id,
        peer_boot_id=runner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        hello=hello,
    )


def _accepted_profile(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    *,
    maximum_data_frame_bytes: int,
) -> SessionProfile:
    accepted = envelope.session_accepted
    profile = SessionProfile(
        data_frame_bytes=accepted.data_frame_bytes,
        request_stream_window_bytes=accepted.request_stream_window_bytes,
        response_stream_window_bytes=accepted.response_stream_window_bytes,
        request_session_window_bytes=accepted.request_session_window_bytes,
        response_session_window_bytes=accepted.response_session_window_bytes,
    )
    if profile.data_frame_bytes > maximum_data_frame_bytes:
        raise ValueError("Runner Web accepted frame size exceeds the Runner offer")
    return profile


assert SessionPeerRole.RUNNER.value == "runner"
