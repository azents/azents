"""Completed database operations for Workspace upload authorization."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, AgentType, WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.workspace_upload_authority.data import (
    WorkspaceUploadRequesterAccessDenied,
    WorkspaceUploadRequesterAgentUnavailable,
    WorkspaceUploadRequesterAuthority,
)
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass
class WorkspaceUploadAuthorizationRepository:
    """Own the complete database transaction for upload authorization."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def authorize(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[
        WorkspaceUploadRequesterAuthority,
        WorkspaceUploadRequesterAgentUnavailable | WorkspaceUploadRequesterAccessDenied,
    ]:
        """Resolve upload authority in one completed database transaction."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return Failure(WorkspaceUploadRequesterAgentUnavailable())

            membership = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                workspace_id=agent.workspace_id,
                user_id=user_id,
            )
            if membership is None:
                return Failure(WorkspaceUploadRequesterAccessDenied())

            if (
                agent.type is AgentType.PRIVATE
                and membership.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session,
                    agent_id,
                    membership.id,
                )
            ):
                return Failure(WorkspaceUploadRequesterAccessDenied())

            return Success(
                WorkspaceUploadRequesterAuthority(
                    agent=agent,
                    workspace_user_id=membership.id,
                    role=membership.role,
                )
            )
