"""Transactional External Channel provider-event admission."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelEventAdmission,
    ExternalChannelEventCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass
class ExternalChannelAdmissionService:
    """Commit durable provider-event admission before acknowledging the provider."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]

    async def admit(
        self,
        create: ExternalChannelEventCreate,
    ) -> ExternalChannelEventAdmission:
        """Atomically admit or deduplicate one provider event."""
        async with self.session_manager() as session:
            admission = await self.repository.admit_event(session, create)
            await session.commit()
            return admission
