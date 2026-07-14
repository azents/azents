"""Session Workspace Project service."""

import asyncio
import dataclasses
import logging
import posixpath
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    AgentSessionStatus,
    RuntimeRunnerState,
)
from azents.engine.tools.deps import get_skill_state_store
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations

SESSION_WORKSPACE_ROOT = PurePosixPath("/workspace/agent")
_RUNNER_PROJECT_VALIDATION_TIMEOUT_SECONDS = 120
_POST_COMMIT_PROJECTION_TIMEOUT_SECONDS = 1.0

logger = logging.getLogger(__name__)


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


@dataclasses.dataclass(frozen=True)
class _ProjectFolderRegistrationSnapshot:
    """Detached project/runtime state validated before Runner I/O."""

    context: AccessibleProjectContext
    normalized_path: str
    runtime: AgentRuntime


@dataclasses.dataclass(frozen=True)
class _LockedProjectRegistrationAuthority:
    """Project registration authority held until the database commit."""

    context: AccessibleProjectContext
    runtime: AgentRuntime


@dataclasses.dataclass(frozen=True)
class _DeletedProjectInvalidation:
    """Committed Project deletion data for post-transaction projection cleanup."""

    agent_id: str
    session_id: str
    project_id: str
    project_path: str


ProjectCreateError = InvalidProjectPath | ProjectPathConflict
ProjectAccessError = AgentNotFound | ProjectAccessDenied
ProjectFolderRegistrationError = ProjectAccessError | ProjectCreateError


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
    return normalized.as_posix()


def normalize_session_workspace_project_paths(paths: list[str]) -> list[str]:
    """Normalize Project paths and remove exact duplicates while preserving order."""
    normalized_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_session_workspace_path(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)
    return normalized_paths


def _runner_project_validation_deadline() -> datetime:
    """Return Runtime operation deadline for Project path validation."""
    return datetime.now(UTC) + timedelta(
        seconds=_RUNNER_PROJECT_VALIDATION_TIMEOUT_SECONDS
    )


def _available_project_status_patch() -> AgentProjectCatalogStatusPatch:
    """Return status patch for a Project directory validated through Runner."""
    return AgentProjectCatalogStatusPatch(
        status=AgentProjectCatalogStatus.AVAILABLE,
        status_detail=None,
        checked_at=datetime.now(UTC),
    )


