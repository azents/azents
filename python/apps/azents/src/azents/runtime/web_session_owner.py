"""Inactive Owner-session lease and Runner offer for replacement Runtime Web."""

import asyncio
import dataclasses
import datetime
import hashlib
import secrets
from collections.abc import Callable
from typing import Protocol

from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    MANDATORY_DATA_FRAME_BYTES,
    OPTIONAL_DATA_FRAME_BYTES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
    SessionProfile,
    validate_runner_web_connect_address,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteRepository,
)


@dataclasses.dataclass(frozen=True)
class RuntimeWebOwnedSession:
    """Exact durable Owner route and plaintext one-time join offer."""

    route: RuntimeWebSessionRoute
    offer: RunnerSessionOffer


@dataclasses.dataclass(frozen=True)
class RuntimeWebAcceptedRunnerSession:
    """One exact process-local Runner join for an Owner epoch."""

    owner: OwnerSessionEpoch
    runner_boot_id: str
    profile: SessionProfile
    connected_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class RuntimeWebAuthenticatedRunnerConnection:
    """Current identity proven by the ordinary authenticated Runner connection."""

    runtime_id: str
    runner_boot_id: str
    desired_generation: int
    runner_generation: int


class RuntimeWebSessionJoinRepository(Protocol):
    """Consume one exact durable Runner join authority."""

    async def consume_join(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
        protocol_fingerprint: str,
        join_nonce_hash: str,
        join_deadline_at: datetime.datetime,
    ) -> RuntimeWebSessionRoute: ...


