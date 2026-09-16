"""Production lifecycle for persistent Gateway-to-Control Runtime Web sessions."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import random
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

import grpc
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    SessionIdentity,
    SessionPeerRole,
    SessionProfile,
)

from azents.runtime_web_gateway.operations import RuntimeWebGatewayResourceTracker
from azents.runtime_web_gateway.web_session_bridge import (
    PersistentGatewaySessionTransport,
)
from azents.runtime_web_gateway.web_session_pool import (
    GatewaySessionRegistration,
    RuntimeWebGatewaySessionPool,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_web_session_pb2_grpc import (
        RuntimeWebGatewaySessionAsyncStub as _RuntimeWebGatewaySessionStub,
    )
else:
    from azents_runtime_control.proto.runtime_web_session_pb2_grpc import (
        RuntimeWebGatewaySessionStub as _RuntimeWebGatewaySessionStub,
    )

_HANDSHAKE_SECONDS = 10.0
_LOCAL_SUBCHANNEL_POOL = (("grpc.use_local_subchannel_pool", 1),)
_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _GatewayHello:
    identity: SessionIdentity
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope


class RuntimeWebGatewayControlSessions:
    """Maintain a bounded reconnecting pool of exact-fingerprint Control sessions."""

    def __init__(
        self,
        *,
        channel: grpc.aio.Channel,
        pool: RuntimeWebGatewaySessionPool,
        gateway_boot_id: str,
        session_count: int,
        resources: RuntimeWebGatewayResourceTracker,
    ) -> None:
        if not gateway_boot_id or session_count <= 0:
            raise ValueError("Runtime Web Gateway session settings are invalid")
        self.channel = channel
        self.pool = pool
        self.gateway_boot_id = gateway_boot_id
        self.session_count = session_count
        self.resources = resources
        self.stop = asyncio.Event()
        self.draining = False
        self.tasks: tuple[asyncio.Task[None], ...] = ()
        self.transports: set[PersistentGatewaySessionTransport] = set()
        self.registrations: dict[
            PersistentGatewaySessionTransport, GatewaySessionRegistration
        ] = {}

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        allow_insecure: bool,
        ca_file: Path | None,
        certificate_file: Path | None,
        private_key_file: Path | None,
        session_count: int,
        resources: RuntimeWebGatewayResourceTracker,
    ) -> RuntimeWebGatewayControlSessions:
        """Create one shared channel and a bounded persistent session pool."""
        if allow_insecure:
            channel = grpc.aio.insecure_channel(
                endpoint,
                options=_LOCAL_SUBCHANNEL_POOL,
            )
        else:
            if ca_file is None or certificate_file is None or private_key_file is None:
                raise RuntimeError("Runtime Web Gateway mTLS files are required")
            credentials = grpc.ssl_channel_credentials(
                root_certificates=ca_file.read_bytes(),
                private_key=private_key_file.read_bytes(),
                certificate_chain=certificate_file.read_bytes(),
            )
            channel = grpc.aio.secure_channel(
                endpoint,
                credentials,
                options=_LOCAL_SUBCHANNEL_POOL,
            )
        return cls(
            channel=channel,
            pool=RuntimeWebGatewaySessionPool(maximum_sessions=session_count),
            gateway_boot_id=secrets.token_hex(16),
            session_count=session_count,
            resources=resources,
        )

    async def start(self) -> None:
        """Start one reconnecting task per configured session slot."""
        if self.tasks:
            raise RuntimeError("Runtime Web Gateway sessions are already started")
        self.tasks = tuple(
            asyncio.create_task(
                self._run_slot(slot),
                name=f"runtime-web-gateway-control-session:{slot}",
            )
            for slot in range(self.session_count)
        )

    async def close(self) -> None:
        """Stop reconnects and close every active session without replay."""
        self.stop.set()
        transports = tuple(self.transports)
        await asyncio.gather(
            *(transport.close() for transport in transports),
            return_exceptions=True,
        )
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = ()
        self.transports.clear()
        self.registrations.clear()
        await self.channel.close()

    async def begin_drain(self, reason: CloseReason) -> None:
        """Stop reconnects and send GOAWAY without terminating active streams."""
        if reason is not CloseReason.SERVICE_DRAIN:
            raise ValueError("Runtime Web Gateway drain reason is invalid")
        self.draining = True
        self.stop.set()
        deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=120)
        for transport, registration in tuple(self.registrations.items()):
            envelope = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
                protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
                session_id=registration.session_id,
                peer_boot_id=registration.peer_boot_id,
                go_away=runtime_web_session_pb2.RuntimeWebSessionGoAway(
                    last_accepted_stream_id=(2**64 - 1),
                    reason=(
                        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
                    ),
                ),
            )
            envelope.go_away.drain_deadline_at.FromDatetime(deadline)
            await transport.send(envelope)

    async def compatible_fingerprints(self) -> frozenset[str]:
        """Return exact fingerprints represented by active accepted sessions."""
        if await self.pool.active_session_count() == 0:
            return frozenset()
        return frozenset({RUNTIME_WEB_PROTOCOL_FINGERPRINT})

    async def _run_slot(self, slot: int) -> None:
        attempt = 0
        stream = _RuntimeWebGatewaySessionStub(self.channel).Connect
        while not self.stop.is_set():
            registration: GatewaySessionRegistration | None = None
            transport = PersistentGatewaySessionTransport(
                stream,
                resources=self.resources,
            )
            registration_ready: asyncio.Future[GatewaySessionRegistration] = (
                asyncio.get_running_loop().create_future()
            )

            async def handle_go_away(
                last_accepted_stream_id: int,
                reason: CloseReason,
                deadline: datetime.datetime,
                *,
                registration_future: asyncio.Future[
                    GatewaySessionRegistration
                ] = registration_ready,
            ) -> tuple[int, ...]:
                del reason, deadline
                current_registration = await registration_future
                return await self.pool.start_draining(
                    current_registration,
                    last_accepted_stream_id=last_accepted_stream_id,
                )

            transport.set_go_away_handler(handle_go_away)
            self.transports.add(transport)
            try:
                gateway_hello = _gateway_hello(self.gateway_boot_id)
                accepted = await transport.start(
                    gateway_hello.envelope,
                    timeout_seconds=_HANDSHAKE_SECONDS,
                )
                profile = _accepted_profile(accepted)
                registration = await self.pool.register(
                    identity=gateway_hello.identity,
                    profile=profile,
                    transport=transport,
                )
                registration_ready.set_result(registration)
                self.registrations[transport] = registration
                attempt = 0
                await transport.wait_closed()
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt += 1
                _LOGGER.exception(
                    "Runtime Web Gateway Control session failed",
                    extra={
                        "slot": slot,
                        "attempt": attempt,
                    },
                )
            finally:
                if not registration_ready.done():
                    registration_ready.cancel()
                if registration is not None:
                    await self.pool.close_session(registration)
                self.registrations.pop(transport, None)
                await transport.close()
                self.transports.discard(transport)
            if self.stop.is_set() or self.draining:
                return
            maximum = min(5.0, 0.25 * (2 ** min(attempt, 4)))
            await asyncio.sleep(random.uniform(maximum / 2, maximum) + slot * 0.01)


def _gateway_hello(
    gateway_boot_id: str,
) -> _GatewayHello:
    now = datetime.datetime.now(datetime.UTC)
    deadline = now + datetime.timedelta(seconds=_HANDSHAKE_SECONDS)
    session_id = secrets.token_hex(16)
    nonce = secrets.token_urlsafe(24)
    identity = SessionIdentity(
        session_id=session_id,
        peer_boot_id=gateway_boot_id,
        role=SessionPeerRole.GATEWAY,
        owner=None,
        session_nonce=nonce,
        deadline_at=deadline,
    )
    hello = runtime_web_session_pb2.RuntimeWebSessionHello(
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY,
        session_nonce=nonce,
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
    hello.deadline_at.FromDatetime(deadline)
    return _GatewayHello(
        identity=identity,
        envelope=runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id=session_id,
            peer_boot_id=gateway_boot_id,
            hello=hello,
        ),
    )


def _accepted_profile(
    envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
) -> SessionProfile:
    if (
        envelope.protocol_fingerprint != RUNTIME_WEB_PROTOCOL_FINGERPRINT
        or envelope.WhichOneof("payload") != "session_accepted"
    ):
        raise ValueError("Runtime Web Control session acceptance is incompatible")
    accepted = envelope.session_accepted
    profile = SessionProfile(
        data_frame_bytes=accepted.data_frame_bytes,
        request_stream_window_bytes=accepted.request_stream_window_bytes,
        response_stream_window_bytes=accepted.response_stream_window_bytes,
        request_session_window_bytes=accepted.request_session_window_bytes,
        response_session_window_bytes=accepted.response_session_window_bytes,
    )
    if profile != APPROVED_SESSION_PROFILE:
        raise ValueError("Runtime Web Control session profile is incompatible")
    return profile
