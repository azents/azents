"""Replacement Runtime Web logical-stream dispatch for the Runtime Runner."""

# Protobuf generated enum names are intentionally explicit at the wire boundary.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import h11
import httpcore
from azents_runtime_control.grpc_runner_web_session_client import (
    GrpcRunnerWebSessionClient,
)
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import (
    AbsoluteCreditWindow,
    HierarchicalCredit,
)
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    Header,
    RequestHead,
    RunnerSessionOffer,
    StreamAuthority,
    StreamProtocol,
    WebSocketOpcode,
)
from wsproto.events import (
    BytesMessage,
    CloseConnection,
    Event,
    Ping,
    Pong,
    TextMessage,
)
from wsproto.utilities import LocalProtocolError as WsprotoLocalProtocolError
from wsproto.utilities import RemoteProtocolError as WsprotoRemoteProtocolError

from azents_runtime_runner.web_session import (
    RunnerWebLoopbackProtocolError,
    RunnerWebSessionManager,
    RunnerWebSocket,
)

_LOGGER = logging.getLogger(__name__)
_MAX_UINT64 = (1 << 64) - 1
_IGNORED_TOMBSTONE_PAYLOADS = frozenset(
    {
        "window_update",
        "direction_end",
        "cancel",
        "reset",
        "stream_end",
    }
)


@dataclasses.dataclass
class _Stream:
    offer: RunnerSessionOffer
    client: GrpcRunnerWebSessionClient
    authority: StreamAuthority
    head: RequestHead
    inbound: asyncio.Queue[runtime_web_session_pb2.RuntimeWebSessionEnvelope]
    response_credit: HierarchicalCredit
    credit_changed: asyncio.Condition
    task: asyncio.Task[None] | None = None
    request_sequence: int = 0
    request_consumed_total: int = 0
    close_reason: CloseReason = CloseReason.CALLER


