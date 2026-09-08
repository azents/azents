"""Shared database-only authority validation for file metadata operations."""

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, AgentSessionStatus
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository


@dataclasses.dataclass(frozen=True)
class FileResourceAuthority:
    """Detached canonical authority input for repository operations."""

    workspace_id: str
    agent_id: str
    session_id: str
    root_session_id: str
    run_id: str
    run_index: int
    owner_generation: int


@dataclasses.dataclass
class FileMetadataAuthorityRepository:
    """Validate file-resource authority inside a repository-owned transaction."""

    agent_session_repository: AgentSessionRepository
    agent_run_repository: AgentRunRepository

    async def validate(
        self,
        session: AsyncSession,
        authority: FileResourceAuthority,
        *,
        lock: bool,
    ) -> bool:
        """Validate current Session, root, owner-generation, and Run authority."""
        if lock:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                authority.session_id,
            )
        else:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                authority.session_id,
            )
        if (
            agent_session is None
            or agent_session.workspace_id != authority.workspace_id
            or agent_session.agent_id != authority.agent_id
            or agent_session.owner_generation != authority.owner_generation
            or agent_session.status is not AgentSessionStatus.ACTIVE
        ):
            return False
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            authority.session_id,
        )
        if root is None or root.agent_session_id != authority.root_session_id:
            return False
        if authority.root_session_id == authority.session_id:
            root_session = agent_session
        else:
            root_session = await self.agent_session_repository.get_by_id(
                session,
                authority.root_session_id,
            )
        if (
            root_session is None
            or root_session.workspace_id != authority.workspace_id
            or root_session.status is not AgentSessionStatus.ACTIVE
        ):
            return False
        if lock:
            run = await self.agent_run_repository.lock_by_id(session, authority.run_id)
        else:
            run = await self.agent_run_repository.get_by_id(session, authority.run_id)
        return (
            run is not None
            and run.session_id == authority.session_id
            and run.run_index == authority.run_index
            and run.status in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
        )
