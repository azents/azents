"""Completed native read-only ingress recovery observation."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import ExternalChannelIngressOwner


@dataclass
class ExternalChannelIngressRecoveryReadRepository:
    """Observe due owners without retaining a transaction during job submission."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]

    async def list_recoverable_owners(
        self, *, now: datetime.datetime, limit: int
    ) -> list[ExternalChannelIngressOwner]:
        """Return the existing bounded recovery owner projection."""
        async with self.session_manager() as session:
            owners = await self.queue_repository.list_recoverable_owners(
                session, now=now, limit=limit
            )
        return owners
