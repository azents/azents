"""Completed, database-only Slack Work presence lease operations."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    SlackWorkPresenceTarget,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass(frozen=True)
class SlackPresenceOperationRepository:
    """Own read and mutation lifetimes without exposing sessions to managers."""

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
        """Complete independent discovery in a native read-only scope."""
        async with self.read_session_manager() as session:
            ids = await self.repository.list_slack_presence_connection_ids(session)
        return ids

    async def claim(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Commit the original eligible-connection conditional lease claim."""
        async with self.write_session_manager() as session:
            configuration = await self.repository.claim_slack_presence_connection(
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
        configuration_generation: int,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> bool:
        """Complete the existing owner/configuration/expiry renewal fence."""
        async with self.write_session_manager() as session:
            renewed = await self.repository.renew_slack_presence_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                required_configuration_generation=configuration_generation,
                now=now,
                lease_until=lease_until,
            )
        return renewed

    async def release(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Commit the existing owner-conditional presence lease release."""
        async with self.write_session_manager() as session:
            released = await self.repository.release_slack_presence_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
            )
        return released

    async def load_targets(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        configuration_generation: int,
        now: datetime.datetime,
    ) -> tuple[SlackWorkPresenceTarget, ...] | None:
        """Read detached targets through the original authority predicates."""
        async with self.read_session_manager() as session:
            targets = await self.repository.list_owned_slack_work_presence_targets(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                required_configuration_generation=configuration_generation,
                now=now,
            )
        return targets
