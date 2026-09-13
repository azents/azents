"""Runtime Web owner lifecycle across PostgreSQL, memory, and Runner Control."""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import datetime

from azents_runtime_control.runner_web import (
    RunnerWebCancelReason,
    RunnerWebIdentity,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.runtime_web.data import (
    RuntimeWebTunnelAuthority,
    RuntimeWebTunnelRoute,
)
from azents.repos.runtime_web.transport_repository import (
    RuntimeWebTransportRepository,
)
from azents.runtime.control_protocol.grpc.runner_web_registry import (
    RuntimeWebOwnerRegistry,
    RuntimeWebOwnerTunnel,
)
from azents.runtime.web_transport_dispatcher import RuntimeWebTransportDispatcher


@dataclasses.dataclass(frozen=True)
class RuntimeWebOwnedTunnel:
    """One local owner with its exact durable route lease."""

    route: RuntimeWebTunnelRoute
    tunnel: RuntimeWebOwnerTunnel


class RuntimeWebTransportCoordinator:
    """Coordinate durable ownership without holding DB transactions during I/O."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebTransportRepository,
        registry: RuntimeWebOwnerRegistry,
        dispatcher: RuntimeWebTransportDispatcher,
        owner_replica_id: str,
        owner_boot_id: str,
        owner_address: str,
        lease_seconds: float,
        maximum_active_connections: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.registry = registry
        self.dispatcher = dispatcher
        self.owner_replica_id = owner_replica_id
        self.owner_boot_id = owner_boot_id
        self.owner_address = owner_address
        self.lease_seconds = lease_seconds
        self.maximum_active_connections = maximum_active_connections
        self.clock = clock

    async def open_owner(
        self,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebOwnedTunnel:
        """Acquire ownership, publish the local rendezvous, and dispatch Runner open."""
        route = await self._acquire(identity)
        try:
            tunnel = await self.registry.create_owner(route)
        except asyncio.CancelledError:
            await self._release(route)
            raise
        except Exception:
            await self._release(route)
            raise
        try:
            await self.dispatcher.open(identity, requested_at=self._now())
        except asyncio.CancelledError:
            await self.registry.release(tunnel)
            await self._release(route)
            raise
        except Exception:
            await self.registry.release(tunnel)
            await self._release(route)
            raise
        return RuntimeWebOwnedTunnel(route=route, tunnel=tunnel)

    async def renew_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        allow_replaced_cycle: bool,
    ) -> RuntimeWebOwnedTunnel:
        """Renew only this boot's exact route and admission leases."""
        async with self.session_manager() as session:
            route = await self.repository.renew_route(
                session,
                tunnel_id=owned.route.authority.tunnel_id,
                route_lease_id=owned.route.route_lease_id,
                owner_boot_id=owned.route.owner_boot_id,
                lease_generation=owned.route.lease_generation,
                lease_seconds=self.lease_seconds,
                allow_replaced_cycle=allow_replaced_cycle,
            )
        return RuntimeWebOwnedTunnel(route=route, tunnel=owned.tunnel)

    async def resolve_route(
        self,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebTunnelRoute | None:
        """Resolve an exact live route for local join or one-hop relay."""
        async with self.session_manager() as session:
            route = await self.repository.get_live_route(
                session,
                tunnel_id=identity.tunnel_id,
            )
        if route is None or _identity(route) != identity:
            return None
        return route

    async def close_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        reason: RunnerWebCancelReason,
    ) -> None:
        """Cancel transport, remove volatile frames, then release durable leases."""
        try:
            await self.dispatcher.cancel(
                _identity(owned.route),
                reason=reason,
                requested_at=self._now(),
            )
        finally:
            try:
                await self.registry.release(owned.tunnel)
            finally:
                await self._release(owned.route)

    async def _acquire(
        self,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebTunnelRoute:
        async with self.session_manager() as session:
            return await self.repository.acquire_route(
                session,
                authority=_authority(identity),
                owner_replica_id=self.owner_replica_id,
                owner_boot_id=self.owner_boot_id,
                owner_address=self.owner_address,
                lease_seconds=self.lease_seconds,
                maximum_active_connections=self.maximum_active_connections,
            )

    async def _release(self, route: RuntimeWebTunnelRoute) -> None:
        async with self.session_manager() as session:
            await self.repository.release_route(
                session,
                tunnel_id=route.authority.tunnel_id,
                route_lease_id=route.route_lease_id,
                owner_boot_id=route.owner_boot_id,
                lease_generation=route.lease_generation,
            )

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Web coordinator clock must be timezone-aware")
        return now


def _authority(identity: RunnerWebIdentity) -> RuntimeWebTunnelAuthority:
    return RuntimeWebTunnelAuthority(
        tunnel_id=identity.tunnel_id,
        endpoint_id=identity.endpoint_id,
        cycle_id=identity.cycle_id,
        endpoint_authority_revision=identity.endpoint_authority_revision,
        close_barrier=identity.close_barrier,
        runtime_id=identity.runtime_id,
        desired_generation=identity.desired_generation,
        runner_generation=identity.runner_generation,
        port=identity.port,
        join_nonce=identity.join_nonce,
        registration_deadline_at=identity.registration_deadline_at,
        approval_deadline_at=identity.approval_deadline_at,
        transport_deadline_at=identity.transport_deadline_at,
    )


def _identity(route: RuntimeWebTunnelRoute) -> RunnerWebIdentity:
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