class RuntimeWebOwnerSessionRegistry:
    """Accept one nonce-bound Runner join per live Owner epoch."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebSessionJoinRepository,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.clock = clock
        self.lock = asyncio.Lock()
        self.sessions: dict[OwnerSessionEpoch, RuntimeWebAcceptedRunnerSession] = {}

    async def accept(
        self,
        owned: RuntimeWebOwnedSession,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        authenticated: RuntimeWebAuthenticatedRunnerConnection,
    ) -> RuntimeWebAcceptedRunnerSession:
        """Validate and consume the exact one-time Owner session offer."""
        now = self._now()
        owner = owned.offer.owner
        hello = envelope.hello
        hello_deadline = hello.deadline_at.ToDatetime(tzinfo=datetime.UTC)
        if (
            envelope.WhichOneof("payload") != "hello"
            or envelope.protocol_fingerprint != owned.offer.protocol_fingerprint
            or envelope.session_id != owner.session_lease_id
            or envelope.owner_boot_id != owner.owner_boot_id
            or envelope.session_lease_id != owner.session_lease_id
            or envelope.lease_generation != owner.lease_generation
            or envelope.peer_boot_id != authenticated.runner_boot_id
            or hello.role
            != runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_RUNNER
            or hello.runtime_id != owner.runtime_id
            or hello.desired_generation != owner.desired_generation
            or hello.runner_generation != owner.runner_generation
            or authenticated.runtime_id != owner.runtime_id
            or authenticated.desired_generation != owner.desired_generation
            or authenticated.runner_generation != owner.runner_generation
            or hello.session_nonce != owned.offer.session_nonce
            or hello_deadline != owned.offer.deadline_at
            or owned.offer.deadline_at <= now
        ):
            raise ValueError("Runtime Web Runner session offer is stale")
        if hello.maximum_data_frame_bytes < MANDATORY_DATA_FRAME_BYTES:
            raise ValueError("Runtime Web Runner data frame offer is too small")
        profile = SessionProfile(
            data_frame_bytes=(
                OPTIONAL_DATA_FRAME_BYTES
                if hello.maximum_data_frame_bytes >= OPTIONAL_DATA_FRAME_BYTES
                else MANDATORY_DATA_FRAME_BYTES
            ),
            request_stream_window_bytes=hello.request_stream_window_bytes,
            response_stream_window_bytes=hello.response_stream_window_bytes,
            request_session_window_bytes=hello.request_session_window_bytes,
            response_session_window_bytes=hello.response_session_window_bytes,
        )
        async with self.session_manager() as session:
            await self.repository.consume_join(
                session,
                runtime_id=owner.runtime_id,
                owner_boot_id=owner.owner_boot_id,
                session_lease_id=owner.session_lease_id,
                lease_generation=owner.lease_generation,
                protocol_fingerprint=owned.offer.protocol_fingerprint,
                join_nonce_hash=hashlib.sha256(
                    hello.session_nonce.encode()
                ).hexdigest(),
                join_deadline_at=owned.offer.deadline_at,
            )
        if owned.offer.deadline_at <= self._now():
            raise ValueError("Runtime Web Runner session offer expired during join")
        accepted = RuntimeWebAcceptedRunnerSession(
            owner=owner,
            runner_boot_id=authenticated.runner_boot_id,
            profile=profile,
            connected_at=now,
        )
        async with self.lock:
            if owner in self.sessions:
                raise ValueError("Runtime Web Runner session is already joined")
            self.sessions[owner] = accepted
        return accepted

    async def release(self, accepted: RuntimeWebAcceptedRunnerSession) -> bool:
        """Release only the exact process-local Runner session."""
        async with self.lock:
            current = self.sessions.get(accepted.owner)
            if current != accepted:
                return False
            self.sessions.pop(accepted.owner)
            return True

    def _now(self) -> datetime.datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Web Owner registry clock must be timezone-aware")
        return now


class RuntimeWebSessionOwnerManager:
    """Acquire and maintain one inactive Owner session without application data."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebSessionRouteRepository,
        owner_replica_id: str,
        owner_boot_id: str,
        trusted_owner_address: str,
        runner_connect_address: str,
        runner_tls_server_name: str,
        lease_seconds: float,
        clock: Callable[[], datetime.datetime],
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Runtime Web session lease duration must be positive")
        for name, value in (
            ("owner_replica_id", owner_replica_id),
            ("owner_boot_id", owner_boot_id),
            ("trusted_owner_address", trusted_owner_address),
            ("runner_connect_address", runner_connect_address),
            ("runner_tls_server_name", runner_tls_server_name),
        ):
            if not value:
                raise ValueError(f"Runtime Web {name} must not be empty")
        self.session_manager = session_manager
        self.repository = repository
        self.owner_replica_id = owner_replica_id
        self.owner_boot_id = owner_boot_id
        self.trusted_owner_address = trusted_owner_address
        validate_runner_web_connect_address(runner_connect_address)
        self.runner_connect_address = runner_connect_address
        self.runner_tls_server_name = runner_tls_server_name
        self.lease_seconds = lease_seconds
        self.clock = clock

    async def acquire(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
    ) -> RuntimeWebOwnedSession:
        """Acquire one Owner epoch and return its plaintext join offer once."""
        nonce = secrets.token_urlsafe(32)
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        async with self.session_manager() as session:
            route = await self.repository.acquire(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
                owner_replica_id=self.owner_replica_id,
                owner_boot_id=self.owner_boot_id,
                owner_address=self.trusted_owner_address,
                join_nonce_hash=nonce_hash,
                protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
                lease_seconds=self.lease_seconds,
            )
        owner = OwnerSessionEpoch(
            owner_boot_id=route.owner_boot_id,
            session_lease_id=route.session_lease_id,
            lease_generation=route.lease_generation,
            runtime_id=route.runtime_id,
            desired_generation=route.desired_generation,
            runner_generation=route.runner_generation,
        )
        return RuntimeWebOwnedSession(
            route=route,
            offer=RunnerSessionOffer(
                owner=owner,
                owner_replica_id=route.owner_replica_id,
                connect_address=self.runner_connect_address,
                tls_server_name=self.runner_tls_server_name,
                session_nonce=nonce,
                protocol_fingerprint=route.protocol_fingerprint,
                deadline_at=min(
                    route.lease_expires_at,
                    self._now()
                    + datetime.timedelta(seconds=min(self.lease_seconds, 10.0)),
                ),
            ),
        )

    async def renew(self, owned: RuntimeWebOwnedSession) -> RuntimeWebOwnedSession:
        """Renew the exact lease without extending the one-time join deadline."""
        async with self.session_manager() as session:
            route = await self.repository.renew(
                session,
                runtime_id=owned.route.runtime_id,
                owner_boot_id=owned.route.owner_boot_id,
                session_lease_id=owned.route.session_lease_id,
                lease_generation=owned.route.lease_generation,
                protocol_fingerprint=owned.route.protocol_fingerprint,
                lease_seconds=self.lease_seconds,
            )
        return dataclasses.replace(owned, route=route)

    async def mark_draining(
        self,
        owned: RuntimeWebOwnedSession,
    ) -> RuntimeWebOwnedSession:
        """Fence new work while the exact Owner drains existing streams."""
        async with self.session_manager() as session:
            route = await self.repository.mark_draining(
                session,
                runtime_id=owned.route.runtime_id,
                owner_boot_id=owned.route.owner_boot_id,
                session_lease_id=owned.route.session_lease_id,
                lease_generation=owned.route.lease_generation,
            )
        return dataclasses.replace(owned, route=route)

    async def release(self, owned: RuntimeWebOwnedSession) -> bool:
        """Release only the exact current Owner epoch."""
        async with self.session_manager() as session:
            return await self.repository.release(
                session,
                runtime_id=owned.route.runtime_id,
                owner_boot_id=owned.route.owner_boot_id,
                session_lease_id=owned.route.session_lease_id,
                lease_generation=owned.route.lease_generation,
            )

    def _now(self) -> datetime.datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Web Owner clock must be timezone-aware")
        return now
