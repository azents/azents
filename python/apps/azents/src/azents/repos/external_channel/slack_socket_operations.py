"""Completed, database-only Slack Socket lease and lifecycle operations."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass(frozen=True)
class SlackSocketOperationRepository:
    """Finish each original lease transition before any SDK/provider operation."""

    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    write_session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def list_connection_ids(self) -> list[str]:
        """Complete independent Socket discovery in a native read-only scope."""
        async with self.read_session_manager() as session:
            ids = await self.repository.list_socket_connection_ids(session)
        return ids

    async def owned_active(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Finish the original owned-active lookup before callback ingestion."""
        async with self.read_session_manager() as session:
            connection = await self.repository.socket_connection_owned_active(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
            )
        return connection is not None

    async def claim(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Commit the existing connection eligibility and lease-owner CAS."""
        async with self.write_session_manager() as session:
            configuration = await self.repository.claim_socket_connection(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
                lease_until=lease_until,
            )
        return configuration

    async def renew(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> bool:
        """Complete the existing live-owner/expiry conditional renewal."""
        async with self.write_session_manager() as session:
            renewed = await self.repository.renew_socket_connection_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
                lease_until=lease_until,
            )
        return renewed

    async def mark_active(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Commit active health and prior-gap clearing through the lease fence."""
        async with self.write_session_manager() as session:
            active = await self.repository.mark_socket_connection_active(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
            )
        return active

    async def record_gap(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        reason: str,
    ) -> bool:
        """Commit degraded gap bookkeeping only for the current live owner."""
        async with self.write_session_manager() as session:
            recorded = await self.repository.record_socket_connection_gap(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
                gap_reason=reason,
            )
        return recorded

    async def release(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        reason: str,
        status: ExternalChannelConnectionStatus,
    ) -> bool:
        """Keep reconnect invalidation or recoverable lease release atomic."""
        async with self.write_session_manager() as session:
            if status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED:
                released = await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=connection_id,
                    reason=reason,
                    now=now,
                    required_configuration_generation=None,
                    required_socket_lease_owner=lease_owner,
                )
            else:
                released = await self.repository.release_socket_connection_lease(
                    session,
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    now=now,
                    gap_reason=reason,
                    gap_status=status,
                )
        return released
