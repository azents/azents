"""Completed authorized Agent Runtime environment storage operations."""

import dataclasses
import json
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    WorkspaceUserRole,
)
from azents.core.runtime_environment import (
    RuntimeEnvironmentAccessError,
    RuntimeEnvironmentEntryEdit,
    merge_runtime_environment,
    parse_runtime_environment,
    validate_runtime_environment,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace_environment import (
    RDBAgentWorkspaceEnvironmentSelection,
    RDBWorkspaceEnvironmentVariable,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_mutation_guard import require_active_agent


@dataclasses.dataclass(frozen=True)
class RuntimeEnvironmentAccess:
    """Detached redacted management projection."""

    names: list[str]
    can_manage: bool


@dataclasses.dataclass
class AgentRuntimeEnvironmentRepository:
    """Own read/write scopes and recheck Agent management inside each write."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    admin_repository: Annotated[AgentAdminRepository, Depends(AgentAdminRepository)]

    async def authorize(
        self,
        session: ReadSession,
        agent: RDBAgent | None,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        manage: bool,
    ) -> Result[bool, RuntimeEnvironmentAccessError]:
        if agent is None:
            return Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
        if agent.workspace_id != workspace_id:
            return Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
        can_manage = (
            role is WorkspaceUserRole.OWNER
            or await self.admin_repository.is_admin(
                session, agent_id, workspace_user_id
            )
        )
        if agent.type is AgentType.PRIVATE and not can_manage:
            return Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
        if manage and not can_manage:
            return Failure(RuntimeEnvironmentAccessError.DENIED)
        return Success(can_manage)

    def _decode(self, encrypted: str | None) -> dict[str, str]:
        return (
            {}
            if encrypted is None
            else parse_runtime_environment(self.cipher.decrypt(encrypted))
        )

    async def get(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeEnvironmentAccess, RuntimeEnvironmentAccessError]:
        """Read variable names without returning secret values to the caller."""
        async with self.read_session_manager() as session:
            agent = await session.read_session.get(RDBAgent, agent_id)
            access = await self.authorize(
                session,
                agent,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                manage=False,
            )
            if isinstance(access, Failure):
                return access
            assert agent is not None
            return Success(
                RuntimeEnvironmentAccess(
                    names=sorted(self._decode(agent.encrypted_runtime_environment)),
                    can_manage=access.value,
                )
            )

    async def replace(
        self,
        agent_id: str,
        *,
        edits: list[RuntimeEnvironmentEntryEdit],
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeEnvironmentAccess, RuntimeEnvironmentAccessError]:
        """Serialize replacement and retain/rename secrets without a plaintext read."""
        async with self.session_manager() as session:
            agent = (
                await session.write_session.execute(
                    sa.select(RDBAgent).where(RDBAgent.id == agent_id).with_for_update()
                )
            ).scalar_one_or_none()
            access = await self.authorize(
                session,
                agent,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                manage=True,
            )
            if isinstance(access, Failure):
                return access
            assert agent is not None
            await require_active_agent(session, agent_id=agent_id)
            desired = merge_runtime_environment(
                self._decode(agent.encrypted_runtime_environment), edits
            )
            agent.encrypted_runtime_environment = (
                self.cipher.encrypt(json.dumps(desired)) if desired else None
            )
            await session.write_session.flush()
            return Success(
                RuntimeEnvironmentAccess(names=sorted(desired), can_manage=True)
            )

    async def read_values(self, agent_id: str) -> dict[str, str]:
        """Read fresh secrets for the managed Runtime owner before command launch."""
        async with self.read_session_manager() as session:
            rows = (
                await session.read_session.execute(
                    sa.select(
                        RDBAgent.encrypted_runtime_environment,
                        RDBWorkspaceEnvironmentVariable.name,
                        RDBWorkspaceEnvironmentVariable.encrypted_value,
                    )
                    .outerjoin(
                        RDBAgentWorkspaceEnvironmentSelection,
                        RDBAgentWorkspaceEnvironmentSelection.agent_id == RDBAgent.id,
                    )
                    .outerjoin(
                        RDBWorkspaceEnvironmentVariable,
                        sa.and_(
                            RDBWorkspaceEnvironmentVariable.id
                            == RDBAgentWorkspaceEnvironmentSelection.variable_id,
                            RDBWorkspaceEnvironmentVariable.workspace_id
                            == RDBAgent.workspace_id,
                        ),
                    )
                    .where(
                        RDBAgent.id == agent_id,
                        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                        RDBAgent.runtime_capability == AgentRuntimeCapability.MANAGED,
                    )
                )
            ).all()
        if not rows:
            return {}
        shared = {
            row.name: self.cipher.decrypt(row.encrypted_value)
            for row in rows
            if row.name is not None and row.encrypted_value is not None
        }
        validate_runtime_environment(shared)
        shared.update(self._decode(rows[0].encrypted_runtime_environment))
        return shared
