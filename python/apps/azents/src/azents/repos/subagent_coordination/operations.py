"""Completed native read-only Subagent coordination observations."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.subagent_coordination.data import SubagentCoordinationSnapshot
from azents.repos.subagent_coordination.repository import SubagentCoordinationRepository


@dataclass(frozen=True)
class SubagentCoordinationReadRepository:
    """Own and close one bounded coordination snapshot before returning."""

    repository: Annotated[
        SubagentCoordinationRepository, Depends(SubagentCoordinationRepository)
    ]
    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def project_root_tree(
        self,
        *,
        current_session_id: str,
        configured_capacity: int,
    ) -> SubagentCoordinationSnapshot | None:
        """Observe the existing root-first bounded tree without writer locks."""
        async with self.session_manager() as session:
            return await self.repository.project_root_tree(
                session,
                current_session_id=current_session_id,
                configured_capacity=configured_capacity,
            )