class RunnerWebSessionDispatcher:
    """Translate one persistent Runner session into bounded loopback exchanges."""

    def __init__(self, manager: RunnerWebSessionManager) -> None:
        self.manager = manager
        self.streams: dict[int, _Stream] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()
        self.last_stream_id = 0
        self.request_session_consumed_total = 0
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
            maximum_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        )
        self.response_credit_changed = asyncio.Condition()
        self.offer_lock = asyncio.Lock()
        self.accepting_envelopes = False
        self.accepting_streams = False
        self.drain_task: asyncio.Task[None] | None = None

    async def handle_offer(self, offer: RunnerSessionOffer) -> None:
        """Activate the sole exact offer with this dispatcher."""
        async with self.offer_lock:
            if not self.manager.offer_is_current(offer):
                return
            previous_accepting_envelopes = self.accepting_envelopes
            previous_accepting_streams = self.accepting_streams
            self.accepting_envelopes = False
            try:
                current = self.manager.offer
                if current is None or current.owner != offer.owner:
                    if current is not None:
                        await self.close(reason=CloseReason.GENERATION_REPLACED)
                    self._reset_session_flow()
                accepted = await self.manager.accept_offer(
                    offer,
                    self,
                    self.fail_transport,
                )
                if accepted:
                    self.accepting_envelopes = True
                    self.accepting_streams = True
                else:
                    self.accepting_envelopes = previous_accepting_envelopes
                    self.accepting_streams = previous_accepting_streams
            except asyncio.CancelledError:
                raise
            except Exception:
                self.accepting_envelopes = False
                raise

    async def __call__(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        offer = self.manager.offer
        client = self.manager.client
        if (
            not self.accepting_envelopes
            or offer is None
            or client is None
            or not _matches_offer(envelope, offer)
        ):
            raise ValueError("Runner Web envelope authority is stale")
        payload = envelope.WhichOneof("payload")
        if payload == "heartbeat":
            response = self._envelope(offer=offer)
            response.heartbeat_ack.monotonic_sequence = (
                envelope.heartbeat.monotonic_sequence
            )
            await self._send(response, client=client)
            return
        if payload == "go_away":
            self.accepting_streams = False
            deadline = envelope.go_away.drain_deadline_at.ToDatetime(tzinfo=UTC)
            if self.drain_task is None or self.drain_task.done():
                self.drain_task = asyncio.create_task(
                    self._drain(deadline),
                    name="runtime-web-runner-drain",
                )
            return
        if payload == "open":
            if not self.accepting_streams:
                await self._reset(
                    envelope.stream_id,
                    CloseReason.SERVICE_DRAIN,
                )
                return
            await self._open(envelope)
            return
        stream = self.streams.get(envelope.stream_id)
        if stream is None:
            if envelope.stream_id in self.tombstone_set:
                if payload in _IGNORED_TOMBSTONE_PAYLOADS:
                    return
                raise ValueError("Runner Web tombstoned stream received new data")
            raise ValueError("Runner Web stream is unknown")
        if payload == "window_update":
            if (
                envelope.window_update.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            ):
                raise ValueError("Runner Web response credit direction is invalid")
            async with self.response_credit_changed:
                stream.response_credit.update_consumed(
                    stream_consumed_total=envelope.window_update.stream_consumed_total,
                    session_consumed_total=envelope.window_update.session_consumed_total,
                )
                self.response_credit_changed.notify_all()
            return
        if payload in {"cancel", "reset"}:
            if stream.task is not None:
                stream.task.cancel()
            return
        if payload not in {"data", "direction_end", "websocket"}:
            raise ValueError("Runner Web stream frame is invalid")
        await stream.inbound.put(envelope)

    async def close(
        self,
        *,
        reason: CloseReason = CloseReason.SERVICE_DRAIN,
    ) -> None:
        """Cancel every stream without preserving application outcomes."""
        self.accepting_envelopes = False
        self.accepting_streams = False
        drain_task = self.drain_task
        self.drain_task = None
        if (
            drain_task is not None
            and drain_task is not asyncio.current_task()
            and not drain_task.done()
        ):
            drain_task.cancel()
        active = tuple(self.streams.values())
        tasks = tuple(stream.task for stream in active if stream.task is not None)
        for stream in active:
            stream.close_reason = reason
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.streams.clear()
        self.tombstones.clear()
        self.tombstone_set.clear()
        self.last_stream_id = 0

    async def fail_transport(self) -> None:
        """Fail all old-epoch work when the independent gRPC receiver ends."""
        await self.close(reason=CloseReason.TRANSPORT_UNAVAILABLE)

    async def _drain(self, deadline: datetime) -> None:
        """Wait for active work until the peer deadline, then reset the remainder."""
        tasks = tuple(
            stream.task for stream in self.streams.values() if stream.task is not None
        )
        remaining = max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        if tasks and remaining > 0:
            _, pending = await asyncio.wait(tasks, timeout=remaining)
        else:
            pending = set(tasks)
        for task in pending:
            stream = next(
                (
                    candidate
                    for candidate in self.streams.values()
                    if candidate.task is task
                ),
                None,
            )
            if stream is not None:
                stream.close_reason = CloseReason.SERVICE_DRAIN
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _open(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        stream_id = envelope.stream_id
        self._claim_stream_id(stream_id)
        authority = _authority(envelope.open.authority)
        head = _head(envelope.open.request_head)
        offer = self.manager.offer
        client = self.manager.client
        if offer is None or client is None:
            raise RuntimeError("Runner Web session epoch is absent")
        if (
            authority.runtime_id != self.manager.runtime_id
            or authority.desired_generation
            != self.manager.accepted_desired_generation()
            or authority.runner_generation != self.manager.accepted_generation()
        ):
            await self._reset(stream_id, CloseReason.GENERATION_REPLACED)
            return
        stream = _Stream(
            offer=offer,
            client=client,
            authority=authority,
            head=head,
            inbound=asyncio.Queue(maxsize=8),
            response_credit=HierarchicalCredit(
                stream=AbsoluteCreditWindow(
                    initial_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                    maximum_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                ),
                session=self.response_session_credit,
            ),
            credit_changed=self.response_credit_changed,
        )
        self.streams[stream_id] = stream
        accepted = self._envelope(stream_id=stream_id, offer=offer)
        accepted.open_accepted.data_frame_bytes = (
            APPROVED_SESSION_PROFILE.data_frame_bytes
        )
        accepted.open_accepted.request_credit_bytes = (
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        )
        accepted.open_accepted.response_credit_bytes = (
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        )
        accepted.open_accepted.route_path = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL
        )
        await self._send(accepted, client=client)
        stream.task = asyncio.create_task(
            self._run(stream_id, stream),
            name=f"runtime-web-runner-stream:{stream_id}",
        )

    async def _run(self, stream_id: int, stream: _Stream) -> None:
        try:
            if stream.head.protocol is StreamProtocol.HTTP:
                await self._http(stream_id, stream)
            else:
                await self._websocket(stream_id, stream)
        except asyncio.CancelledError:
            _LOGGER.info(
                "Runtime Web Runner stream cancelled",
                extra={"close_reason": stream.close_reason.value},
            )
            await self._reset(stream_id, stream.close_reason, stream=stream)
            raise
        except TimeoutError:
            _LOGGER.info("Runtime Web Runner stream deadline reached")
            await self._reset(stream_id, CloseReason.DEADLINE, stream=stream)
        except OSError, httpcore.NetworkError, httpcore.ProtocolError:
            _LOGGER.exception("Runtime Web Runner loopback stream failed")
            await self._reset(
                stream_id,
                CloseReason.APPLICATION_UNAVAILABLE,
                stream=stream,
            )
        except (
            RunnerWebLoopbackProtocolError,
            h11.LocalProtocolError,
            WsprotoLocalProtocolError,
            WsprotoRemoteProtocolError,
        ):
            _LOGGER.warning("Runtime Web Runner WebSocket protocol failed")
            await self._reset(
                stream_id,
                CloseReason.PROTOCOL_VIOLATION,
                stream=stream,
            )
        except (
            RuntimeError,
            ValueError,
            UnicodeError,
        ):
            _LOGGER.exception("Runtime Web Runner stream protocol failed")
            await self._reset(
                stream_id,
                CloseReason.PROTOCOL_VIOLATION,
                stream=stream,
            )
        else:
            _LOGGER.info("Runtime Web Runner stream completed")
        finally:
            if self.streams.pop(stream_id, None) is stream:
                self._retire(stream_id)
            stream.response_credit.close()

    async def _http(self, stream_id: int, stream: _Stream) -> None:
        remaining = _remaining(stream.authority.transport_deadline_at)
        async with self.manager.loopback.request(
            method=stream.head.method,
            target=stream.head.target,
            headers=tuple(
                (header.name, header.value) for header in stream.head.headers
            ),
            port=stream.authority.port,
            body=self._body(stream_id, stream),
            timeout_seconds=remaining,
        ) as response:
            head = self._envelope(stream_id=stream_id, offer=stream.offer)
            head.response_head.status = response.status
            head.response_head.headers.extend(
                runtime_web_session_pb2.RuntimeWebSessionHeader(name=name, value=value)
                for name, value in response.headers
            )
            await self._send(head, client=stream.client)
            sequence = 0
            async for chunk in response.body:
                for data in _chunks(chunk):
                    sequence += 1
                    await self._response_data(stream_id, stream, sequence, data)
            end = self._envelope(stream_id=stream_id, offer=stream.offer)
            end.direction_end.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            )
            end.direction_end.final_sequence = sequence
            await self._send(end, client=stream.client)
            await self._stream_end(stream_id, stream)

    async def _body(self, stream_id: int, stream: _Stream) -> AsyncIterator[bytes]:
        while True:
            envelope = await stream.inbound.get()
            payload = envelope.WhichOneof("payload")
            if payload == "direction_end":
                if (
                    envelope.direction_end.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                    or envelope.direction_end.final_sequence != stream.request_sequence
                ):
                    raise ValueError("Runner Web request end sequence is invalid")
                return
            if (
                payload != "data"
                or envelope.data.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                or envelope.frame_sequence != stream.request_sequence + 1
            ):
                raise ValueError("Runner Web request body sequence is invalid")
            stream.request_sequence = envelope.frame_sequence
            data = bytes(envelope.data.data)
            yield data
            stream.request_consumed_total += len(data)
            self.request_session_consumed_total += len(data)
            update = self._envelope(stream_id=stream_id, offer=stream.offer)
            update.window_update.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
            )
            update.window_update.stream_consumed_total = stream.request_consumed_total
            update.window_update.session_consumed_total = (
                self.request_session_consumed_total
            )
            await self._send(update, client=stream.client)

    async def _websocket(self, stream_id: int, stream: _Stream) -> None:
        websocket = await self.manager.loopback.websocket(
            target=stream.head.target,
            headers=tuple(
                (header.name, header.value) for header in stream.head.headers
            ),
            port=stream.authority.port,
            timeout_seconds=_remaining(stream.authority.transport_deadline_at),
        )
        try:
            head = self._envelope(stream_id=stream_id, offer=stream.offer)
            head.response_head.status = 101
            head.response_head.headers.extend(
                runtime_web_session_pb2.RuntimeWebSessionHeader(name=name, value=value)
                for name, value in websocket.response_headers
            )
            await self._send(head, client=stream.client)
            browser = asyncio.create_task(self._ws_from_browser(stream, websocket))
            application = asyncio.create_task(
                self._ws_from_application(stream_id, stream, websocket)
            )
            done, pending = await asyncio.wait(
                (browser, application),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                await task
            await self._stream_end(stream_id, stream)
        finally:
            await websocket.close()

    async def _ws_from_browser(
        self,
        stream: _Stream,
        websocket: RunnerWebSocket,
    ) -> None:
        current: WebSocketOpcode | None = None
        while True:
            envelope = await stream.inbound.get()
            if envelope.WhichOneof("payload") == "direction_end":
                if (
                    envelope.direction_end.direction
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                    or envelope.direction_end.final_sequence != stream.request_sequence
                ):
                    raise ValueError("Runner WebSocket request end is invalid")
                return
            if (
                envelope.WhichOneof("payload") != "websocket"
                or envelope.websocket.direction
                != runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                or envelope.frame_sequence != stream.request_sequence + 1
            ):
                raise ValueError("Runner WebSocket request frame is invalid")
            stream.request_sequence = envelope.frame_sequence
            opcode = _opcode(envelope.websocket.opcode)
            effective = current if opcode is WebSocketOpcode.CONTINUATION else opcode
            if effective is None:
                raise ValueError("Runner WebSocket continuation is invalid")
            data = bytes(envelope.websocket.data)
            await websocket.send(
                _ws_event(
                    effective,
                    data,
                    final=envelope.websocket.final,
                )
            )
            if data and opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                stream.request_consumed_total += len(data)
                self.request_session_consumed_total += len(data)
                update = self._envelope(
                    stream_id=envelope.stream_id,
                    offer=stream.offer,
                )
                update.window_update.direction = (
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                )
                update.window_update.stream_consumed_total = (
                    stream.request_consumed_total
                )
                update.window_update.session_consumed_total = (
                    self.request_session_consumed_total
                )
                await self._send(update, client=stream.client)
            current = None if envelope.websocket.final else effective
            if effective is WebSocketOpcode.CLOSE:
                return

    async def _ws_from_application(
        self,
        stream_id: int,
        stream: _Stream,
        websocket: RunnerWebSocket,
    ) -> None:
        sequence = 0
        fragmented_opcode: WebSocketOpcode | None = None
        async for event in websocket.receive():
            converted = _from_ws_event(event)
            if converted is None:
                continue
            opcode, final, data = converted
            wire_opcode = opcode
            if opcode in {WebSocketOpcode.TEXT, WebSocketOpcode.BINARY}:
                if fragmented_opcode is not None:
                    if opcode is not fragmented_opcode:
                        raise ValueError(
                            "Runner WebSocket response message type changed"
                        )
                    wire_opcode = WebSocketOpcode.CONTINUATION
                if final:
                    fragmented_opcode = None
                else:
                    fragmented_opcode = opcode
            sequence += 1
            if data and wire_opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                await self._reserve(stream, len(data))
            envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
            envelope.frame_sequence = sequence
            envelope.websocket.direction = (
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
            )
            envelope.websocket.opcode = _opcode_proto(wire_opcode)
            envelope.websocket.final = final
            envelope.websocket.data = data
            await self._send(envelope, client=stream.client)
            if opcode is WebSocketOpcode.CLOSE:
                return

    async def _response_data(
        self,
        stream_id: int,
        stream: _Stream,
        sequence: int,
        data: bytes,
    ) -> None:
        await self._reserve(stream, len(data))
        envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
        envelope.frame_sequence = sequence
        envelope.data.direction = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
        )
        envelope.data.data = data
        await self._send(envelope, client=stream.client)

    async def _reserve(self, stream: _Stream, size: int) -> None:
        async with stream.credit_changed:
            await stream.credit_changed.wait_for(
                lambda: stream.response_credit.available_bytes >= size
            )
            stream.response_credit.reserve(size)

    def _reset_session_flow(self) -> None:
        """Start each Owner epoch with independent absolute session totals."""
        self.request_session_consumed_total = 0
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
            maximum_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        )
        self.response_credit_changed = asyncio.Condition()
        self.tombstones.clear()
        self.tombstone_set.clear()
        self.last_stream_id = 0

    def _claim_stream_id(self, stream_id: int) -> None:
        """Claim one strictly increasing stream ID for the current session epoch."""
        if stream_id <= self.last_stream_id or stream_id > _MAX_UINT64:
            raise ValueError("Runner Web stream ID is not monotonic")
        self.last_stream_id = stream_id

    def _retire(self, stream_id: int) -> None:
        """Retain one completed stream ID for bounded late-credit handling."""
        if stream_id in self.tombstone_set:
            return
        if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.tombstones.popleft()
            self.tombstone_set.remove(expired)
        self.tombstones.append(stream_id)
        self.tombstone_set.add(stream_id)

    async def _stream_end(self, stream_id: int, stream: _Stream) -> None:
        envelope = self._envelope(stream_id=stream_id, offer=stream.offer)
        envelope.stream_end.SetInParent()
        await self._send(envelope, client=stream.client)

    async def _reset(
        self,
        stream_id: int,
        reason: CloseReason,
        *,
        stream: _Stream | None = None,
    ) -> None:
        offer = self.manager.offer if stream is None else stream.offer
        client = self.manager.client if stream is None else stream.client
        if client is None or offer is None:
            return
        envelope = self._envelope(stream_id=stream_id, offer=offer)
        envelope.reset.reason = _reason_proto(reason)
        await self._send(envelope, client=client)

    async def _send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        client: GrpcRunnerWebSessionClient,
    ) -> None:
        await client.send(envelope)

    def _envelope(
        self,
        *,
        offer: RunnerSessionOffer,
        stream_id: int = 0,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        owner = offer.owner
        return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id=owner.session_lease_id,
            peer_boot_id=self.manager.runner_boot_id,
            owner_boot_id=owner.owner_boot_id,
            session_lease_id=owner.session_lease_id,
            lease_generation=owner.lease_generation,
            stream_id=stream_id,
        )


