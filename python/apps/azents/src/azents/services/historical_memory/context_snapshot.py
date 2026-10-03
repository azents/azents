"""Completed owner-fenced Memory snapshot orchestration and rendering."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.historical_memory_snapshot_policy import render_memory_context_snapshot
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.historical_memory.context_snapshot_operations import (
    MemoryContextSnapshotOperations,
)


@dataclasses.dataclass
class MemoryContextSnapshotService:
    """Render detached snapshots without owning live database sessions."""

    operations: Annotated[
        MemoryContextSnapshotOperations, Depends(MemoryContextSnapshotOperations)
    ]

    def with_owner(
        self, owner: SessionExecutionOwner
    ) -> "MemoryContextSnapshotService":
        """Return an execution-local service with repository-owned fencing."""
        return dataclasses.replace(self, operations=self.operations.with_owner(owner))

    async def prompt_for_turn(self, *, session_id: str) -> str:
        """Return filtered Memory only after its database transaction completes."""
        snapshot = await self.operations.prompt_snapshot(session_id=session_id)
        return "" if snapshot is None else render_memory_context_snapshot(snapshot)

    async def refresh_snapshot(
        self, *, session_id: str, after_compaction: bool
    ) -> bool:
        """Prepare the explicit boundary through one completed repository operation."""
        return await self.operations.refresh_snapshot(
            session_id=session_id, after_compaction=after_compaction
        )
