"""Repository-owned Session working-folder binding operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    SessionWorkingFolderBindingState,
)
from azents.core.session_working_folder import build_session_working_folder_path
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import SessionWorkingFolderContext

from .data import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderTarget,
)


@dataclasses.dataclass
class SessionWorkingFolderBindingRepository:
    """Own DB-only Session working-folder authority transactions."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def require_bindable_context(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Reject terminal binding states in one completed transaction."""
        async with self.session_manager() as session:
            await self.require_context_state_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                allow_pending=True,
            )

    async def require_bound_context(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Require a bound context in one completed transaction."""
        async with self.session_manager() as session:
            await self.require_context_state_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                allow_pending=False,
            )

    async def resolve_authority(
        self,
        *,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        """Resolve authority in one completed transaction."""
        async with self.session_manager() as session:
            return await self.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                target=target,
                bind_pending=bind_pending,
            )

    async def require_context_state_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        allow_pending: bool,
    ) -> None:
        """Check current Agent and binding state for a composing repository."""
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if (
            agent is None
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
        ):
            raise SessionWorkingFolderBindingError("runtime_capability_unavailable")
        lock_binding = (
            self.agent_session_repository.lock_working_folder_binding_by_session_id
        )
        locked = await lock_binding(
            session,
            session_id=session_id,
        )
        if locked is None or locked.context.agent_id != agent_id:
            raise SessionWorkingFolderBindingError("binding_context_unavailable")
        match locked.context.binding_state:
            case SessionWorkingFolderBindingState.NONE:
                raise SessionWorkingFolderBindingError("binding_none")
            case SessionWorkingFolderBindingState.INVALIDATED:
                raise SessionWorkingFolderBindingError("binding_invalidated")
            case SessionWorkingFolderBindingState.PENDING:
                if not allow_pending:
                    raise SessionWorkingFolderBindingError("binding_pending")
            case SessionWorkingFolderBindingState.BOUND:
                return

    async def resolve_authority_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        """Resolve exact authority for a database-only composing repository."""
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if agent is None:
            raise SessionWorkingFolderBindingError("agent_unavailable")
        return await self.resolve_locked_authority_in_session(
            session,
            agent=agent,
            session_id=session_id,
            target=target,
            bind_pending=bind_pending,
        )

    async def resolve_locked_authority_in_session(
        self,
        session: AsyncSession,
        *,
        agent: Agent,
        session_id: str,
        target: SessionWorkingFolderTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        """Resolve authority after the composing repository locks Agent first."""
        agent_id = agent.id
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            raise SessionWorkingFolderBindingError("runtime_capability_unavailable")
        if agent.runtime_capability_version != target.capability_snapshot_version:
            raise SessionWorkingFolderBindingError("runtime_capability_stale")
        if (
            target.runtime_target_capability_version
            != target.capability_snapshot_version
        ):
            raise SessionWorkingFolderBindingError("runtime_target_stale")

        lock_binding = (
            self.agent_session_repository.lock_working_folder_binding_by_session_id
        )
        locked = await lock_binding(
            session,
            session_id=session_id,
        )
        if locked is None or locked.context.agent_id != agent_id:
            raise SessionWorkingFolderBindingError("binding_context_unavailable")
        expected_path = build_session_working_folder_path(
            locked.root_session_handle,
            workspace_root=target.workspace_path,
        )
        context = locked.context
        match context.binding_state:
            case SessionWorkingFolderBindingState.NONE:
                raise SessionWorkingFolderBindingError("binding_none")
            case SessionWorkingFolderBindingState.INVALIDATED:
                raise SessionWorkingFolderBindingError("binding_invalidated")
            case SessionWorkingFolderBindingState.PENDING:
                if not bind_pending:
                    raise SessionWorkingFolderBindingError("binding_pending")
                context = await self._bind_pending(
                    session,
                    context=context,
                    agent_id=agent_id,
                    target=target,
                    expected_path=expected_path,
                )
            case SessionWorkingFolderBindingState.BOUND:
                pass

        if (
            context.agent_runtime_id != target.id
            or context.working_folder_path != expected_path
        ):
            raise SessionWorkingFolderBindingError("binding_stale")
        return SessionWorkingFolderAuthority(
            context_id=context.id,
            agent_id=agent_id,
            agent_runtime_id=target.id,
            working_folder_path=expected_path,
            runtime_capability_version=target.capability_snapshot_version,
        )

    async def _bind_pending(
        self,
        session: AsyncSession,
        *,
        context: SessionWorkingFolderContext,
        agent_id: str,
        target: SessionWorkingFolderTarget,
        expected_path: str,
    ) -> SessionWorkingFolderContext:
        """Apply the one allowed pending-to-bound transition."""
        if context.agent_runtime_id != target.id:
            raise SessionWorkingFolderBindingError("binding_runtime_stale")
        bound = await self.agent_session_repository.bind_pending_working_folder(
            session,
            context_id=context.id,
            expected_agent_id=agent_id,
            expected_agent_runtime_id=target.id,
            working_folder_path=expected_path,
        )
        if bound is None:
            raise SessionWorkingFolderBindingError("binding_changed")
        return bound
