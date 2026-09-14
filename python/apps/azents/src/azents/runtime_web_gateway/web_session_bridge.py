"""Inactive persistent Gateway transport and browser logical-stream bridge."""

from __future__ import annotations

import asyncio
import dataclasses
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import Protocol

from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import (
    AbsoluteCreditWindow,
    FairFrameScheduler,
    HierarchicalCredit,
    QueueLane,
    ScheduledItem,
)
from azents_runtime_control.runtime_web_session import (
    CONTROL_RESERVE_BYTES,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_ENVELOPE_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    SESSION_WINDOW_BYTES,
    CloseReason,
    Header,
    RequestHead,
    StreamAuthority,
    StreamDirection,
    StreamProtocol,
    WebSocketOpcode,
)

from azents.runtime_web_gateway.web_session_pool import (
    GatewaySessionTransport,
    GatewayStreamBinding,
    GatewayStreamHandler,
    RuntimeWebGatewaySessionPool,
)

_MAX_PENDING_ENVELOPES = {
    QueueLane.CONTROL: 32,
    QueueLane.LATENCY: 32,
    QueueLane.DATA: 32,
}
_MAX_PENDING_BROWSER_EVENTS = 8


class GatewaySessionStream(Protocol):
    """Generated persistent Gateway session call surface."""

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope]: ...


