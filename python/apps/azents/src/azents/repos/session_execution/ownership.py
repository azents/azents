"""Database-only transaction scopes bound to one Session execution owner."""

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)


@dataclasses.dataclass(frozen=True)
class OwnerBoundSessionManager:
    """Fence every execution transaction against durable ownership takeover.

    Only database work may run inside the yielded scope. Model, tool, Runtime,
    broker, and filesystem operations must execute after that scope closes.
    """

    session_manager: SessionManager[AsyncSession]
    session_id: str
    owner_generation: int

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        """Lock current ownership until the database operation commits or aborts."""
        async with self.session_manager() as session:
            current = await AgentSessionRepository().wait_for_execution_lock_by_id(
                session,
                self.session_id,
            )
            if current is None or current.owner_generation != self.owner_generation:
                raise CanonicalExecutionOwnerGenerationStaleError(
                    "Session owner generation is stale"
                )
            yield session

    async def assert_current(self) -> None:
        """Check admission authority without retaining a transaction across I/O."""
        async with self():
            pass
