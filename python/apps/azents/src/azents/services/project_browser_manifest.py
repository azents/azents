"""Project browser manifest service."""

import dataclasses
import datetime
import posixpath
from typing import Annotated, Literal

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    AgentSessionStatus,
    SessionGitWorktreeStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTargetResolver
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_agent_workspace_root,
    normalize_session_workspace_project_paths,
)

ProjectBrowserModeId = Literal["projects", "all_files"]
ProjectBrowserEntrySourceType = Literal[
    "session_folder",
    "session_project",
    "preview_project",
]
ProjectBrowserEntryRepositoryType = Literal["git"]


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
    delete_worktree: bool
    filesystem_delete: bool
    filesystem_move: bool
    filesystem_rename: bool
    prepare_session_folder: bool


@dataclasses.dataclass(frozen=True)
class ProjectBrowserEntry:
    """Project root entry in the browser manifest."""

    name: str
    path: str
    kind: Literal["directory"]
    repository_type: ProjectBrowserEntryRepositoryType | None
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
    worktree_repository: Annotated[
        SessionGitWorktreeRepository,
        Depends(SessionGitWorktreeRepository),
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
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
    ]
    session_working_folder_binding_service: Annotated[
        SessionWorkingFolderBindingService,
        Depends(),
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
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding = await binding_service.resolve_bound_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        working_folder_path = binding.working_folder_path
        async with self.session_manager() as session:
            projects = await self.project_repository.list_projects(
                session,
                session_id=session_id,
            )
            worktrees = await self.worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            paths = [
                working_folder_path,
                *(project.path for project in projects),
            ]
            catalog_entries = await self.catalog_repository.list_entries_by_paths(
                session,
                agent_id=agent_id,
                paths=paths,
            )
        try:
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalize_session_workspace_project_paths(
                paths,
                workspace_root=workspace_root,
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        catalog_by_path = {entry.path: entry for entry in catalog_entries}
        git_project_ids = {
            worktree.session_workspace_project_id
            for worktree in worktrees
            if worktree.session_workspace_project_id is not None
        }
        deletable_worktree_project_ids = {
            worktree.session_workspace_project_id
            for worktree in worktrees
            if worktree.session_workspace_project_id is not None
            and worktree.status is not SessionGitWorktreeStatus.CLEANED
        }
        git_project_paths = {worktree.worktree_path for worktree in worktrees}
        session_folder_entry = ProjectBrowserEntry(
            name="Session files",
            path=working_folder_path,
            kind="directory",
            repository_type=None,
            source=ProjectBrowserEntrySource(
                type="session_folder",
                project_id=None,
            ),
            status=_status_from_catalog(catalog_by_path.get(working_folder_path)),
            capabilities=_SESSION_FOLDER_CAPABILITIES,
        )
        entries = [
            session_folder_entry,
            *[
                _entry_from_path(
                    path=project.path,
                    source=ProjectBrowserEntrySource(
                        type="session_project",
                        project_id=project.id,
                    ),
                    catalog_entry=catalog_by_path.get(project.path),
                    remove_project=True,
                    delete_worktree=project.id in deletable_worktree_project_ids,
                    repository_type=_repository_type_for_project(
                        project_id=project.id,
                        project_path=project.path,
                        git_project_ids=git_project_ids,
                        git_project_paths=git_project_paths,
                    ),
                )
                for project in projects
            ],
        ]
        return Success(
            ProjectBrowserManifestBuildResult(
                manifest=_manifest(
                    agent_id=agent_id,
                    session_id=session_id,
                    entries=entries,
                    workspace_root=workspace_root,
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
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_paths = normalize_session_workspace_project_paths(
                project_paths,
                workspace_root=workspace_root,
            )
        except (RuntimeStorageError, ValueError) as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        async with self.session_manager() as session:
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
                delete_worktree=False,
                repository_type=None,
            )
            for path in normalized_paths
        ]
        return Success(
            ProjectBrowserManifestBuildResult(
                manifest=_manifest(
                    agent_id=agent_id,
                    session_id=None,
                    entries=entries,
                    workspace_root=workspace_root,
                ),
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


_PROJECT_ROOT_CAPABILITIES = ProjectBrowserEntryCapabilities(
    open=True,
    remove_project=True,
    delete_worktree=False,
    filesystem_delete=False,
    filesystem_move=False,
    filesystem_rename=False,
    prepare_session_folder=False,
)


_PREVIEW_PROJECT_ROOT_CAPABILITIES = ProjectBrowserEntryCapabilities(
    open=True,
    remove_project=False,
    delete_worktree=False,
    filesystem_delete=False,
    filesystem_move=False,
    filesystem_rename=False,
    prepare_session_folder=False,
)


_SESSION_FOLDER_CAPABILITIES = ProjectBrowserEntryCapabilities(
    open=True,
    remove_project=False,
    delete_worktree=False,
    filesystem_delete=False,
    filesystem_move=False,
    filesystem_rename=False,
    prepare_session_folder=True,
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
    workspace_root: str,
) -> ProjectBrowserManifest:
    """Create manifest wrapper for Project-mode entries."""
    return ProjectBrowserManifest(
        agent_id=agent_id,
        session_id=session_id,
        root=workspace_root,
        active_mode="projects",
        modes=[
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
                root_path=workspace_root,
            ),
        ],
        entries=entries,
        empty_state=_EMPTY_STATE if not entries else None,
    )


def _repository_type_for_project(
    *,
    project_id: str,
    project_path: str,
    git_project_ids: set[str],
    git_project_paths: set[str],
) -> ProjectBrowserEntryRepositoryType | None:
    """Return repository metadata for known Azents-created worktree Projects."""
    if project_id in git_project_ids or project_path in git_project_paths:
        return "git"
    return None


def _entry_from_path(
    *,
    path: str,
    source: ProjectBrowserEntrySource,
    catalog_entry: AgentProjectCatalogEntry | None,
    remove_project: bool,
    delete_worktree: bool,
    repository_type: ProjectBrowserEntryRepositoryType | None,
) -> ProjectBrowserEntry:
    """Build a Project root entry from path and stored status projection."""
    name = posixpath.basename(path.rstrip("/")) or path
    return ProjectBrowserEntry(
        name=name,
        path=path,
        kind="directory",
        repository_type=repository_type,
        source=source,
        status=_status_from_catalog(catalog_entry),
        capabilities=(
            dataclasses.replace(
                _PROJECT_ROOT_CAPABILITIES,
                delete_worktree=delete_worktree,
            )
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
