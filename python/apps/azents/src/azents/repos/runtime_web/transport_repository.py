"""PostgreSQL Runtime Web route and shared admission leases."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAdmissionLease,
    RDBRuntimeWebCycle,
    RDBRuntimeWebEndpoint,
    RDBRuntimeWebTunnelRoute,
    RuntimeWebCycleEndReason,
)
from azents.repos.runtime_web.data import (
    RuntimeWebTunnelAuthority,
    RuntimeWebTunnelRoute,
)

_ADMISSION_LOCK_KEY = 5_933_850_203_020_431_445


class RuntimeWebRouteConflict(ValueError):
    """The requested tunnel route is stale or already owned."""


class RuntimeWebAdmissionCapacityExceeded(ValueError):
    """The shared active Runtime Web connection limit is exhausted."""


class RuntimeWebTransportRepository:
    """Own exact route fencing and shared connection admission transactions."""

    async def acquire_route(
        self,
        session: AsyncSession,
        *,
        authority: RuntimeWebTunnelAuthority,
        owner_replica_id: str,
        owner_boot_id: str,
        owner_address: str,
        lease_seconds: float,
        maximum_active_connections: int,
    ) -> RuntimeWebTunnelRoute:
        """Acquire or renew one route after locking all durable authority."""
        if lease_seconds <= 0:
            raise ValueError("Runtime Web route lease duration must be positive")
        if maximum_active_connections <= 0:
            raise ValueError("Runtime Web connection limit must be positive")
        now = await self._database_now(session)
        self._validate_deadlines(authority, now=now)
        await self._validate_authority(
            session,
            authority=authority,
            now=now,
            for_update=True,
        )
        existing = await session.scalar(
            sa.select(RDBRuntimeWebTunnelRoute)
            .where(RDBRuntimeWebTunnelRoute.tunnel_id == authority.tunnel_id)
            .with_for_update()
        )
        lease_generation = 1
        if existing is not None:
            if existing.lease_expires_at > now:
                raise RuntimeWebRouteConflict("Runtime Web route is already owned")
            lease_generation = existing.lease_generation + 1
            await session.delete(existing)
            await session.flush()
        await session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _ADMISSION_LOCK_KEY},
        )
        active_count = await session.scalar(
            sa.select(sa.func.count(RDBRuntimeWebAdmissionLease.id)).where(
                RDBRuntimeWebAdmissionLease.lease_expires_at > now
            )
        )
        if int(active_count or 0) >= maximum_active_connections:
            raise RuntimeWebAdmissionCapacityExceeded
        lease_expires_at = self._lease_deadline(
            authority,
            now=now,
            lease_seconds=lease_seconds,
        )
        route = RDBRuntimeWebTunnelRoute(
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
            owner_replica_id=owner_replica_id,
            owner_boot_id=owner_boot_id,
            owner_address=owner_address,
            route_lease_id=uuid7().hex,
            lease_generation=lease_generation,
            registration_deadline_at=authority.registration_deadline_at,
            approval_deadline_at=authority.approval_deadline_at,
            transport_deadline_at=authority.transport_deadline_at,
            lease_expires_at=lease_expires_at,
        )
        admission = RDBRuntimeWebAdmissionLease(
            tunnel_id=authority.tunnel_id,
            owner_boot_id=owner_boot_id,
            lease_generation=lease_generation,
            lease_expires_at=lease_expires_at,
        )
        session.add(route)
        await session.flush()
        session.add(admission)
        await session.flush()
        return self._route(route, admission)

    async def renew_route(
        self,
        session: AsyncSession,
        *,
        tunnel_id: str,
        route_lease_id: str,
        owner_boot_id: str,
        lease_generation: int,
        lease_seconds: float,
        allow_replaced_cycle: bool,
    ) -> RuntimeWebTunnelRoute:
        """Renew only the exact current owner and revalidate durable authority."""
        if lease_seconds <= 0:
            raise ValueError("Runtime Web route lease duration must be positive")
        now = await self._database_now(session)
        snapshot = await session.get(RDBRuntimeWebTunnelRoute, tunnel_id)
        if (
            snapshot is None
            or snapshot.route_lease_id != route_lease_id
            or snapshot.owner_boot_id != owner_boot_id
            or snapshot.lease_generation != lease_generation
            or snapshot.lease_expires_at <= now
        ):
            raise RuntimeWebRouteConflict("Runtime Web route lease is stale")
        authority = self._authority(snapshot)
        if (
            authority.approval_deadline_at <= now
            or authority.transport_deadline_at <= now
        ):
            raise RuntimeWebRouteConflict("Runtime Web tunnel deadline is stale")
        await self._validate_renewal_authority(
            session,
            authority=authority,
            now=now,
            allow_replaced_cycle=allow_replaced_cycle,
        )
        route = await self._lock_route(session, tunnel_id)
        if (
            route is None
            or route.route_lease_id != route_lease_id
            or route.owner_boot_id != owner_boot_id
            or route.lease_generation != lease_generation
            or route.lease_expires_at <= now
        ):
            raise RuntimeWebRouteConflict("Runtime Web route lease is stale")
        return await self._renew_locked(
            session,
            route=route,
            now=now,
            lease_seconds=lease_seconds,
        )

    async def get_live_route(
        self,
        session: AsyncSession,
        *,
        tunnel_id: str,
    ) -> RuntimeWebTunnelRoute | None:
        """Resolve a live owner route and reject stale durable authority."""
        now = await self._database_now(session)
        snapshot = await session.get(RDBRuntimeWebTunnelRoute, tunnel_id)
        if snapshot is None or snapshot.lease_expires_at <= now:
            return None
        authority = self._authority(snapshot)
        try:
            self._validate_deadlines(authority, now=now)
            await self._validate_authority(
                session,
                authority=authority,
                now=now,
                for_update=True,
            )
        except RuntimeWebRouteConflict:
            return None
        route = await self._lock_route(session, tunnel_id)
        if (
            route is None
            or route.route_lease_id != snapshot.route_lease_id
            or route.owner_boot_id != snapshot.owner_boot_id
            or route.lease_generation != snapshot.lease_generation
            or route.lease_expires_at <= now
        ):
            return None
        admission = await self._admission(session, tunnel_id, for_update=True)
        if (
            admission is None
            or admission.lease_expires_at <= now
            or admission.owner_boot_id != route.owner_boot_id
            or admission.lease_generation != route.lease_generation
        ):
            return None
        return self._route(route, admission)

    async def release_route(
        self,
        session: AsyncSession,
        *,
        tunnel_id: str,
        route_lease_id: str,
        owner_boot_id: str,
        lease_generation: int,
    ) -> bool:
        """Release only the exact current route lease."""
        route = await self._lock_route(session, tunnel_id)
        if (
            route is None
            or route.route_lease_id != route_lease_id
            or route.owner_boot_id != owner_boot_id
            or route.lease_generation != lease_generation
        ):
            return False
        await session.delete(route)
        await session.flush()
        return True

    async def _renew_locked(
        self,
        session: AsyncSession,
        *,
        route: RDBRuntimeWebTunnelRoute,
        now: datetime.datetime,
        lease_seconds: float,
    ) -> RuntimeWebTunnelRoute:
        admission = await self._admission(session, route.tunnel_id, for_update=True)
        if (
            admission is None
            or admission.owner_boot_id != route.owner_boot_id
            or admission.lease_generation != route.lease_generation
        ):
            raise RuntimeWebRouteConflict("Runtime Web admission lease is stale")
        lease_expires_at = self._lease_deadline(
            self._authority(route),
            now=now,
            lease_seconds=lease_seconds,
        )
        route.lease_expires_at = lease_expires_at
        admission.lease_expires_at = lease_expires_at
        await session.flush()
        await session.refresh(route, attribute_names=["updated_at"])
        await session.refresh(admission, attribute_names=["updated_at"])
        return self._route(route, admission)

    async def _validate_authority(
        self,
        session: AsyncSession,
        *,
        authority: RuntimeWebTunnelAuthority,
        now: datetime.datetime,
        for_update: bool,
    ) -> None:
        endpoint_statement = sa.select(RDBRuntimeWebEndpoint).where(
            RDBRuntimeWebEndpoint.id == authority.endpoint_id
        )
        cycle_statement = sa.select(RDBRuntimeWebCycle).where(
            RDBRuntimeWebCycle.id == authority.cycle_id
        )
        runtime_statement = sa.select(RDBAgentRuntime).where(
            RDBAgentRuntime.id == authority.runtime_id
        )
        if for_update:
            endpoint_statement = endpoint_statement.with_for_update()
            cycle_statement = cycle_statement.with_for_update()
            runtime_statement = runtime_statement.with_for_update()
        endpoint = await session.scalar(endpoint_statement)
        cycle = await session.scalar(cycle_statement)
        runtime = await session.scalar(runtime_statement)
        if (
            endpoint is None
            or cycle is None
            or runtime is None
            or endpoint.current_cycle_id != cycle.id
            or cycle.endpoint_id != endpoint.id
            or cycle.ended_at is not None
            or cycle.expires_at <= now
            or cycle.expires_at != authority.approval_deadline_at
            or endpoint.authority_revision != authority.endpoint_authority_revision
            or endpoint.close_barrier != authority.close_barrier
            or endpoint.port != authority.port
            or runtime.agent_id != endpoint.agent_id
            or runtime.desired_generation != authority.desired_generation
            or runtime.runner_generation != authority.runner_generation
        ):
            raise RuntimeWebRouteConflict("Runtime Web authority is stale")

    async def _validate_renewal_authority(
        self,
        session: AsyncSession,
        *,
        authority: RuntimeWebTunnelAuthority,
        now: datetime.datetime,
        allow_replaced_cycle: bool,
    ) -> None:
        endpoint = await session.scalar(
            sa.select(RDBRuntimeWebEndpoint)
            .where(RDBRuntimeWebEndpoint.id == authority.endpoint_id)
            .with_for_update()
        )
        cycle = await session.scalar(
            sa.select(RDBRuntimeWebCycle)
            .where(RDBRuntimeWebCycle.id == authority.cycle_id)
            .with_for_update()
        )
        runtime = await session.scalar(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == authority.runtime_id)
            .with_for_update()
        )
        active_cycle = (
            endpoint is not None
            and cycle is not None
            and endpoint.current_cycle_id == cycle.id
            and cycle.ended_at is None
            and cycle.expires_at > now
        )
        replaced_cycle = (
            allow_replaced_cycle
            and cycle is not None
            and cycle.end_reason is RuntimeWebCycleEndReason.REPLACED
            and cycle.expires_at > now
        )
        if (
            endpoint is None
            or cycle is None
            or runtime is None
            or cycle.endpoint_id != endpoint.id
            or not (active_cycle or replaced_cycle)
            or endpoint.close_barrier != authority.close_barrier
            or endpoint.port != authority.port
            or runtime.agent_id != endpoint.agent_id
            or runtime.desired_generation != authority.desired_generation
            or runtime.runner_generation != authority.runner_generation
        ):
            raise RuntimeWebRouteConflict("Runtime Web renewal authority is stale")

    async def _lock_route(
        self,
        session: AsyncSession,
        tunnel_id: str,
    ) -> RDBRuntimeWebTunnelRoute | None:
        return await session.scalar(
            sa.select(RDBRuntimeWebTunnelRoute)
            .where(RDBRuntimeWebTunnelRoute.tunnel_id == tunnel_id)
            .with_for_update()
        )

    async def _admission(
        self,
        session: AsyncSession,
        tunnel_id: str,
        *,
        for_update: bool = False,
    ) -> RDBRuntimeWebAdmissionLease | None:
        statement = sa.select(RDBRuntimeWebAdmissionLease).where(
            RDBRuntimeWebAdmissionLease.tunnel_id == tunnel_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _database_now(self, session: AsyncSession) -> datetime.datetime:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return now

    @staticmethod
    def _validate_deadlines(
        authority: RuntimeWebTunnelAuthority,
        *,
        now: datetime.datetime,
    ) -> None:
        deadlines = (
            authority.registration_deadline_at,
            authority.approval_deadline_at,
            authority.transport_deadline_at,
        )
        if any(
            value.tzinfo is None or value.utcoffset() is None for value in deadlines
        ):
            raise RuntimeWebRouteConflict(
                "Runtime Web deadlines must be timezone-aware"
            )
        if (
            authority.registration_deadline_at <= now
            or authority.approval_deadline_at <= now
            or authority.transport_deadline_at <= now
            or authority.registration_deadline_at > authority.transport_deadline_at
            or authority.approval_deadline_at > authority.transport_deadline_at
        ):
            raise RuntimeWebRouteConflict("Runtime Web tunnel deadline is stale")

    @staticmethod
    def _lease_deadline(
        authority: RuntimeWebTunnelAuthority,
        *,
        now: datetime.datetime,
        lease_seconds: float,
    ) -> datetime.datetime:
        return min(
            authority.transport_deadline_at,
            now + datetime.timedelta(seconds=lease_seconds),
        )

    @staticmethod
    def _authority(route: RDBRuntimeWebTunnelRoute) -> RuntimeWebTunnelAuthority:
        return RuntimeWebTunnelAuthority(
            tunnel_id=route.tunnel_id,
            endpoint_id=route.endpoint_id,
            cycle_id=route.cycle_id,
            endpoint_authority_revision=route.endpoint_authority_revision,
            close_barrier=route.close_barrier,
            runtime_id=route.runtime_id,
            desired_generation=route.desired_generation,
            runner_generation=route.runner_generation,
            port=route.port,
            join_nonce=route.join_nonce,
            registration_deadline_at=route.registration_deadline_at,
            approval_deadline_at=route.approval_deadline_at,
            transport_deadline_at=route.transport_deadline_at,
        )

    @staticmethod
    def _route(
        route: RDBRuntimeWebTunnelRoute,
        admission: RDBRuntimeWebAdmissionLease,
    ) -> RuntimeWebTunnelRoute:
        return RuntimeWebTunnelRoute(
            authority=RuntimeWebTransportRepository._authority(route),
            owner_replica_id=route.owner_replica_id,
            owner_boot_id=route.owner_boot_id,
            owner_address=route.owner_address,
            route_lease_id=route.route_lease_id,
            lease_generation=route.lease_generation,
            lease_expires_at=route.lease_expires_at,
            admission_lease_id=admission.id,
        )
