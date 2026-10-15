"""Completed database-only reads for public concrete Session Browser access."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends

from azents.core.agent_session_data import AgentSession
from azents.core.enums import AgentLifecycleStatus, AgentType, WorkspaceUserRole
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_profile.data import RuntimeConfigurationAppliedSlot
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session import SessionRepository
from azents.repos.session_resource_authority import (
    AuthorizedPublicSessionResource,
    PublicSessionResourceDenied,
    authorize_public_session_resource,
)
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclass(frozen=True)
class RuntimeBrowserIdentityDenied:
    reason: Literal["unauthenticated", "not_found", "access_denied"]


@dataclass(frozen=True)
class RuntimeBrowserDurableSnapshot:
    agent: Agent
    agent_session: AgentSession
    runtime: AgentRuntime | None
    applied_configuration: RuntimeConfigurationAppliedSlot | None
    authentication_session_expires_at: datetime


@dataclass
class RuntimeBrowserAuthorityReadRepository:
    """Finish identity, Session and Runtime reads before any Runtime I/O."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    authentication_session_repository: Annotated[
        SessionRepository, Depends(SessionRepository)
    ]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository, Depends(AgentAdminRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]

    async def read_snapshot(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        workspace_handle: str,
        agent_id: str,
        session_id: str,
        resolved_at: datetime,
    ) -> RuntimeBrowserDurableSnapshot | RuntimeBrowserIdentityDenied:
        async with self.session_manager() as session:
            user = await self.user_repository.get(session, user_id)
            authentication = await self.authentication_session_repository.get(
                session, authentication_session_id
            )
            if (
                user is None
                or user.access_disabled_at is not None
                or authentication is None
                or authentication.user_id != user_id
                or authentication.revoked_at is not None
                or authentication.expires_at <= resolved_at
            ):
                return RuntimeBrowserIdentityDenied("unauthenticated")
            workspace = await self.workspace_repository.get_with_id_by_handle(
                session, workspace_handle
            )
            if workspace is None:
                return RuntimeBrowserIdentityDenied("not_found")
            membership = await self.workspace_user_repository.get_by_workspace_and_user(
                session, workspace.workspace_id, user_id
            )
            if membership is None:
                return RuntimeBrowserIdentityDenied("access_denied")
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.workspace_id != workspace.workspace_id
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return RuntimeBrowserIdentityDenied("not_found")
            if (
                agent.type is AgentType.PRIVATE
                and membership.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session, agent.id, membership.id
                )
            ):
                return RuntimeBrowserIdentityDenied("not_found")
            concrete = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if concrete is None:
                return RuntimeBrowserIdentityDenied("not_found")
            admission = await authorize_public_session_resource(
                session,
                agent_session=concrete,
                user_id=user_id,
                require_active=True,
                denied_as_not_found=True,
                expected_workspace_id=workspace.workspace_id,
                expected_agent_id=agent.id,
                agent_session_repository=self.agent_session_repository,
                workspace_user_repository=self.workspace_user_repository,
            )
            if not isinstance(admission, AuthorizedPublicSessionResource):
                return RuntimeBrowserIdentityDenied(
                    "access_denied"
                    if isinstance(admission, PublicSessionResourceDenied)
                    else "not_found"
                )
            runtime = await self.runtime_repository.get_by_agent_id(session, agent.id)
            configuration = (
                await self.profile_repository.get_configuration_state(
                    session, runtime_id=runtime.id
                )
                if runtime is not None
                else None
            )
            return RuntimeBrowserDurableSnapshot(
                agent=agent,
                agent_session=admission.session,
                runtime=runtime,
                applied_configuration=(
                    configuration.applied if configuration is not None else None
                ),
                authentication_session_expires_at=authentication.expires_at,
            )

    async def read_stream_workspace_handle(
        self, *, agent_id: str, session_id: str
    ) -> str | None:
        """Derive the resource route from current joined identities, not headers."""
        async with self.session_manager() as session:
            concrete = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if concrete is None or concrete.agent_id != agent_id:
                return None
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != concrete.workspace_id:
                return None
            workspace = await self.workspace_repository.get_by_id(
                session, agent.workspace_id
            )
            return workspace.handle if workspace is not None else None
