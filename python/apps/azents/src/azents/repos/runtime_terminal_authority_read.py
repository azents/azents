"""Native read-only durable Runtime Terminal authority snapshot ownership."""

import dataclasses
from datetime import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    AgentType,
    WorkspaceUserRole,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalDurableSnapshot:
    """One transactionally consistent Terminal authority source snapshot."""

    workspace_id: str | None
    authentication_session_expires_at: datetime | None
    agent: Agent | None
    agent_session: AgentSession | None
    runtime: AgentRuntime | None
    infrastructure_profile: RuntimeInfrastructureProfile | None
    workspace_profile: WorkspaceRuntimeProfile | None
    applied_configuration: RuntimeConfigurationAppliedSlot | None
    reason_code: str | None


@dataclasses.dataclass
class RuntimeTerminalAuthorityReadRepository:
    """Complete the ordered identity and profile reads before Runner/policy effects."""

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
    ) -> RuntimeTerminalDurableSnapshot:
        async with self.session_manager() as session:
            user = await self.user_repository.get(session, user_id)
            authentication_session = await self.authentication_session_repository.get(
                session,
                authentication_session_id,
            )
            if (
                user is None
                or user.access_disabled_at is not None
                or authentication_session is None
                or authentication_session.user_id != user_id
                or authentication_session.revoked_at is not None
                or authentication_session.expires_at <= resolved_at
            ):
                return _empty_snapshot("access_denied")

            workspace_snapshot = await self.workspace_repository.get_with_id_by_handle(
                session,
                workspace_handle,
            )
            if workspace_snapshot is None:
                return _empty_snapshot("access_denied")
            workspace_id = workspace_snapshot.workspace_id
            membership = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                workspace_id,
                user_id,
            )
            if membership is None:
                return _empty_snapshot("access_denied")

            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.workspace_id != workspace_id
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return _empty_snapshot(
                    "agent_not_found",
                    workspace_id=workspace_id,
                )
            if (
                agent.type is AgentType.PRIVATE
                and membership.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session,
                    agent.id,
                    membership.id,
                )
            ):
                return _empty_snapshot(
                    "agent_not_found",
                    workspace_id=workspace_id,
                )
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                return _empty_snapshot(
                    "session_not_found",
                    workspace_id=workspace_id,
                    agent=agent,
                )
            if (
                agent_session.workspace_id != workspace_id
                or agent_session.agent_id != agent.id
            ):
                return _empty_snapshot(
                    "session_agent_mismatch",
                    workspace_id=workspace_id,
                    agent=agent,
                    agent_session=agent_session,
                )
            if (
                agent_session.status is not AgentSessionStatus.ACTIVE
                or not await self._session_access_allowed(
                    session,
                    agent_session=agent_session,
                    user_id=user_id,
                )
            ):
                return _empty_snapshot(
                    "session_not_found",
                    workspace_id=workspace_id,
                    agent=agent,
                    agent_session=agent_session,
                )

            runtime = await self.runtime_repository.get_by_agent_id(session, agent.id)
            workspace_profile = None
            infrastructure = None
            applied = None
            if agent.runtime_profile_id is not None:
                workspace_profile = (
                    await self.profile_repository.get_workspace_runtime_profile(
                        session,
                        workspace_id=workspace_id,
                        profile_id=agent.runtime_profile_id,
                    )
                )
            if workspace_profile is not None:
                infrastructure = (
                    await self.profile_repository.get_infrastructure_profile(
                        session,
                        profile_id=workspace_profile.infrastructure_profile_id,
                    )
                )
            if runtime is not None:
                configuration = await self.profile_repository.get_configuration_state(
                    session,
                    runtime_id=runtime.id,
                )
                applied = configuration.applied if configuration is not None else None
            return RuntimeTerminalDurableSnapshot(
                workspace_id=workspace_id,
                authentication_session_expires_at=authentication_session.expires_at,
                agent=agent,
                agent_session=agent_session,
                runtime=runtime,
                infrastructure_profile=infrastructure,
                workspace_profile=workspace_profile,
                applied_configuration=applied,
                reason_code=None,
            )

    async def _session_access_allowed(
        self,
        session: ReadSession,
        *,
        agent_session: AgentSession,
        user_id: str,
    ) -> bool:
        root = agent_session
        if agent_session.session_kind is AgentSessionKind.SUBAGENT:
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root_agent = await get_root(session, agent_session.id)
            if root_agent is None:
                return False
            loaded = await self.agent_session_repository.get_by_id(
                session,
                root_agent.agent_session_id,
            )
            if loaded is None:
                return False
            root = loaded
        elif agent_session.session_kind is not AgentSessionKind.ROOT:
            return False
        if root.product_mode is AgentSessionProductMode.TEAM:
            return True
        return (
            root.product_mode is AgentSessionProductMode.USER
            and root.associated_user_id == user_id
        )


def _empty_snapshot(
    reason_code: str,
    *,
    workspace_id: str | None = None,
    agent: Agent | None = None,
    agent_session: AgentSession | None = None,
) -> RuntimeTerminalDurableSnapshot:
    return RuntimeTerminalDurableSnapshot(
        workspace_id=workspace_id,
        authentication_session_expires_at=None,
        agent=agent,
        agent_session=agent_session,
        runtime=None,
        infrastructure_profile=None,
        workspace_profile=None,
        applied_configuration=None,
        reason_code=reason_code,
    )
