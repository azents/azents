"""Session Workspace Project service."""

import dataclasses
import posixpath
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeRunnerState,
    SessionWorkspaceProjectRegistrationRequestStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
    SessionWorkspaceProjectRegistrationRequest,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client

SESSION_WORKSPACE_ROOT = PurePosixPath("/workspace/agent")
_RUNNER_PROJECT_VALIDATION_TIMEOUT_SECONDS = 120


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
class ProjectNotFound:
    """Project not found."""


@dataclasses.dataclass(frozen=True)
class RegistrationRequestNotFound:
    """Project registration request not found."""


@dataclasses.dataclass(frozen=True)
class RegistrationRequestAlreadyResolved:
    """Project registration request already processed."""


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


ProjectCreateError = InvalidProjectPath | ProjectPathConflict
ProjectAccessError = AgentNotFound | ProjectAccessDenied
ProjectFolderRegistrationError = ProjectAccessError | ProjectCreateError
ProjectRegistrationRequestError = (
    AgentNotFound
    | ProjectAccessDenied
    | InvalidProjectPath
    | ProjectPathConflict
    | RegistrationRequestNotFound
    | RegistrationRequestAlreadyResolved
)


def normalize_session_workspace_path(path: str) -> str:
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
    if normalized == SESSION_WORKSPACE_ROOT:
        raise ValueError("Session Workspace root cannot be a Project")
    if not normalized.is_relative_to(SESSION_WORKSPACE_ROOT):
        raise ValueError("Project path must be under Agent Workspace root")
    if normalized.parent != SESSION_WORKSPACE_ROOT:
        raise ValueError("Project path must be a direct child of Agent Workspace root")
    return normalized.as_posix()


def _is_nested_or_parent(candidate: PurePosixPath, existing: PurePosixPath) -> bool:
    """Check whether two Project paths have nested relationship."""
    return candidate.is_relative_to(existing) or existing.is_relative_to(candidate)


def _runner_project_validation_deadline() -> datetime:
    """Return Runtime operation deadline for Project path validation."""
    return datetime.now(UTC) + timedelta(
        seconds=_RUNNER_PROJECT_VALIDATION_TIMEOUT_SECONDS
    )


