"""Completed database-only Runtime stream Owner route operations."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.runtime_stream_route_data import RuntimeStreamRouteEpoch
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteRepository,
)


@dataclasses.dataclass(frozen=True)
class RuntimeStreamRouteOperationRepository:
    """Resolve each existing route transaction before application effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    route_repository: Annotated[
        RuntimeWebSessionRouteRepository, Depends(RuntimeWebSessionRouteRepository)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def acquire(
        self,
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
        """Keep Runtime-then-route admission and SQL-time replacement atomic."""
        async with self.session_manager() as session:
            return await self.route_repository.acquire(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
                owner_replica_id=owner_replica_id,
                owner_boot_id=owner_boot_id,
                owner_address=owner_address,
                join_nonce_hash=join_nonce_hash,
                protocol_fingerprint=protocol_fingerprint,
                lease_seconds=lease_seconds,
            )

    async def renew(
        self,
        *,
        epoch: RuntimeStreamRouteEpoch,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> RuntimeWebSessionRoute:
        """Renew the same route-then-Runtime lease, not the original offer."""
        async with self.session_manager() as session:
            return await self.route_repository.renew(
                session,
                runtime_id=epoch.runtime_id,
                owner_boot_id=epoch.owner_boot_id,
                session_lease_id=epoch.session_lease_id,
                lease_generation=epoch.lease_generation,
                protocol_fingerprint=protocol_fingerprint,
                lease_seconds=lease_seconds,
            )

    async def resolve(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
        protocol_fingerprint: str,
    ) -> RuntimeWebSessionRoute | None:
        """Retain exact stale/expired/draining suppression in the narrow query."""
        async with self.read_session_manager() as session:
            return await self.route_repository.resolve(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
                protocol_fingerprint=protocol_fingerprint,
            )

    async def consume_join(
        self,
        *,
        epoch: RuntimeStreamRouteEpoch,
        protocol_fingerprint: str,
        join_nonce_hash: str,
        join_deadline_at: datetime.datetime,
    ) -> RuntimeWebSessionRoute:
        """Commit the existing one-time nonce before local deadline/registry work."""
        async with self.session_manager() as session:
            return await self.route_repository.consume_join(
                session,
                runtime_id=epoch.runtime_id,
                owner_boot_id=epoch.owner_boot_id,
                session_lease_id=epoch.session_lease_id,
                lease_generation=epoch.lease_generation,
                protocol_fingerprint=protocol_fingerprint,
                join_nonce_hash=join_nonce_hash,
                join_deadline_at=join_deadline_at,
            )

    async def mark_draining(
        self, epoch: RuntimeStreamRouteEpoch
    ) -> RuntimeWebSessionRoute:
        """Set the current epoch's drain time once under its existing TTL check."""
        async with self.session_manager() as session:
            return await self.route_repository.mark_draining(
                session,
                runtime_id=epoch.runtime_id,
                owner_boot_id=epoch.owner_boot_id,
                session_lease_id=epoch.session_lease_id,
                lease_generation=epoch.lease_generation,
            )

    async def release(self, epoch: RuntimeStreamRouteEpoch) -> bool:
        """Release exact identity without adding an expiry or draining predicate."""
        async with self.session_manager() as session:
            return await self.route_repository.release(
                session,
                runtime_id=epoch.runtime_id,
                owner_boot_id=epoch.owner_boot_id,
                session_lease_id=epoch.session_lease_id,
                lease_generation=epoch.lease_generation,
            )
