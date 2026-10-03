"""Foreground Memory boundary operations without synchronous generation."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
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
        MemoryContextSnapshotRepository, Depends(MemoryContextSnapshotRepository)
    ]

    async def prompt_for_turn(
        self, *, session_id: str, session_manager: SessionManager[AsyncSession]
    ) -> str:
        try:
            return await self.repository.prompt_for_turn(
                session_id=session_id, session_manager=session_manager
            )
        except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
            logger.warning(
                "Memory context authority could not be confirmed.",
                extra={"session_id": session_id},
            )
            return ""

    async def refresh_snapshot(
        self,
        *,
        session_id: str,
        after_compaction: bool,
        session_manager: SessionManager[AsyncSession],
    ) -> bool:
        """Refresh only at root Run preparation or successful committed compaction."""
        try:
            return await self.repository.refresh_snapshot(
                session_id=session_id,
                after_compaction=after_compaction,
                session_manager=session_manager,
            )
        except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
            logger.warning(
                "Memory boundary authority could not be confirmed.",
                extra={"session_id": session_id},
            )
            return False
