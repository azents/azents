"""Inactive persistent Gateway transport and browser logical-stream bridge."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_flow import (
    AbsoluteCreditWindow,
    FairFrameScheduler,
    HierarchicalCredit,
    QueueLane,
    ScheduledItem,
)
from azents_runtime_control.runtime_stream_session import (
    CONTROL_RESERVE_BYTES,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_ENVELOPE_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    SESSION_WINDOW_BYTES,
    CloseReason,
    Header,
    RequestHead,
    StreamAuthority,
    StreamDirection,
    StreamProtocol,
    WebSocketOpcode,
)

from azents.runtime_web_gateway.operations import RuntimeWebGatewayResourceTracker
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
_BROWSER_EVENT_QUEUE_SIZE = _MAX_PENDING_BROWSER_EVENTS + 1
_CANCEL_DELIVERY_TIMEOUT_SECONDS = 0.1
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_MAX_MISSED_HEARTBEATS = 2
_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _BufferedEnvelope:
    envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    application_bytes: int
    control_bytes: int


class RuntimeWebOpenRejected(RuntimeError):
    """One bounded replacement open rejection."""

    def __init__(self, reason: CloseReason) -> None:
        super().__init__(f"Runtime Web stream was rejected: {reason.value}")
        self.reason = reason


class RuntimeWebGatewayResourceExhausted(RuntimeError):
    """One local hard-limit refusal without transport ambiguity."""


class GatewaySessionStream(Protocol):
    """Generated persistent Gateway session call surface."""

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]: ...


class PersistentGatewaySessionTransport:
    """Own one bounded persistent Gateway-to-Control bidirectional RPC."""

    def __init__(
        self,
        stream: GatewaySessionStream,
        *,
        resources: RuntimeWebGatewayResourceTracker,
    ) -> None:
        self.stream = stream
        self.resources = resources
        self.outbound = _new_outbound_scheduler()
        self.outbound_items = {lane: 0 for lane in QueueLane}
        self.handlers: dict[int, GatewayStreamHandler] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()
        self.condition = asyncio.Condition()
        self.credit_condition = asyncio.Condition()
        self.receiver: asyncio.Task[None] | None = None
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.heartbeat_identity: (
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope | None
        ) = None
        self.heartbeat_sequence = 0
        self.heartbeat_acknowledged_sequence = 0
        self.task_slots_reserved = 0
        self.go_away_task: asyncio.Task[None] | None = None
        self.go_away_handler: (
            Callable[
                [int, CloseReason, datetime],
                Awaitable[tuple[int, ...]],
            ]
            | None
        ) = None
        self.go_away_received = asyncio.Event()
        self.go_away_boundary: int | None = None
        self.go_away_reason: CloseReason | None = None
        self.go_away_deadline: datetime | None = None
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
        hello: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
        *,
        timeout_seconds: float,
    ) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
        """Start the persistent RPC and require acceptance as its first response."""
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web Gateway handshake timeout must be positive")
        if (
            hello.WhichOneof("payload") != "hello"
            or hello.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
            or not hello.session_id
            or not hello.peer_boot_id
            or not 1 <= hello.ByteSize() <= MAX_ENVELOPE_BYTES
        ):
            raise ValueError("Runtime Web Gateway hello identity is invalid")
        async with self.condition:
            if self.receiver is not None:
                raise RuntimeError("Runtime Web Gateway session is already started")
            if not self.resources.try_begin_tasks(2):
                raise RuntimeWebGatewayResourceExhausted(
                    "Runtime Web Gateway session task limit is exhausted"
                )
            self.task_slots_reserved = 2
            accepted = asyncio.get_running_loop().create_future()
            self.active = True
            try:
                responses = self.stream(self._outbound_messages(hello))
            except Exception:
                self.active = False
                self.resources.end_tasks(self.task_slots_reserved)
                self.task_slots_reserved = 0
                raise
            try:
                self.receiver = asyncio.create_task(
                    self._receive(
                        responses,
                        accepted,
                        expected_fingerprint=hello.protocol_fingerprint,
                        expected_session_id=hello.session_id,
                        expected_peer_boot_id=hello.peer_boot_id,
                    )
                )
            except BaseException:
                self.active = False
                self.resources.end_tasks(self.task_slots_reserved)
                self.task_slots_reserved = 0
                raise
        try:
            accepted_envelope = await asyncio.wait_for(accepted, timeout_seconds)
            self.heartbeat_identity = (
                runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
                    protocol_fingerprint=hello.protocol_fingerprint,
                    session_id=hello.session_id,
                    peer_boot_id=hello.peer_boot_id,
                )
            )
            self.resources.transport_epoch_transitions += 1
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(),
                name=f"runtime-web-gateway-heartbeat:{hello.session_id}",
            )
            return accepted_envelope
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
                or self.go_away_boundary is not None
                and stream_id > self.go_away_boundary
            ):
                raise RuntimeError("Runtime Web Gateway stream cannot be bound")
            self.handlers[stream_id] = handler

    def set_go_away_handler(
        self,
        handler: Callable[
            [int, CloseReason, datetime],
            Awaitable[tuple[int, ...]],
        ],
    ) -> None:
        """Bind the exact pool lifecycle callback before session activation."""
        if self.go_away_handler is not None:
            raise RuntimeError("Runtime Web Gateway GOAWAY handler is already bound")
        self.go_away_handler = handler

    async def unbind(self, stream_id: int) -> None:
        """Release one terminal stream handler."""
        async with self.condition:
            if self.handlers.pop(stream_id, None) is None:
                return
            self._add_tombstone(stream_id)

    async def send(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        """Queue one byte-bounded envelope without replay."""
        size_bytes = envelope.ByteSize()
        if not 1 <= size_bytes <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web Gateway envelope size is invalid")
        lane = _outbound_lane(envelope)
        application_bytes = _application_bytes(envelope)
        control_bytes = size_bytes - application_bytes
        if application_bytes and not self.resources.try_reserve_application_buffer(
            application_bytes
        ):
            raise RuntimeWebGatewayResourceExhausted(
                "Runtime Web application buffer is exhausted"
            )
        queued_successfully = False
        control_reserved = False
        try:
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
                            self.outbound.latency_bytes + size_bytes
                            <= SESSION_WINDOW_BYTES
                            and non_control_bytes + size_bytes <= SESSION_WINDOW_BYTES
                        ),
                        QueueLane.DATA: (
                            self.outbound.data_bytes + size_bytes
                            <= SESSION_WINDOW_BYTES
                            and non_control_bytes + size_bytes <= SESSION_WINDOW_BYTES
                        ),
                    }[lane]
                    return (
                        self.outbound_items[lane] < _MAX_PENDING_ENVELOPES[lane]
                        and self.outbound_bytes + size_bytes
                        <= SESSION_WINDOW_BYTES + CONTROL_RESERVE_BYTES
                        and lane_available
                    ) or not self.active

                waiter_reserved = False
                if not can_queue():
                    waiter_reserved = self.resources.try_add_scheduler_waiter()
                    if not waiter_reserved:
                        raise RuntimeWebGatewayResourceExhausted(
                            "Runtime Web scheduler waiters are exhausted"
                        )
                try:
                    await self.condition.wait_for(can_queue)
                finally:
                    if waiter_reserved:
                        self.resources.remove_scheduler_waiter()
                if not self.active or self.receiver is None or self.receiver.done():
                    raise RuntimeError(
                        "Runtime Web Gateway session is not active"
                    ) from self.failure
                queued = runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
                queued.CopyFrom(envelope)
                if not self.resources.try_reserve_control_buffer(control_bytes):
                    raise RuntimeWebGatewayResourceExhausted(
                        "Runtime Web control buffer is exhausted"
                    )
                control_reserved = True
                self.outbound.enqueue(
                    ScheduledItem(
                        lane=lane,
                        stream_id=queued.stream_id if lane is QueueLane.DATA else None,
                        size_bytes=size_bytes,
                        value=_BufferedEnvelope(
                            envelope=queued,
                            application_bytes=application_bytes,
                            control_bytes=control_bytes,
                        ),
                    )
                )
                self.outbound_items[lane] += 1
                self.outbound_bytes += size_bytes
                self.condition.notify_all()
                queued_successfully = True
        finally:
            if not queued_successfully:
                if control_reserved:
                    self.resources.release_control_buffer(control_bytes)
                if application_bytes:
                    await self.resources.release_application_buffer(application_bytes)

    async def close(self) -> tuple[int, ...]:
        """Close once, discard queued work, and return active stream IDs."""
        async with self.condition:
            if (
                not self.active
                and self.receiver is None
                and self.go_away_task is None
                and self.heartbeat_task is None
                and self.task_slots_reserved == 0
            ):
                return ()
            self.active = False
            buffered = _drain_outbound_scheduler(self.outbound)
            self.outbound = _new_outbound_scheduler()
            self.outbound_items = {lane: 0 for lane in QueueLane}
            self.outbound_bytes = 0
            failed = tuple(sorted(self.handlers))
            receiver = self.receiver
            self.receiver = None
            go_away_task = self.go_away_task
            self.go_away_task = None
            heartbeat_task = self.heartbeat_task
            self.heartbeat_task = None
            self.condition.notify_all()
        await self._release_buffered(buffered)
        if receiver is not None:
            if not receiver.done():
                receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        if go_away_task is not None and go_away_task is not asyncio.current_task():
            if not go_away_task.done():
                go_away_task.cancel()
            await asyncio.gather(go_away_task, return_exceptions=True)
        if heartbeat_task is not None and heartbeat_task is not asyncio.current_task():
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        if self.task_slots_reserved:
            self.resources.end_tasks(self.task_slots_reserved)
            self.task_slots_reserved = 0
        return failed

    async def wait_closed(self) -> None:
        """Wait until the persistent receiver terminates."""
        receiver = self.receiver
        if receiver is None:
            return
        await receiver

    async def _outbound_messages(
        self, hello: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> AsyncIterator[runtime_stream_session_pb2.RuntimeStreamSessionEnvelope]:
        yield hello
        while True:
            async with self.condition:
                await self.condition.wait_for(
                    lambda: sum(self.outbound_items.values()) > 0 or not self.active
                )
                if not self.active:
                    return
                scheduled = self.outbound.pop()
                if scheduled is None:
                    raise RuntimeError("Runtime Web Gateway scheduler lost an item")
                buffered = scheduled.value
                self.outbound_items[scheduled.lane] -= 1
                self.outbound_bytes -= buffered.envelope.ByteSize()
                self.condition.notify_all()
            try:
                yield buffered.envelope
            finally:
                await self._release_buffered((buffered,))

    async def _receive(
        self,
        responses: AsyncIterable[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
        accepted: asyncio.Future[
            runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
        ],
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
                    if envelope.stream_id != 0:
                        raise RuntimeError(
                            "Runtime Web Gateway acceptance must be session-scoped"
                        )
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
                if payload == "heartbeat_ack":
                    if (
                        envelope.stream_id != 0
                        or envelope.heartbeat_ack.monotonic_sequence
                        <= self.heartbeat_acknowledged_sequence
                        or envelope.heartbeat_ack.monotonic_sequence
                        > self.heartbeat_sequence
                    ):
                        raise RuntimeError(
                            "Runtime Web Gateway heartbeat acknowledgement is invalid"
                        )
                    self.heartbeat_acknowledged_sequence = (
                        envelope.heartbeat_ack.monotonic_sequence
                    )
                    self.resources.transport_heartbeat_acknowledgements += 1
                    continue
                if payload == "heartbeat":
                    if envelope.stream_id != 0:
                        raise RuntimeError(
                            "Runtime Web Gateway heartbeat must be session-scoped"
                        )
                    acknowledgement = (
                        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
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
                if payload == "go_away":
                    self.resources.transport_go_aways += 1
                    await self._receive_go_away(envelope)
                    continue
                if payload == "session_error":
                    if envelope.stream_id != 0:
                        raise RuntimeError(
                            "Runtime Web Gateway session error must be session-scoped"
                        )
                    raise RuntimeError(
                        "Runtime Web Control reported a Gateway session error"
                    )
                if envelope.stream_id == 0:
                    raise RuntimeError("Runtime Web Gateway session frame is invalid")
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
            raise
        finally:
            async with self.condition:
                self.active = False
                buffered = _drain_outbound_scheduler(self.outbound)
                self.outbound = _new_outbound_scheduler()
                self.outbound_items = {lane: 0 for lane in QueueLane}
                self.outbound_bytes = 0
                handlers = tuple(self.handlers.items())
                self.handlers.clear()
                for stream_id, _ in handlers:
                    self._add_tombstone(stream_id)
                self.condition.notify_all()
            await self._release_buffered(buffered)
            for _, handler in handlers:
                await handler.fail_transport()

    async def _heartbeat_loop(self) -> None:
        """Send one session heartbeat every five seconds and fail after two misses."""
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            async with self.condition:
                if not self.active:
                    return
                missed = self.heartbeat_sequence - self.heartbeat_acknowledged_sequence
                if missed >= _MAX_MISSED_HEARTBEATS:
                    self.resources.transport_missed_heartbeats += 1
                    self.failure = TimeoutError(
                        "Runtime Web Gateway heartbeat acknowledgement timed out"
                    )
                    receiver = self.receiver
                else:
                    receiver = None
                    identity = self.heartbeat_identity
                    if identity is None:
                        raise RuntimeError(
                            "Runtime Web Gateway heartbeat identity is absent"
                        )
                    self.heartbeat_sequence += 1
                    heartbeat = (
                        runtime_stream_session_pb2.RuntimeStreamSessionEnvelope()
                    )
                    heartbeat.CopyFrom(identity)
                    heartbeat.heartbeat.monotonic_sequence = self.heartbeat_sequence
                    self.resources.transport_heartbeats_sent += 1
            if receiver is not None:
                receiver.cancel()
                return
            await self.send(heartbeat)

    async def _receive_go_away(
        self,
        envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
    ) -> None:
        if envelope.stream_id != 0:
            raise RuntimeError("Runtime Web Gateway GOAWAY must be session-scoped")
        reason = _close_reason(envelope.go_away.reason)
        deadline = envelope.go_away.drain_deadline_at.ToDatetime(tzinfo=UTC)
        boundary = envelope.go_away.last_accepted_stream_id
        handler = self.go_away_handler
        if handler is None:
            raise RuntimeError("Runtime Web Gateway GOAWAY handler is absent")
        async with self.condition:
            if self.go_away_boundary is not None:
                raise RuntimeError("Runtime Web Gateway GOAWAY was duplicated")
            self.go_away_boundary = boundary
            self.go_away_reason = reason
            self.go_away_deadline = deadline
            self.condition.notify_all()
        terminated = await handler(boundary, reason, deadline)
        async with self.condition:
            fenced_handlers = tuple(
                stream_handler
                for stream_id in terminated
                if (stream_handler := self.handlers.get(stream_id)) is not None
            )
        if fenced_handlers:
            await asyncio.gather(
                *(
                    stream_handler.fail_go_away(reason)
                    for stream_handler in fenced_handlers
                )
            )
        self.go_away_task = asyncio.create_task(
            self._expire_go_away(deadline, reason),
            name=f"runtime-web-gateway-go-away:{envelope.session_id}",
        )
        self.go_away_received.set()

    async def _expire_go_away(
        self,
        deadline: datetime,
        reason: CloseReason,
    ) -> None:
        delay = (deadline - datetime.now(UTC)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        async with self.condition:
            remaining = tuple(self.handlers.values())
        if remaining:
            await asyncio.gather(
                *(stream_handler.fail_go_away(reason) for stream_handler in remaining)
            )

    async def _release_buffered(
        self,
        buffered: tuple[_BufferedEnvelope, ...],
    ) -> None:
        application_bytes = sum(item.application_bytes for item in buffered)
        control_bytes = sum(item.control_bytes for item in buffered)
        if control_bytes:
            self.resources.release_control_buffer(control_bytes)
        if application_bytes:
            await self.resources.release_application_buffer(application_bytes)

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
    control_buffer_bytes: int


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
        self.resources = binding.transport.resources
        self.events: asyncio.Queue[BrowserStreamEvent] = asyncio.Queue(
            maxsize=_BROWSER_EVENT_QUEUE_SIZE
        )
        self.event_condition = asyncio.Condition()
        self.accepted = asyncio.Event()
        self.acceptance_error: CloseReason | None = None
        self.route: str | None = None
        self.credit_condition = binding.transport.credit_condition
        self.request_sequence = 0
        self.released = False
        self.terminal_published = False
        self.terminal_metric_recorded = False
        self.transport_open_recorded = False
        self.started_at = asyncio.get_running_loop().time()
        self.ttfb_seconds: float | None = None
        self.request_bytes = 0
        self.response_bytes = 0
        self.buffered_event_ids: set[int] = set()
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
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        """Dispatch one stream envelope from the persistent transport."""
        await self.receive(envelope)

    async def fail_transport(self) -> None:
        """Fail and release one attached stream after session loss."""
        await self.pool.close_session(self.binding.registration)
        snapshot = self.binding.state.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            self.binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)
        self._fail_pending_acceptance(CloseReason.TRANSPORT_UNAVAILABLE)
        await self._publish_terminal(CloseReason.TRANSPORT_UNAVAILABLE)
        await self._release()

    async def fail_go_away(self, reason: CloseReason) -> None:
        """Terminate one stream fenced by session GOAWAY without transport failure."""
        snapshot = self.binding.state.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            self.binding.state.reset(reason)
            terminal_reason = reason
        else:
            terminal_reason = snapshot.terminal_reason
        self._fail_pending_acceptance(reason)
        await self._publish_terminal(terminal_reason)
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
            _reset_open_failure(binding)
            await transport.unbind(stream_id)
            await pool.release(binding)
            raise
        except Exception:
            _reset_open_failure(binding)
            await transport.unbind(stream_id)
            await pool.release(binding)
            raise
        return bridge

    async def send_request_data(self, data: bytes) -> None:
        """Forward one raw request body frame after stream acceptance."""
        size_bytes = len(data)
        try:
            await self._reserve_request_credit(size_bytes)
        except RuntimeWebGatewayResourceExhausted:
            await self.cancel(CloseReason.RESOURCE_EXHAUSTED)
            raise
        sequence = self.request_sequence + 1
        self.binding.state.receive_data(StreamDirection.REQUEST, sequence, data)
        self.request_sequence = sequence
        await self._send_or_fail(
            _data_envelope(
                self.binding,
                direction=StreamDirection.REQUEST,
                sequence=self.request_sequence,
                data=data,
            )
        )
        self._record_frame("request", size_bytes)

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
            try:
                await self._reserve_request_credit(len(data))
            except RuntimeWebGatewayResourceExhausted:
                await self.cancel(CloseReason.RESOURCE_EXHAUSTED)
                raise
        sequence = self.request_sequence + 1
        self.binding.state.receive_websocket(
            direction=StreamDirection.REQUEST,
            sequence=sequence,
            opcode=opcode,
            final=final,
            data=data,
        )
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
        self._record_frame("request", len(data))

    async def cancel(self, reason: CloseReason = CloseReason.CALLER) -> None:
        """Best-effort one bounded CANCEL while always releasing local ownership."""
        snapshot = self.binding.state.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            self.binding.state.reset(reason)
            self._fail_pending_acceptance(reason)
            terminal_reason = reason
            send_cancel = True
        else:
            terminal_reason = snapshot.terminal_reason
            send_cancel = False
        try:
            if send_cancel:
                await self._send_cancel_best_effort(reason)
        finally:
            await self._finalize_cancel_shielded(terminal_reason)

    async def _send_cancel_best_effort(self, reason: CloseReason) -> None:
        delivery = asyncio.create_task(
            self.transport.send(_cancel_envelope(self.binding, reason)),
            name=f"runtime-web-gateway-cancel:{self.binding.stream_id}",
        )
        try:
            done, _ = await asyncio.wait(
                (delivery,),
                timeout=_CANCEL_DELIVERY_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            self._detach_cancel_delivery(delivery)
            raise
        if delivery not in done:
            _LOGGER.warning(
                "Runtime Web Gateway CANCEL delivery timed out",
                extra={"error_type": TimeoutError.__name__},
            )
            self._detach_cancel_delivery(delivery)
            return
        if delivery.cancelled():
            _LOGGER.warning(
                "Runtime Web Gateway CANCEL delivery was cancelled",
                extra={"error_type": asyncio.CancelledError.__name__},
            )
            return
        error = delivery.exception()
        if error is not None:
            _LOGGER.warning(
                "Runtime Web Gateway CANCEL delivery failed",
                extra={"error_type": _bounded_error_type(error)},
            )

    def _detach_cancel_delivery(self, delivery: asyncio.Task[None]) -> None:
        delivery.add_done_callback(_observe_cancel_delivery)
        delivery.cancel()

    async def _finalize_cancel_shielded(
        self,
        reason: CloseReason | None,
    ) -> None:
        cleanup = asyncio.create_task(
            self._finalize_cancel(reason),
            name=f"runtime-web-gateway-cancel-cleanup:{self.binding.stream_id}",
        )
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise

    async def _finalize_cancel(self, reason: CloseReason | None) -> None:
        try:
            await self._publish_terminal(reason)
        finally:
            await self._release()

    def _fail_pending_acceptance(self, reason: CloseReason) -> None:
        snapshot = self.binding.state.snapshot()
        if snapshot.accepted or self.accepted.is_set():
            return
        self.acceptance_error = reason
        self.accepted.set()

    async def receive(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
    ) -> None:
        """Validate and enqueue one bounded response envelope."""
        if (
            envelope.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
            or envelope.session_id != self.binding.session_id
            or envelope.stream_id != self.binding.stream_id
        ):
            raise ValueError("Runtime Web Gateway response identity is invalid")
        payload = envelope.WhichOneof("payload")
        snapshot = self.binding.state.snapshot()
        if self.released or snapshot.completed or snapshot.terminal_reason is not None:
            return
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
            if (
                envelope.open_accepted.route_path
                == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL
            ):
                self.route = "local"
            elif (
                envelope.open_accepted.route_path
                == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_ROUTE_PATH_RELAY
            ):
                self.route = "relay"
            else:
                raise ValueError("Runtime Web Gateway open route is invalid")
            self.binding.state.accept()
            self.resources.record_transport_open(
                protocol=self.binding.state.request_head.protocol,
                path=self.route,
                setup_seconds=asyncio.get_running_loop().time() - self.started_at,
            )
            self.transport_open_recorded = True
            self.accepted.set()
            return
        if payload == "open_rejected":
            reason = _close_reason(envelope.open_rejected.reason)
            self.resources.record_transport_rejection(reason)
            self.acceptance_error = reason
            self.accepted.set()
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
            if self.ttfb_seconds is None:
                self.ttfb_seconds = asyncio.get_running_loop().time() - self.started_at
                self.resources.record_transport_ttfb(self.ttfb_seconds)
            await self._queue_event(
                BrowserStreamEvent(
                    payload=payload,
                    status=envelope.response_head.status,
                    headers=headers,
                    data=b"",
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                    control_buffer_bytes=envelope.ByteSize(),
                )
            )
            return
        if payload == "window_update":
            direction = _direction(envelope.window_update.direction)
            if direction is not StreamDirection.REQUEST:
                raise ValueError("Runtime Web Gateway received response-side credit")
            async with self.credit_condition:
                self.request_credit.update_consumed(
                    stream_consumed_total=(
                        envelope.window_update.stream_consumed_total
                    ),
                    session_consumed_total=(
                        envelope.window_update.session_consumed_total
                    ),
                )
                self.credit_condition.notify_all()
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
            if not await self._queue_event(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=envelope.data.data,
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                    control_buffer_bytes=(
                        envelope.ByteSize() - len(envelope.data.data)
                    ),
                )
            ):
                return
            self._record_frame("response", len(envelope.data.data))
            return
        if payload == "direction_end":
            direction = _direction(envelope.direction_end.direction)
            if direction is not StreamDirection.RESPONSE:
                raise ValueError("Runtime Web Gateway received request-side end")
            self.binding.state.end_direction(
                direction, envelope.direction_end.final_sequence
            )
            await self._queue_event(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=b"",
                    websocket_opcode=None,
                    websocket_final=None,
                    terminal_reason=None,
                    control_buffer_bytes=envelope.ByteSize(),
                )
            )
            return
        if payload == "websocket":
            direction = _direction(envelope.websocket.direction)
            if direction is not StreamDirection.RESPONSE:
                raise ValueError("Runtime Web Gateway received request-side WebSocket")
            opcode = _websocket_opcode(envelope.websocket.opcode)
            application_bytes = _websocket_application_bytes(
                opcode, envelope.websocket.data
            )
            if application_bytes:
                _validate_credit_reserve(self.response_credit, application_bytes)
            self.binding.state.receive_websocket(
                direction=direction,
                sequence=envelope.frame_sequence,
                opcode=opcode,
                final=envelope.websocket.final,
                data=envelope.websocket.data,
            )
            if application_bytes:
                self.response_credit.reserve(application_bytes)
            if not await self._queue_event(
                BrowserStreamEvent(
                    payload=payload,
                    status=None,
                    headers=(),
                    data=envelope.websocket.data,
                    websocket_opcode=opcode,
                    websocket_final=envelope.websocket.final,
                    terminal_reason=None,
                    control_buffer_bytes=(envelope.ByteSize() - application_bytes),
                )
            ):
                return
            self._record_frame("response", len(envelope.websocket.data))
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

    async def wait_accepted(self, *, timeout_seconds: float) -> None:
        """Wait until Control accepts or rejects the logical stream."""
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web open timeout must be positive")
        await asyncio.wait_for(self.accepted.wait(), timeout=timeout_seconds)
        if self.acceptance_error is not None:
            raise RuntimeWebOpenRejected(self.acceptance_error)
        if self.route is None:
            raise RuntimeError("Runtime Web stream route is absent")

    async def _release(self) -> None:
        if self.released:
            return
        self.released = True
        self.request_credit.close()
        self.response_credit.close()
        async with self.credit_condition:
            self.credit_condition.notify_all()
        async with self.event_condition:
            self.event_condition.notify_all()
        await self.transport.unbind(self.binding.stream_id)
        await self.pool.release(self.binding)

    async def _reserve_request_credit(self, size_bytes: int) -> None:
        if size_bytes <= 0:
            raise ValueError("Runtime Web request credit size must be positive")
        async with self.credit_condition:

            def ready() -> bool:
                return (
                    self.released or self.request_credit.available_bytes >= size_bytes
                )

            waiter_reserved = False
            stalled_at: float | None = None
            if not ready():
                stalled_at = asyncio.get_running_loop().time()
                waiter_reserved = self.resources.try_add_scheduler_waiter()
                if not waiter_reserved:
                    raise RuntimeWebGatewayResourceExhausted(
                        "Runtime Web scheduler waiters are exhausted"
                    )
            try:
                await self.credit_condition.wait_for(ready)
            finally:
                if waiter_reserved:
                    self.resources.remove_scheduler_waiter()
            if self.released:
                raise RuntimeError("Runtime Web request stream is closed")
            self.request_credit.reserve(size_bytes)
        if stalled_at is not None:
            self.resources.record_transport_credit_stall(
                asyncio.get_running_loop().time() - stalled_at
            )

    async def next_event(self) -> BrowserStreamEvent:
        """Consume one browser event without acknowledging unwritten bytes."""
        event = await self.events.get()
        async with self.event_condition:
            self.event_condition.notify_all()
        return event

    async def release_event(self, event: BrowserStreamEvent) -> None:
        """Release one written browser event and return absolute response credit."""
        await self._release_event(event, acknowledge=True)

    async def discard_event(self, event: BrowserStreamEvent) -> None:
        """Release one unwritten browser event without returning peer credit."""
        await self._release_event(event, acknowledge=False)

    async def _release_event(
        self,
        event: BrowserStreamEvent,
        *,
        acknowledge: bool,
    ) -> None:
        event_id = id(event)
        if event_id not in self.buffered_event_ids:
            return
        self.buffered_event_ids.remove(event_id)
        application_bytes = _browser_event_application_bytes(event)
        try:
            if acknowledge and application_bytes and not self.response_credit.closed:
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
        finally:
            if event.control_buffer_bytes:
                self.resources.release_control_buffer(event.control_buffer_bytes)
            if application_bytes:
                await self.resources.release_application_buffer(application_bytes)

    async def discard_buffered_events(self) -> None:
        """Release queued application bytes when the browser exchange terminates."""
        while True:
            try:
                event = self.events.get_nowait()
            except asyncio.QueueEmpty:
                break
            event_id = id(event)
            if event_id not in self.buffered_event_ids:
                continue
            await self.discard_event(event)
        async with self.event_condition:
            self.event_condition.notify_all()

    async def _send_or_fail(
        self, envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope
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
        except RuntimeWebGatewayResourceExhausted:
            snapshot = self.binding.state.snapshot()
            if not snapshot.completed and snapshot.terminal_reason is None:
                self.binding.state.reset(CloseReason.RESOURCE_EXHAUSTED)
            await self._publish_terminal(CloseReason.RESOURCE_EXHAUSTED)
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
        terminal = BrowserStreamEvent(
            payload="terminal",
            status=None,
            headers=(),
            data=b"",
            websocket_opcode=None,
            websocket_final=None,
            terminal_reason=reason,
            control_buffer_bytes=0,
        )
        async with self.event_condition:
            if self.terminal_published:
                return
            self._record_terminal_metric(reason)
            self.events.put_nowait(terminal)
            self.terminal_published = True
            self.event_condition.notify_all()

    def _record_frame(self, direction: str, size_bytes: int) -> None:
        path = self.route
        if path is None:
            raise RuntimeError("Runtime Web transport path is absent")
        self.resources.record_transport_frame(
            protocol=self.binding.state.request_head.protocol,
            direction=direction,
            path=path,
            size_bytes=size_bytes,
        )
        if direction == "request":
            self.request_bytes += size_bytes
        elif direction == "response":
            self.response_bytes += size_bytes
        else:
            raise ValueError("Runtime Web transport direction is invalid")

    def _record_terminal_metric(self, reason: CloseReason | None) -> None:
        if self.terminal_metric_recorded:
            return
        self.terminal_metric_recorded = True
        duration_seconds = asyncio.get_running_loop().time() - self.started_at
        self.resources.record_transport_terminal(
            protocol=self.binding.state.request_head.protocol,
            path=self.route if self.transport_open_recorded else None,
            reason=reason,
            duration_seconds=duration_seconds,
            application_bytes=self.request_bytes + self.response_bytes,
        )
        _LOGGER.info(
            "Runtime Web transport completed",
            extra={
                "protocol": self.binding.state.request_head.protocol.value,
                "route": self.route or "unresolved",
                "terminal_reason": ("completed" if reason is None else reason.value),
                "request_bytes": self.request_bytes,
                "response_bytes": self.response_bytes,
                "ttfb_seconds": self.ttfb_seconds,
                "duration_seconds": duration_seconds,
            },
        )

    async def _queue_event(self, event: BrowserStreamEvent) -> bool:
        application_bytes = _browser_event_application_bytes(event)
        control_bytes = event.control_buffer_bytes
        if application_bytes and not await self.resources.reserve_application_buffer(
            application_bytes
        ):
            await self.cancel(CloseReason.RESOURCE_EXHAUSTED)
            return False
        control_reserved = False
        if control_bytes:
            control_reserved = self.resources.try_reserve_control_buffer(control_bytes)
            if not control_reserved:
                if application_bytes:
                    await self.resources.release_application_buffer(application_bytes)
                await self.cancel(CloseReason.RESOURCE_EXHAUSTED)
                return False
        waiter_reserved = False
        application_reserved = bool(application_bytes)
        queued_successfully = False
        resource_exhausted = False
        try:
            async with self.event_condition:

                def can_queue() -> bool:
                    return (
                        self.events.qsize() < _MAX_PENDING_BROWSER_EVENTS
                        or self.released
                    )

                if not can_queue():
                    waiter_reserved = self.resources.try_add_scheduler_waiter()
                    if not waiter_reserved:
                        resource_exhausted = True
                    else:
                        await self.event_condition.wait_for(can_queue)
                if not resource_exhausted and not self.released:
                    self.events.put_nowait(event)
                    queued_successfully = True
        finally:
            if waiter_reserved:
                self.resources.remove_scheduler_waiter()
            if not queued_successfully:
                if control_reserved:
                    self.resources.release_control_buffer(control_bytes)
                if application_reserved:
                    await self.resources.release_application_buffer(application_bytes)
        if resource_exhausted:
            await self.cancel(CloseReason.RESOURCE_EXHAUSTED)
        if queued_successfully and (application_bytes or control_bytes):
            self.buffered_event_ids.add(id(event))
        return queued_successfully


def _base_envelope(
    binding: GatewayStreamBinding,
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    return runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=binding.registration.session_id,
        peer_boot_id=binding.registration.peer_boot_id,
        stream_id=binding.stream_id,
    )


def _observe_cancel_delivery(delivery: asyncio.Task[None]) -> None:
    if delivery.cancelled():
        return
    error = delivery.exception()
    if error is not None:
        _LOGGER.warning(
            "Runtime Web Gateway detached CANCEL delivery failed",
            extra={"error_type": _bounded_error_type(error)},
        )


def _bounded_error_type(error: BaseException) -> str:
    return type(error).__name__[:128]


def _reset_open_failure(binding: GatewayStreamBinding) -> None:
    snapshot = binding.state.snapshot()
    if not snapshot.completed and snapshot.terminal_reason is None:
        binding.state.reset(CloseReason.TRANSPORT_UNAVAILABLE)


def _validate_credit_reserve(
    credit: HierarchicalCredit,
    size_bytes: int,
) -> None:
    credit.stream.validate_reserve(size_bytes)
    credit.session.validate_reserve(size_bytes)


def _new_outbound_scheduler() -> FairFrameScheduler[_BufferedEnvelope]:
    return FairFrameScheduler(
        latency_capacity_bytes=SESSION_WINDOW_BYTES,
        data_capacity_bytes=SESSION_WINDOW_BYTES,
        quantum_bytes=MANDATORY_DATA_FRAME_BYTES,
        maximum_priority_items_before_data=4,
    )


def _drain_outbound_scheduler(
    scheduler: FairFrameScheduler[_BufferedEnvelope],
) -> tuple[_BufferedEnvelope, ...]:
    buffered: list[_BufferedEnvelope] = []
    while (item := scheduler.pop()) is not None:
        buffered.append(item.value)
    return tuple(buffered)


def _outbound_lane(
    envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
) -> QueueLane:
    payload = envelope.WhichOneof("payload")
    if payload in {"data", "direction_end", "stream_end", "websocket"}:
        return QueueLane.DATA
    if payload in {"open", "response_head"}:
        return QueueLane.LATENCY
    return QueueLane.CONTROL


def _application_bytes(
    envelope: runtime_stream_session_pb2.RuntimeStreamSessionEnvelope,
) -> int:
    payload = envelope.WhichOneof("payload")
    if payload == "data":
        return len(envelope.data.data)
    if payload == "websocket" and envelope.websocket.opcode in {
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_TEXT,
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY,
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CONTINUATION,
    }:
        return len(envelope.websocket.data)
    return 0


def _websocket_application_bytes(opcode: WebSocketOpcode, data: bytes) -> int:
    if opcode in {
        WebSocketOpcode.TEXT,
        WebSocketOpcode.BINARY,
        WebSocketOpcode.CONTINUATION,
    }:
        return len(data)
    return 0


def _browser_event_application_bytes(event: BrowserStreamEvent) -> int:
    if event.payload == "data":
        return len(event.data)
    if event.payload == "websocket" and event.websocket_opcode is not None:
        return _websocket_application_bytes(event.websocket_opcode, event.data)
    return 0


def _open_envelope(
    binding: GatewayStreamBinding,
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    authority = binding.state.authority
    head = binding.state.request_head
    envelope = _base_envelope(binding)
    envelope.open.authority.CopyFrom(
        runtime_stream_session_pb2.RuntimeStreamSessionAuthority(
            correlation_id=authority.correlation_id,
            service_id=authority.service_id,
            service_revision=authority.service_revision,
            identity_id=authority.identity_id,
            authentication_session_id=authority.authentication_session_id,
            user_id=authority.user_id,
            agent_id=authority.agent_id,
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
    envelope.open.authority.exposure_deadline_at.FromDatetime(
        authority.exposure_deadline_at
    )
    envelope.open.request_head.protocol = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET
        if head.protocol is StreamProtocol.WEBSOCKET
        else runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_HTTP
    )
    envelope.open.request_head.method = head.method
    envelope.open.request_head.target = head.target
    envelope.open.request_head.headers.extend(
        runtime_stream_session_pb2.RuntimeStreamSessionHeader(
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
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
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
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
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
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.window_update.direction = _direction_proto(direction)
    envelope.window_update.stream_consumed_total = stream_consumed_total
    envelope.window_update.session_consumed_total = session_consumed_total
    return envelope


def _cancel_envelope(
    binding: GatewayStreamBinding, reason: CloseReason
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
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
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    envelope = _base_envelope(binding)
    envelope.frame_sequence = sequence
    envelope.websocket.direction = _direction_proto(direction)
    envelope.websocket.opcode = _websocket_opcode_proto(opcode)
    envelope.websocket.final = final
    envelope.websocket.data = data
    return envelope


def _direction_proto(
    direction: StreamDirection,
) -> runtime_stream_session_pb2.RuntimeStreamSessionDirection.ValueType:
    if direction is StreamDirection.REQUEST:
        return runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
    return runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE


def _direction(
    value: runtime_stream_session_pb2.RuntimeStreamSessionDirection.ValueType,
) -> StreamDirection:
    if value == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST:
        return StreamDirection.REQUEST
    if value == runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE:
        return StreamDirection.RESPONSE
    raise ValueError("Runtime Web direction is invalid")


_WEBSOCKET_OPCODE_TO_PROTO: dict[
    WebSocketOpcode,
    runtime_stream_session_pb2.RuntimeStreamSessionWebSocketOpcode.ValueType,
] = {
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
}
_PROTO_TO_WEBSOCKET_OPCODE = {
    value: opcode for opcode, value in _WEBSOCKET_OPCODE_TO_PROTO.items()
}


def _websocket_opcode_proto(
    opcode: WebSocketOpcode,
) -> runtime_stream_session_pb2.RuntimeStreamSessionWebSocketOpcode.ValueType:
    return _WEBSOCKET_OPCODE_TO_PROTO[opcode]


def _websocket_opcode(
    value: runtime_stream_session_pb2.RuntimeStreamSessionWebSocketOpcode.ValueType,
) -> WebSocketOpcode:
    try:
        return _PROTO_TO_WEBSOCKET_OPCODE[value]
    except KeyError:
        raise ValueError("Runtime WebSocket opcode is invalid") from None


_CLOSE_REASON_TO_PROTO: dict[
    CloseReason,
    runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.ValueType,
] = {
    CloseReason.CALLER: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER
    ),
    CloseReason.SERVICE_EXPIRED: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_SERVICE_EXPIRED
    ),
    CloseReason.AUTHORITY_REVOKED: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_AUTHORITY_REVOKED
    ),
    CloseReason.GENERATION_REPLACED: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_GENERATION_REPLACED
    ),
    CloseReason.DEADLINE: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_DEADLINE
    ),
    CloseReason.SERVICE_DRAIN: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_SERVICE_DRAIN
    ),
    CloseReason.OWNER_LOST: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_OWNER_LOST
    ),
    CloseReason.PROTOCOL_VIOLATION: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
    ),
    CloseReason.RESOURCE_EXHAUSTED: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_RESOURCE_EXHAUSTED
    ),
    CloseReason.APPLICATION_UNAVAILABLE: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_APPLICATION_UNAVAILABLE
    ),
    CloseReason.TRANSPORT_UNAVAILABLE: (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
    ),
}
_PROTO_TO_CLOSE_REASON = {
    value: reason for reason, value in _CLOSE_REASON_TO_PROTO.items()
}


def _close_reason_proto(
    reason: CloseReason,
) -> runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.ValueType:
    return _CLOSE_REASON_TO_PROTO[reason]


def _close_reason(
    value: runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.ValueType,
) -> CloseReason:
    try:
        return _PROTO_TO_CLOSE_REASON[value]
    except KeyError:
        raise ValueError("Runtime Web close reason is invalid") from None
