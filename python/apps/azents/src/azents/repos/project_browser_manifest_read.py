"""Completed authorized read snapshots for Project browser presentation."""

import dataclasses
import enum
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import AgentSessionStatus
from azents.core.session_workspace_project import SessionWorkspaceProject
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import SessionGitWorktree
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace_user import WorkspaceUserRepository


class ManifestReadDenial(enum.StrEnum):
    """Existing manifest access categories without Runtime or display policy."""

    AGENT_MISSING = "agent_missing"
    SESSION_MISSING = "session_missing"
    ACCESS_DENIED = "access_denied"


@dataclasses.dataclass(frozen=True)
class SessionManifestSnapshot:
    """Detached authorized project/worktree/catalog rows in retained order."""

    projects: tuple[SessionWorkspaceProject, ...]
    worktrees: tuple[SessionGitWorktree, ...]
    catalog_entries: tuple[AgentProjectCatalogEntry, ...]


@dataclasses.dataclass
class ProjectBrowserManifestReadRepository:
    """Own read-only access checks and data preparation before presentation effects."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ]
    worktree_repository: Annotated[
        SessionGitWorktreeRepository, Depends(SessionGitWorktreeRepository)
    ]
    catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends(AgentProjectCatalogRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def authorize_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[None, ManifestReadDenial]:
        """Complete Session admission before any binding or Runtime probe."""
        async with self.read_session_manager() as session:
            denial = await self._session_denial(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            return Failure(denial) if denial is not None else Success(None)

    async def read_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        working_folder_path: str,
    ) -> Result[SessionManifestSnapshot, ManifestReadDenial]:
        """Recheck admission after Runtime evidence and close the entire DB read."""
        async with self.read_session_manager() as session:
            denial = await self._session_denial(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            if denial is not None:
                return Failure(denial)
            projects = await self.project_repository.list_projects(
                session, session_id=session_id
            )
            worktrees = await self.worktree_repository.list_by_session_id(
                session, session_id=session_id
            )
            entries = await self.catalog_repository.list_entries_by_paths(
                session,
                agent_id=agent_id,
                paths=[working_folder_path, *(project.path for project in projects)],
            )
            return Success(
                SessionManifestSnapshot(
                    projects=tuple(projects),
                    worktrees=tuple(worktrees),
                    catalog_entries=tuple(entries),
                )
            )

    async def authorize_preview(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[None, ManifestReadDenial]:
        """Complete Agent membership admission before Runtime root discovery."""
        async with self.read_session_manager() as session:
            denial = await self._agent_denial(
                session, agent_id=agent_id, user_id=user_id
            )
            return Failure(denial) if denial is not None else Success(None)

    async def read_preview(
        self,
        *,
        agent_id: str,
        user_id: str,
        paths: list[str],
    ) -> Result[tuple[AgentProjectCatalogEntry, ...], ManifestReadDenial]:
        """Recheck exact Agent access and return only detached stored catalog rows."""
        async with self.read_session_manager() as session:
            denial = await self._agent_denial(
                session, agent_id=agent_id, user_id=user_id
            )
            if denial is not None:
                return Failure(denial)
            entries = await self.catalog_repository.list_entries_by_paths(
                session,
                agent_id=agent_id,
                paths=paths,
            )
            return Success(tuple(entries))

    async def _session_denial(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> ManifestReadDenial | None:
        current = await self.session_repository.get_by_id(session, session_id)
        if (
            current is None
            or current.agent_id != agent_id
            or current.status != AgentSessionStatus.ACTIVE
        ):
            return ManifestReadDenial.SESSION_MISSING
        membership = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=current.workspace_id,
            user_id=user_id,
        )
        return ManifestReadDenial.ACCESS_DENIED if membership is None else None

    async def _agent_denial(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        user_id: str,
    ) -> ManifestReadDenial | None:
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return ManifestReadDenial.AGENT_MISSING
        membership = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=agent.workspace_id,
            user_id=user_id,
        )
        return ManifestReadDenial.ACCESS_DENIED if membership is None else None
