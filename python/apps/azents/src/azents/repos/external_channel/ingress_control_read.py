"""Completed reads for bounded ingress controls and sanitized diagnostics."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressDiagnosticSnapshot,
    ExternalChannelIngressOwner,
)


@dataclass(frozen=True, kw_only=True)
class ExternalChannelIngressControlReadRepository:
    """Finish the original explicit commits before control or metric effects."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]

    async def get_release_owner(
        self, *, owner_id: str
    ) -> ExternalChannelIngressOwner | None:
        """Read lifecycle presence without adding lease, lock or time predicates."""
        async with self.session_manager() as session:
            owner = await self.queue_repository.get_active_owner(
                session, owner_id=owner_id
            )
            await session.commit()
        return owner

    async def inspect_active(
        self, *, now: datetime.datetime, limit: int
    ) -> ExternalChannelIngressDiagnosticSnapshot:
        """Complete the original bounded aggregate and ordered sanitized read."""
        async with self.session_manager() as session:
            snapshot = await self.queue_repository.inspect_active(
                session, now=now, limit=limit
            )
            await session.commit()
        return snapshot