@dataclasses.dataclass
class SessionWorkspaceProjectService:
    """Manage Session Workspace Project registry."""

    repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
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
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None

    async def create_project(
        self,
        *,
        session_id: str,
        path: str,
    ) -> Result[SessionWorkspaceProject, ProjectCreateError]:
        """Create Project registry row."""
        normalized_result = await self._validate_project_path(
            session_id=session_id,
            path=path,
        )
        match normalized_result:
            case Success(normalized_path):
                pass
            case Failure(error):
                return Failure(error)
        async with self.session_manager() as session:
            project = await self.repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=session_id,
                    path=normalized_path,
                ),
            )
            await session.commit()
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
            )
            match validation:
                case Success(normalized_path):
                    pass
                case Failure(error):
                    return Failure(error)
            runtime_result = await self._get_runtime_for_project_context(
                session,
                context,
            )
            match runtime_result:
                case Success(runtime):
                    pass
                case Failure(error):
                    return Failure(error)
            exists_result = await _ensure_real_directory_in_runtime(
                self.runner_operations,
                runtime=runtime,
                path=normalized_path,
            )
            match exists_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
            project = await self.repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=context.session_id,
                    path=normalized_path,
                ),
            )
            await session.commit()
            return Success(project)

    async def list_registration_requests_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[list[SessionWorkspaceProjectRegistrationRequest], ProjectAccessError]:
        """Fetch Project registration requests of AgentSession accessible by user."""
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
            requests = await self.repository.list_registration_requests(
                session,
                session_id=context.session_id,
            )
            return Success(requests)

    async def approve_registration_request_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        request_id: str,
    ) -> Result[SessionWorkspaceProject, ProjectRegistrationRequestError]:
        """User approves AgentSession Project registration request."""
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
            request = await self.repository.get_registration_request_by_id_for_update(
                session,
                request_id,
            )
            if request is None or request.session_id != context.session_id:
                return Failure(RegistrationRequestNotFound())
            if (
                request.status
                is not SessionWorkspaceProjectRegistrationRequestStatus.PENDING
            ):
                return Failure(RegistrationRequestAlreadyResolved())
            validation = await self._validate_project_path_in_session(
                session,
                session_id=context.session_id,
                path=request.path,
            )
            match validation:
                case Success(normalized_path):
                    pass
                case Failure(error):
                    return Failure(error)
            runtime_result = await self._get_runtime_for_project_context(
                session,
                context,
            )
            match runtime_result:
                case Success(runtime):
                    pass
                case Failure(error):
                    return Failure(error)
            exists_result = await _ensure_real_directory_in_runtime(
                self.runner_operations,
                runtime=runtime,
                path=normalized_path,
            )
            match exists_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
            project = await self.repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=context.session_id,
                    path=normalized_path,
                ),
            )
            updated = await self.repository.mark_registration_request_approved(
                session,
                request_id,
                session_id=context.session_id,
                project_id=project.id,
            )
            if not updated:
                await self.repository.delete_project(
                    session,
                    project.id,
                    session_id=context.session_id,
                )
                return Failure(RegistrationRequestAlreadyResolved())
            await session.commit()
            return Success(project)

    async def reject_registration_request_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        request_id: str,
    ) -> Result[
        None,
        ProjectAccessError
        | RegistrationRequestNotFound
        | RegistrationRequestAlreadyResolved,
    ]:
        """User rejects AgentSession Project registration request."""
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
            request = await self.repository.get_registration_request_by_id_for_update(
                session,
                request_id,
            )
            if request is None or request.session_id != context.session_id:
                return Failure(RegistrationRequestNotFound())
            if (
                request.status
                is not SessionWorkspaceProjectRegistrationRequestStatus.PENDING
            ):
                return Failure(RegistrationRequestAlreadyResolved())
            updated = await self.repository.mark_registration_request_rejected(
                session,
                request_id,
                session_id=context.session_id,
            )
            if not updated:
                return Failure(RegistrationRequestAlreadyResolved())
            await session.commit()
            return Success(None)

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
            deleted = await self.repository.delete_project(
                session,
                project_id,
                session_id=context.session_id,
            )
            if not deleted:
                return Failure(ProjectNotFound())
            await session.commit()
            return Success(None)

    async def _validate_project_path(
        self,
        *,
        session_id: str,
        path: str,
    ) -> Result[str, InvalidProjectPath | ProjectPathConflict]:
        """Validate Project path contract and existing Project conflicts."""
        async with self.session_manager() as session:
            return await self._validate_project_path_in_session(
                session,
                session_id=session_id,
                path=path,
            )

    async def _validate_project_path_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        path: str,
    ) -> Result[str, InvalidProjectPath | ProjectPathConflict]:
        """Validate Project path inside open DB session."""
        try:
            normalized = normalize_session_workspace_path(path)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        candidate = PurePosixPath(normalized)
        existing_projects = await self.repository.list_projects(
            session,
            session_id=session_id,
        )
        for project in existing_projects:
            existing = PurePosixPath(project.path)
            if _is_nested_or_parent(candidate, existing):
                return Failure(
                    ProjectPathConflict(
                        path=normalized,
                        conflicting_project_id=project.id,
                    )
                )
        return Success(normalized)

    async def _get_runtime_for_project_context(
        self,
        session: AsyncSession,
        context: AccessibleProjectContext,
    ) -> Result[AgentRuntime, AgentNotFound]:
        """Fetch runtime for a Project context without ensuring new rows."""
        runtime = await self.agent_runtime_repository.get_by_agent_id(
            session,
            context.agent_id,
        )
        if runtime is None:
            return Failure(AgentNotFound())
        return Success(runtime)

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
        if agent_session is None or agent_session.agent_id != agent_id:
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


async def _ensure_real_directory_in_runtime(
    runner_operations: RuntimeRunnerOperationClient | None,
    *,
    runtime: AgentRuntime,
    path: str,
) -> Result[None, InvalidProjectPath]:
    """Check whether actual directory exists in Runtime."""
    if runner_operations is None or runtime.runner_state != RuntimeRunnerState.READY:
        return Failure(
            InvalidProjectPath(
                path=path,
                reason="Project path can only be approved from a ready runtime.",
            )
        )
    try:
        await runner_operations.list_files(
            runtime_id=runtime.id,
            runner_generation=runtime.runner_generation,
            path=path,
            deadline_at=_runner_project_validation_deadline(),
        )
    except (
        RuntimeRunnerOperationUnavailable,
        RuntimeRunnerOperationGenerationError,
    ):
        return Failure(
            InvalidProjectPath(
                path=path,
                reason="Project path can only be approved from a ready runtime.",
            )
        )
    except RuntimeRunnerOperationFailedError as error:
        return Failure(
            InvalidProjectPath(
                path=path,
                reason=f"Project path must exist as a runtime directory: {error}",
            )
        )
    return Success(None)
