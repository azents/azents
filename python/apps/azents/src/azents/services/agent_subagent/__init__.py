"""AgentSubagent service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_subagent import AgentSubagentRepository
from azents.repos.agent_subagent.data import (
    AgentSubagent,
    AgentSubagentCreate,
    DuplicateAgentSubagent,
    NotFound,
)

from .data import (
    AgentNotFound,
    AgentSubagentCreateInput,
    AgentSubagentListOutput,
    AgentSubagentOutput,
    AgentSubagentUpdateInput,
    CrossWorkspace,
    InvalidAgentRole,
    SubagentNotFound,
)


@dataclasses.dataclass
class AgentSubagentService:
    """AgentSubagent CRUD service.

    Handles validation for Subagent links, such as role validation and workspace match.
    """

    repository: Annotated[AgentSubagentRepository, Depends(AgentSubagentRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self,
        create: AgentSubagentCreateInput,
    ) -> Result[
        AgentSubagentOutput,
        AgentNotFound
        | SubagentNotFound
        | InvalidAgentRole
        | CrossWorkspace
        | DuplicateAgentSubagent,
    ]:
        """Create Subagent link.

        :param create: Create data
        :return: Created AgentSubagent or error
        """
        # Fetch agent + validate role
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, create.agent_id)
        if agent is None:
            return Failure(AgentNotFound(agent_id=create.agent_id))
        if agent.role != AgentRole.AGENT:
            return Failure(
                InvalidAgentRole(
                    agent_id=create.agent_id,
                    expected=AgentRole.AGENT.value,
                    actual=agent.role.value,
                )
            )

        # Fetch subagent + validate role
        async with self.session_manager() as session:
            subagent = await self.agent_repository.get_by_id(
                session, create.subagent_id
            )
        if subagent is None:
            return Failure(SubagentNotFound(subagent_id=create.subagent_id))
        if subagent.role != AgentRole.SUBAGENT:
            return Failure(
                InvalidAgentRole(
                    agent_id=create.subagent_id,
                    expected=AgentRole.SUBAGENT.value,
                    actual=subagent.role.value,
                )
            )

        # Validate workspace match
        if agent.workspace_id != subagent.workspace_id:
            return Failure(
                CrossWorkspace(
                    agent_id=create.agent_id,
                    subagent_id=create.subagent_id,
                )
            )

        # Create link
        repo_create = AgentSubagentCreate(
            agent_id=create.agent_id,
            subagent_id=create.subagent_id,
            description=create.description,
            enabled=create.enabled,
        )
        async with self.session_manager() as session:
            result = await self.repository.create(session, repo_create)

        match result:
            case Success(value):
                return Success(self._to_output(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def list_by_agent(self, agent_id: str) -> AgentSubagentListOutput:
        """Fetch subagent link list for parent agent.

        :param agent_id: Parent agent ID
        :return: AgentSubagent list
        """
        async with self.session_manager() as session:
            items = await self.repository.list_by_agent(session, agent_id)
        return AgentSubagentListOutput(items=[self._to_output(item) for item in items])

    async def update(
        self,
        agent_subagent_id: str,
        update: AgentSubagentUpdateInput,
    ) -> Result[AgentSubagentOutput, NotFound]:
        """Update Subagent link.

        :param agent_subagent_id: AgentSubagent ID
        :param update: Update data
        :return: Updated AgentSubagent or error
        """
        async with self.session_manager() as session:
            result = await self.repository.update_by_id(
                session, agent_subagent_id, update
            )

        match result:
            case Success(value):
                return Success(self._to_output(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def delete(self, agent_subagent_id: str) -> None:
        """Delete Subagent link.

        :param agent_subagent_id: AgentSubagent ID
        """
        async with self.session_manager() as session:
            await self.repository.delete_by_id(session, agent_subagent_id)

    def _to_output(
        self,
        item: AgentSubagent,
    ) -> AgentSubagentOutput:
        """Convert domain model to output model."""
        return AgentSubagentOutput(
            id=item.id,
            agent_id=item.agent_id,
            subagent_id=item.subagent_id,
            description=item.description,
            enabled=item.enabled,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
