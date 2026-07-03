"""Project browser manifest service."""

import dataclasses
import datetime
import posixpath
from typing import Annotated, Literal

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, AgentSessionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_project_paths,
)

_PROJECT_BROWSER_ROOT = "/workspace/agent"
ProjectBrowserModeId = Literal["projects", "all_files"]
ProjectBrowserEntrySourceType = Literal["session_project", "preview_project"]


@dataclasses.dataclass(frozen=True)
class ProjectBrowserAgentNotFound:
    """Agent not found."""


@dataclasses.dataclass(frozen=True)
class ProjectBrowserAccessDenied:
    """User cannot access the Agent or AgentSession."""


@dataclasses.dataclass(frozen=True)
class ProjectBrowserSessionNotFound:
    """AgentSession not found for the Agent."""


ProjectBrowserManifestError = (
    ProjectBrowserAgentNotFound
    | ProjectBrowserAccessDenied
    | ProjectBrowserSessionNotFound
    | InvalidProjectPath
)


@dataclasses.dataclass(frozen=True)
class ProjectBrowserMode:
    """Workspace browser mode descriptor."""

    id: ProjectBrowserModeId
    label: str
    default: bool
    root_path: str | None


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEntrySource:
    """Project browser entry source metadata."""

    type: ProjectBrowserEntrySourceType
    project_id: str | None


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEntryStatus:
    """Filesystem status projection for a Project browser entry."""

    value: AgentProjectCatalogStatus
    detail: str | None
    checked_at: datetime.datetime | None
    stale: bool


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEntryCapabilities:
    """Backend-provided Project root action policy."""

    open: bool
    remove_project: bool
    filesystem_delete: bool
    filesystem_move: bool
    filesystem_rename: bool


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEntry:
    """Project root entry in the browser manifest."""

    name: str
    path: str
    kind: Literal["directory"]
    source: ProjectBrowserEntrySource
    status: ProjectBrowserEntryStatus
    capabilities: ProjectBrowserEntryCapabilities


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEmptyState:
    """Project mode empty-state metadata."""

    title: str
    description: str


@dataclasses.dataclass(frozen=True)
class ProjectBrowserManifest:
    """Backend-owned Project browser manifest."""

    agent_id: str
    session_id: str | None
    root: str
    active_mode: ProjectBrowserModeId
    modes: list[ProjectBrowserMode]
    entries: list[ProjectBrowserEntry]
    empty_state: ProjectBrowserEmptyState | None


@dataclasses.dataclass(frozen=True)
class ProjectBrowserManifestBuildResult:
    """Manifest build result and non-blocking refresh hint."""

    manifest: ProjectBrowserManifest
    refresh_paths: list[str]


