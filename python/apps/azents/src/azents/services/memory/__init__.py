"""Memory service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentType, WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent, NotFound
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import Memory, MemoryCreate, MemoryScope, MemoryUpdate
from azents.services.agent.data import (
    NotAdmin,
    NotBelongToWorkspace,
    PrivateAgentAccessDenied,
)

from .data import (
    DuplicateMemory,
    MemoryCreateInput,
    MemoryListOutput,
    MemoryNotFound,
    MemoryOutput,
    MemoryUpdateInput,
)


@dataclasses.dataclass
class MemoryService:
    """Agent Memory CRUD service for human-facing UI semantics."""

    repository: Annotated[MemoryRepository, Depends(MemoryRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    admin_repository: Annotated[AgentAdminRepository, Depends(AgentAdminRepository)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def list_by_agent(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
        scope: MemoryScope,
        type: str | None,
        query: str | None,
    ) -> Result[
        MemoryListOutput,
        NotFound | NotBelongToWorkspace | PrivateAgentAccessDenied,
    ]:
        """List memories for one visible Agent and one exact scope."""
        access = await self._get_visible_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match access:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        effective_user_id = self._scope_user_id(scope, user_id)
        async with self.session_manager() as session:
            if query is None or query.strip() == "":
                memories = await self.repository.list(
                    session,
                    agent_id=agent_id,
                    user_id=effective_user_id,
                    type=type,
                )
            else:
                memories = await self.repository.search_full(
                    session,
                    agent_id=agent_id,
                    user_id=effective_user_id,
                    query=query,
                    type=type,
                )
        return Success(
            MemoryListOutput(items=[MemoryOutput.convert_from(m) for m in memories])
        )

    async def get_by_id(
        self,
        agent_id: str,
        memory_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        MemoryOutput,
        NotFound | NotBelongToWorkspace | PrivateAgentAccessDenied | MemoryNotFound,
    ]:
        """Fetch one visible Memory by ID."""
        access = await self._get_visible_memory(
            memory_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            user_id=user_id,
            role=role,
        )
        match access:
            case Success(memory):
                return Success(MemoryOutput.convert_from(memory))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

    async def create(
        self,
        agent_id: str,
        create: MemoryCreateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        MemoryOutput,
        NotFound
        | NotBelongToWorkspace
        | PrivateAgentAccessDenied
        | NotAdmin
        | DuplicateMemory,
    ]:
        """Create Memory with strict conflict semantics."""
        access = await self._get_visible_agent(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match access:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        if create.scope == MemoryScope.AGENT:
            admin_check = await self._check_admin_or_owner(
                agent_id,
                workspace_user_id,
                role,
            )
            if admin_check is not None:
                return Failure(admin_check)

        effective_user_id = self._scope_user_id(create.scope, user_id)
        async with self.session_manager() as session:
            duplicate = await self.repository.get_by_name(
                session,
                agent_id=agent_id,
                user_id=effective_user_id,
                name=create.name,
            )
            if duplicate is not None:
                return Failure(
                    DuplicateMemory(
                        agent_id=agent_id,
                        user_id=effective_user_id,
                        name=create.name,
                    )
                )
            memory = await self.repository.create(
                session,
                agent_id=agent_id,
                user_id=effective_user_id,
                create=MemoryCreate(
                    scope=create.scope,
                    type=create.type,
                    name=create.name,
                    description=create.description,
                    content=create.content,
                ),
            )
        return Success(MemoryOutput.convert_from(memory))

    async def update_by_id(
        self,
        agent_id: str,
        memory_id: str,
        update: MemoryUpdateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        MemoryOutput,
        NotFound
        | NotBelongToWorkspace
        | PrivateAgentAccessDenied
        | NotAdmin
        | MemoryNotFound
        | DuplicateMemory,
    ]:
        """Update Memory by ID."""
        access = await self._get_visible_memory(
            memory_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            user_id=user_id,
            role=role,
        )
        match access:
            case Success(existing):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        if existing.scope == MemoryScope.AGENT:
            admin_check = await self._check_admin_or_owner(
                existing.agent_id,
                workspace_user_id,
                role,
            )
            if admin_check is not None:
                return Failure(admin_check)

        if "name" in update:
            duplicate_user_id = (
                None if existing.scope == MemoryScope.AGENT else existing.user_id
            )
            async with self.session_manager() as session:
                duplicate = await self.repository.get_by_name(
                    session,
                    agent_id=existing.agent_id,
                    user_id=duplicate_user_id,
                    name=update["name"],
                )
            if duplicate is not None and duplicate.id != memory_id:
                return Failure(
                    DuplicateMemory(
                        agent_id=existing.agent_id,
                        user_id=duplicate_user_id,
                        name=update["name"],
                    )
                )

        repo_update = MemoryUpdate()
        if "type" in update:
            repo_update["type"] = update["type"]
        if "name" in update:
            repo_update["name"] = update["name"]
        if "description" in update:
            repo_update["description"] = update["description"]
        if "content" in update:
            repo_update["content"] = update["content"]

        async with self.session_manager() as session:
            memory = await self.repository.update_by_id(
                session,
                memory_id,
                repo_update,
            )
        if memory is None:
            return Failure(MemoryNotFound(memory_id=memory_id))
        return Success(MemoryOutput.convert_from(memory))

    async def delete_by_id(
        self,
        agent_id: str,
        memory_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        NotFound
        | NotBelongToWorkspace
        | PrivateAgentAccessDenied
        | NotAdmin
        | MemoryNotFound,
    ]:
        """Delete Memory by ID."""
        access = await self._get_visible_memory(
            memory_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            user_id=user_id,
            role=role,
        )
        match access:
            case Success(existing):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        if existing.scope == MemoryScope.AGENT:
            admin_check = await self._check_admin_or_owner(
                existing.agent_id,
                workspace_user_id,
                role,
            )
            if admin_check is not None:
                return Failure(admin_check)

        async with self.session_manager() as session:
            deleted = await self.repository.delete_by_id(session, memory_id)
        if not deleted:
            return Failure(MemoryNotFound(memory_id=memory_id))
        return Success(None)

    async def _get_visible_agent(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[Agent, NotFound | NotBelongToWorkspace | PrivateAgentAccessDenied]:
        """Fetch Agent and check workspace visibility."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(NotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        if agent.type == AgentType.PRIVATE and role != WorkspaceUserRole.OWNER:
            async with self.session_manager() as session:
                admin = await self.admin_repository.is_admin(
                    session,
                    agent_id,
                    workspace_user_id,
                )
            if not admin:
                return Failure(PrivateAgentAccessDenied(agent_id=agent_id))
        return Success(agent)

    async def _get_visible_memory(
        self,
        memory_id: str,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        Memory,
        NotFound | NotBelongToWorkspace | PrivateAgentAccessDenied | MemoryNotFound,
    ]:
        """Fetch Memory and check scope visibility."""
        async with self.session_manager() as session:
            memory = await self.repository.get_by_id(session, memory_id)
        if memory is None:
            return Failure(MemoryNotFound(memory_id=memory_id))
        if memory.agent_id != agent_id:
            return Failure(MemoryNotFound(memory_id=memory_id))
        agent_access = await self._get_visible_agent(
            memory.agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match agent_access:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(agent_access)

        if memory.scope == MemoryScope.USER and memory.user_id != user_id:
            return Failure(MemoryNotFound(memory_id=memory_id))
        return Success(memory)

    async def _check_admin_or_owner(
        self,
        agent_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> NotAdmin | None:
        """Check whether requester is Agent admin or workspace owner."""
        if role == WorkspaceUserRole.OWNER:
            return None
        async with self.session_manager() as session:
            admin = await self.admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            )
        if not admin:
            return NotAdmin(agent_id=agent_id)
        return None

    def _scope_user_id(self, scope: MemoryScope, user_id: str) -> str | None:
        """Return the repository user ID for a Memory scope."""
        if scope == MemoryScope.AGENT:
            return None
        return user_id
