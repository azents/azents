"""Foreground Memory boundary operations without synchronous generation."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.core.historical_memory_context import (
    MemoryContextPrompt,
    prepare_memory_context_prompt,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationDeadlineError,
)
from azents.repos.memory_context_snapshot import MemoryContextSnapshotRepository

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MemoryContextSnapshotService:
    """Delegate complete database operations; ordinary turns only filter authority."""

    repository: Annotated[
        MemoryContextSnapshotRepository, Depends(MemoryContextSnapshotRepository.create)
    ]

    def with_owner(
        self, owner: SessionExecutionOwner
    ) -> "MemoryContextSnapshotService":
        """Bind the foreground operation to one immutable execution owner."""
        return dataclasses.replace(self, repository=self.repository.with_owner(owner))

    async def prompt_for_turn(self, *, session_id: str) -> str:
        """Render the same atomic admission used by model preparation."""
        return (await self.context_for_turn(session_id=session_id)).text

    async def context_for_turn(self, *, session_id: str) -> MemoryContextPrompt:
        """Return text and exact selected identities from one authority check."""
        try:
            return await self.repository.prompt_for_turn(session_id=session_id)
        except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
            logger.warning(
                "Memory context authority could not be confirmed.",
                extra={"session_id": session_id},
            )
            return prepare_memory_context_prompt(None)

    async def refresh_snapshot(
        self,
        *,
        session_id: str,
        after_compaction: bool,
    ) -> bool:
        """Refresh only at root Run preparation or successful committed compaction."""
        try:
            return await self.repository.refresh_snapshot(
                session_id=session_id,
                after_compaction=after_compaction,
            )
        except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
            logger.warning(
                "Memory boundary authority could not be confirmed.",
                extra={"session_id": session_id},
            )
            return False