@dataclasses.dataclass
class ProjectBrowserManifestService:
    """Build backend-owned Workspace Project browser manifests."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    project_repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    catalog_service: Annotated[
        AgentProjectCatalogService,
        Depends(AgentProjectCatalogService),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get_session_manifest(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ProjectBrowserManifestBuildResult, ProjectBrowserManifestError]:
        """Build a Project browser manifest for an existing AgentSession."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(ProjectBrowserSessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(ProjectBrowserAccessDenied())
            projects = await self.project_repository.list_projects(
                session,
                session_id=session_id,
            )
            paths = [project.path for project in projects]
            catalog_entries = await self.catalog_repository.list_entries_by_paths(
                session,
                agent_id=agent_id,
                paths=paths,
            )
        catalog_by_path = {entry.path: entry for entry in catalog_entries}
        entries = [
            _entry_from_path(
                path=project.path,
                source=ProjectBrowserEntrySource(
                    type="session_project",
                    project_id=project.id,
                ),
                catalog_entry=catalog_by_path.get(project.path),
                remove_project=True,
            )
            for project in projects
        ]
        return Success(
            ProjectBrowserManifestBuildResult(
                manifest=_manifest(
                    agent_id=agent_id,
                    session_id=session_id,
                    entries=entries,
                ),
                refresh_paths=_refresh_paths(entries),
            )
        )

    async def preview_manifest(
        self,
        *,
        agent_id: str,
        user_id: str,
        project_paths: list[str],
    ) -> Result[ProjectBrowserManifestBuildResult, ProjectBrowserManifestError]:
        """Build a Project browser manifest from explicit pre-session paths."""
        try:
            normalized_paths = normalize_session_workspace_project_paths(project_paths)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(ProjectBrowserAgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(ProjectBrowserAccessDenied())
            catalog_entries = await self.catalog_repository.list_entries_by_paths(
                session,
                agent_id=agent_id,
                paths=normalized_paths,
            )
        catalog_by_path = {entry.path: entry for entry in catalog_entries}
        entries = [
            _entry_from_path(
                path=path,
                source=ProjectBrowserEntrySource(
                    type="preview_project",
                    project_id=None,
                ),
                catalog_entry=catalog_by_path.get(path),
                remove_project=False,
            )
            for path in normalized_paths
        ]
        return Success(
            ProjectBrowserManifestBuildResult(
                manifest=_manifest(agent_id=agent_id, session_id=None, entries=entries),
                refresh_paths=_refresh_paths(entries),
            )
        )

    async def refresh_project_statuses(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> None:
        """Best-effort status refresh target for background execution."""
        await self.catalog_service.refresh_project_statuses(
            agent_id=agent_id,
            paths=paths,
        )


_PROJECT_MODES = [
    ProjectBrowserMode(
        id="projects",
        label="Projects",
        default=True,
        root_path=None,
    ),
    ProjectBrowserMode(
        id="all_files",
        label="All files",
        default=False,
        root_path=_PROJECT_BROWSER_ROOT,
    ),
]


_PROJECT_ROOT_CAPABILITIES = ProjectBrowserEntryCapabilities(
    open=True,
    remove_project=True,
    filesystem_delete=False,
    filesystem_move=False,
    filesystem_rename=False,
)


_PREVIEW_PROJECT_ROOT_CAPABILITIES = ProjectBrowserEntryCapabilities(
    open=True,
    remove_project=False,
    filesystem_delete=False,
    filesystem_move=False,
    filesystem_rename=False,
)


_EMPTY_STATE = ProjectBrowserEmptyState(
    title="No Projects registered",
    description=(
        "This session has no registered Projects. Register an existing directory or "
        "switch to All files to inspect the Agent Workspace root."
    ),
)


def _manifest(
    *,
    agent_id: str,
    session_id: str | None,
    entries: list[ProjectBrowserEntry],
) -> ProjectBrowserManifest:
    """Create manifest wrapper for Project-mode entries."""
    return ProjectBrowserManifest(
        agent_id=agent_id,
        session_id=session_id,
        root=_PROJECT_BROWSER_ROOT,
        active_mode="projects",
        modes=_PROJECT_MODES,
        entries=entries,
        empty_state=_EMPTY_STATE if not entries else None,
    )


def _entry_from_path(
    *,
    path: str,
    source: ProjectBrowserEntrySource,
    catalog_entry: AgentProjectCatalogEntry | None,
    remove_project: bool,
) -> ProjectBrowserEntry:
    """Build a Project root entry from path and stored status projection."""
    name = posixpath.basename(path.rstrip("/")) or path
    return ProjectBrowserEntry(
        name=name,
        path=path,
        kind="directory",
        source=source,
        status=_status_from_catalog(catalog_entry),
        capabilities=(
            _PROJECT_ROOT_CAPABILITIES
            if remove_project
            else _PREVIEW_PROJECT_ROOT_CAPABILITIES
        ),
    )


def _status_from_catalog(
    catalog_entry: AgentProjectCatalogEntry | None,
) -> ProjectBrowserEntryStatus:
    """Map optional catalog row to manifest status projection."""
    if catalog_entry is None:
        return ProjectBrowserEntryStatus(
            value=AgentProjectCatalogStatus.UNCHECKED,
            detail=None,
            checked_at=None,
            stale=True,
        )
    return ProjectBrowserEntryStatus(
        value=catalog_entry.status,
        detail=catalog_entry.status_detail,
        checked_at=catalog_entry.checked_at,
        stale=catalog_entry.status == AgentProjectCatalogStatus.UNCHECKED,
    )


def _refresh_paths(entries: list[ProjectBrowserEntry]) -> list[str]:
    """Return paths whose projection should refresh outside the response path."""
    return [entry.path for entry in entries if entry.status.stale]
