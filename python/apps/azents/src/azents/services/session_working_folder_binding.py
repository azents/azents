"""Authoritative Session working-folder binding resolution."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_capabilities import RuntimeCapabilitySnapshot
from azents.repos.session_working_folder_binding import (
    SessionWorkingFolderBindingRepository,
)
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderTarget,
)
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget


@dataclasses.dataclass
class SessionWorkingFolderBindingService:
    """Orchestrate Runtime evidence around repository-owned binding operations."""

    repository: Annotated[
        SessionWorkingFolderBindingRepository,
        Depends(SessionWorkingFolderBindingRepository),
    ]

    async def require_bindable_context(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Reject terminal binding states before Runtime provisioning or start."""
        await self.repository.require_bindable_context(
            agent_id=agent_id,
            session_id=session_id,
        )

    async def require_bound_context(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Require an existing bound context before Runtime resolution."""
        await self.repository.require_bound_context(
            agent_id=agent_id,
            session_id=session_id,
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
        self._validate_capability_snapshot(capability_snapshot, runtime_target)
        return await self.repository.resolve_authority(
            agent_id=agent_id,
            session_id=session_id,
            target=self.target_evidence(
                runtime_target,
                capability_snapshot_version=capability_snapshot.version,
            ),
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
        self._validate_capability_snapshot(capability_snapshot, runtime_target)
        return await self.repository.resolve_authority(
            agent_id=agent_id,
            session_id=session_id,
            target=self.target_evidence(
                runtime_target,
                capability_snapshot_version=capability_snapshot.version,
            ),
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
        """Delegate DB-only composition for domains not migrated in this slice."""
        return await self.repository.resolve_authority_in_session(
            session,
            agent_id=agent_id,
            session_id=session_id,
            target=self.target_evidence(runtime_target),
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
        """Delegate DB-only composition for domains not migrated in this slice."""
        return await self.repository.resolve_authority_in_session(
            session,
            agent_id=agent_id,
            session_id=session_id,
            target=self.target_evidence(runtime_target),
            bind_pending=False,
        )

    @staticmethod
    def target_evidence(
        runtime_target: RuntimeOperationTarget,
        *,
        capability_snapshot_version: int | None = None,
    ) -> SessionWorkingFolderTarget:
        """Project Runtime operation evidence into DB-only binding input."""
        return SessionWorkingFolderTarget(
            id=runtime_target.id,
            capability_snapshot_version=(
                capability_snapshot_version
                if capability_snapshot_version is not None
                else runtime_target.runtime_capability_version
            ),
            runtime_target_capability_version=(
                runtime_target.runtime_capability_version
            ),
            workspace_path=runtime_target.workspace_path,
        )

    @staticmethod
    def _capability_snapshot(
        runtime_target: RuntimeOperationTarget,
    ) -> RuntimeCapabilitySnapshot:
        """Reconstruct the managed snapshot carried by an exact Runtime target."""
        return RuntimeCapabilitySnapshot(
            state=AgentRuntimeCapability.MANAGED,
            version=runtime_target.runtime_capability_version,
        )

    @staticmethod
    def _validate_capability_snapshot(
        capability_snapshot: RuntimeCapabilitySnapshot,
        runtime_target: RuntimeOperationTarget,
    ) -> None:
        """Reject inconsistent caller-supplied Runtime capability evidence."""
        if capability_snapshot.state is not AgentRuntimeCapability.MANAGED:
            raise SessionWorkingFolderBindingError("runtime_capability_unavailable")
