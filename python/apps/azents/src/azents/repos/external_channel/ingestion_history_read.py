"""Completed read-only configuration capture for external-channel orchestration."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclass(frozen=True, kw_only=True)
class ExternalChannelHistoryReadRepository:
    """Close the native read-only scope before authentication or provider work."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def get_configuration(
        self, *, connection_id: str
    ) -> ExternalChannelConnectionConfiguration | None:
        async with self.session_manager() as session:
            result = await self.repository.get_connection_configuration(
                session, connection_id=connection_id
            )
        return result