def _same_runner_generation(current: AgentRuntime, snapshot: AgentRuntime) -> bool:
    """Return whether Runner validation still applies to the current Runtime."""
    return (
        current.id == snapshot.id
        and current.runner_generation == snapshot.runner_generation
        and current.runner_state == snapshot.runner_state
        and current.runner_state == RuntimeRunnerState.READY
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
        normalized_result = await self._validate_project_path(
            session_id=session_id,
            path=path,
        )
        match normalized_result:
            case Success(normalized_path):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(normalized_result)
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            project = await self.repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=session_id,
                    path=normalized_path,
                ),
            )
            await session.commit()
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
                case _:
                    assert_never(context_result)
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
                case _:
                    assert_never(validation)
            runtime_result = await self._get_runtime_for_project_context(
                session,
                context,
            )
            match runtime_result:
                case Success(runtime):
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(runtime_result)
            snapshot = _ProjectFolderRegistrationSnapshot(
                context=context,
                normalized_path=normalized_path,
                runtime=runtime,
            )

        exists_result = await _ensure_real_directory_in_runtime(
            self.runner_operations,
            runtime=snapshot.runtime,
            path=snapshot.normalized_path,
        )
        match exists_result:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(exists_result)

        async with self.session_manager() as session:
            authority_result = await self._lock_project_registration_authority(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            match authority_result:
                case Success(authority):
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(authority_result)
            validation = await self._validate_project_path_in_session(
                session,
                session_id=authority.context.session_id,
                path=snapshot.normalized_path,
            )
            match validation:
                case Success(refreshed_normalized_path):
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(validation)
            if (
                authority.context != snapshot.context
                or refreshed_normalized_path != snapshot.normalized_path
                or not _same_runner_generation(authority.runtime, snapshot.runtime)
            ):
                return Failure(
                    InvalidProjectPath(
                        path=snapshot.normalized_path,
                        reason=(
                            "Runtime changed while the Project directory was being "
                            "validated. Please retry."
                        ),
                    )
                )
            project = await self.repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=authority.context.session_id,
                    path=refreshed_normalized_path,
                ),
            )
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=authority.context.agent_id,
                path=refreshed_normalized_path,
            )
            await self.agent_project_catalog_repository.update_status(
                session,
                agent_id=authority.context.agent_id,
                path=refreshed_normalized_path,
                patch=_available_project_status_patch(),
            )
            await session.commit()
        await self._sync_skill_projection_for_project_change(
            agent_id=snapshot.context.agent_id,
            session_id=snapshot.context.session_id,
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
                case _:
                    assert_never(context_result)
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
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                return Failure(ProjectNotFound())
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
            context_result = await self._lock_project_access_authority(
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
                case _:
                    assert_never(context_result)
            project = await self.repository.get_project_by_id(session, project_id)
            if project is None or project.session_id != context.session_id:
                return Failure(ProjectNotFound())
            deleted = await self.repository.delete_project(
                session,
                project_id,
                session_id=context.session_id,
            )
            if not deleted:
                return Failure(ProjectNotFound())
            invalidation = _DeletedProjectInvalidation(
                agent_id=context.agent_id,
                session_id=context.session_id,
                project_id=project.id,
                project_path=project.path,
            )
            await session.commit()
        if self.skill_store is not None:
            skill_store = self.skill_store
            await _run_post_commit_projection(
                lambda: skill_store.invalidate_project(
                    invalidation.agent_id,
                    invalidation.session_id,
                    project_id=invalidation.project_id,
                    project_path=invalidation.project_path,
                ),
                failure_message=(
                    "Failed to invalidate Skill projection after Project deletion"
                ),
                extra={
                    "agent_id": invalidation.agent_id,
                    "session_id": invalidation.session_id,
                    "project_id": invalidation.project_id,
                },
            )
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
            agent_session_repository=self.agent_session_repository,
            runner_operations=adapt_runtime_runner_operations(self.runner_operations),
            runtime_repository=self.agent_runtime_repository,
            project_repository=self.repository,
        )
        await _run_post_commit_projection(
            lambda: projection_service.sync_latest(
                agent_id=agent_id,
                session_id=session_id,
                reason="project_change",
            ),
            failure_message="Failed to refresh Skill projection after Project creation",
            extra={"agent_id": agent_id, "session_id": session_id},
        )

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

    async def _lock_project_registration_authority(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[_LockedProjectRegistrationAuthority, ProjectAccessError]:
        """Lock Runtime, AgentSession, and membership in one fixed order."""
        runtime = await self.agent_runtime_repository.lock_by_agent_id(
            session,
            agent_id,
        )
        if runtime is None:
            return Failure(AgentNotFound())
        context_result = await self._lock_project_access_authority(
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
            case _:
                assert_never(context_result)
        return Success(
            _LockedProjectRegistrationAuthority(
                context=context,
                runtime=runtime,
            )
        )

    async def _lock_project_access_authority(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AccessibleProjectContext, ProjectAccessError]:
        """Lock AgentSession then membership for one final Project mutation."""
        agent_session = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if (
            agent_session is None
            or agent_session.agent_id != agent_id
            or agent_session.status != AgentSessionStatus.ACTIVE
        ):
            return Failure(ProjectAccessDenied())
        workspace_user = (
            await self.workspace_user_repository.lock_by_workspace_and_user(
                session,
                agent_session.workspace_id,
                user_id,
            )
        )
        if workspace_user is None:
            return Failure(ProjectAccessDenied())
        return Success(
            AccessibleProjectContext(
                agent_id=agent_id,
                session_id=agent_session.id,
            )
        )


async def _run_post_commit_projection(
    operation: Callable[[], Awaitable[object]],
    *,
    failure_message: str,
    extra: dict[str, object],
) -> None:
    """Bound best-effort projection I/O without reversing a durable commit."""
    try:
        async with asyncio.timeout(_POST_COMMIT_PROJECTION_TIMEOUT_SECONDS):
            await operation()
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        logger.warning(
            "%s (timed out)",
            failure_message,
            extra={
                **extra,
                "timeout_seconds": _POST_COMMIT_PROJECTION_TIMEOUT_SECONDS,
            },
        )
    except (
        RedisError,
        RuntimeRunnerOperationFailedError,
        RuntimeRunnerOperationUnavailable,
        RuntimeRunnerOperationGenerationError,
    ):
        logger.warning(failure_message, extra=extra, exc_info=True)
    except Exception:
        logger.exception(failure_message, extra=extra)


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
            owner_session_id=None,
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
