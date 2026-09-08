"""Session Workspace Project service."""

import dataclasses
import posixpath
from pathlib import PurePosixPath
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.engine.tools.deps import get_skill_state_store
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderTarget,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.repos.session_workspace_project_operations import (
    ProjectCreateDatabaseError,
    SessionWorkspaceProjectOperationsRepository,
)
from azents.repos.session_workspace_project_operations.data import (
    ProjectBindingUnavailable,
    ProjectCleanupInProgress,
    ProjectConflict,
    ProjectContextUnavailable,
    ProjectDatabaseContext,
    ProjectMissing,
    ProjectMutationResult,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
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


@dataclasses.dataclass
class SessionWorkspaceProjectService:
    """Manage Session Workspace Project registry and Runtime validation."""

    operations_repository: Annotated[
        SessionWorkspaceProjectOperationsRepository,
        Depends(SessionWorkspaceProjectOperationsRepository),
    ]
    repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
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
        context = await self.operations_repository.load_project_context(
            session_id=session_id
        )
        if context is None:
            return Failure(
                InvalidProjectPath(path=path, reason="AgentSession not found")
            )
        target_result = await self._resolve_target(
            context=context,
            require_bound=False,
            failure_path=path,
        )
        if isinstance(target_result, Failure):
            return Failure(target_result.error)
        runtime = target_result.value
        normalized_result = self._normalize_path(path, runtime=runtime)
        if isinstance(normalized_result, Failure):
            return Failure(normalized_result.error)
        normalized_path = normalized_result.value
        result = await self.operations_repository.create_project(
            context=context,
            path=normalized_path,
            target=self._target_evidence(runtime),
        )
        mapped = self._map_create_result(result, path=normalized_path)
        if isinstance(mapped, Failure):
            return mapped
        await self._sync_skill_projection_for_project_change(
            agent_id=context.agent_id,
            session_id=context.session_id,
        )
        return Success(mapped.value)

    async def register_existing_folder_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        path: str,
    ) -> Result[SessionWorkspaceProject, ProjectFolderRegistrationError]:
        """Register existing directory in AgentSession Workspace as Project."""
        context = await self.operations_repository.load_accessible_project_context(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        if context is None:
            return Failure(ProjectAccessDenied())
        target_result = await self._resolve_target(
            context=context,
            require_bound=False,
            failure_path=path,
        )
        if isinstance(target_result, Failure):
            return Failure(target_result.error)
        runtime = target_result.value
        normalized_result = self._normalize_path(path, runtime=runtime)
        if isinstance(normalized_result, Failure):
            return Failure(normalized_result.error)
        normalized_path = normalized_result.value
        existing = await self.operations_repository.find_project_by_path(
            session_id=context.session_id,
            path=normalized_path,
        )
        if existing is not None:
            return Failure(
                ProjectPathConflict(
                    path=normalized_path,
                    conflicting_project_id=existing.id,
                )
            )
        exists_result = await validate_runtime_directory(
            self.runner_operations,
            runtime=runtime,
            path=normalized_path,
        )
        if not exists_result.success:
            error = exists_result.error
            match error:
                case RuntimeDirectoryValidationUnavailable():
                    return Failure(
                        InvalidProjectPath(
                            path=normalized_path,
                            reason=(
                                "Project path can only be approved from a ready "
                                "runtime."
                            ),
                        )
                    )
                case RuntimeDirectoryNotFound():
                    return Failure(
                        InvalidProjectPath(
                            path=normalized_path,
                            reason="Project path must exist as a runtime directory.",
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
        result = await self.operations_repository.register_existing_project(
            context=context,
            user_id=user_id,
            path=normalized_path,
            target=self._target_evidence(runtime),
        )
        if isinstance(result, Failure) and isinstance(
            result.error,
            ProjectContextUnavailable,
        ):
            return Failure(ProjectAccessDenied())
        mapped = self._map_create_result(result, path=normalized_path)
        if isinstance(mapped, Failure):
            return Failure(mapped.error)
        await self._sync_skill_projection_for_project_change(
            agent_id=context.agent_id,
            session_id=context.session_id,
        )
        return Success(mapped.value)

    async def list_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Return Project list of AgentSession."""
        return await self.operations_repository.list_projects(session_id=session_id)

    async def list_projects_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[list[SessionWorkspaceProject], ProjectAccessError]:
        """Fetch Project list of AgentSession accessible by user."""
        context = await self.operations_repository.load_accessible_project_context(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        if context is None:
            return Failure(ProjectAccessDenied())
        target_result = await self._resolve_target(
            context=context,
            require_bound=True,
            failure_path="",
        )
        if isinstance(target_result, Failure):
            return Failure(ProjectAccessDenied())
        result = await self.operations_repository.list_accessible_projects(
            context=context,
            user_id=user_id,
            target=self._target_evidence(target_result.value),
        )
        if isinstance(result, Failure):
            return Failure(ProjectAccessDenied())
        return result

    async def delete_project(
        self,
        *,
        session_id: str,
        project_id: str,
    ) -> Result[None, ProjectNotFound]:
        """Delete only Project registry row."""
        deleted = await self.operations_repository.delete_project(
            session_id=session_id,
            project_id=project_id,
        )
        if not deleted:
            return Failure(ProjectNotFound())
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
        context = await self.operations_repository.load_accessible_project_context(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        if context is None:
            return Failure(ProjectAccessDenied())
        target_result = await self._resolve_target(
            context=context,
            require_bound=True,
            failure_path="",
        )
        if isinstance(target_result, Failure):
            return Failure(ProjectAccessDenied())
        result = await self.operations_repository.delete_accessible_project(
            context=context,
            user_id=user_id,
            project_id=project_id,
            target=self._target_evidence(target_result.value),
            invalidate_skill_state=self.skill_store is not None,
        )
        if isinstance(result, Success):
            return result
        match result.error:
            case ProjectMissing():
                return Failure(ProjectNotFound())
            case ProjectContextUnavailable() | ProjectBindingUnavailable():
                return Failure(ProjectAccessDenied())

    async def _resolve_target(
        self,
        *,
        context: ProjectDatabaseContext,
        require_bound: bool,
        failure_path: str,
    ) -> Result[RuntimeOperationTarget, InvalidProjectPath]:
        """Resolve Runtime target after one completed database preflight."""
        try:
            binding_service = self.session_working_folder_binding_service
            if require_bound:
                await binding_service.require_bound_context(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                )
            else:
                await binding_service.require_bindable_context(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                context.agent_id,
                start_if_stopped=not require_bound,
            )
            if not require_bound:
                await binding_service.resolve_authority_for_target(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    runtime_target=runtime,
                )
            return Success(runtime)
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            return Failure(
                InvalidProjectPath(
                    path=failure_path,
                    reason=(
                        "Project path can only be approved from an available runtime."
                    ),
                )
            )

    @staticmethod
    def _normalize_path(
        path: str,
        *,
        runtime: RuntimeOperationTarget,
    ) -> Result[str, InvalidProjectPath]:
        """Normalize one Project path against current Runner Workspace evidence."""
        try:
            return Success(
                normalize_session_workspace_path(
                    path,
                    workspace_root=runtime.workspace_path,
                )
            )
        except ValueError as error:
            return Failure(InvalidProjectPath(path=path, reason=str(error)))

    @staticmethod
    def _target_evidence(
        runtime: RuntimeOperationTarget,
    ) -> SessionWorkingFolderTarget:
        """Project Runtime target into the database-only finalization input."""
        return SessionWorkingFolderTarget(
            id=runtime.id,
            capability_snapshot_version=runtime.runtime_capability_version,
            runtime_target_capability_version=runtime.runtime_capability_version,
            workspace_path=runtime.workspace_path,
        )

    @staticmethod
    def _map_create_result(
        result: Result[ProjectMutationResult, ProjectCreateDatabaseError],
        *,
        path: str,
    ) -> Result[SessionWorkspaceProject, ProjectCreateError]:
        """Map database-only operation outcomes to the stable service contract."""
        if isinstance(result, Success):
            return Success(result.value.project)
        match result.error:
            case ProjectConflict(project):
                return Failure(
                    ProjectPathConflict(
                        path=path,
                        conflicting_project_id=project.id,
                    )
                )
            case ProjectCleanupInProgress():
                return Failure(ProjectPathCleanupInProgress(path=path))
            case ProjectContextUnavailable() | ProjectBindingUnavailable():
                return Failure(
                    InvalidProjectPath(
                        path=path,
                        reason=(
                            "Project path can only be approved from an available "
                            "runtime."
                        ),
                    )
                )

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
            project_reader=self.operations_repository,
            runtime_target_resolver=self.runtime_target_resolver,
            session_working_folder_binding_service=(
                self.session_working_folder_binding_service
            ),
            runner_operations=adapt_runtime_runner_operations(self.runner_operations),
        )
        await projection_service.sync_latest(
            agent_id=agent_id,
            session_id=session_id,
            reason="project_change",
        )
