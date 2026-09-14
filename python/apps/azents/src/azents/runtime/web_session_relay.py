"""Inactive bounded one-hop relay pool for Runtime Web Owner sessions."""

from __future__ import annotations

import asyncio
import dataclasses
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Sequence
from typing import Protocol, Self, TypeVar

from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    CONTROL_RESERVE_BYTES,
    MAX_ENVELOPE_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    SESSION_WINDOW_BYTES,
    OwnerSessionEpoch,
)

from azents.runtime.web_session_broker import BrokerTarget

_MAX_PENDING_RELAY_ENVELOPES = 32
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_MAX_MISSED_HEARTBEATS = 2
_TaskResult = TypeVar("_TaskResult")
_IGNORED_TOMBSTONE_PAYLOADS = frozenset(
    {
        "window_update",
        "direction_end",
        "cancel",
        "reset",
        "stream_end",
    }
)


@dataclasses.dataclass(frozen=True)
class RelaySessionKey:
    """Exact remote Owner epoch and replacement protocol identity."""

    owner: OwnerSessionEpoch
    protocol_fingerprint: str

    def __post_init__(self) -> None:
        if self.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT:
            raise ValueError("Runtime Web relay fingerprint is incompatible")


@dataclasses.dataclass(frozen=True)
class RelaySourceStreamKey:
    """Exact source Gateway peer-session stream identity."""

    source_session_id: str
    source_peer_boot_id: str
    source_stream_id: int

    def __post_init__(self) -> None:
        if (
            not self.source_session_id
            or not self.source_peer_boot_id
            or self.source_stream_id <= 0
        ):
            raise ValueError("Runtime Web relay source stream identity is invalid")


@dataclasses.dataclass(frozen=True)
class RelayStreamBinding:
    """Bidirectional source-to-relay stream identity mapping."""

    source: RelaySourceStreamKey
    relay_stream_id: int


class PersistentRelayConnection(Protocol):
    """One already-authenticated persistent Control-to-Control session."""

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None: ...

    async def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


class ControlRelayStream(Protocol):
    """Generated persistent Control relay call surface."""

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope]: ...


class ControlRelayEnvelopeHandler(Protocol):
    """Dispatch one inbound Owner envelope to the accepting Control."""

    def __call__(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        /,
    ) -> Awaitable[None]: ...


class ControlRelayResources(Protocol):
    """Control process hard-limit accounting used by outbound relays."""

    def try_open_session(self) -> bool: ...

    def close_session(self) -> None: ...

    def try_begin_task(self) -> bool: ...

    def end_task(self) -> None: ...

    def try_reserve_envelope(
        self,
        *,
        application_bytes: int,
        control_bytes: int,
    ) -> bool: ...

    def release_envelope(
        self,
        *,
        application_bytes: int,
        control_bytes: int,
    ) -> None: ...


@dataclasses.dataclass(frozen=True)
class _BufferedRelayEnvelope:
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    application_bytes: int
    control_bytes: int


def _create_relay_task(
    resources: ControlRelayResources | None,
    task: Callable[[], Awaitable[_TaskResult]],
    *,
    name: str | None = None,
) -> asyncio.Task[_TaskResult]:
    """Create one relay task with an exactly paired process reservation."""
    if resources is not None and not resources.try_begin_task():
        raise RuntimeError("Runtime Web relay hard task limit is exhausted")
    released = False

    def release() -> None:
        nonlocal released
        if resources is not None and not released:
            resources.end_task()
            released = True

    async def run() -> _TaskResult:
        try:
            return await task()
        finally:
            release()

    managed = run()
    try:
        created = asyncio.create_task(managed, name=name)
    except BaseException:
        managed.close()
        release()
        raise
    created.add_done_callback(lambda _completed: release())
    return created


