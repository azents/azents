"""Read-only Routine inspection over completed authorized repository snapshots."""

from dataclasses import dataclass
from typing import Annotated

from azcommon.result import Result
from fastapi import Depends

from azents.repos.routine.inspection import (
    RoutineDetailSnapshot,
    RoutineInspectionError,
    RoutineInspectionRepository,
    RoutineInventorySnapshot,
)


@dataclass(frozen=True)
class RoutineInspectionService:
    """Expose inventory and detail without admitting or modifying Routine work."""

    repository: Annotated[RoutineInspectionRepository, Depends()]

    async def list_for_session(
        self, *, agent_id: str, session_id: str, user_id: str
    ) -> Result[RoutineInventorySnapshot, RoutineInspectionError]:
        """Return the selected Session's definitions after authorization."""
        return await self.repository.list_for_session(
            agent_id=agent_id, session_id=session_id, user_id=user_id
        )

    async def detail(
        self, *, agent_id: str, session_id: str, user_id: str, slug: str
    ) -> Result[RoutineDetailSnapshot, RoutineInspectionError]:
        """Return current content, latest occurrence and bounded retained work."""
        return await self.repository.detail(
            agent_id=agent_id, session_id=session_id, user_id=user_id, slug=slug
        )
