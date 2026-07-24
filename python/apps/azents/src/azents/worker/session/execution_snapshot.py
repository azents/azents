"""Worker entry point for canonical Postgres-derived Session execution authority."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.session_execution.data import (
    CanonicalExecutionSnapshot,
    PendingCommandSnapshot,
)


class CanonicalExecutionWorkDriftError(CanonicalExecutionSnapshotError):
    """Raised when durable work changes after the canonical snapshot."""


__all__ = [
    "CanonicalExecutionSnapshot",
    "CanonicalExecutionOwnerGenerationStaleError",
    "CanonicalExecutionSnapshotError",
    "CanonicalExecutionSnapshotLoader",
    "CanonicalExecutionWorkDriftError",
    "PendingCommandSnapshot",
]


@dataclasses.dataclass(frozen=True)
class CanonicalExecutionSnapshotLoader:
    """Delegate durable projection to the Session execution repository."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    session_execution_repository: Annotated[
        SessionExecutionRepository, Depends(SessionExecutionRepository)
    ]

    async def load(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> CanonicalExecutionSnapshot:
        """Load one immutable execution snapshot after the ownership claim."""
        async with self.session_manager() as session:
            return await self.session_execution_repository.load_canonical_snapshot(
                session,
                session_id=session_id,
                owner_generation=owner_generation,
            )