class GrpcPersistentControlRelay:
    """Own one exact byte-bounded Control-to-Owner persistent Relay RPC."""

    def __init__(
        self,
        *,
        key: RelaySessionKey,
        stream: ControlRelayStream,
        handler: ControlRelayEnvelopeHandler,
        local_peer_boot_id: str,
        resources: ControlRelayResources | None,
    ) -> None:
        self.key = key
        self.stream = stream
        self.handler = handler
        self.local_peer_boot_id = local_peer_boot_id
        self.resources = resources
        self.outbound: deque[_BufferedRelayEnvelope] = deque()
        self.outbound_bytes = 0
        self.condition = asyncio.Condition()
        self.receiver: asyncio.Task[None] | None = None
        self.closed = asyncio.Event()
        self.active = False
        self.failure: Exception | None = None
        self.session_reserved = False
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.heartbeat_sequence = 0
        self.heartbeat_acknowledged_sequence = 0

    @classmethod
    async def connect(
        cls,
        *,
        key: RelaySessionKey,
        stream: ControlRelayStream,
        hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        handler: ControlRelayEnvelopeHandler,
        timeout_seconds: float,
        resources: ControlRelayResources | None,
    ) -> Self:
        """Start and authenticate one exact persistent Owner relay."""
        if timeout_seconds <= 0:
            raise ValueError("Runtime Web relay handshake timeout must be positive")
        if not _matches_epoch(hello, key) or not hello.peer_boot_id:
            raise ValueError("Runtime Web relay hello identity is stale")
        relay = cls(
            key=key,
            stream=stream,
            handler=handler,
            local_peer_boot_id=hello.peer_boot_id,
            resources=resources,
        )
        if resources is not None:
            if not resources.try_open_session():
                raise RuntimeError("Runtime Web relay hard session limit is exhausted")
            relay.session_reserved = True
        accepted = asyncio.get_running_loop().create_future()
        relay.active = True
        try:
            responses = stream(relay._outbound_messages(hello))
        except Exception:
            relay.active = False
            relay.closed.set()
            await relay.close()
            raise
        try:
            relay.receiver = _create_relay_task(
                resources,
                lambda: relay._receive(responses, accepted),
                name=f"runtime-web-control-relay-reader:{key.owner.session_lease_id}",
            )
        except Exception:
            await relay.close()
            raise
        try:
            await asyncio.wait_for(accepted, timeout_seconds)
        except asyncio.CancelledError:
            await relay.close()
            raise
        except Exception:
            await relay.close()
            raise
        try:
            relay.heartbeat_task = _create_relay_task(
                resources,
                relay._heartbeat_loop,
                name=(
                    f"runtime-web-control-relay-heartbeat:{key.owner.session_lease_id}"
                ),
            )
        except Exception:
            await relay.close()
            raise
        return relay

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        """Queue one exact byte-bounded relay envelope without replay."""
        if (
            not _matches_epoch(envelope, self.key)
            or envelope.peer_boot_id != self.local_peer_boot_id
        ):
            raise ValueError("Runtime Web relay envelope identity is stale")
        size_bytes = envelope.ByteSize()
        if not 1 <= size_bytes <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web relay envelope size is invalid")
        application_bytes = _application_bytes(envelope)
        control_bytes = size_bytes - application_bytes
        reserved = False
        async with self.condition:
            await self.condition.wait_for(
                lambda: (
                    (
                        len(self.outbound) < _MAX_PENDING_RELAY_ENVELOPES
                        and self.outbound_bytes + size_bytes
                        <= SESSION_WINDOW_BYTES + CONTROL_RESERVE_BYTES
                    )
                    or not self.active
                )
            )
            if not self.active or self.receiver is None or self.receiver.done():
                raise RuntimeError("Runtime Web relay session is not active") from (
                    self.failure
                )
            if self.resources is not None:
                if not self.resources.try_reserve_envelope(
                    application_bytes=application_bytes,
                    control_bytes=control_bytes,
                ):
                    raise RuntimeError(
                        "Runtime Web relay hard queue limit is exhausted"
                    )
                reserved = True
            queued = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            try:
                queued.CopyFrom(envelope)
                self.outbound.append(
                    _BufferedRelayEnvelope(
                        envelope=queued,
                        application_bytes=application_bytes,
                        control_bytes=control_bytes,
                    )
                )
                self.outbound_bytes += size_bytes
                self.condition.notify_all()
            except BaseException:
                if self.resources is not None and reserved:
                    self.resources.release_envelope(
                        application_bytes=application_bytes,
                        control_bytes=control_bytes,
                    )
                raise

    async def close(self) -> None:
        """Close once and discard queued envelopes without replay."""
        async with self.condition:
            self.active = False
            buffered = tuple(self.outbound)
            self.outbound.clear()
            self.outbound_bytes = 0
            receiver = self.receiver
            self.receiver = None
            heartbeat_task = self.heartbeat_task
            self.heartbeat_task = None
            self.condition.notify_all()
        self._release_buffered(buffered)
        if receiver is not None:
            if not receiver.done():
                receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
        if heartbeat_task is not None and heartbeat_task is not asyncio.current_task():
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        if self.session_reserved:
            resources = self.resources
            if resources is not None:
                resources.close_session()
            self.session_reserved = False
        self.closed.set()

    async def wait_closed(self) -> None:
        """Wait until receiver failure or explicit close is complete."""
        await self.closed.wait()

    async def _outbound_messages(
        self, hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        yield hello
        while True:
            async with self.condition:
                await self.condition.wait_for(
                    lambda: bool(self.outbound) or not self.active
                )
                if not self.active:
                    return
                buffered = self.outbound.popleft()
                self.outbound_bytes -= buffered.envelope.ByteSize()
                self.condition.notify_all()
            self._release_buffered((buffered,))
            yield buffered.envelope

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        accepted: asyncio.Future[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
    ) -> None:
        first = True
        try:
            async for envelope in responses:
                if not 1 <= envelope.ByteSize() <= MAX_ENVELOPE_BYTES:
                    raise RuntimeError("Runtime Web relay envelope size is invalid")
                if (
                    not _matches_epoch(envelope, self.key)
                    or envelope.peer_boot_id != self.key.owner.owner_boot_id
                ):
                    raise RuntimeError("Runtime Web relay response identity changed")
                if first:
                    first = False
                    if envelope.WhichOneof("payload") != "session_accepted":
                        raise RuntimeError("Runtime Web relay acceptance must be first")
                    accepted.set_result(envelope)
                    continue
                if envelope.WhichOneof("payload") == "heartbeat_ack":
                    sequence = envelope.heartbeat_ack.monotonic_sequence
                    if (
                        envelope.stream_id != 0
                        or sequence <= self.heartbeat_acknowledged_sequence
                        or sequence > self.heartbeat_sequence
                    ):
                        raise RuntimeError(
                            "Runtime Web relay heartbeat acknowledgement is invalid"
                        )
                    self.heartbeat_acknowledged_sequence = sequence
                    continue
                await self.handler(envelope)
            if not accepted.done():
                accepted.set_exception(
                    RuntimeError("Runtime Web relay closed before acceptance")
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
                buffered = tuple(self.outbound)
                self.outbound.clear()
                self.outbound_bytes = 0
                self.condition.notify_all()
            self._release_buffered(buffered)
            self.closed.set()

    async def _heartbeat_loop(self) -> None:
        """Send application-independent heartbeats and fail after two misses."""
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            if not self.active:
                return
            if (
                self.heartbeat_sequence - self.heartbeat_acknowledged_sequence
                >= _MAX_MISSED_HEARTBEATS
            ):
                self.failure = TimeoutError(
                    "Runtime Web relay heartbeat acknowledgement timed out"
                )
                receiver = self.receiver
                if receiver is not None:
                    receiver.cancel()
                return
            self.heartbeat_sequence += 1
            owner = self.key.owner
            heartbeat = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
                protocol_fingerprint=self.key.protocol_fingerprint,
                session_id=owner.session_lease_id,
                peer_boot_id=self.local_peer_boot_id,
                owner_boot_id=owner.owner_boot_id,
                session_lease_id=owner.session_lease_id,
                lease_generation=owner.lease_generation,
            )
            heartbeat.heartbeat.monotonic_sequence = self.heartbeat_sequence
            try:
                await self.send(heartbeat)
            except RuntimeError:
                return

    def _release_buffered(
        self,
        buffered: tuple[_BufferedRelayEnvelope, ...],
    ) -> None:
        resources = self.resources
        if resources is None:
            return
        for item in buffered:
            resources.release_envelope(
                application_bytes=item.application_bytes,
                control_bytes=item.control_bytes,
            )


class RelayConnector(Protocol):
    """Create one persistent connection for an exact remote Owner epoch."""

    async def __call__(self, key: RelaySessionKey) -> PersistentRelayConnection: ...


class RuntimeWebRelayPool:
    """Reuse one bounded relay per Owner epoch without retry or replay."""

    def __init__(
        self,
        *,
        connector: RelayConnector,
        maximum_sessions: int,
        peer_boot_id: str,
    ) -> None:
        if maximum_sessions <= 0 or not peer_boot_id:
            raise ValueError("Runtime Web relay pool settings are invalid")
        self.connector = connector
        self.maximum_sessions = maximum_sessions
        self.peer_boot_id = peer_boot_id
        self.resources: ControlRelayResources | None = None
        self.sessions: dict[RelaySessionKey, PersistentRelayConnection] = {}
        self.monitors: dict[RelaySessionKey, asyncio.Task[None]] = {}
        self.next_stream_ids: dict[RelaySessionKey, int] = {}
        self.source_bindings: dict[
            tuple[RelaySessionKey, RelaySourceStreamKey], RelayStreamBinding
        ] = {}
        self.relay_bindings: dict[tuple[RelaySessionKey, int], RelayStreamBinding] = {}
        self.relay_tombstones: deque[tuple[RelaySessionKey, int]] = deque(
            maxlen=MAX_STREAM_TOMBSTONES
        )
        self.relay_tombstone_set: set[tuple[RelaySessionKey, int]] = set()
        self.source_tombstones: deque[tuple[RelaySessionKey, RelaySourceStreamKey]] = (
            deque(maxlen=MAX_STREAM_TOMBSTONES)
        )
        self.source_tombstone_set: set[tuple[RelaySessionKey, RelaySourceStreamKey]] = (
            set()
        )
        self.lock = asyncio.Lock()

    def bind_resources(self, resources: ControlRelayResources) -> None:
        """Bind the process-wide Control task budget before relay use."""
        if self.resources is not None and self.resources is not resources:
            raise RuntimeError("Runtime Web relay resources are already bound")
        self.resources = resources

    async def forward(
        self,
        *,
        target: BrokerTarget,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> RelayStreamBinding | None:
        """Map and send one source envelope over exactly one persistent relay."""
        if target.local or target.relay_count != 1:
            raise ValueError("Runtime Web relay requires one remote Owner hop")
        if envelope.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT:
            raise ValueError("Runtime Web relay envelope fingerprint is incompatible")
        if not 1 <= envelope.ByteSize() <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web relay envelope size is invalid")
        if (
            envelope.HasField("owner_boot_id")
            and envelope.owner_boot_id != target.owner.owner_boot_id
        ):
            raise ValueError("Runtime Web relay envelope Owner epoch is stale")
        if (
            envelope.HasField("session_lease_id")
            and envelope.session_lease_id != target.owner.session_lease_id
        ):
            raise ValueError("Runtime Web relay envelope Owner epoch is stale")
        if (
            envelope.HasField("lease_generation")
            and envelope.lease_generation != target.owner.lease_generation
        ):
            raise ValueError("Runtime Web relay envelope Owner epoch is stale")
        source = RelaySourceStreamKey(
            source_session_id=envelope.session_id,
            source_peer_boot_id=envelope.peer_boot_id,
            source_stream_id=envelope.stream_id,
        )
        key = RelaySessionKey(target.owner, RUNTIME_WEB_PROTOCOL_FINGERPRINT)
        routed = await self._route(
            key,
            source,
            create=envelope.WhichOneof("payload") == "open",
            payload=envelope.WhichOneof("payload"),
        )
        if routed is None:
            return None
        connection, binding = routed
        forwarded = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
        forwarded.CopyFrom(envelope)
        forwarded.session_id = key.owner.session_lease_id
        forwarded.peer_boot_id = self.peer_boot_id
        forwarded.owner_boot_id = key.owner.owner_boot_id
        forwarded.session_lease_id = key.owner.session_lease_id
        forwarded.lease_generation = key.owner.lease_generation
        forwarded.stream_id = binding.relay_stream_id
        try:
            await connection.send(forwarded)
        except asyncio.CancelledError:
            await self.retire(key, connection)
            raise
        except Exception:
            await self.retire(key, connection)
            raise
        return binding

    async def route_response(
        self,
        *,
        key: RelaySessionKey,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope | None:
        """Translate one exact Owner relay stream ID back to its source session."""
        if (
            not _matches_epoch(envelope, key)
            or envelope.peer_boot_id != key.owner.owner_boot_id
        ):
            raise ValueError("Runtime Web relay response identity is stale")
        if not 1 <= envelope.ByteSize() <= MAX_ENVELOPE_BYTES:
            raise ValueError("Runtime Web relay response size is invalid")
        async with self.lock:
            binding = self.relay_bindings.get((key, envelope.stream_id))
            if binding is None:
                if (key, envelope.stream_id) in self.relay_tombstone_set:
                    return None
                raise ValueError("Runtime Web relay response stream is unknown")
            translated = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
            translated.CopyFrom(envelope)
            translated.session_id = binding.source.source_session_id
            translated.peer_boot_id = self.peer_boot_id
            translated.stream_id = binding.source.source_stream_id
            if envelope.WhichOneof("payload") == "open_accepted":
                if (
                    envelope.open_accepted.route_path
                    != runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL
                ):
                    raise ValueError(
                        "Runtime Web Owner-local route acceptance is invalid"
                    )
                translated.open_accepted.route_path = (
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_ROUTE_PATH_RELAY
                )
            if envelope.WhichOneof("payload") in {
                "open_rejected",
                "reset",
                "stream_end",
            }:
                self._release_binding(key, binding)
            return translated

    async def retire(
        self,
        key: RelaySessionKey,
        connection: PersistentRelayConnection,
    ) -> bool:
        """Retire only the exact failed relay connection and all its mappings."""
        return await self._retire(key, connection, from_monitor=False)

    async def close(self) -> None:
        """Attempt every relay close, then report aggregated failures."""
        async with self.lock:
            sessions = tuple(self.sessions.values())
            monitors = tuple(self.monitors.values())
            self.sessions.clear()
            self.monitors.clear()
            self.next_stream_ids.clear()
            self.source_bindings.clear()
            self.relay_bindings.clear()
        for monitor in monitors:
            monitor.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)
        results = await asyncio.gather(
            *(session.close() for session in sessions),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Runtime Web relay close failed", errors)

    async def _route(
        self,
        key: RelaySessionKey,
        source: RelaySourceStreamKey,
        *,
        create: bool,
        payload: str | None,
    ) -> tuple[PersistentRelayConnection, RelayStreamBinding] | None:
        async with self.lock:
            mapping_key = (key, source)
            binding = self.source_bindings.get(mapping_key)
            if binding is None and mapping_key in self.source_tombstone_set:
                if not create and payload in _IGNORED_TOMBSTONE_PAYLOADS:
                    return None
                raise ValueError("Runtime Web relay source stream is not reusable")
            if binding is None and not create:
                raise ValueError("Runtime Web relay source stream is unknown")
            connection = self.sessions.get(key)
            if connection is None:
                if len(self.sessions) >= self.maximum_sessions:
                    raise RuntimeError(
                        "Runtime Web relay session capacity is exhausted"
                    )
                connection = await self.connector(key)
                self.sessions[key] = connection
                try:
                    monitor = _create_relay_task(
                        self.resources,
                        lambda: self._monitor(key, connection),
                        name=(
                            "runtime-web-control-relay-monitor:"
                            f"{key.owner.session_lease_id}"
                        ),
                    )
                except Exception:
                    self.sessions.pop(key)
                    await connection.close()
                    raise
                self.monitors[key] = monitor
            if binding is None:
                relay_stream_id = self.next_stream_ids.get(key, 1)
                self.next_stream_ids[key] = relay_stream_id + 1
                binding = RelayStreamBinding(source, relay_stream_id)
                self.source_bindings[mapping_key] = binding
                self.relay_bindings[(key, relay_stream_id)] = binding
            return connection, binding

    async def _monitor(
        self,
        key: RelaySessionKey,
        connection: PersistentRelayConnection,
    ) -> None:
        await connection.wait_closed()
        await self._retire(key, connection, from_monitor=True)

    async def _retire(
        self,
        key: RelaySessionKey,
        connection: PersistentRelayConnection,
        *,
        from_monitor: bool,
    ) -> bool:
        async with self.lock:
            if self.sessions.get(key) is not connection:
                return False
            self.sessions.pop(key)
            monitor = self.monitors.pop(key, None)
            self.next_stream_ids.pop(key, None)
            bindings = tuple(
                binding
                for (binding_key, _), binding in self.source_bindings.items()
                if binding_key == key
            )
            for binding in bindings:
                self._release_binding(key, binding)
        if monitor is not None and not from_monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await connection.close()
        return True

    def _release_binding(
        self, key: RelaySessionKey, binding: RelayStreamBinding
    ) -> None:
        self.source_bindings.pop((key, binding.source), None)
        self.relay_bindings.pop((key, binding.relay_stream_id), None)
        source_tombstone = (key, binding.source)
        if len(self.source_tombstones) == MAX_STREAM_TOMBSTONES:
            expired_source = self.source_tombstones.popleft()
            self.source_tombstone_set.remove(expired_source)
        self.source_tombstones.append(source_tombstone)
        self.source_tombstone_set.add(source_tombstone)
        tombstone = (key, binding.relay_stream_id)
        if len(self.relay_tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.relay_tombstones.popleft()
            self.relay_tombstone_set.remove(expired)
        self.relay_tombstones.append(tombstone)
        self.relay_tombstone_set.add(tombstone)


def _matches_epoch(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    key: RelaySessionKey,
) -> bool:
    return (
        envelope.protocol_fingerprint == key.protocol_fingerprint
        and envelope.session_id == key.owner.session_lease_id
        and envelope.HasField("owner_boot_id")
        and envelope.owner_boot_id == key.owner.owner_boot_id
        and envelope.HasField("session_lease_id")
        and envelope.session_lease_id == key.owner.session_lease_id
        and envelope.HasField("lease_generation")
        and envelope.lease_generation == key.owner.lease_generation
    )


def _application_bytes(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> int:
    payload = envelope.WhichOneof("payload")
    if payload == "data":
        return len(envelope.data.data)
    if payload == "websocket":
        return len(envelope.websocket.data)
    return 0
