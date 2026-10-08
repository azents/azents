"""Completed durable authority reads for volatile live projection."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository


@dataclass(frozen=True)
class LiveProjectionAuthorityRepository:
    """Close PostgreSQL reads before volatile store and broadcast effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]

    async def owns_generation(
        self,
        *,
        session_id: str,
        owner_generation: int,
    ) -> bool:
        """Return whether the Session exists with the requested generation."""
        async with self.session_manager() as session:
            current = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            owned = current is not None and current.owner_generation == owner_generation
        return owned

    async def terminal_matches_current_run(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> bool:
        """Accept terminal cleanup when no Run or the same Run is running."""
        async with self.session_manager() as session:
            current = await self.agent_run_repository.get_running_by_session_id(
                session,
                session_id=session_id,
            )
            matches = current is None or current.id == run_id
        return matches
