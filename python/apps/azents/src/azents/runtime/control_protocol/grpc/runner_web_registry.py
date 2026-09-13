"""Process-local owner registry for bounded Runtime Web tunnel frames."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import assert_never

from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES,
    RunnerWebBodyChunk,
    RunnerWebCancel,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebHeartbeat,
    RunnerWebHeartbeatAcknowledgement,
    RunnerWebIdentity,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebSocketFrame,
    RunnerWebSocketOpcode,
    RunnerWebStreamAccepted,
    RunnerWebStreamEnd,
    RunnerWebStreamError,
    RunnerWebStreamErrorCode,
)

from azents.repos.runtime_web.data import RuntimeWebTunnelRoute

_DEFAULT_PENDING_BYTES = 256 * 1024
_MAX_PENDING_FRAMES = _DEFAULT_PENDING_BYTES // MAX_RUNTIME_WEB_FRAME_BYTES


class RuntimeWebTunnelAdmissionError(RuntimeError):
    """Bounded tunnel join or frame rejection."""

    def __init__(self, code: RunnerWebStreamErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class RuntimeWebOwnerRegistry:
    """Own process-local tunnel rendezvous without persisting application bytes."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        self.tunnels: dict[str, RuntimeWebOwnerTunnel] = {}
        self.lock = asyncio.Lock()

    async def create_owner(
        self,
        route: RuntimeWebTunnelRoute,
    ) -> "RuntimeWebOwnerTunnel":
        """Create the only local owner for a newly acquired durable route."""
        tunnel = RuntimeWebOwnerTunnel(route=route, clock=self.clock)
        async with self.lock:
            if route.authority.tunnel_id in self.tunnels:
                raise RuntimeWebTunnelAdmissionError(
                    RunnerWebStreamErrorCode.DUPLICATE_JOIN
                )
            self.tunnels[route.authority.tunnel_id] = tunnel
        return tunnel

    async def join_runner(
        self,
        identity: RunnerWebIdentity,
    ) -> "RuntimeWebRunnerTunnel":
        """Join one Runner to the exact local owner route."""
        async with self.lock:
            tunnel = self.tunnels.get(identity.tunnel_id)
        if tunnel is None:
            raise RuntimeWebTunnelAdmissionError(RunnerWebStreamErrorCode.STALE_ROUTE)
        return await tunnel.join_runner(identity)

    async def release(self, tunnel: "RuntimeWebOwnerTunnel") -> None:
        """Remove one owner only when it is still the registered instance."""
        async with self.lock:
            if self.tunnels.get(tunnel.identity.tunnel_id) is tunnel:
                self.tunnels.pop(tunnel.identity.tunnel_id, None)
        await tunnel.close()


