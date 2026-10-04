"""Explicit quiesced handover orchestration; never a foreground fallback."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverRequest,
    MemoryHandoverResult,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.cutover import (
    MemoryHandoverRepository,
)


@dataclasses.dataclass
class MemoryHandoverService:
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def handover(self, request: MemoryHandoverRequest) -> MemoryHandoverResult:
        """Reset snapshots, fence units, and reconcile before new-code admission."""
        request.validate()
        repository = MemoryHandoverRepository(self.session_manager)
        snapshots = 0
        cursor = None
        while True:
            page = await repository.reset_snapshots(request=request, after=cursor)
            snapshots += page.count
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        units = 0
        cursor = None
        while True:
            page = await repository.fence_units(request=request, after=cursor)
            units += page.count
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        sources = 0
        if request.action is not MemoryHandoverAction.ROLLBACK:
            cursor = None
            while True:
                page = await repository.reconcile_sources(request=request, after=cursor)
                sources += page.count
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        return MemoryHandoverResult(snapshots, units, sources)
