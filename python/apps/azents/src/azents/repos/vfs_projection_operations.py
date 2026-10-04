"""Completed owner-fenced database operations for immutable VFS projections."""

import dataclasses
from collections.abc import Callable, Sequence
from typing import Annotated, AsyncContextManager, Protocol

from fastapi import Depends

from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.vfs import VfsProjection
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.deps import get_toolkit_repository


class VfsRun(Protocol):
    """Run fields used to validate one VFS projection."""

    @property
    def session_id(self) -> str:
        """Return the owning Session id."""
        ...

    @property
    def vfs_projection(self) -> VfsProjection | None:
        """Return the persisted VFS projection."""
        ...


class VfsSessionRecord(Protocol):
    """Session ownership fields used by VFS projection lookup."""

    @property
    def agent_id(self) -> str:
        """Return the owning Agent id."""
        ...

    @property
    def workspace_id(self) -> str:
        """Return the owning Workspace id."""
        ...


class VfsToolkitConfig(Protocol):
    """Toolkit configuration fields used to select VFS release sources."""

    @property
    def enabled(self) -> bool:
        """Return whether the toolkit is enabled."""
        ...

    @property
    def workspace_id(self) -> str:
        """Return the owning Workspace id."""
        ...

    @property
    def toolkit_type(self) -> str:
        """Return the registered Toolkit provider type."""
        ...


class VfsEffectiveToolkitConfig(Protocol):
    """Effective Toolkit projection used to select release sources."""

    @property
    def toolkit(self) -> VfsToolkitConfig:
        """Return the effective ToolkitConfig."""
        ...


class VfsRunRepository(Protocol):
    """Run repository operations used by VFS projection service."""

    async def get_by_id(
        self,
        session: ReadSession,
        run_id: str,
    ) -> VfsRun | None:
        """Load one Agent run."""
        ...

    async def set_vfs_projection_if_unset(
        self,
        session: WriteSession,
        *,
        run_id: str,
        session_id: str,
        projection: VfsProjection,
    ) -> VfsProjection:
        """Persist a VFS projection exactly once."""
        ...


class VfsSessionRepository(Protocol):
    """Session repository operation used by VFS projection service."""

    async def get_by_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> VfsSessionRecord | None:
        """Load one Agent session."""
        ...


class VfsToolkitRepository(Protocol):
    """Effective Toolkit operation used by VFS projection service."""

    async def list_effective_for_agent(
        self,
        session: ReadSession,
        agent_id: str,
        *,
        workspace_id: str,
    ) -> Sequence[VfsEffectiveToolkitConfig]:
        """List enabled ToolkitConfigs effective for one Agent."""
        ...


@dataclasses.dataclass(frozen=True)
class VfsRunSnapshot:
    """Detached run and Session ownership captured in one database read."""

    run_session_id: str
    agent_id: str
    workspace_id: str
    projection: VfsProjection | None


@dataclasses.dataclass(frozen=True)
class VfsToolkitSnapshot:
    """Only the known toolkit fields used for release-resource eligibility."""

    enabled: bool
    workspace_id: str
    toolkit_type: str


class VfsProjectionOperationProtocol(Protocol):
    """Completed operation interface consumed by release projection orchestration."""

    def with_owner(
        self, owner: SessionExecutionOwner
    ) -> "VfsProjectionOperationProtocol": ...

    async def read_run(
        self, *, run_id: str, session_id: str
    ) -> VfsRunSnapshot | None: ...

    async def publish_projection(
        self, *, run_id: str, session_id: str, projection: VfsProjection
    ) -> VfsProjection: ...

    async def list_effective_toolkits(
        self, *, agent_id: str, workspace_id: str
    ) -> tuple[VfsToolkitSnapshot, ...]: ...


@dataclasses.dataclass(frozen=True)
class VfsProjectionOperations:
    """Own VFS read/CAS transactions and durable execution ownership fencing."""

    session_manager: Callable[[], AsyncContextManager[WriteSession]]
    agent_run_repository: VfsRunRepository
    agent_session_repository: VfsSessionRepository
    toolkit_repository: VfsToolkitRepository
    owner: SessionExecutionOwner | None

    def with_owner(self, owner: SessionExecutionOwner) -> "VfsProjectionOperations":
        return dataclasses.replace(
            self,
            owner=owner,
        )

    async def read_run(self, *, run_id: str, session_id: str) -> VfsRunSnapshot | None:
        async with self.session_manager() as session:
            run = await self.agent_run_repository.get_by_id(session, run_id)
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if run is None or agent_session is None:
                return None
            return VfsRunSnapshot(
                run_session_id=run.session_id,
                agent_id=agent_session.agent_id,
                workspace_id=agent_session.workspace_id,
                projection=run.vfs_projection,
            )

    async def publish_projection(
        self, *, run_id: str, session_id: str, projection: VfsProjection
    ) -> VfsProjection:
        async with self.session_manager() as session:
            if self.owner is not None:
                if self.owner.session_id != session_id:
                    raise ValueError("VFS publication Session does not match owner")
                await fence_owned_session_mutation(session, self.owner)
            published = await self.agent_run_repository.set_vfs_projection_if_unset(
                session, run_id=run_id, session_id=session_id, projection=projection
            )
            await session.write_session.commit()
        return published

    async def list_effective_toolkits(
        self, *, agent_id: str, workspace_id: str
    ) -> tuple[VfsToolkitSnapshot, ...]:
        async with self.session_manager() as session:
            toolkits = await self.toolkit_repository.list_effective_for_agent(
                session, agent_id, workspace_id=workspace_id
            )
            return tuple(
                VfsToolkitSnapshot(
                    enabled=effective.toolkit.enabled,
                    workspace_id=effective.toolkit.workspace_id,
                    toolkit_type=effective.toolkit.toolkit_type,
                )
                for effective in toolkits
            )


def get_vfs_projection_operations(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    toolkit_repository: Annotated[ToolkitRepository, Depends(get_toolkit_repository)],
) -> VfsProjectionOperations:
    """Wire real persistence collaborators behind the completed VFS boundary."""
    return VfsProjectionOperations(
        owner=None,
        session_manager=session_manager,
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
        toolkit_repository=toolkit_repository,
    )
