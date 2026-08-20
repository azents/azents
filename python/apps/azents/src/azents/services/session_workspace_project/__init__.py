"""Session Workspace Project service."""

import dataclasses
import posixpath
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    AgentSessionStatus,
)
from azents.engine.tools.deps import get_skill_state_store
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.session_workspace_project import (
    SessionWorkspaceProjectCleanupInProgress,
    SessionWorkspaceProjectRepository,
)
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTargetResolver
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_directory_validation import (
    RuntimeDirectoryNotDirectory,
    RuntimeDirectoryNotFound,
    RuntimeDirectoryValidationUnavailable,
    validate_runtime_directory,
)
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)


@dataclasses.dataclass(frozen=True)
class InvalidProjectPath:
    """Project path does not satisfy Session Workspace contract."""

    path: str
    reason: str


@dataclasses.dataclass(frozen=True)
class ProjectPathConflict:
    """Project path conflicts with existing Project."""

    path: str
    conflicting_project_id: str


@dataclasses.dataclass(frozen=True)
class ProjectPathCleanupInProgress:
    """A manual cleanup currently owns this Project path."""

    path: str


@dataclasses.dataclass(frozen=True)
class ProjectNotFound:
    """Project not found."""


@dataclasses.dataclass(frozen=True)
class AgentNotFound:
    """Agent not found."""


@dataclasses.dataclass(frozen=True)
class ProjectAccessDenied:
    """No Project access permission."""


@dataclasses.dataclass(frozen=True)
class AccessibleProjectContext:
    """Project context accessible by user."""

    agent_id: str
    session_id: str


ProjectCreateError = (
    InvalidProjectPath | ProjectPathConflict | ProjectPathCleanupInProgress
)
ProjectAccessError = AgentNotFound | ProjectAccessDenied
ProjectFolderRegistrationError = ProjectAccessError | ProjectCreateError


def normalize_agent_workspace_root(workspace_root: str | None) -> PurePosixPath:
    """Normalize the Runner-reported Agent Workspace root."""
    if workspace_root is None or not workspace_root.strip():
        raise ValueError("Agent Workspace path is unavailable")
    normalized = PurePosixPath(posixpath.normpath(workspace_root.strip()))
    if not normalized.is_absolute():
        raise ValueError("Agent Workspace path must be absolute")
    return normalized


def normalize_session_workspace_path(
    path: str,
    *,
    workspace_root: str,
) -> str:
    """Normalize absolute path inside Session Workspace.

    :param path: Path to validate
    :return: Normalized POSIX absolute path
    :raises ValueError: When path is empty, relative, root, or outside prefix
    """
    stripped = path.strip()
    if not stripped:
        raise ValueError("Project path is required")
    pure = PurePosixPath(posixpath.normpath(stripped))
    if not pure.is_absolute():
        raise ValueError("Project path must be absolute")
    normalized = PurePosixPath("/") / pure.relative_to("/")
    root = normalize_agent_workspace_root(workspace_root)
    if normalized == root:
        raise ValueError("Session Workspace root cannot be a Project")
    if not normalized.is_relative_to(root):
        raise ValueError("Project path must be under Agent Workspace root")
    return normalized.as_posix()


