"""PostgreSQL Owner-session route lease for inactive Runtime Web transport."""

import datetime
import hashlib

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_web import RDBRuntimeWebSessionRoute
from azents.repos.runtime_web.data import RuntimeWebSessionRoute


class RuntimeWebSessionRouteConflict(ValueError):
    """The requested Owner-session route is stale or already owned."""


class RuntimeWebSessionRouteRepository:
    """Own the exact one-per-Runtime replacement session lease."""

    async def acquire(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
        owner_replica_id: str,
        owner_boot_id: str,
        owner_address: str,
        join_nonce_hash: str,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> RuntimeWebSessionRoute:
        """Acquire a new Owner epoch after validating current Runtime evidence."""
        self._validate_input(
            desired_generation=desired_generation,
            runner_generation=runner_generation,
            join_nonce_hash=join_nonce_hash,
            protocol_fingerprint=protocol_fingerprint,
            lease_seconds=lease_seconds,
        )
        now = await self._database_now(session)
        await self._validate_runtime(
            session,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
        )
        existing = await session.scalar(
            sa.select(RDBRuntimeWebSessionRoute)
            .where(RDBRuntimeWebSessionRoute.runtime_id == runtime_id)
            .with_for_update()
        )
        lease_generation = 1
        if existing is not None:
            if existing.lease_expires_at > now:
                raise RuntimeWebSessionRouteConflict(
                    "Runtime Web session route is already owned"
                )
            lease_generation = existing.lease_generation + 1
            await session.delete(existing)
            await session.flush()
        route = RDBRuntimeWebSessionRoute(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
            owner_replica_id=owner_replica_id,
            owner_boot_id=owner_boot_id,
            owner_address=owner_address,
            session_lease_id=uuid7().hex,
            lease_generation=lease_generation,
            join_nonce_hash=join_nonce_hash,
            protocol_fingerprint=protocol_fingerprint,
            lease_expires_at=now + datetime.timedelta(seconds=lease_seconds),
            draining_at=None,
        )
        session.add(route)
        await session.flush()
        return self._route(route)

    async def renew(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> RuntimeWebSessionRoute:
        """Renew only the exact current Owner epoch and Runtime generation."""
        if lease_generation <= 0 or lease_seconds <= 0:
            raise ValueError("Runtime Web session lease values must be positive")
        now = await self._database_now(session)
        route = await self._lock(session, runtime_id)
        if not self._matches(
            route,
            owner_boot_id=owner_boot_id,
            session_lease_id=session_lease_id,
            lease_generation=lease_generation,
            protocol_fingerprint=protocol_fingerprint,
            now=now,
        ):
            raise RuntimeWebSessionRouteConflict("Runtime Web session route is stale")
        assert route is not None
        await self._validate_runtime(
            session,
            runtime_id=runtime_id,
            desired_generation=route.desired_generation,
            runner_generation=route.runner_generation,
        )
        route.lease_expires_at = now + datetime.timedelta(seconds=lease_seconds)
        await session.flush()
        await session.refresh(route, attribute_names=["updated_at"])
        return self._route(route)

    async def resolve(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
        protocol_fingerprint: str,
    ) -> RuntimeWebSessionRoute | None:
        """Resolve the exact live Owner epoch without accepting stale generations."""
        now = await self._database_now(session)
        route = await self._lock(session, runtime_id)
        if (
            route is None
            or route.lease_expires_at <= now
            or route.draining_at is not None
            or route.desired_generation != desired_generation
            or route.runner_generation != runner_generation
            or route.protocol_fingerprint != protocol_fingerprint
        ):
            return None
        try:
            await self._validate_runtime(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
            )
        except RuntimeWebSessionRouteConflict:
            return None
        return self._route(route)

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
    ) -> RuntimeWebSessionRoute:
        """Atomically consume one exact live non-draining Runner join nonce."""
        route = await self._lock(session, runtime_id)
        now = await self._database_now(session)
        if (
            not self._matches(
                route,
                owner_boot_id=owner_boot_id,
                session_lease_id=session_lease_id,
                lease_generation=lease_generation,
                protocol_fingerprint=protocol_fingerprint,
                now=now,
            )
            or route is None
            or route.draining_at is not None
            or route.join_nonce_hash != join_nonce_hash
            or join_deadline_at <= now
        ):
            raise RuntimeWebSessionRouteConflict(
                "Runtime Web session join authority is stale"
            )
        await self._validate_runtime(
            session,
            runtime_id=runtime_id,
            desired_generation=route.desired_generation,
            runner_generation=route.runner_generation,
        )
        route.join_nonce_hash = hashlib.sha256(
            f"consumed:{route.session_lease_id}:{route.lease_generation}".encode()
        ).hexdigest()
        await session.flush()
        return self._route(route)

    async def mark_draining(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
    ) -> RuntimeWebSessionRoute:
        """Fence new work while preserving the exact lease for bounded drain."""
        now = await self._database_now(session)
        route = await self._lock(session, runtime_id)
        if (
            route is None
            or route.owner_boot_id != owner_boot_id
            or route.session_lease_id != session_lease_id
            or route.lease_generation != lease_generation
            or route.lease_expires_at <= now
        ):
            raise RuntimeWebSessionRouteConflict("Runtime Web session route is stale")
        if route.draining_at is None:
            route.draining_at = now
            await session.flush()
        return self._route(route)

    async def release(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
    ) -> bool:
        """Release only the exact current Owner epoch."""
        route = await self._lock(session, runtime_id)
        if (
            route is None
            or route.owner_boot_id != owner_boot_id
            or route.session_lease_id != session_lease_id
            or route.lease_generation != lease_generation
        ):
            return False
        await session.delete(route)
        await session.flush()
        return True

    async def _validate_runtime(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
    ) -> None:
        runtime = await session.scalar(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .with_for_update()
        )
        if (
            runtime is None
            or runtime.desired_generation != desired_generation
            or runtime.runner_generation != runner_generation
        ):
            raise RuntimeWebSessionRouteConflict(
                "Runtime Web session generation is stale"
            )

    @staticmethod
    async def _database_now(session: AsyncSession) -> datetime.datetime:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return a current timestamp")
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("Database returned a naive current timestamp")
        return now

    @staticmethod
    async def _lock(
        session: AsyncSession,
        runtime_id: str,
    ) -> RDBRuntimeWebSessionRoute | None:
        return await session.scalar(
            sa.select(RDBRuntimeWebSessionRoute)
            .where(RDBRuntimeWebSessionRoute.runtime_id == runtime_id)
            .with_for_update()
        )

    @staticmethod
    def _matches(
        route: RDBRuntimeWebSessionRoute | None,
        *,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
        protocol_fingerprint: str,
        now: datetime.datetime,
    ) -> bool:
        return (
            route is not None
            and route.owner_boot_id == owner_boot_id
            and route.session_lease_id == session_lease_id
            and route.lease_generation == lease_generation
            and route.protocol_fingerprint == protocol_fingerprint
            and route.lease_expires_at > now
        )

    @staticmethod
    def _validate_input(
        *,
        desired_generation: int,
        runner_generation: int,
        join_nonce_hash: str,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> None:
        if desired_generation <= 0 or runner_generation <= 0:
            raise ValueError("Runtime Web session generations must be positive")
        if lease_seconds <= 0:
            raise ValueError("Runtime Web session lease duration must be positive")
        if len(join_nonce_hash) != 64 or len(protocol_fingerprint) != 64:
            raise ValueError("Runtime Web session hashes must be SHA-256 hex strings")
        try:
            bytes.fromhex(join_nonce_hash)
            bytes.fromhex(protocol_fingerprint)
        except ValueError as error:
            raise ValueError(
                "Runtime Web session hashes must be SHA-256 hex strings"
            ) from error

    @staticmethod
    def _route(route: RDBRuntimeWebSessionRoute) -> RuntimeWebSessionRoute:
        return RuntimeWebSessionRoute(
            runtime_id=route.runtime_id,
            desired_generation=route.desired_generation,
            runner_generation=route.runner_generation,
            owner_replica_id=route.owner_replica_id,
            owner_boot_id=route.owner_boot_id,
            owner_address=route.owner_address,
            session_lease_id=route.session_lease_id,
            lease_generation=route.lease_generation,
            join_nonce_hash=route.join_nonce_hash,
            protocol_fingerprint=route.protocol_fingerprint,
            lease_expires_at=route.lease_expires_at,
            draining_at=route.draining_at,
        )
