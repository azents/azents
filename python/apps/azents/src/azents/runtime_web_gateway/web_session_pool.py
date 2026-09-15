"""Inactive Gateway-side pool for replacement Runtime Web peer sessions."""

from __future__ import annotations

import asyncio
import dataclasses
from collections import deque
from collections.abc import Awaitable
from typing import Protocol

from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import AbsoluteCreditWindow
from azents_runtime_control.runtime_web_session import (
    CloseReason,
    LogicalStreamState,
    PeerSessionState,
    RequestHead,
    SessionIdentity,
    SessionPeerRole,
    SessionProfile,
    SessionState,
    StreamAuthority,
)

from azents.runtime_web_gateway.operations import RuntimeWebGatewayResourceTracker


class GatewayStreamHandler(Protocol):
    """Receive frames and fail one logical stream on session loss."""

    def __call__(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        /,
    ) -> Awaitable[None]: ...

    async def fail_transport(self) -> None: ...

    async def fail_go_away(self, reason: CloseReason) -> None: ...


class GatewaySessionTransport(Protocol):
    """One exact persistent transport associated with a pool registration."""

    request_session_credit: AbsoluteCreditWindow
    response_session_credit: AbsoluteCreditWindow
    credit_condition: asyncio.Condition
    resources: RuntimeWebGatewayResourceTracker

    async def bind(
        self,
        stream_id: int,
        handler: GatewayStreamHandler,
    ) -> None: ...

    async def unbind(self, stream_id: int) -> None: ...

    async def send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None: ...


@dataclasses.dataclass(frozen=True)
class GatewaySessionRegistration:
    """Exact process-local registration identity for one peer connection."""

    session_id: str
    peer_boot_id: str
    registration_id: int


@dataclasses.dataclass(frozen=True)
class GatewayStreamBinding:
    """One logical stream bound to one exact Gateway peer session."""

    registration: GatewaySessionRegistration
    stream_id: int
    state: LogicalStreamState = dataclasses.field(compare=False, repr=False)
    transport: GatewaySessionTransport = dataclasses.field(compare=False, repr=False)

    @property
    def session_id(self) -> str:
        """Return the wire session identity for correlation."""
        return self.registration.session_id


@dataclasses.dataclass
class _RegisteredSession:
    registration: GatewaySessionRegistration
    state: PeerSessionState
    transport: GatewaySessionTransport


class RuntimeWebGatewaySessionPool:
    """Select bounded active Gateway sessions without application replay."""

    def __init__(self, *, maximum_sessions: int) -> None:
        if maximum_sessions <= 0:
            raise ValueError("Runtime Web Gateway session limit must be positive")
        self.maximum_sessions = maximum_sessions
        self.sessions: dict[str, _RegisteredSession] = {}
        self.retired_session_ids: deque[str] = deque(
            maxlen=max(16, maximum_sessions * 4)
        )
        self.retired_session_id_set: set[str] = set()
        self.next_registration_id = 1
        self.lock = asyncio.Lock()

    async def register(
        self,
        *,
        identity: SessionIdentity,
        profile: SessionProfile,
        transport: GatewaySessionTransport,
    ) -> GatewaySessionRegistration:
        """Register one already-authenticated active Gateway peer session."""
        if identity.role is not SessionPeerRole.GATEWAY:
            raise ValueError("Runtime Web Gateway pool requires a Gateway session")
        state = PeerSessionState(identity=identity)
        state.hello_sent()
        state.accept(profile)
        async with self.lock:
            if (
                identity.session_id in self.sessions
                or identity.session_id in self.retired_session_id_set
            ):
                raise ValueError("Runtime Web Gateway session ID is not reusable")
            if len(self.sessions) >= self.maximum_sessions:
                raise ValueError("Runtime Web Gateway session capacity is exhausted")
            registration = GatewaySessionRegistration(
                session_id=identity.session_id,
                peer_boot_id=identity.peer_boot_id,
                registration_id=self.next_registration_id,
            )
            self.next_registration_id += 1
            self.sessions[identity.session_id] = _RegisteredSession(
                registration=registration,
                state=state,
                transport=transport,
            )
            return registration

    async def open(
        self,
        *,
        stream_id: int,
        authority: StreamAuthority,
        request_head: RequestHead,
    ) -> GatewayStreamBinding:
        """Bind a new stream to the least-loaded active session."""
        async with self.lock:
            candidates = [
                session
                for session in self.sessions.values()
                if session.state.state is SessionState.ACTIVE
            ]
            if not candidates:
                raise RuntimeError("Runtime Web Gateway has no active Control session")
            session = min(
                candidates,
                key=lambda item: (
                    len(item.state.streams),
                    item.registration.session_id,
                ),
            )
            stream = session.state.open_stream(
                stream_id=stream_id,
                authority=authority,
                request_head=request_head,
            )
            return GatewayStreamBinding(
                registration=session.registration,
                stream_id=stream_id,
                state=stream,
                transport=session.transport,
            )

    async def release(self, binding: GatewayStreamBinding) -> bool:
        """Release one exact terminal binding into bounded session tombstones."""
        async with self.lock:
            session = self.sessions.get(binding.session_id)
            if (
                session is None
                or session.registration != binding.registration
                or session.state.streams.get(binding.stream_id) is not binding.state
            ):
                return False
            session.state.release_stream(binding.stream_id)
            return True

    async def active_session_count(self) -> int:
        """Return the number of exact active Control sessions."""
        async with self.lock:
            return sum(
                session.state.state is SessionState.ACTIVE
                for session in self.sessions.values()
            )

    async def start_draining(
        self,
        registration: GatewaySessionRegistration,
        *,
        last_accepted_stream_id: int,
    ) -> tuple[int, ...]:
        """Fence new opens and return work above the peer GOAWAY boundary."""
        async with self.lock:
            session = self.sessions.get(registration.session_id)
            if session is None or session.registration != registration:
                raise RuntimeError("Runtime Web Gateway session registration is stale")
            effective_boundary = min(
                last_accepted_stream_id,
                session.state.last_stream_id,
            )
            return session.state.start_draining(effective_boundary)

    async def close_session(
        self, registration: GatewaySessionRegistration
    ) -> tuple[GatewayStreamBinding, ...]:
        """Close one exact failed connection and return active work only."""
        async with self.lock:
            session = self.sessions.get(registration.session_id)
            if session is None or session.registration != registration:
                return ()
            self.sessions.pop(registration.session_id)
            failed = tuple(
                GatewayStreamBinding(
                    registration=registration,
                    stream_id=stream_id,
                    state=stream,
                    transport=session.transport,
                )
                for stream_id, stream in sorted(session.state.streams.items())
                if not stream.snapshot().completed
                and stream.snapshot().terminal_reason is None
            )
            session.state.close()
            self._retire(registration.session_id)
            return failed

    def _retire(self, session_id: str) -> None:
        if len(self.retired_session_ids) == self.retired_session_ids.maxlen:
            expired = self.retired_session_ids.popleft()
            self.retired_session_id_set.remove(expired)
        self.retired_session_ids.append(session_id)
        self.retired_session_id_set.add(session_id)
