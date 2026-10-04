"""Completed unlocked canonical Worker execution snapshot projection."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution import SessionExecutionRepository
from azents.repos.session_execution.data import CanonicalExecutionSnapshot


@dataclasses.dataclass(frozen=True)
class WorkerSessionSnapshotOperationRepository:
    """Own the existing canonical read after the separate ownership claim."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    session_execution_repository: Annotated[
        SessionExecutionRepository, Depends(SessionExecutionRepository)
    ]

    async def load(
        self, session_id: str, *, owner_generation: int
    ) -> CanonicalExecutionSnapshot:
        """Preserve the unlocked canonical validation and detached snapshot."""
        async with self.session_manager() as session:
            return await self.session_execution_repository.load_canonical_snapshot(
                session, session_id=session_id, owner_generation=owner_generation
            )