def _matches_offer(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    offer: RunnerSessionOffer,
) -> bool:
    owner = offer.owner
    return (
        envelope.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
        and envelope.session_id == owner.session_lease_id
        and envelope.owner_boot_id == owner.owner_boot_id
        and envelope.session_lease_id == owner.session_lease_id
        and envelope.lease_generation == owner.lease_generation
    )


def _authority(
    message: runtime_web_session_pb2.RuntimeWebSessionAuthority,
) -> StreamAuthority:
    return StreamAuthority(
        correlation_id=message.correlation_id,
        endpoint_id=message.endpoint_id,
        cycle_id=message.cycle_id,
        endpoint_authority_revision=message.endpoint_authority_revision,
        close_barrier=message.close_barrier,
        identity_id=message.identity_id,
        authentication_session_id=message.authentication_session_id,
        user_id=message.user_id,
        agent_session_id=message.agent_session_id,
        runtime_id=message.runtime_id,
        desired_generation=message.desired_generation,
        runner_generation=message.runner_generation,
        port=message.port,
        open_deadline_at=message.open_deadline_at.ToDatetime(tzinfo=UTC),
        approval_deadline_at=message.approval_deadline_at.ToDatetime(tzinfo=UTC),
        transport_deadline_at=message.transport_deadline_at.ToDatetime(tzinfo=UTC),
    )