class RuntimeWebOwnerTunnel:
    """Owner-facing half of one exact Runtime Web tunnel."""

    def __init__(
        self,
        *,
        route: RuntimeWebTunnelRoute,
        clock: Callable[[], datetime],
    ) -> None:
        self.route = route
        self.identity = _runner_identity(route)
        self.clock = clock
        self.control_queue: asyncio.Queue[RunnerWebControlFrame | None] = asyncio.Queue(
            maxsize=_MAX_PENDING_FRAMES
        )
        self.event_queue: asyncio.Queue[RunnerWebEventFrame | None] = asyncio.Queue(
            maxsize=_MAX_PENDING_FRAMES
        )
        self.runner_joined = asyncio.Event()
        self.lock = asyncio.Lock()
        self.joined = False
        self.closed = False
        self.request_protocol: RunnerWebProtocol | None = None
        self.request_sequence = 1
        self.request_ended = False
        self.request_websocket_opcode: RunnerWebSocketOpcode | None = None
        self.request_websocket_bytes = 0
        self.response_started = False
        self.response_sequence = 1
        self.response_ended = False
        self.response_websocket_opcode: RunnerWebSocketOpcode | None = None
        self.response_websocket_bytes = 0
        self.server_sent_events = False

    @property
    def allows_replaced_cycle(self) -> bool:
        """Allow only finite HTTP to finish after a replacement approval."""
        return (
            self.request_protocol is RunnerWebProtocol.HTTP
            and not self.server_sent_events
        )

    async def join_runner(
        self,
        identity: RunnerWebIdentity,
    ) -> "RuntimeWebRunnerTunnel":
        """Admit one exact nonce/generation Runner join."""
        async with self.lock:
            if self.closed or self.clock() >= self.identity.registration_deadline_at:
                raise RuntimeWebTunnelAdmissionError(
                    RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
                )
            if identity != self.identity:
                raise RuntimeWebTunnelAdmissionError(
                    RunnerWebStreamErrorCode.STALE_AUTHORITY
                )
            if self.joined:
                raise RuntimeWebTunnelAdmissionError(
                    RunnerWebStreamErrorCode.DUPLICATE_JOIN
                )
            self.joined = True
            self.runner_joined.set()
        return RuntimeWebRunnerTunnel(self)

    async def wait_for_runner(self) -> None:
        """Wait only until the fixed registration deadline."""
        remaining = (
            self.identity.registration_deadline_at - self.clock()
        ).total_seconds()
        if remaining <= 0:
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
            )
        try:
            await asyncio.wait_for(self.runner_joined.wait(), timeout=remaining)
        except TimeoutError:
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
            ) from None

    async def send(self, frame: RunnerWebControlFrame) -> None:
        """Validate and forward one owner/Gateway control frame."""
        async with self.lock:
            if self.closed:
                raise RuntimeWebTunnelAdmissionError(
                    RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE
                )
            self._validate_control(frame)
        await self.control_queue.put(frame)
        if isinstance(frame, RunnerWebCancel | RunnerWebStreamError):
            await self.close()

    def events(self) -> AsyncIterator[RunnerWebEventFrame]:
        """Yield ordered Runner frames with queue backpressure."""
        return self._events()

    async def close(self) -> None:
        """Close both halves and unblock current consumers."""
        async with self.lock:
            if self.closed:
                return
            self.closed = True
        _finish_queue(self.control_queue)
        _finish_queue(self.event_queue)

    async def _receive_runner(self, frame: RunnerWebEventFrame) -> None:
        async with self.lock:
            if self.closed:
                return
            self._validate_event(frame)
        await self.event_queue.put(frame)
        if isinstance(frame, RunnerWebStreamEnd | RunnerWebStreamError):
            await self.close()

    async def _events(self) -> AsyncIterator[RunnerWebEventFrame]:
        while True:
            frame = await self.event_queue.get()
            if frame is None:
                return
            yield frame

    async def _controls(self) -> AsyncIterator[RunnerWebControlFrame]:
        while True:
            frame = await self.control_queue.get()
            if frame is None:
                return
            yield frame

    def _validate_control(self, frame: RunnerWebControlFrame) -> None:
        match frame:
            case RunnerWebRequestHead(identity=identity, protocol=protocol):
                if self.request_protocol is not None or identity != self.identity:
                    self._protocol_violation()
                self.request_protocol = protocol
            case RunnerWebBodyChunk(sequence=sequence):
                if (
                    self.request_protocol is not RunnerWebProtocol.HTTP
                    or self.request_ended
                    or sequence != self.request_sequence
                ):
                    self._protocol_violation()
                self.request_sequence += 1
            case RunnerWebStreamEnd(final_sequence=final_sequence):
                if (
                    self.request_protocol is None
                    or self.request_ended
                    or self.request_websocket_opcode is not None
                    or final_sequence != self.request_sequence - 1
                ):
                    self._protocol_violation()
                self.request_ended = True
            case RunnerWebSocketFrame(
                sequence=sequence,
                opcode=opcode,
                final=final,
                data=data,
            ):
                if (
                    self.request_protocol is not RunnerWebProtocol.WEBSOCKET
                    or sequence != self.request_sequence
                ):
                    self._protocol_violation()
                self.request_sequence += 1
                if opcode in {
                    RunnerWebSocketOpcode.PING,
                    RunnerWebSocketOpcode.PONG,
                    RunnerWebSocketOpcode.CLOSE,
                }:
                    if self.request_websocket_opcode is not None or not final:
                        self._protocol_violation()
                else:
                    if self.request_websocket_opcode is None:
                        self.request_websocket_opcode = opcode
                    elif self.request_websocket_opcode is not opcode:
                        self._protocol_violation()
                    self.request_websocket_bytes += len(data)
                    if (
                        self.request_websocket_bytes
                        > MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES
                    ):
                        self._protocol_violation()
                    if final:
                        self.request_websocket_opcode = None
                        self.request_websocket_bytes = 0
            case (
                RunnerWebHeartbeat()
                | RunnerWebHeartbeatAcknowledgement()
                | RunnerWebCancel()
                | RunnerWebStreamError()
            ):
                pass
            case _ as unreachable:
                assert_never(unreachable)

    def _validate_event(self, frame: RunnerWebEventFrame) -> None:
        match frame:
            case RunnerWebResponseHead(headers=headers):
                if self.response_started:
                    self._protocol_violation()
                self.response_started = True
                self.server_sent_events = any(
                    header.name.lower() == b"content-type"
                    and header.value.split(b";", 1)[0].strip().lower()
                    == b"text/event-stream"
                    for header in headers
                )
            case RunnerWebBodyChunk(sequence=sequence):
                if (
                    not self.response_started
                    or self.response_ended
                    or self.request_protocol is not RunnerWebProtocol.HTTP
                    or sequence != self.response_sequence
                ):
                    self._protocol_violation()
                self.response_sequence += 1
            case RunnerWebStreamEnd(final_sequence=final_sequence):
                if (
                    not self.response_started
                    or self.response_ended
                    or self.response_websocket_opcode is not None
                    or final_sequence != self.response_sequence - 1
                ):
                    self._protocol_violation()
                self.response_ended = True
            case RunnerWebSocketFrame(
                sequence=sequence,
                opcode=opcode,
                final=final,
                data=data,
            ):
                if (
                    not self.response_started
                    or self.request_protocol is not RunnerWebProtocol.WEBSOCKET
                    or sequence != self.response_sequence
                ):
                    self._protocol_violation()
                self.response_sequence += 1
                if opcode in {
                    RunnerWebSocketOpcode.PING,
                    RunnerWebSocketOpcode.PONG,
                    RunnerWebSocketOpcode.CLOSE,
                }:
                    if self.response_websocket_opcode is not None or not final:
                        self._protocol_violation()
                else:
                    if self.response_websocket_opcode is None:
                        self.response_websocket_opcode = opcode
                    elif self.response_websocket_opcode is not opcode:
                        self._protocol_violation()
                    self.response_websocket_bytes += len(data)
                    if (
                        self.response_websocket_bytes
                        > MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES
                    ):
                        self._protocol_violation()
                    if final:
                        self.response_websocket_opcode = None
                        self.response_websocket_bytes = 0
            case (
                RunnerWebHeartbeat()
                | RunnerWebHeartbeatAcknowledgement()
                | RunnerWebStreamError()
            ):
                pass
            case _ as unreachable:
                assert_never(unreachable)

    @staticmethod
    def _protocol_violation() -> None:
        raise RuntimeWebTunnelAdmissionError(
            RunnerWebStreamErrorCode.PROTOCOL_VIOLATION
        )


