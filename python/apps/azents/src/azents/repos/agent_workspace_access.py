"""Completed Agent Workspace inspection and Runtime-work admission."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceAgentNotFound:
    """Workspace target Agent does not exist."""


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceMembershipNotFound:
    """Requesting user is not a member of the Agent Workspace."""


type AgentWorkspaceAccess = Result[
    Agent, AgentWorkspaceAgentNotFound | AgentWorkspaceMembershipNotFound
]


@dataclasses.dataclass
class AgentWorkspaceAccessRepository:
    """Keep inspection read-only and fence new Runtime work separately."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    write_session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def get_agent_for_user(
        self, agent_id: str, *, user_id: str
    ) -> AgentWorkspaceAccess:
        """Return one authorized detached Agent snapshot without starting work."""
        async with self.session_manager() as session:
            return await self._authorize(session, agent_id=agent_id, user_id=user_id)

    async def admit_runtime_work(
        self, agent_id: str, *, user_id: str
    ) -> AgentWorkspaceAccess:
        """Serialize new external work admission with Agent deletion, then close SQL."""
        async with self.write_session_manager() as session:
            result = await self._authorize(session, agent_id=agent_id, user_id=user_id)
            if isinstance(result, Success):
                await require_active_agent(session, agent_id=agent_id)
            return result

    async def _authorize(
        self, session: ReadSession, *, agent_id: str, user_id: str
    ) -> AgentWorkspaceAccess:
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(AgentWorkspaceAgentNotFound())
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session, workspace_id=agent.workspace_id, user_id=user_id
        )
        if workspace_user is None:
            return Failure(AgentWorkspaceMembershipNotFound())
        return Success(agent)