def normalize_session_workspace_project_paths(
    paths: list[str],
    *,
    workspace_root: str,
) -> list[str]:
    """Normalize Project paths and remove exact duplicates while preserving order."""
    normalized_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_session_workspace_path(
            path,
            workspace_root=workspace_root,
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    return normalized_paths


def _available_project_status_patch() -> AgentProjectCatalogStatusPatch:
    """Return status patch for a Project directory validated through Runner."""
    return AgentProjectCatalogStatusPatch(
        status=AgentProjectCatalogStatus.AVAILABLE,
        status_detail=None,
        checked_at=datetime.now(UTC),
    )


@dataclasses.dataclass
class SessionWorkspaceProjectService:
    """Manage Session Workspace Project registry."""

    repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    agent_project_preset_repository: Annotated[
        AgentProjectPresetRepository,
        Depends(AgentProjectPresetRepository),
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
    ]
    session_working_folder_binding_service: Annotated[
        SessionWorkingFolderBindingService,
        Depends(),
    ]
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None
    skill_store: Annotated[SkillStateStore | None, Depends(get_skill_state_store)] = (
        None
    )

    async def create_project(
        self,
        *,
        session_id: str,
        path: str,
    ) -> Result[SessionWorkspaceProject, ProjectCreateError]:
        """Create Project registry row."""
        async with self.session_manager() as session:
            normalized_result = await self._validate_project_path_in_session(
                session,
                session_id=session_id,
                path=path,
                bind_in_transaction=True,
            )
            match normalized_result:
                case Success(normalized_path):
                    pass
                case Failure(error):
                    return Failure(error)
            try:
                project = await self.repository.create_project(
                    session,
                    SessionWorkspaceProjectCreate(
                        session_id=session_id,
                        path=normalized_path,
                    ),
                )
            except SessionWorkspaceProjectCleanupInProgress:
                return Failure(ProjectPathCleanupInProgress(path=normalized_path))
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            await session.commit()
        if agent_session is not None:
            await self._sync_skill_projection_for_project_change(
                agent_id=agent_session.agent_id,
                session_id=session_id,
            )
        return Success(project)

    async def register_existing_folder_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        path: str,
    ) -> Result[SessionWorkspaceProject, ProjectFolderRegistrationError]:
        """Register existing directory in AgentSession Workspace as Project."""
        async with self.session_manager() as session:
            context_result = await self._get_accessible_project_context_for_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            match context_result:
                case Success(context):
                    pass
                case Failure(error):
                    return Failure(error)
            validation = await self._validate_project_path_in_session(
                session,
                session_id=context.session_id,
                path=path,
                bind_in_transaction=False,
            )
            match validation:
                case Success(normalized_path):
                    pass
                case Failure(error):
                    return Failure(error)
            try:
                binding_service = self.session_working_folder_binding_service
                await binding_service.require_bindable_context(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                )
                runtime = await self.runtime_target_resolver.resolve_operation_target(
                    context.agent_id
                )
                await binding_service.resolve_authority_for_target(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    runtime_target=runtime,
                )
            except RuntimeStorageError, SessionWorkingFolderBindingError:
                return Failure(
                    InvalidProjectPath(
                        path=normalized_path,
                        reason=(
                            "Project path can only be approved from an available "
                            "runtime."
                        ),
                    )
                )
            try:
                normalized_path = normalize_session_workspace_path(
                    normalized_path,
                    workspace_root=runtime.workspace_path,
                )
            except ValueError as error:
                return Failure(
                    InvalidProjectPath(path=normalized_path, reason=str(error))
                )
            exists_result = await validate_runtime_directory(
                self.runner_operations,
                runtime=runtime,
                path=normalized_path,
            )
            if exists_result.success:
                pass
            else:
                error = exists_result.error
                match error:
                    case RuntimeDirectoryValidationUnavailable():
                        return Failure(
                            InvalidProjectPath(
                                path=normalized_path,
                                reason=(
                                    "Project path can only be approved from a "
                                    "ready runtime."
                                ),
                            )
                        )
                    case RuntimeDirectoryNotFound():
                        return Failure(
                            InvalidProjectPath(
                                path=normalized_path,
                                reason=(
                                    "Project path must exist as a runtime directory."
                                ),
                            )
                        )
                    case RuntimeDirectoryNotDirectory():
                        return Failure(
                            InvalidProjectPath(
                                path=normalized_path,
                                reason="Project path must be a runtime directory.",
                            )
                        )
                    case _:
                        assert_never(error)
            try:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    runtime_target=runtime,
                )
            except SessionWorkingFolderBindingError:
                return Failure(
                    InvalidProjectPath(
                        path=normalized_path,
                        reason=(
                            "Project path can only be approved from an available "
                            "runtime."
                        ),
                    )
                )
            try:
                project = await self.repository.create_project(
                    session,
                    SessionWorkspaceProjectCreate(
                        session_id=context.session_id,
                        path=normalized_path,
                    ),
                )
            except SessionWorkspaceProjectCleanupInProgress:
                return Failure(ProjectPathCleanupInProgress(path=normalized_path))
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=context.agent_id,
                path=normalized_path,
            )
            await self.agent_project_catalog_repository.update_status(
                session,
                agent_id=context.agent_id,
                path=normalized_path,
                patch=_available_project_status_patch(),
            )
            await session.commit()
        await self._sync_skill_projection_for_project_change(
            agent_id=context.agent_id,
            session_id=context.session_id,
        )
        return Success(project)

    async def list_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Return Project list of AgentSession."""
        async with self.session_manager() as session:
            return await self.repository.list_projects(
                session,
                session_id=session_id,
            )

    async def list_projects_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[list[SessionWorkspaceProject], ProjectAccessError]:
        """Fetch Project list of AgentSession accessible by user."""
        async with self.session_manager() as session:
            context_result = await self._get_accessible_project_context_for_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            match context_result:
                case Success(context):
                    pass
                case Failure(error):
                    return Failure(error)
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=context.agent_id,
                session_id=context.session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                context.agent_id,
                start_if_stopped=False,
            )
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            return Failure(ProjectAccessDenied())
        async with self.session_manager() as session:
            try:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    runtime_target=runtime,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectAccessDenied())
            projects = await self.repository.list_projects(
                session,
                session_id=context.session_id,
            )
            return Success(projects)

    async def delete_project(
        self,
        *,
        session_id: str,
        project_id: str,
    ) -> Result[None, ProjectNotFound]:
        """Delete only Project registry row."""
        async with self.session_manager() as session:
            deleted = await self.repository.delete_project(
                session,
                project_id,
                session_id=session_id,
            )
            if not deleted:
                return Failure(ProjectNotFound())
            await session.commit()
            return Success(None)

    async def delete_project_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        project_id: str,
    ) -> Result[None, ProjectAccessError | ProjectNotFound]:
        """Delete Project registry row of AgentSession accessible by user."""
        async with self.session_manager() as session:
            context_result = await self._get_accessible_project_context_for_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            match context_result:
                case Success(context):
                    pass
                case Failure(error):
                    return Failure(error)
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=context.agent_id,
                session_id=context.session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                context.agent_id,
                start_if_stopped=False,
            )
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            return Failure(ProjectAccessDenied())
        async with self.session_manager() as session:
            try:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    runtime_target=runtime,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectAccessDenied())
            project = await self.repository.get_project_by_id(session, project_id)
            if project is None or project.session_id != context.session_id:
                return Failure(ProjectNotFound())
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                context.session_id,
            )
            deleted = await self.repository.delete_project(
                session,
                project_id,
                session_id=context.session_id,
            )
            if not deleted:
                return Failure(ProjectNotFound())
            if self.skill_store is not None and agent_session is not None:
                await self.skill_store.invalidate_project(
                    context.agent_id,
                    context.session_id,
                    project_id=project.id,
                    project_path=project.path,
                    session_run_state=agent_session.run_state,
                )
            await session.commit()
            return Success(None)

    async def _sync_skill_projection_for_project_change(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Refresh latest Skill projection after a Project source-set addition."""
        if self.skill_store is None or self.runner_operations is None:
            return
        projection_service = SkillProjectionService(
            store=self.skill_store,
            session_manager=self.session_manager,
            runtime_target_resolver=self.runtime_target_resolver,
            session_working_folder_binding_service=(
                self.session_working_folder_binding_service
            ),
            runner_operations=adapt_runtime_runner_operations(self.runner_operations),
            project_repository=self.repository,
        )
        await projection_service.sync_latest(
            agent_id=agent_id,
            session_id=session_id,
            reason="project_change",
        )

    async def _validate_project_path_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        path: str,
        bind_in_transaction: bool,
    ) -> Result[str, InvalidProjectPath | ProjectPathConflict]:
        """Validate Project path inside open DB session."""
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            return Failure(
                InvalidProjectPath(path=path, reason="AgentSession not found")
            )
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bindable_context(
                agent_id=agent_session.agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_session.agent_id
            )
            if bind_in_transaction:
                await binding_service.resolve_authority_in_transaction(
                    session,
                    agent_id=agent_session.agent_id,
                    session_id=session_id,
                    runtime_target=runtime,
                )
            else:
                await binding_service.resolve_authority_for_target(
                    agent_id=agent_session.agent_id,
                    session_id=session_id,
                    runtime_target=runtime,
                )
            normalized = normalize_session_workspace_path(
                path,
                workspace_root=runtime.workspace_path,
            )
        except (
            RuntimeStorageError,
            SessionWorkingFolderBindingError,
            ValueError,
        ) as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        existing_project = await self.repository.get_project_by_path(
            session,
            session_id=session_id,
            path=normalized,
        )
        if existing_project is not None:
            return Failure(
                ProjectPathConflict(
                    path=normalized,
                    conflicting_project_id=existing_project.id,
                )
            )
        return Success(normalized)

    async def _get_accessible_project_context_for_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AccessibleProjectContext, ProjectAccessError]:
        """Check AgentSession access permission and return Project context."""
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if (
            agent_session is None
            or agent_session.agent_id != agent_id
            or agent_session.status != AgentSessionStatus.ACTIVE
        ):
            return Failure(ProjectAccessDenied())
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            agent_session.workspace_id,
            user_id,
        )
        if workspace_user is None:
            return Failure(ProjectAccessDenied())
        return Success(
            AccessibleProjectContext(
                agent_id=agent_id,
                session_id=agent_session.id,
            )
        )
