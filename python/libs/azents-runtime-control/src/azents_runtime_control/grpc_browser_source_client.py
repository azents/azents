"""One non-replaying API Browser attachment over the common Control stream."""

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import grpc

from azents_runtime_control.browser_source_contract import (
    BrowserSourceCredentialRequest,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig, create_grpc_aio_channel
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    encode_stream_authority,
)
from azents_runtime_control.runtime_stream_flow import (
    AbsoluteCreditWindow,
    HierarchicalCredit,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    MAX_ENVELOPE_BYTES,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
    SessionIdentity,
    SessionPeerRole,
    WebSocketOpcode,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_stream_session_pb2_grpc import (
        RuntimeBrowserSourceSessionAsyncStub as _Stub,
    )
else:
    from azents_runtime_control.proto.runtime_stream_session_pb2_grpc import (
        RuntimeBrowserSourceSessionStub as _Stub,
    )

CredentialSupplier = Callable[[BrowserSourceCredentialRequest], Awaitable[str]]
_MAX_MESSAGE = 1024 * 1024


class BrowserSourceError(RuntimeError):
    """Browser source attachment failed without permission to replay input."""


class BrowserSourceUnavailable(BrowserSourceError):
    """Current transport, authority or resource cannot serve the attachment."""


class BrowserSourceProtocolError(BrowserSourceError):
    """The Browser source peer violated the closed protocol."""


class BrowserSourceScopeRevoked(BrowserSourceError):
    """Current user/resource authority no longer permits retaining displayed content."""

    def __init__(
        self,
        reason: Literal["unauthenticated", "access_revoked", "expired", "stale_target"],
    ) -> None:
        self.reason = reason
        super().__init__("Browser attachment authority is no longer current")


def _transport_error(error: grpc.RpcError) -> BrowserSourceError:
    code = error.code() if isinstance(error, grpc.aio.AioRpcError) else None
    if code == grpc.StatusCode.UNAUTHENTICATED:
        return BrowserSourceScopeRevoked("unauthenticated")
    if code == grpc.StatusCode.PERMISSION_DENIED:
        return BrowserSourceScopeRevoked("access_revoked")
    if code == grpc.StatusCode.DEADLINE_EXCEEDED:
        return BrowserSourceScopeRevoked("expired")
    return BrowserSourceUnavailable("Browser source transport is unavailable")


def _rejection_error(envelope: pb.RuntimeStreamSessionEnvelope) -> BrowserSourceError:
    kind = envelope.WhichOneof("payload")
    reason = (
        envelope.reset.reason
        if kind == "reset"
        else envelope.open_rejected.reason
        if kind == "open_rejected"
        else envelope.session_error.reason
        if kind == "session_error"
        else envelope.go_away.reason
        if kind == "go_away"
        else None
    )
    if reason == pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_AUTHORITY_REVOKED:
        return BrowserSourceScopeRevoked("access_revoked")
    if reason == pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_GENERATION_REPLACED:
        return BrowserSourceScopeRevoked("stale_target")
    if reason == pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_DEADLINE:
        return BrowserSourceScopeRevoked("expired")
    return BrowserSourceUnavailable("Browser source attachment ended")


@dataclass(frozen=True)
class BrowserSourceWebSocketMessage:
    opcode: WebSocketOpcode
    payload: bytes


def _opcode(value: pb.RuntimeStreamSessionWebSocketOpcode.ValueType) -> WebSocketOpcode:
    mapping = {
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_TEXT: WebSocketOpcode.TEXT,
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY: WebSocketOpcode.BINARY,
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CONTINUATION: (
            WebSocketOpcode.CONTINUATION
        ),
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PING: WebSocketOpcode.PING,
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PONG: WebSocketOpcode.PONG,
        pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CLOSE: WebSocketOpcode.CLOSE,
    }
    try:
        return mapping[value]
    except KeyError:
        raise BrowserSourceProtocolError("Browser source opcode is invalid") from None


def _wire_opcode(
    value: WebSocketOpcode,
) -> pb.RuntimeStreamSessionWebSocketOpcode.ValueType:
    return {
        WebSocketOpcode.TEXT: pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_TEXT,
        WebSocketOpcode.BINARY: pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY,
        WebSocketOpcode.CONTINUATION: (
            pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CONTINUATION
        ),
        WebSocketOpcode.PING: pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PING,
        WebSocketOpcode.PONG: pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_PONG,
        WebSocketOpcode.CLOSE: pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CLOSE,
    }[value]


class BrowserSourceConnection:
    """Own one exact source, one stream, bounded credit and no reconnect queue."""

    def __init__(
        self,
        *,
        call: grpc.aio.StreamStreamCall[
            pb.RuntimeStreamSessionEnvelope, pb.RuntimeStreamSessionEnvelope
        ],
        identity: SessionIdentity,
        authority: BrowserStreamAuthority,
    ) -> None:
        self.call = call
        self.identity = identity
        self.authority = authority
        profile = APPROVED_SESSION_PROFILE
        self.credit = HierarchicalCredit(
            stream=AbsoluteCreditWindow(
                initial_bytes=profile.request_stream_window_bytes,
                maximum_bytes=profile.request_stream_window_bytes,
            ),
            session=AbsoluteCreditWindow(
                initial_bytes=profile.request_session_window_bytes,
                maximum_bytes=profile.request_session_window_bytes,
            ),
        )
        self.changed = asyncio.Condition()
        self.write_lock = asyncio.Lock()
        self.message_lock = asyncio.Lock()
        self.messages: asyncio.Queue[
            BrowserSourceWebSocketMessage | BrowserSourceError
        ] = asyncio.Queue(maxsize=2)
        self.send_sequence = 0
        self.receive_sequence = 0
        self.received = 0
        self.consumed = 0
        self.closed = False
        self.terminal_error: BrowserSourceError | None = None
        self.on_close: Callable[[], None] | None = None
        self.control_boot_id: str | None = None
        self.reader: asyncio.Task[None] | None = None

    def envelope(self) -> pb.RuntimeStreamSessionEnvelope:
        return pb.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            session_id=self.identity.session_id,
            peer_boot_id=self.identity.peer_boot_id,
            stream_id=1,
        )

    async def send(self, envelope: pb.RuntimeStreamSessionEnvelope) -> None:
        if self.terminal_error is not None:
            raise self.terminal_error
        if self.closed:
            raise BrowserSourceUnavailable("Browser source is closed")
        if (
            self.closed
            or (
                envelope.session_id,
                envelope.peer_boot_id,
                envelope.protocol_fingerprint,
            )
            != (
                self.identity.session_id,
                self.identity.peer_boot_id,
                RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            )
            or envelope.stream_id not in {0, 1}
            or envelope.WhichOneof("payload")
            not in {
                "websocket",
                "window_update",
                "cancel",
                "heartbeat",
                "heartbeat_ack",
            }
        ):
            raise BrowserSourceProtocolError("Browser source send scope is invalid")
        async with self.write_lock:
            try:
                await self.call.write(envelope)
            except grpc.RpcError as error:
                raise _transport_error(error) from None
            except asyncio.InvalidStateError:
                raise BrowserSourceUnavailable(
                    "Browser source transport is unavailable"
                ) from None

    async def receive(self) -> pb.RuntimeStreamSessionEnvelope:
        """Read an envelope; the live convenience receiver owns reads after setup."""
        try:
            envelope = await self.call.read()
        except grpc.RpcError as error:
            raise _transport_error(error) from None
        if envelope is grpc.aio.EOF:
            raise BrowserSourceUnavailable("Browser source connection ended")
        if not isinstance(envelope, pb.RuntimeStreamSessionEnvelope):
            raise BrowserSourceProtocolError("Browser source envelope is invalid")
        if (
            not 0 < envelope.ByteSize() <= MAX_ENVELOPE_BYTES
            or envelope.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
            or envelope.session_id != self.identity.session_id
            or (
                self.control_boot_id is not None
                and envelope.peer_boot_id != self.control_boot_id
            )
            or envelope.stream_id not in {0, 1}
        ):
            raise BrowserSourceProtocolError("Browser source response scope is invalid")
        return envelope

    async def send_websocket(self, *, opcode: WebSocketOpcode, payload: bytes) -> None:
        if (
            opcode
            not in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.PING,
                WebSocketOpcode.PONG,
                WebSocketOpcode.CLOSE,
            }
            or len(payload) > _MAX_MESSAGE
            or (
                opcode
                in {WebSocketOpcode.PING, WebSocketOpcode.PONG, WebSocketOpcode.CLOSE}
                and len(payload) > 125
            )
        ):
            raise BrowserSourceProtocolError("Browser source message is invalid")
        async with self.message_lock:
            chunks = [
                payload[i : i + APPROVED_SESSION_PROFILE.data_frame_bytes]
                for i in range(
                    0, len(payload), APPROVED_SESSION_PROFILE.data_frame_bytes
                )
            ] or [b""]
            for index, chunk in enumerate(chunks):
                if chunk:
                    size = len(chunk)
                    async with self.changed:
                        await self.changed.wait_for(
                            lambda size=size: (
                                self.closed or self.credit.available_bytes >= size
                            )
                        )
                        if self.terminal_error is not None:
                            raise self.terminal_error
                        if self.closed:
                            raise BrowserSourceUnavailable("Browser source is closed")
                        self.credit.reserve(len(chunk))
                self.send_sequence += 1
                envelope = self.envelope()
                envelope.frame_sequence = self.send_sequence
                envelope.websocket.CopyFrom(
                    pb.RuntimeStreamSessionWebSocketFrame(
                        direction=pb.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST,
                        opcode=_wire_opcode(
                            opcode if index == 0 else WebSocketOpcode.CONTINUATION
                        ),
                        final=index == len(chunks) - 1,
                        data=chunk,
                    )
                )
                await self.send(envelope)

    async def receive_websocket(self) -> BrowserSourceWebSocketMessage:
        if self.terminal_error is not None:
            raise self.terminal_error
        message = await self.messages.get()
        if self.terminal_error is not None:
            raise self.terminal_error
        if isinstance(message, BrowserSourceError):
            raise message
        self.consumed += len(message.payload)
        if message.payload:
            envelope = self.envelope()
            envelope.window_update.CopyFrom(
                pb.RuntimeStreamSessionWindowUpdate(
                    direction=pb.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
                    stream_consumed_total=self.consumed,
                    session_consumed_total=self.consumed,
                )
            )
            await self.send(envelope)
        return message

    async def _read_messages(self) -> None:
        data = bytearray()
        active: WebSocketOpcode | None = None
        try:
            while True:
                async with asyncio.timeout(
                    max(
                        0,
                        (
                            self.authority.transport_deadline_at - datetime.now(UTC)
                        ).total_seconds(),
                    )
                ):
                    envelope = await self.receive()
                kind = envelope.WhichOneof("payload")
                if kind == "window_update":
                    update = envelope.window_update
                    if update.direction != pb.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST:
                        raise BrowserSourceProtocolError(
                            "Browser source credit direction is invalid"
                        )
                    async with self.changed:
                        self.credit.update_consumed(
                            stream_consumed_total=update.stream_consumed_total,
                            session_consumed_total=update.session_consumed_total,
                        )
                        self.changed.notify_all()
                    continue
                if kind in {
                    "reset",
                    "open_rejected",
                    "session_error",
                    "stream_end",
                    "go_away",
                }:
                    raise _rejection_error(envelope)
                if kind == "heartbeat":
                    response = self.envelope()
                    response.stream_id = 0
                    response.heartbeat_ack.monotonic_sequence = (
                        envelope.heartbeat.monotonic_sequence
                    )
                    await self.send(response)
                    continue
                if kind == "heartbeat_ack":
                    continue
                if kind == "response_head":
                    if envelope.response_head.status != 101:
                        raise BrowserSourceUnavailable(
                            "Browser consumer is unavailable"
                        )
                    continue
                if kind != "websocket":
                    raise BrowserSourceProtocolError(
                        "Browser source response is invalid"
                    )
                frame = envelope.websocket
                if (
                    envelope.stream_id != 1
                    or frame.direction != pb.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
                    or envelope.frame_sequence != self.receive_sequence + 1
                    or len(frame.data) > APPROVED_SESSION_PROFILE.data_frame_bytes
                ):
                    raise BrowserSourceProtocolError("Browser source frame is invalid")
                self.receive_sequence += 1
                self.received += len(frame.data)
                if (
                    self.received - self.consumed
                    > APPROVED_SESSION_PROFILE.response_stream_window_bytes
                ):
                    raise BrowserSourceProtocolError("Browser response exceeds credit")
                opcode = _opcode(frame.opcode)
                if opcode in {
                    WebSocketOpcode.PING,
                    WebSocketOpcode.PONG,
                    WebSocketOpcode.CLOSE,
                }:
                    if not frame.final or len(frame.data) > 125:
                        raise BrowserSourceProtocolError(
                            "Browser control frame is invalid"
                        )
                    self.consumed += len(frame.data)
                    if opcode is WebSocketOpcode.CLOSE:
                        raise BrowserSourceUnavailable("Browser consumer closed")
                    if opcode is WebSocketOpcode.PING:
                        await self.send_websocket(
                            opcode=WebSocketOpcode.PONG, payload=frame.data
                        )
                    continue
                if opcode is not WebSocketOpcode.CONTINUATION:
                    if active is not None:
                        raise BrowserSourceProtocolError("Browser fragments overlap")
                    active = opcode
                elif active is None:
                    raise BrowserSourceProtocolError("Browser continuation is orphaned")
                data.extend(frame.data)
                if len(data) > _MAX_MESSAGE:
                    raise BrowserSourceProtocolError("Browser message is too large")
                if frame.final:
                    assert active is not None
                    await self.messages.put(
                        BrowserSourceWebSocketMessage(active, bytes(data))
                    )
                    data.clear()
                    active = None
        except asyncio.CancelledError:
            raise
        except (BrowserSourceError, ValueError, TimeoutError) as exc:
            error = (
                exc
                if isinstance(exc, BrowserSourceError)
                else BrowserSourceScopeRevoked("expired")
                if isinstance(exc, TimeoutError)
                else BrowserSourceProtocolError("Browser source protocol failed")
            )
            self.terminal_error = error
            self.closed = True
            self.call.cancel()
            async with self.changed:
                self.changed.notify_all()
            while not self.messages.empty():
                self.messages.get_nowait()
            self.messages.put_nowait(error)

    async def close(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.closed = True
        self.call.cancel()
        async with self.changed:
            self.changed.notify_all()
        if self.reader is not None:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)


