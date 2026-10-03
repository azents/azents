"""Completed database-only operations for human-facing Memory CRUD."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import Memory, MemoryCreate, MemoryUpdate


@dataclasses.dataclass(frozen=True)
class MemoryUIOperations:
    """Return detached records, preserving the existing CRUD transaction groups."""

    repository: Annotated[MemoryRepository, Depends(MemoryRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    admin_repository: Annotated[AgentAdminRepository, Depends(AgentAdminRepository)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def list_memories(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        type: str | None,
        query: str | None,
    ) -> list[Memory]:
        async with self.session_manager() as session:
            if query is None or query.strip() == "":
                return await self.repository.list(
                    session, agent_id=agent_id, user_id=user_id, type=type
                )
            return await self.repository.search_full(
                session, agent_id=agent_id, user_id=user_id, query=query, type=type
            )

    async def create_if_name_available(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        create: MemoryCreate,
    ) -> Memory | None:
        """Keep the existing name check and create in one database operation."""
        async with self.session_manager() as session:
            duplicate = await self.repository.get_by_name(
                session, agent_id=agent_id, user_id=user_id, name=create.name
            )
            if duplicate is not None:
                return None
            return await self.repository.create(
                session, agent_id=agent_id, user_id=user_id, create=create
            )

    async def get_by_name(
        self, *, agent_id: str, user_id: str | None, name: str
    ) -> Memory | None:
        async with self.session_manager() as session:
            return await self.repository.get_by_name(
                session, agent_id=agent_id, user_id=user_id, name=name
            )

    async def update_by_id(self, memory_id: str, update: MemoryUpdate) -> Memory | None:
        async with self.session_manager() as session:
            return await self.repository.update_by_id(session, memory_id, update)

    async def delete_by_id(self, memory_id: str) -> bool:
        async with self.session_manager() as session:
            return await self.repository.delete_by_id(session, memory_id)

    async def get_agent(self, agent_id: str) -> Agent | None:
        async with self.session_manager() as session:
            return await self.agent_repository.get_by_id(session, agent_id)

    async def is_admin(self, agent_id: str, workspace_user_id: str) -> bool:
        async with self.session_manager() as session:
            return await self.admin_repository.is_admin(
                session, agent_id, workspace_user_id
            )

    async def get_by_id(self, memory_id: str) -> Memory | None:
        async with self.session_manager() as session:
            return await self.repository.get_by_id(session, memory_id)