def _head(message: runtime_web_session_pb2.RuntimeWebSessionRequestHead) -> RequestHead:
    if message.protocol == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_HTTP:
        protocol = StreamProtocol.HTTP
    elif (
        message.protocol
        == runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_WEBSOCKET
    ):
        protocol = StreamProtocol.WEBSOCKET
    else:
        raise ValueError("Runner Web request protocol is invalid")
    return RequestHead(
        protocol=protocol,
        method=bytes(message.method),
        target=bytes(message.target),
        headers=tuple(
            Header(bytes(item.name), bytes(item.value)) for item in message.headers
        ),
    )


def _chunks(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        data[offset : offset + MANDATORY_DATA_FRAME_BYTES]
        for offset in range(0, len(data), MANDATORY_DATA_FRAME_BYTES)
    )


def _remaining(deadline: datetime) -> float:
    seconds = (deadline - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        raise TimeoutError
    return seconds


def _opcode(value: int) -> WebSocketOpcode:
    mapping = {
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT: WebSocketOpcode.TEXT,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY: WebSocketOpcode.BINARY,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION: WebSocketOpcode.CONTINUATION,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PING: WebSocketOpcode.PING,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PONG: WebSocketOpcode.PONG,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CLOSE: WebSocketOpcode.CLOSE,
    }
    try:
        return mapping[value]
    except KeyError:
        raise ValueError("Runner WebSocket opcode is invalid") from None


def _opcode_proto(opcode: WebSocketOpcode) -> int:
    return {
        WebSocketOpcode.TEXT: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT,
        WebSocketOpcode.BINARY: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY,
        WebSocketOpcode.CONTINUATION: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION,
        WebSocketOpcode.PING: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PING,
        WebSocketOpcode.PONG: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PONG,
        WebSocketOpcode.CLOSE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CLOSE,
    }[opcode]


def _reason_proto(reason: CloseReason) -> int:
    return {
        CloseReason.CALLER: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER,
        CloseReason.GENERATION_REPLACED: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_GENERATION_REPLACED,
        CloseReason.DEADLINE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_DEADLINE,
        CloseReason.SERVICE_DRAIN: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN,
        CloseReason.PROTOCOL_VIOLATION: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION,
        CloseReason.APPLICATION_UNAVAILABLE: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE,
    }[reason]


def _ws_event(opcode: WebSocketOpcode, data: bytes, *, final: bool) -> Event:
    if opcode is WebSocketOpcode.TEXT:
        return TextMessage(data=data.decode("utf-8"), message_finished=final)
    if opcode is WebSocketOpcode.BINARY:
        return BytesMessage(data=data, message_finished=final)
    if opcode is WebSocketOpcode.PING:
        return Ping(payload=data)
    if opcode is WebSocketOpcode.PONG:
        return Pong(payload=data)
    if opcode is WebSocketOpcode.CLOSE:
        code = int.from_bytes(data[:2], "big") if len(data) >= 2 else 1000
        return CloseConnection(
            code=code, reason=data[2:].decode("utf-8", errors="replace")
        )
    raise ValueError("Runner WebSocket continuation must retain its message type")


def _from_ws_event(event: Event) -> tuple[WebSocketOpcode, bool, bytes] | None:
    if isinstance(event, TextMessage):
        return WebSocketOpcode.TEXT, event.message_finished, event.data.encode()
    if isinstance(event, BytesMessage):
        return WebSocketOpcode.BINARY, event.message_finished, bytes(event.data)
    if isinstance(event, Ping):
        return WebSocketOpcode.PING, True, event.payload
    if isinstance(event, Pong):
        return WebSocketOpcode.PONG, True, event.payload
    if isinstance(event, CloseConnection):
        return (
            WebSocketOpcode.CLOSE,
            True,
            event.code.to_bytes(2, "big") + (event.reason or "").encode(),
        )
    return None
