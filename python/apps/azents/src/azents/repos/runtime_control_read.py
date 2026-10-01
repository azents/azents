"""Completed database reads used by the Runtime Control composition root."""

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_connection_generation.data import (
    RuntimeConnectionGenerationCutover,
)
from azents.repos.runtime_connection_generation.repository import (
    RuntimeConnectionGenerationRepository,
)


@dataclasses.dataclass
class RuntimeControlReadRepository:
    """Own completed Runtime Control startup and offer reads."""

    session_manager: SessionManager[AsyncSession]
    runtime_repository: AgentRuntimeRepository
    generation_repository: RuntimeConnectionGenerationRepository

    async def get_runtime(self, runtime_id: str) -> AgentRuntime | None:
        """Return one detached Runtime after completing the read transaction."""
        async with self.session_manager() as session:
            return await self.runtime_repository.get_by_id(session, runtime_id)

    async def get_generation_cutover(
        self,
    ) -> RuntimeConnectionGenerationCutover | None:
        """Return the current allocator cutover after completing its transaction."""
        async with self.session_manager() as session:
            return await self.generation_repository.get_cutover(session)