class GrpcBrowserSourceClient:
    """Existing Control endpoint/TLS; dedicated API-purpose RPC and no retries."""

    def __init__(
        self, *, channel: grpc.aio.Channel, credential_supplier: CredentialSupplier
    ) -> None:
        self.channel = channel
        self.stub = _Stub(channel)
        self.credential_supplier = credential_supplier
        self.connections: set[BrowserSourceConnection] = set()

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        credential_supplier: CredentialSupplier,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcBrowserSourceClient":
        return cls(
            channel=create_grpc_aio_channel(
                endpoint, tls=tls, allow_insecure=allow_insecure
            ),
            credential_supplier=credential_supplier,
        )

    async def connect(
        self, *, authority: BrowserStreamAuthority
    ) -> BrowserSourceConnection:
        call = self.stub.Connect()
        identity = SessionIdentity(
            session_id=secrets.token_hex(16),
            peer_boot_id=secrets.token_hex(16),
            role=SessionPeerRole.API_BROWSER,
            owner=None,
            session_nonce=secrets.token_hex(16),
            deadline_at=authority.transport_deadline_at,
        )
        connection = BrowserSourceConnection(
            call=call, identity=identity, authority=authority
        )
        self.connections.add(connection)
        connection.on_close = lambda: self.connections.discard(connection)
        try:
            async with asyncio.timeout(10):
                challenge_envelope = await call.read()
                if (
                    not isinstance(challenge_envelope, pb.RuntimeStreamSessionEnvelope)
                    or challenge_envelope.WhichOneof("payload")
                    != "browser_source_challenge"
                    or challenge_envelope.protocol_fingerprint
                    != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
                ):
                    raise BrowserSourceProtocolError(
                        "Browser source challenge is invalid"
                    )
                challenge = challenge_envelope.browser_source_challenge
                profile = APPROVED_SESSION_PROFILE
                hello = pb.RuntimeStreamSessionEnvelope(
                    protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
                    session_id=identity.session_id,
                    peer_boot_id=identity.peer_boot_id,
                    hello=pb.RuntimeStreamSessionHello(
                        role=pb.RUNTIME_STREAM_SESSION_PEER_ROLE_API_BROWSER,
                        session_nonce=identity.session_nonce,
                        maximum_data_frame_bytes=profile.data_frame_bytes,
                        request_stream_window_bytes=profile.request_stream_window_bytes,
                        response_stream_window_bytes=profile.response_stream_window_bytes,
                        request_session_window_bytes=profile.request_session_window_bytes,
                        response_session_window_bytes=profile.response_session_window_bytes,
                    ),
                )
                hello.hello.deadline_at.FromDatetime(authority.transport_deadline_at)
                opened = connection.envelope()
                opened.open.CopyFrom(
                    pb.RuntimeStreamSessionOpen(
                        authority=encode_stream_authority(authority),
                        request_head=pb.RuntimeStreamSessionRequestHead(
                            protocol=pb.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET,
                            method=b"GET",
                            target=b"/browser",
                        ),
                    )
                )
                request = BrowserSourceCredentialRequest(
                    challenge.nonce,
                    challenge.control_boot_id,
                    challenge.deadline_at.ToDatetime(tzinfo=UTC),
                    hello,
                    opened,
                )
                request.validate(datetime.now(UTC))
                credential = await self.credential_supplier(request)
                proof = pb.RuntimeStreamSessionEnvelope(
                    protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
                    browser_source_proof=pb.RuntimeBrowserSourceProof(
                        hello=hello, admitted_open=opened, credential=credential
                    ),
                )
                await call.write(proof)
                connection.control_boot_id = challenge.control_boot_id
                accepted = await connection.receive()
                if (
                    accepted.WhichOneof("payload") != "session_accepted"
                    or accepted.stream_id != 0
                ):
                    raise BrowserSourceUnavailable("Browser source admission failed")
                opened_response = await connection.receive()
                if opened_response.WhichOneof("payload") != "open_accepted":
                    raise _rejection_error(opened_response)
                connection.reader = asyncio.create_task(connection._read_messages())
                return connection
        except grpc.RpcError as error:
            await connection.close()
            raise _transport_error(error) from None
        except TimeoutError:
            await connection.close()
            raise BrowserSourceScopeRevoked("expired") from None
        except BaseException:
            await connection.close()
            raise

    async def close(self) -> None:
        await asyncio.gather(
            *(connection.close() for connection in tuple(self.connections))
        )
        await self.channel.close()