class RuntimeWebRunnerTunnel:
    """Runner-facing half joined to one process-local owner."""

    def __init__(self, owner: RuntimeWebOwnerTunnel) -> None:
        self.owner = owner
        self.accepted = RunnerWebStreamAccepted(tunnel_id=owner.identity.tunnel_id)

    async def receive(self, frame: RunnerWebEventFrame) -> None:
        """Forward one validated Runner event toward the owner."""
        await self.owner._receive_runner(frame)

    def control_frames(self) -> AsyncIterator[RunnerWebControlFrame]:
        """Yield owner controls until either half closes."""
        return self.owner._controls()

    async def close(self) -> None:
        """Detach the Runner and terminate this non-resumable transport."""
        await self.owner.close()


def _runner_identity(route: RuntimeWebTunnelRoute) -> RunnerWebIdentity:
    authority = route.authority
    return RunnerWebIdentity(
        tunnel_id=authority.tunnel_id,
        endpoint_id=authority.endpoint_id,
        cycle_id=authority.cycle_id,
        endpoint_authority_revision=authority.endpoint_authority_revision,
        close_barrier=authority.close_barrier,
        runtime_id=authority.runtime_id,
        desired_generation=authority.desired_generation,
        runner_generation=authority.runner_generation,
        port=authority.port,
        join_nonce=authority.join_nonce,
        registration_deadline_at=authority.registration_deadline_at,
        approval_deadline_at=authority.approval_deadline_at,
        transport_deadline_at=authority.transport_deadline_at,
    )


def _finish_queue[FrameT](queue: asyncio.Queue[FrameT | None]) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(None)
