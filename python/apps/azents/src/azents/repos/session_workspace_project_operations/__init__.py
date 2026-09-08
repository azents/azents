"""Repository-owned Session Workspace Project database operations."""

import dataclasses
from datetime import UTC, datetime
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, AgentSessionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.session_working_folder_binding import (
    SessionWorkingFolderBindingRepository,
)
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderTarget,
)
from azents.repos.session_workspace_project import (
    SessionWorkspaceProjectCleanupInProgress,
    SessionWorkspaceProjectRepository,
)
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)
from azents.repos.skill_state import SkillStateRepository
from azents.repos.workspace_user import WorkspaceUserRepository

from .data import (
    ProjectBindingUnavailable,
    ProjectCleanupInProgress,
    ProjectConflict,
    ProjectContextUnavailable,
    ProjectDatabaseContext,
    ProjectMissing,
    ProjectMutationResult,
)

ProjectCreateDatabaseError = (
    ProjectContextUnavailable
    | ProjectBindingUnavailable
    | ProjectConflict
    | ProjectCleanupInProgress
)
ProjectAccessDatabaseError = ProjectContextUnavailable | ProjectBindingUnavailable
ProjectDeleteDatabaseError = ProjectAccessDatabaseError | ProjectMissing


@dataclasses.dataclass(frozen=True)
class _LockedProjectContext:
    """Agent-first locked Project mutation context."""

    agent: Agent
    session: AgentSession