class PersistentGatewaySessionTransport:
    """Own one bounded persistent Gateway-to-Control bidirectional RPC."""

    def __init__(self, stream: GatewaySessionStream) -> None:
        self.stream = stream
        self.outbound = _new_outbound_scheduler()
        self.outbound_items = {lane: 0 for lane in QueueLane}
        self.handlers: dict[int, GatewayStreamHandler] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()
        self.condition = asyncio.Condition()
        self.receiver: asyncio.Task[None] | None = None
        self.active = False
        self.failure: Exception | None = None
        self.outbound_bytes = 0
        self.request_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )

    async def start(
        self,
        hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        *,
        timeout_seconds: float,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        """Start the persistent RPC and require acceptance as its first response."""
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web Gateway handshake timeout must be positive")
        if (
            hello.WhichOneof("payload") != "hello"
            or hello.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT
            or not hello.session_id
            or not hello.peer_boot_id
            or not 1 <= hello.ByteSize() <= MAX_ENVELOPE_BYTES
        ):
            raise ValueError("Runtime Web Gateway hello identity is invalid")
        async with self.condition:
            if self.receiver is not None:
                raise RuntimeError("Runtime Web Gateway session is already started")
            accepted = asyncio.get_running_loop().create_future()
            self.active = True
            try:
                responses = self.stream(self._outbound_messages(hello))
            except Exception:
                self.active = False
                raise
            self.receiver = asyncio.create_task(
                self._receive(
                    responses,
                    accepted,
                    expected_fingerprint=hello.protocol_fingerprint,
                    expected_session_id=hello.session_id,
                    expected_peer_boot_id=hello.peer_boot_id,
                )
            )
        try:
            return await asyncio.wait_for(accepted, timeout_seconds)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise

    async def bind(self, stream_id: int, handler: GatewayStreamHandler) -> None:
        """Register one non-reusable logical stream response handler."""
        if stream_id <= 0:
            raise ValueError("Runtime Web stream ID must be positive")
        async with self.condition:
            if (
                not self.active
                or stream_id in self.handlers
                or stream_id in self.tombstone_set
            ):
                raise RuntimeError("Runtime Web Gateway stream cannot be bound")
            self.handlers[stream_id] = handler

    async def unbind(self, stream_id: int) -> None:
        """Release one terminal stream handler."""
        async with self.condition:
            if self.handlers.pop(stream_id, None) is None:
                return
            self._add_tombstone(stream_id)

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        """Queue one byte-bounded envelope without replay."""
        size_bytes = envelope.ByteSize()
        if not 1 <= size_bytes <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web Gateway envelope size is invalid")
        lane = _outbound_lane(envelope)
        async with self.condition:

            def can_queue() -> bool:
                non_control_bytes = (
                    self.outbound.data_bytes + self.outbound.latency_bytes
                )
                lane_available = {
                    QueueLane.CONTROL: (
                        self.outbound.control_bytes + size_bytes
                        <= CONTROL_RESERVE_BYTES
                    ),
                    QueueLane.LATENCY: (
                        self.outbound.latency_bytes + size_bytes <= SESSION_WINDOW_BYTES
                        and non_control_bytes + size_bytes <= SESSION_WINDOW_BYTES
                    ),
                    QueueLane.DATA: (
                        self.outbound.data_bytes + size_bytes <= SESSION_WINDOW_BYTES
                        and non_control_bytes + size_bytes <= SESSION_WINDOW_BYTES
                    ),
                }[lane]
                return (
                    self.outbound_items[lane] < _MAX_PENDING_ENVELOPES[lane]
                    and self.outbound_bytes + size_bytes
                    <= SESSION_WINDOW_BYTES + CONTROL_RESERVE_BYTES
                    and lane_available
                ) or not self.active

            await self.condition.wait_for(can_queue)
            if not self.active or self.receiver is None or self.receiver.done():
                raise RuntimeError(
                    "Runtime Web Gateway session is not active"
                ) from self.failure
            queued = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            queued.CopyFrom(envelope)
            self.outbound.enqueue(
                ScheduledItem(
                    lane=lane,
                    stream_id=queued.stream_id if lane is QueueLane.DATA else None,
                    size_bytes=size_bytes,
                    value=queued,
                )
            )
            self.outbound_items[lane] += 1
            self.outbound_bytes += size_bytes
            self.condition.notify_all()

    async def close(self) -> tuple[int, ...]:
        """Close once, discard queued work, and return active stream IDs."""
        async with self.condition:
            if not self.active and self.receiver is None:
                return ()
            self.active = False
            self.outbound = _new_outbound_scheduler()
            self.outbound_items = {lane: 0 for lane in QueueLane}
            self.outbound_bytes = 0
            failed = tuple(sorted(self.handlers))
            receiver = self.receiver
            self.receiver = None
            self.condition.notify_all()
        if receiver is not None:
            if not receiver.done():
                receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
        return failed

    async def _outbound_messages(
        self, hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        yield hello
        while True:
            async with self.condition:
                await self.condition.wait_for(
                    lambda: sum(self.outbound_items.values()) > 0 or not self.active
                )
                if not self.active:
                    return
                item = self.outbound.pop()
                if item is None:
                    raise RuntimeError("Runtime Web Gateway scheduler lost an item")
                envelope = item.value
                self.outbound_items[item.lane] -= 1
                self.outbound_bytes -= envelope.ByteSize()
                self.condition.notify_all()
            yield envelope

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        accepted: asyncio.Future[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        expected_fingerprint: str,
        expected_session_id: str,
        expected_peer_boot_id: str,
    ) -> None:
        first = True
        peer_boot_id: str | None = None
        try:
            async for envelope in responses:
                if not 1 <= envelope.ByteSize() <= MAX_ENVELOPE_BYTES:
                    raise RuntimeError("Runtime Web Gateway envelope size is invalid")
                if (
                    envelope.protocol_fingerprint != expected_fingerprint
                    or envelope.session_id != expected_session_id
                ):
                    raise RuntimeError("Runtime Web Gateway session identity changed")
                if first:
                    first = False
                    if not envelope.peer_boot_id:
                        raise RuntimeError("Runtime Web Gateway peer identity is empty")
                    peer_boot_id = envelope.peer_boot_id
                    if envelope.WhichOneof("payload") != "session_accepted":
                        raise RuntimeError(
                            "Runtime Web Gateway acceptance must be first"
                        )
                    accepted.set_result(envelope)
                    continue
                if envelope.peer_boot_id != peer_boot_id:
                    raise RuntimeError("Runtime Web Gateway peer identity changed")
                payload = envelope.WhichOneof("payload")
                if payload in {
                    "heartbeat",
                    "heartbeat_ack",
                    "go_away",
                    "session_error",
                }:
                    if envelope.stream_id != 0:
                        raise RuntimeError(
                            "Runtime Web Gateway session frame used a stream ID"
                        )
                    if payload == "heartbeat":
                        acknowledgement = (
                            runtime_web_session_pb2.RuntimeWebSessionEnvelope(
                                protocol_fingerprint=expected_fingerprint,
                                session_id=expected_session_id,
                                peer_boot_id=expected_peer_boot_id,
                            )
                        )
                        acknowledgement.heartbeat_ack.monotonic_sequence = (
                            envelope.heartbeat.monotonic_sequence
                        )
                        await self.send(acknowledgement)
                        continue
                    if payload == "heartbeat_ack":
                        continue
                    if payload == "go_away":
                        raise RuntimeError(
                            "Runtime Web Control requested Gateway session drain"
                        )
                    raise RuntimeError(
                        "Runtime Web Control reported a Gateway session error"
                    )
                async with self.condition:
                    handler = self.handlers.get(envelope.stream_id)
                    terminal = envelope.stream_id in self.tombstone_set
                if handler is None:
                    if terminal:
                        continue
                    raise RuntimeError("Runtime Web Gateway received an unknown stream")
                await handler(envelope)
            if not accepted.done():
                accepted.set_exception(
                    RuntimeError("Runtime Web Gateway session closed before acceptance")
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = error
            if not accepted.done():
                accepted.set_exception(error)
        finally:
            async with self.condition:
                self.active = False
                self.outbound = _new_outbound_scheduler()
                self.outbound_items = {lane: 0 for lane in QueueLane}
                self.outbound_bytes = 0
                handlers = tuple(self.handlers.items())
                self.handlers.clear()
                for stream_id, _ in handlers:
                    self._add_tombstone(stream_id)
                self.condition.notify_all()
            for _, handler in handlers:
                await handler.fail_transport()

    def _add_tombstone(self, stream_id: int) -> None:
        if stream_id in self.tombstone_set:
            return
        if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.tombstones.popleft()
            self.tombstone_set.remove(expired)
        self.tombstones.append(stream_id)
        self.tombstone_set.add(stream_id)


@dataclasses.dataclass(frozen=True)
class BrowserStreamEvent:
    """One raw, typed response event for the browser adapter."""

    payload: str
    status: int | None
    headers: tuple[Header, ...]
    data: bytes
    websocket_opcode: WebSocketOpcode | None
    websocket_final: bool | None
    terminal_reason: CloseReason | None


class RuntimeWebBrowserStreamBridge:
    """Translate one browser exchange into typed persistent envelopes."""

    def __init__(
        self,
        *,
        pool: RuntimeWebGatewaySessionPool,
        binding: GatewayStreamBinding,
    ) -> None:
        self.pool = pool
        self.transport: GatewaySessionTransport = binding.transport
        self.binding = binding
        self.events: asyncio.Queue[BrowserStreamEvent] = asyncio.Queue(
            maxsize=_MAX_PENDING_BROWSER_EVENTS
        )
        self.request_sequence = 0
        self.released = False
        profile = binding.state.profile
        self.request_credit = HierarchicalCredit(
            stream=AbsoluteCreditWindow(
                initial_bytes=profile.request_stream_window_bytes,
                maximum_bytes=profile.request_stream_window_bytes,
            ),
            session=binding.transport.request_session_credit,
        )
        self.response_credit = HierarchicalCredit(
            stream=AbsoluteCreditWindow(
                initial_bytes=profile.response_stream_window_bytes,
                maximum_bytes=profile.response_stream_window_bytes,
            ),
            session=binding.transport.response_session_credit,
        )

    async def __call__(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        """Dispatch one stream envelope from the persistent transport."""
        await self.receive(envelope)

    async def fail_transport(self) -> None:
        """Fail and release one attached stream after session loss."""
        await self.pool.close_session(self.binding.registration)
        snapshot = self.binding.state.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            self.binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
        await self._publish_terminal(CloseReason.TRANSPORT_UNAVAILABLE)
        await self._release()

    @classmethod
    async def open(
        cls,
        *,
        pool: RuntimeWebGatewaySessionPool,
        stream_id: int,
        authority: StreamAuthority,
        request_head: RequestHead,
    ) -> RuntimeWebBrowserStreamBridge:
        """Bind and send one exact OPEN without consuming browser body data."""
        binding = await pool.open(
            stream_id=stream_id,
            authority=authority,
            request_head=request_head,
        )
        transport = binding.transport
        bridge = cls(pool=pool, binding=binding)
        try:
            await transport.bind(stream_id, bridge)
            await transport.send(_open_envelope(binding))
        except asyncio.CancelledError:
            binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
            await transport.unbind(stream_id)
            await pool.release(binding)
            raise
        except Exception:
            binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
            await transport.unbind(stream_id)
            await pool.release(binding)
            raise
        return bridge

    async def send_request_data(self, data: bytes) -> None:
        """Forward one raw request body frame after stream acceptance."""
        size_bytes = len(data)
        _validate_credit_reserve(self.request_credit, size_bytes)
        sequence = self.request_sequence + 1
        self.binding.state.receive_data(StreamDirection.REQUEST, sequence, data)
        self.request_credit.reserve(size_bytes)
        self.request_sequence = sequence
        await self._send_or_fail(
            _data_envelope(
                self.binding,
                direction=StreamDirection.REQUEST,
                sequence=self.request_sequence,
                data=data,
            )
        )

    async def finish_request(self) -> None:
        """Half-close the request direction at the exact sequence."""
        self.binding.state.end_direction(StreamDirection.REQUEST, self.request_sequence)
        await self._send_or_fail(
            _direction_end_envelope(
                self.binding,
                direction=StreamDirection.REQUEST,
                final_sequence=self.request_sequence,
            )
        )

    async def send_websocket(
        self,
        *,
        opcode: WebSocketOpcode,
        final: bool,
        data: bytes,
    ) -> None:
        """Forward one typed request-side WebSocket frame."""
        if data and opcode in {
            WebSocketOpcode.TEXT,
            WebSocketOpcode.BINARY,
            WebSocketOpcode.CONTINUATION,
        }:
            _validate_credit_reserve(self.request_credit, len(data))
        sequence = self.request_sequence + 1
        self.binding.state.receive_websocket(
            direction=StreamDirection.REQUEST,
            sequence=sequence,
            opcode=opcode,
            final=final,
            data=data,
        )
        if data and opcode in {
            WebSocketOpcode.TEXT,
            WebSocketOpcode.BINARY,
            WebSocketOpcode.CONTINUATION,
        }:
            self.request_credit.reserve(len(data))
        self.request_sequence = sequence
        await self._send_or_fail(
            _websocket_envelope(
                self.binding,
                direction=StreamDirection.REQUEST,
                sequence=self.request_sequence,
                opcode=opcode,
                final=final,
                data=data,
            )
        )

    async def cancel(self, reason: CloseReason = CloseReason.CALLER) -> None:
        """Cancel once and release the binding without application replay."""
        snapshot = self.binding.state.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            self.binding.state.reset(reason)
            await self._send_or_fail(_cancel_envelope(self.binding, reason))
        await self._release()

    async def receive(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        """Validate and enqueue one bounded response envelope."""
        if (
            envelope.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT
            or envelope.session_id != self.binding.session_id
            or envelope.stream_id != self.binding.stream_id
        ):
            raise ValueError("Runtime Web Gateway response identity is invalid")
        payload = envelope.WhichOneof("payload")
        if payload == "open_accepted":
            profile = self.binding.state.profile
            if (
                envelope.open_accepted.data_frame_bytes != profile.data_frame_bytes
                or envelope.open_accepted.request_credit_bytes
                != profile.request_stream_window_bytes
                or envelope.open_accepted.response_credit_bytes
                != profile.response_stream_window_bytes
            ):
                raise ValueError("Runtime Web Gateway open profile is invalid")
            self.binding.state.accept()
            return
        if payload == "open_rejected":
            reason = _close_reason(envelope.open_rejected.reason)
            self.binding.state.reject(reason)
            await self._publish_terminal(reason)
            await self._release()
            return
        if payload == "response_head":
            headers = tuple(
                Header(header.name, header.value)
                for header in envelope.response_head.headers
            )
            self.binding.state.receive_response_head(
                envelope.response_head.status, headers
            )
            await self.events.put(
                BrowserStreamEvent(
                    payload=payload,
                    status=envelope.response_head.status,
                    headers=headers,
                    data=b"",
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                )
            )
            return
        if payload == "window_update":
            direction = _direction(envelope.window_update.direction)
            if direction is not StreamDirection.REQUEST:
                raise ValueError("Runtime Web Gateway received response-side credit")
            self.request_credit.update_consumed(
                stream_consumed_total=(envelope.window_update.stream_consumed_total),
                session_consumed_total=(envelope.window_update.session_consumed_total),
            )
            return
        if payload == "data":
            direction = _direction(envelope.data.direction)
            if direction is not StreamDirection.RESPONSE:
                raise ValueError("Runtime Web Gateway received request-side data")
            _validate_credit_reserve(self.response_credit, len(envelope.data.data))
            self.binding.state.receive_data(
                direction, envelope.frame_sequence, envelope.data.data
            )
            self.response_credit.reserve(len(envelope.data.data))
            await self.events.put(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=envelope.data.data,
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                )
            )
            return
        if payload == "direction_end":
            direction = _direction(envelope.direction_end.direction)
            if direction is not StreamDirection.RESPONSE:
                raise ValueError("Runtime Web Gateway received request-side end")
            self.binding.state.end_direction(
                direction, envelope.direction_end.final_sequence
            )
            await self.events.put(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=b"",
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                )
            )
            return
        if payload == "websocket":
            direction = _direction(envelope.websocket.direction)
            if direction is not StreamDirection.RESPONSE:
                raise ValueError("Runtime Web Gateway received request-side WebSocket")
            opcode = _websocket_opcode(envelope.websocket.opcode)
            if envelope.websocket.data and opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                _validate_credit_reserve(
                    self.response_credit, len(envelope.websocket.data)
                )
            self.binding.state.receive_websocket(
                direction=direction,
                sequence=envelope.frame_sequence,
                opcode=opcode,
                final=envelope.websocket.final,
                data=envelope.websocket.data,
            )
            if envelope.websocket.data and opcode in {
                WebSocketOpcode.TEXT,
                WebSocketOpcode.BINARY,
                WebSocketOpcode.CONTINUATION,
            }:
                self.response_credit.reserve(len(envelope.websocket.data))
            await self.events.put(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=envelope.websocket.data,
                    websocket_opcode=opcode,
                    websocket_final=envelope.websocket.final,
                    terminal_reason=None,
                )
            )
            return
        if payload == "reset":
            reason = _close_reason(envelope.reset.reason)
            self.binding.state.reset(reason)
            await self._publish_terminal(reason)
            await self._release()
            return
        if payload == "stream_end":
            self.binding.state.finish()
            await self._publish_terminal(None)
            await self._release()
            return
        raise ValueError("Runtime Web Gateway response envelope is invalid")

    async def _release(self) -> None:
        if self.released:
            return
        self.released = True
        self.request_credit.close()
        self.response_credit.close()
        await self.transport.unbind(self.binding.stream_id)
        await self.pool.release(self.binding)

    async def next_event(self) -> BrowserStreamEvent:
        """Consume one browser event and return absolute response credit."""
        event = await self.events.get()
        application_bytes = _browser_event_application_bytes(event)
        if application_bytes and not self.response_credit.closed:
            stream_total = (
                self.response_credit.stream.consumed_total + application_bytes
            )
            session_total = (
                self.response_credit.session.consumed_total + application_bytes
            )
            self.response_credit.update_consumed(
                stream_consumed_total=stream_total,
                session_consumed_total=session_total,
            )
            await self._send_or_fail(
                _window_update_envelope(
                    self.binding,
                    direction=StreamDirection.RESPONSE,
                    stream_consumed_total=stream_total,
                    session_consumed_total=session_total,
                )
            )
        return event

    async def _send_or_fail(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        try:
            await self.transport.send(envelope)
        except asyncio.CancelledError:
            snapshot = self.binding.state.snapshot()
            if not snapshot.completed and snapshot.terminal_reason is None:
                self.binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
            await self._publish_terminal(CloseReason.TRANSPORT_UNAVAILABLE)
            await self._release()
            raise
        except Exception:
            snapshot = self.binding.state.snapshot()
            if not snapshot.completed and snapshot.terminal_reason is None:
                self.binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
            await self._publish_terminal(CloseReason.TRANSPORT_UNAVAILABLE)
            await self._release()
            raise

    async def _publish_terminal(self, reason: CloseReason | None) -> None:
        await self.events.put(
            BrowserStreamEvent(
                payload="terminal",
                status=None,
                headers=(),
                data=b"",
                websocket_opcode=None,
                websocket_final=None,
                terminal_reason=reason,
            )
        )


def _base_envelope(
    binding: GatewayStreamBinding,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=binding.registration.session_id,
        peer_boot_id=binding.registration.peer_boot_id,
        stream_id=binding.stream_id,
    )


def _validate_credit_reserve(
    credit: HierarchicalCredit,
    size_bytes: int,
) -> None:
    credit.stream.validate_reserve(size_bytes)
    credit.session.validate_reserve(size_bytes)


def _new_outbound_scheduler() -> FairFrameScheduler[
    runtime_web_session_pb2.RuntimeWebSessionEnvelope
]:
    return FairFrameScheduler(
        latency_capacity_bytes=SESSION_WINDOW_BYTES,
        data_capacity_bytes=SESSION_WINDOW_BYTES,
        quantum_bytes=MANDATORY_DATA_FRAME_BYTES,
        maximum_priority_items_before_data=4,
    )


def _outbound_lane(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> QueueLane:
    payload = envelope.WhichOneof("payload")
    if payload == "data":
        return QueueLane.DATA
    if payload == "websocket" and envelope.websocket.opcode in {
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY,
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION,
    }:
        return QueueLane.DATA
    if payload == "websocket":
        return QueueLane.LATENCY
    if payload in {"open", "response_head", "direction_end"}:
        return QueueLane.LATENCY
    return QueueLane.CONTROL


def _browser_event_application_bytes(event: BrowserStreamEvent) -> int:
    if event.payload == "data":
        return len(event.data)
    if event.payload == "websocket" and event.websocket_opcode in {
        WebSocketOpcode.TEXT,
        WebSocketOpcode.BINARY,
        WebSocketOpcode.CONTINUATION,
    }:
        return len(event.data)
    return 0


def _open_envelope(
    binding: GatewayStreamBinding,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    authority = binding.state.authority
    head = binding.state.request_head
    envelope = _base_envelope(binding)
    envelope.open.authority.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionAuthority(
            correlation_id=authority.correlation_id,
            endpoint_id=authority.endpoint_id,
            cycle_id=authority.cycle_id,
            endpoint_authority_revision=authority.endpoint_authority_revision,
            close_barrier=authority.close_barrier,
            identity_id=authority.identity_id,
            authentication_session_id=authority.authentication_session_id,
            user_id=authority.user_id,
            agent_session_id=authority.agent_session_id,
            runtime_id=authority.runtime_id,
            desired_generation=authority.desired_generation,
            runner_generation=authority.runner_generation,
            port=authority.port,
        )
    )
    envelope.open.authority.open_deadline_at.FromDatetime(authority.open_deadline_at)
    envelope.open.authority.transport_deadline_at.FromDatetime(
        authority.transport_deadline_at
    )
    envelope.open.authority.approval_deadline_at.FromDatetime(
        authority.approval_deadline_at
    )
    envelope.open.request_head.protocol = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_WEBSOCKET
        if head.protocol is StreamProtocol.WEBSOCKET
        else runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_HTTP
    )
    envelope.open.request_head.method = head.method
    envelope.open.request_head.target = head.target
    envelope.open.request_head.headers.extend(
        runtime_web_session_pb2.RuntimeWebSessionHeader(
            name=header.name, value=header.value
        )
        for header in head.headers
    )
    return envelope


def _data_envelope(
    binding: GatewayStreamBinding,
    *,
    direction: StreamDirection,
    sequence: int,
    data: bytes,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.frame_sequence = sequence
    envelope.data.direction = _direction_proto(direction)
    envelope.data.data = data
    return envelope


def _direction_end_envelope(
    binding: GatewayStreamBinding,
    *,
    direction: StreamDirection,
    final_sequence: int,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.direction_end.direction = _direction_proto(direction)
    envelope.direction_end.final_sequence = final_sequence
    return envelope


def _window_update_envelope(
    binding: GatewayStreamBinding,
    *,
    direction: StreamDirection,
    stream_consumed_total: int,
    session_consumed_total: int,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.window_update.direction = _direction_proto(direction)
    envelope.window_update.stream_consumed_total = stream_consumed_total
    envelope.window_update.session_consumed_total = session_consumed_total
    return envelope


def _cancel_envelope(
    binding: GatewayStreamBinding, reason: CloseReason
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.cancel.reason = _close_reason_proto(reason)
    return envelope


def _websocket_envelope(
    binding: GatewayStreamBinding,
    *,
    direction: StreamDirection,
    sequence: int,
    opcode: WebSocketOpcode,
    final: bool,
    data: bytes,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.frame_sequence = sequence
    envelope.websocket.direction = _direction_proto(direction)
    envelope.websocket.opcode = _websocket_opcode_proto(opcode)
    envelope.websocket.final = final
    envelope.websocket.data = data
    return envelope


def _direction_proto(
    direction: StreamDirection,
) -> runtime_web_session_pb2.RuntimeWebSessionDirection.ValueType:
    if direction is StreamDirection.REQUEST:
        return runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    return runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE


def _direction(
    value: runtime_web_session_pb2.RuntimeWebSessionDirection.ValueType,
) -> StreamDirection:
    if value == runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST:
        return StreamDirection.REQUEST
    if value == runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE:
        return StreamDirection.RESPONSE
    raise ValueError("Runtime Web direction is invalid")


_WEBSOCKET_OPCODE_TO_PROTO: dict[
    WebSocketOpcode,
    runtime_web_session_pb2.RuntimeWebSessionWebSocketOpcode.ValueType,
] = {
    WebSocketOpcode.TEXT: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_TEXT
    ),
    WebSocketOpcode.BINARY: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY
    ),
    WebSocketOpcode.CONTINUATION: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CONTINUATION
    ),
    WebSocketOpcode.PING: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PING
    ),
    WebSocketOpcode.PONG: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_PONG
    ),
    WebSocketOpcode.CLOSE: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_CLOSE
    ),
}
_PROTO_TO_WEBSOCKET_OPCODE = {
    value: opcode for opcode, value in _WEBSOCKET_OPCODE_TO_PROTO.items()
}


def _websocket_opcode_proto(
    opcode: WebSocketOpcode,
) -> runtime_web_session_pb2.RuntimeWebSessionWebSocketOpcode.ValueType:
    return _WEBSOCKET_OPCODE_TO_PROTO[opcode]


def _websocket_opcode(
    value: runtime_web_session_pb2.RuntimeWebSessionWebSocketOpcode.ValueType,
) -> WebSocketOpcode:
    try:
        return _PROTO_TO_WEBSOCKET_OPCODE[value]
    except KeyError:
        raise ValueError("Runtime WebSocket opcode is invalid") from None


_CLOSE_REASON_TO_PROTO: dict[
    CloseReason,
    runtime_web_session_pb2.RuntimeWebSessionCloseReason.ValueType,
] = {
    CloseReason.CALLER: runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER,
    CloseReason.APPROVAL_EXPIRED: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPROVAL_EXPIRED
    ),
    CloseReason.AUTHORITY_REVOKED: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_AUTHORITY_REVOKED
    ),
    CloseReason.GENERATION_REPLACED: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_GENERATION_REPLACED
    ),
    CloseReason.DEADLINE: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_DEADLINE
    ),
    CloseReason.SERVICE_DRAIN: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    ),
    CloseReason.OWNER_LOST: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_OWNER_LOST
    ),
    CloseReason.PROTOCOL_VIOLATION: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
    ),
    CloseReason.RESOURCE_EXHAUSTED: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_RESOURCE_EXHAUSTED
    ),
    CloseReason.APPLICATION_UNAVAILABLE: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE
    ),
    CloseReason.TRANSPORT_UNAVAILABLE: (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
    ),
}
_PROTO_TO_CLOSE_REASON = {
    value: reason for reason, value in _CLOSE_REASON_TO_PROTO.items()
}


def _close_reason_proto(
    reason: CloseReason,
) -> runtime_web_session_pb2.RuntimeWebSessionCloseReason.ValueType:
    return _CLOSE_REASON_TO_PROTO[reason]


def _close_reason(
    value: runtime_web_session_pb2.RuntimeWebSessionCloseReason.ValueType,
) -> CloseReason:
    try:
        return _PROTO_TO_CLOSE_REASON[value]
    except KeyError:
        raise ValueError("Runtime Web close reason is invalid") from None
