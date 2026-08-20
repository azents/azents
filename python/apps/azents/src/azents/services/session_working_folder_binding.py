"""Authoritative Session working-folder binding resolution."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    SessionWorkingFolderBindingState,
)
from azents.core.runtime_capabilities import RuntimeCapabilitySnapshot
from azents.core.session_working_folder import build_session_working_folder_path
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session.data import SessionWorkingFolderContext
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget


@dataclasses.dataclass(frozen=True)
class SessionWorkingFolderAuthority:
    """Exact current Session folder authority for one Runtime operation."""

    context_id: str
    agent_id: str
    agent_runtime_id: str
    working_folder_path: str
    runtime_capability_version: int


class SessionWorkingFolderBindingError(RuntimeError):
    """Raised when a Session folder cannot authorize Runtime work."""

    def __init__(self, reason_code: str) -> None:
        """Create a stable content-free binding failure."""
        super().__init__("Session working-folder binding is unavailable.")
        self.reason_code = reason_code


@dataclasses.dataclass
class SessionWorkingFolderBindingService:
    """Resolve or create one current root Session folder binding."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def require_bindable_context(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Reject terminal binding states before Runtime provisioning or start."""
        await self._require_context_state(
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
        """Require an existing bound context before Runtime resolution."""
        await self._require_context_state(
            agent_id=agent_id,
            session_id=session_id,
            allow_pending=False,
        )

    async def resolve_authority(
        self,
        *,
        agent_id: str,
        session_id: str,
        capability_snapshot: RuntimeCapabilitySnapshot,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Return exact bound authority or bind one eligible pending context."""
        return await self._resolve_authority(
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=capability_snapshot,
            runtime_target=runtime_target,
            bind_pending=True,
        )

    async def resolve_authority_for_target(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Resolve operation authority from a capability-fenced Runtime target."""
        return await self.resolve_authority(
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=self._capability_snapshot(runtime_target),
            runtime_target=runtime_target,
        )

    async def resolve_bound_authority(
        self,
        *,
        agent_id: str,
        session_id: str,
        capability_snapshot: RuntimeCapabilitySnapshot,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Return exact existing bound authority without changing pending state."""
        return await self._resolve_authority(
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=capability_snapshot,
            runtime_target=runtime_target,
            bind_pending=False,
        )

    async def resolve_bound_authority_for_target(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Resolve read-only authority from a capability-fenced Runtime target."""
        return await self.resolve_bound_authority(
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=self._capability_snapshot(runtime_target),
            runtime_target=runtime_target,
        )

    async def resolve_authority_in_transaction(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Resolve or bind authority while retaining caller-owned row locks."""
        return await self._resolve_authority_in_transaction(
            session,
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=self._capability_snapshot(runtime_target),
            runtime_target=runtime_target,
            bind_pending=True,
        )

    async def resolve_bound_authority_in_transaction(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Resolve existing bound authority while retaining caller-owned locks."""
        return await self._resolve_authority_in_transaction(
            session,
            agent_id=agent_id,
            session_id=session_id,
            capability_snapshot=self._capability_snapshot(runtime_target),
            runtime_target=runtime_target,
            bind_pending=False,
        )

    @staticmethod
    def _capability_snapshot(
        runtime_target: RuntimeOperationTarget,
    ) -> RuntimeCapabilitySnapshot:
        """Reconstruct the managed snapshot carried by an exact Runtime target."""
        return RuntimeCapabilitySnapshot(
            state=AgentRuntimeCapability.MANAGED,
            version=runtime_target.runtime_capability_version,
            shell_enabled=True,
        )

    async def _require_context_state(
        self,
        *,
        agent_id: str,
        session_id: str,
        allow_pending: bool,
    ) -> None:
        """Check current Agent and binding state without Runtime side effects."""
        async with self.session_manager() as session:
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

    async def _resolve_authority(
        self,
        *,
        agent_id: str,
        session_id: str,
        capability_snapshot: RuntimeCapabilitySnapshot,
        runtime_target: RuntimeOperationTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        """Resolve current binding authority under one locked transaction."""
        async with self.session_manager() as session:
            return await self._resolve_authority_in_transaction(
                session,
                agent_id=agent_id,
                session_id=session_id,
                capability_snapshot=capability_snapshot,
                runtime_target=runtime_target,
                bind_pending=bind_pending,
            )

    async def _resolve_authority_in_transaction(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        capability_snapshot: RuntimeCapabilitySnapshot,
        runtime_target: RuntimeOperationTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        """Resolve current binding authority under caller-owned row locks."""
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if agent is None:
            raise SessionWorkingFolderBindingError("agent_unavailable")
        if (
            capability_snapshot.state is not AgentRuntimeCapability.MANAGED
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
        ):
            raise SessionWorkingFolderBindingError("runtime_capability_unavailable")
        if agent.runtime_capability_version != capability_snapshot.version:
            raise SessionWorkingFolderBindingError("runtime_capability_stale")
        if runtime_target.runtime_capability_version != capability_snapshot.version:
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
            workspace_root=runtime_target.workspace_path,
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
                    runtime_target=runtime_target,
                    expected_path=expected_path,
                )
            case SessionWorkingFolderBindingState.BOUND:
                pass

        if (
            context.agent_runtime_id != runtime_target.id
            or context.working_folder_path != expected_path
        ):
            raise SessionWorkingFolderBindingError("binding_stale")
        return SessionWorkingFolderAuthority(
            context_id=context.id,
            agent_id=agent_id,
            agent_runtime_id=runtime_target.id,
            working_folder_path=expected_path,
            runtime_capability_version=capability_snapshot.version,
        )

    async def _bind_pending(
        self,
        session: AsyncSession,
        *,
        context: SessionWorkingFolderContext,
        agent_id: str,
        runtime_target: RuntimeOperationTarget,
        expected_path: str,
    ) -> SessionWorkingFolderContext:
        """Apply the one allowed pending-to-bound transition."""
        if context.agent_runtime_id != runtime_target.id:
            raise SessionWorkingFolderBindingError("binding_runtime_stale")
        bound = await self.agent_session_repository.bind_pending_working_folder(
            session,
            context_id=context.id,
            expected_agent_id=agent_id,
            expected_agent_runtime_id=runtime_target.id,
            working_folder_path=expected_path,
        )
        if bound is None:
            raise SessionWorkingFolderBindingError("binding_changed")
        return bound
