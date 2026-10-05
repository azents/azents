"""Completed Agent Workspace access reads."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceAgentNotFound:
    """Workspace target Agent does not exist."""


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceMembershipNotFound:
    """Requesting user is not a member of the Agent Workspace."""


@dataclasses.dataclass
class AgentWorkspaceAccessRepository:
    """Own the completed Agent and Workspace membership snapshot read."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def get_agent_for_user(
        self,
        agent_id: str,
        *,
        user_id: str,
    ) -> Result[
        Agent,
        AgentWorkspaceAgentNotFound | AgentWorkspaceMembershipNotFound,
    ]:
        """Return one authorized detached Agent snapshot."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentWorkspaceAgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(AgentWorkspaceMembershipNotFound())
            return Success(agent)