@dataclasses.dataclass
class SessionWorkspaceProjectOperationsRepository:
    """Compose atomic Project registry database operations."""

    project_repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    preset_repository: Annotated[
        AgentProjectPresetRepository,
        Depends(AgentProjectPresetRepository),
    ]
    catalog_repository: Annotated[
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
    binding_repository: Annotated[
        SessionWorkingFolderBindingRepository,
        Depends(SessionWorkingFolderBindingRepository),
    ]
    skill_state_repository: Annotated[
        SkillStateRepository,
        Depends(SkillStateRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def load_project_context(
        self,
        *,
        session_id: str,
    ) -> ProjectDatabaseContext | None:
        """Load detached Session identity before Runtime work."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                return None
            return ProjectDatabaseContext(
                agent_id=agent_session.agent_id,
                session_id=agent_session.id,
            )

    async def load_accessible_project_context(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> ProjectDatabaseContext | None:
        """Load detached authorization context before Runtime work."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
            ):
                return None
            membership = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                agent_session.workspace_id,
                user_id,
            )
            if membership is None:
                return None
            return ProjectDatabaseContext(
                agent_id=agent_id,
                session_id=agent_session.id,
            )

    async def create_project(
        self,
        *,
        context: ProjectDatabaseContext,
        path: str,
        target: SessionWorkingFolderTarget,
    ) -> Result[ProjectMutationResult, ProjectCreateDatabaseError]:
        """Revalidate and create one Project in a repository-owned transaction."""
        async with self.session_manager() as session:
            locked = await self._lock_context(
                session,
                context=context,
                user_id=None,
            )
            if locked is None:
                return Failure(ProjectContextUnavailable())
            try:
                await self.binding_repository.resolve_locked_authority_in_session(
                    session,
                    agent=locked.agent,
                    session_id=context.session_id,
                    target=target,
                    bind_pending=True,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectBindingUnavailable())
            create_result = await self._create_project_in_session(
                session,
                context=context,
                path=path,
                target=target,
                update_agent_projection=False,
            )
            if isinstance(create_result, Failure):
                return Failure(create_result.error)
            return Success(
                ProjectMutationResult(project=create_result.value, context=context)
            )

    async def register_existing_project(
        self,
        *,
        context: ProjectDatabaseContext,
        user_id: str,
        path: str,
        target: SessionWorkingFolderTarget,
    ) -> Result[ProjectMutationResult, ProjectCreateDatabaseError]:
        """Atomically reauthorize and register Project, preset, and catalog state."""
        async with self.session_manager() as session:
            locked = await self._lock_context(
                session,
                context=context,
                user_id=user_id,
            )
            if locked is None:
                return Failure(ProjectContextUnavailable())
            try:
                await self.binding_repository.resolve_locked_authority_in_session(
                    session,
                    agent=locked.agent,
                    session_id=context.session_id,
                    target=target,
                    bind_pending=False,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectBindingUnavailable())
            create_result = await self._create_project_in_session(
                session,
                context=context,
                path=path,
                target=target,
                update_agent_projection=True,
            )
            if isinstance(create_result, Failure):
                return Failure(create_result.error)
            return Success(
                ProjectMutationResult(project=create_result.value, context=context)
            )

    async def list_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """List Projects in one completed read transaction."""
        async with self.session_manager() as session:
            return await self.project_repository.list_projects(
                session,
                session_id=session_id,
            )

    async def find_project_by_path(
        self,
        *,
        session_id: str,
        path: str,
    ) -> SessionWorkspaceProject | None:
        """Find an exact path in one completed read transaction."""
        async with self.session_manager() as session:
            return await self.project_repository.get_project_by_path(
                session,
                session_id=session_id,
                path=path,
            )

    async def list_accessible_projects(
        self,
        *,
        context: ProjectDatabaseContext,
        user_id: str,
        target: SessionWorkingFolderTarget,
    ) -> Result[list[SessionWorkspaceProject], ProjectAccessDatabaseError]:
        """Reauthorize and list Projects under current bound Runtime authority."""
        async with self.session_manager() as session:
            locked = await self._lock_context(
                session,
                context=context,
                user_id=user_id,
            )
            if locked is None:
                return Failure(ProjectContextUnavailable())
            try:
                await self.binding_repository.resolve_locked_authority_in_session(
                    session,
                    agent=locked.agent,
                    session_id=context.session_id,
                    target=target,
                    bind_pending=False,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectBindingUnavailable())
            return Success(
                await self.project_repository.list_projects(
                    session,
                    session_id=context.session_id,
                )
            )

    async def delete_project(
        self,
        *,
        session_id: str,
        project_id: str,
    ) -> bool:
        """Delete one Project registry row in a completed transaction."""
        async with self.session_manager() as session:
            return await self.project_repository.delete_project(
                session,
                project_id,
                session_id=session_id,
            )

    async def delete_accessible_project(
        self,
        *,
        context: ProjectDatabaseContext,
        user_id: str,
        project_id: str,
        target: SessionWorkingFolderTarget,
        invalidate_skill_state: bool,
    ) -> Result[None, ProjectDeleteDatabaseError]:
        """Atomically reauthorize, delete Project, and invalidate Skill state."""
        async with self.session_manager() as session:
            locked = await self._lock_context(
                session,
                context=context,
                user_id=user_id,
            )
            if locked is None:
                return Failure(ProjectContextUnavailable())
            try:
                resolve_authority = (
                    self.binding_repository.resolve_locked_authority_in_session
                )
                authority = await resolve_authority(
                    session,
                    agent=locked.agent,
                    session_id=context.session_id,
                    target=target,
                    bind_pending=False,
                )
            except SessionWorkingFolderBindingError:
                return Failure(ProjectBindingUnavailable())
            project = await self.project_repository.lock_project_by_id(
                session,
                project_id=project_id,
                context_id=authority.context_id,
                session_id=context.session_id,
            )
            if project is None:
                return Failure(ProjectMissing())
            deleted = await self.project_repository.delete_project(
                session,
                project_id,
                session_id=context.session_id,
            )
            if not deleted:
                return Failure(ProjectMissing())
            if invalidate_skill_state:
                await self.skill_state_repository.invalidate_project_in_session(
                    session,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    project_id=project.id,
                    project_path=project.path,
                    session_run_state=locked.session.run_state,
                )
            return Success(None)

    async def _lock_context(
        self,
        session: AsyncSession,
        *,
        context: ProjectDatabaseContext,
        user_id: str | None,
    ) -> _LockedProjectContext | None:
        """Lock Agent, Session, and optional membership in canonical order."""
        agent = await self.agent_repository.lock_by_id(
            session,
            context.agent_id,
        )
        if agent is None:
            return None
        agent_session = await self.agent_session_repository.lock_by_id(
            session,
            context.session_id,
        )
        if (
            agent_session is None
            or agent_session.agent_id != context.agent_id
            or agent_session.status is not AgentSessionStatus.ACTIVE
        ):
            return None
        if user_id is not None:
            membership = (
                await self.workspace_user_repository.lock_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if membership is None:
                return None
        return _LockedProjectContext(agent=agent, session=agent_session)

    async def _create_project_in_session(
        self,
        session: AsyncSession,
        *,
        context: ProjectDatabaseContext,
        path: str,
        target: SessionWorkingFolderTarget,
        update_agent_projection: bool,
    ) -> Result[
        SessionWorkspaceProject,
        ProjectConflict | ProjectCleanupInProgress,
    ]:
        """Create Project and related rows after authority is locked."""
        await self.project_repository.acquire_runtime_path_coordination_lock(
            session,
            runtime_id=target.id,
        )
        existing = await self.project_repository.get_project_by_path(
            session,
            session_id=context.session_id,
            path=path,
        )
        if existing is not None:
            return Failure(ProjectConflict(project=existing))
        if await self.project_repository.has_blocking_git_worktree_claim(
            session,
            runtime_id=target.id,
            worktree_path=path,
        ):
            return Failure(ProjectCleanupInProgress(path=path))
        try:
            project = await self.project_repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=context.session_id,
                    path=path,
                ),
            )
        except SessionWorkspaceProjectCleanupInProgress:
            return Failure(ProjectCleanupInProgress(path=path))
        if update_agent_projection:
            await self.preset_repository.upsert_preset(
                session,
                agent_id=context.agent_id,
                path=path,
            )
            await self.catalog_repository.update_status(
                session,
                agent_id=context.agent_id,
                path=path,
                patch=AgentProjectCatalogStatusPatch(
                    status=AgentProjectCatalogStatus.AVAILABLE,
                    status_detail=None,
                    checked_at=datetime.now(UTC),
                ),
            )
        return Success(project)
