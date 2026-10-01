"""Completed database operations for Engine Memory tools."""

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionKind, AgentSessionProductMode
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import (
    Memory,
    MemoryCreate,
    MemoryScope,
    MemorySearchMatch,
    MemorySummary,
)


@dataclasses.dataclass(frozen=True)
class MemorySummaryGroups:
    """Agent and User Memory summaries loaded in one completed operation."""

    agent: list[MemorySummary]
    user: list[MemorySummary]


@dataclasses.dataclass(frozen=True)
class MemorySearchResult:
    """Exact results or partial fallback results from one search operation."""

    exact: list[MemorySummary]
    partial: list[MemorySearchMatch]


@dataclasses.dataclass
class MemoryOperationRepository:
    """Own completed Memory tool and prompt database operations."""

    session_manager: SessionManager[AsyncSession]
    memory_repository: MemoryRepository
    agent_session_repository: AgentSessionRepository

    async def save(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        create: MemoryCreate,
    ) -> None:
        """Upsert one Memory in a completed transaction."""
        async with self.session_manager() as session:
            await self.memory_repository.upsert(
                session,
                agent_id=agent_id,
                user_id=user_id,
                create=create,
            )

    async def list_summaries(
        self,
        *,
        agent_id: str,
        associated_user_id: str | None,
        scope: MemoryScope | None,
        memory_type: str | None,
    ) -> MemorySummaryGroups:
        """Load the requested Memory summary groups in one transaction."""
        async with self.session_manager() as session:
            if scope is MemoryScope.USER:
                user = await self.memory_repository.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=associated_user_id,
                    type=memory_type,
                )
                return MemorySummaryGroups(agent=[], user=user)
            agent = await self.memory_repository.list_summaries(
                session,
                agent_id=agent_id,
                user_id=None,
                type=memory_type,
            )
            if scope is MemoryScope.AGENT or associated_user_id is None:
                return MemorySummaryGroups(agent=agent, user=[])
            user = await self.memory_repository.list_summaries(
                session,
                agent_id=agent_id,
                user_id=associated_user_id,
                type=memory_type,
            )
            return MemorySummaryGroups(agent=agent, user=user)

    async def get(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        name: str,
    ) -> Memory | None:
        """Load one Memory by name in a completed transaction."""
        async with self.session_manager() as session:
            return await self.memory_repository.get_by_name(
                session,
                agent_id=agent_id,
                user_id=user_id,
                name=name,
            )

    async def search(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        include_agent_scope: bool,
        query: str,
    ) -> MemorySearchResult:
        """Apply exact-to-partial Memory search fallback in one transaction."""
        async with self.session_manager() as session:
            exact = await self.memory_repository.search(
                session,
                agent_id=agent_id,
                user_id=user_id,
                include_agent_scope=include_agent_scope,
                query=query,
            )
            if exact:
                return MemorySearchResult(exact=exact, partial=[])
            partial = await self.memory_repository.search_partial(
                session,
                agent_id=agent_id,
                user_id=user_id,
                include_agent_scope=include_agent_scope,
                query=query,
            )
            return MemorySearchResult(exact=[], partial=partial)

    async def delete(
        self,
        *,
        agent_id: str,
        user_id: str | None,
        name: str,
    ) -> bool:
        """Delete one Memory by name in a completed transaction."""
        async with self.session_manager() as session:
            return await self.memory_repository.delete_by_name(
                session,
                agent_id=agent_id,
                user_id=user_id,
                name=name,
            )

    async def load_prompt_summaries(
        self,
        *,
        agent_id: str,
        user_id: str | None,
    ) -> MemorySummaryGroups:
        """Load prompt summary groups in one completed transaction."""
        async with self.session_manager() as session:
            agent = await self.memory_repository.list_summaries(
                session,
                agent_id=agent_id,
                user_id=None,
            )
            user = (
                await self.memory_repository.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=user_id,
                )
                if user_id is not None
                else []
            )
            return MemorySummaryGroups(agent=agent, user=user)

    async def resolve_associated_user_id(self, *, session_id: str) -> str | None:
        """Resolve the active root User Session owner in one transaction."""
        if not session_id:
            return None
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                return None
            root_session = agent_session
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                root_agent = await (
                    self.agent_session_repository.get_root_session_agent_by_session_id(
                        session, session_id
                    )
                )
                if root_agent is None:
                    return None
                loaded_root = await self.agent_session_repository.get_by_id(
                    session,
                    root_agent.agent_session_id,
                )
                if loaded_root is None:
                    return None
                root_session = loaded_root
            if root_session.product_mode is AgentSessionProductMode.USER:
                return root_session.associated_user_id
        return None
