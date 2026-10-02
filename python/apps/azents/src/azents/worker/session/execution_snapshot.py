"""Worker facade for completed canonical execution snapshot reads."""

import dataclasses
from typing import Annotated

from fastapi import Depends

import azents.repos.session_execution.data
from azents.repos.worker_session_snapshot import (
    WorkerSessionSnapshotOperationRepository,
)


@dataclasses.dataclass(frozen=True)
class CanonicalExecutionSnapshotLoader:
    """Expose the canonical projection without live sessions or DTO re-exports."""

    repository: Annotated[
        WorkerSessionSnapshotOperationRepository,
        Depends(WorkerSessionSnapshotOperationRepository),
    ]

    async def load(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> azents.repos.session_execution.data.CanonicalExecutionSnapshot:
        """Return the unchanged detached snapshot after its repository read closes."""
        return await self.repository.load(session_id, owner_generation=owner_generation)
