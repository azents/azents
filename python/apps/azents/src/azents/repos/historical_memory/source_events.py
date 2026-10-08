"""Completed bounded Historical Memory source-event capture."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.engine.events.types import Event
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.message import MessageRepository


@dataclasses.dataclass(frozen=True)
class HistoricalMemorySourceEventRepository:
    """Capture one source's bounded event tiers before model generation."""

    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def capture(
        self, *, session_id: str, tail_event_id: str, per_tier_limit: int
    ) -> list[Event]:
        async with self.session_manager() as session:
            return await self.message_repository.list_historical_memory_events_by_tier(
                session,
                session_id=session_id,
                tail_event_id=tail_event_id,
                per_tier_limit=per_tier_limit,
            )
