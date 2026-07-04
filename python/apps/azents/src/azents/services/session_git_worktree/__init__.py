"""Session Git worktree initialization service."""

import dataclasses
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    RuntimeRunnerState,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
    SessionInitializationEventKind,
    SessionInitializationStatus,
    SessionInitializationStepStatus,
    SessionInitializationStepType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_initialization.data import (
    SessionInitialization,
    SessionInitializationCreate,
    SessionInitializationEvent,
    SessionInitializationEventCreate,
    SessionInitializationStep,
    SessionInitializationStepCreate,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeGitRefEntry,
    RuntimeOperationTextCallback,
    RuntimeOperationTextDelta,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.session_initialization import SessionInitializationProjection
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
)

_WORKTREE_ROOT = PurePosixPath("/workspace/agent/.azents/worktrees")
_GIT_OPERATION_TIMEOUT_SECONDS = 300
_MAX_COLLISION_ATTEMPTS = 20


@dataclasses.dataclass(frozen=True)
class GitWorktreeWorkspaceMode:
    """Git worktree mode selected for a new AgentSession."""

    source_project_path: str
    starting_ref: str


@dataclasses.dataclass(frozen=True)
class ExplicitProjectsWorkspaceMode:
    """Existing explicit Project path mode selected for a new AgentSession."""

    project_paths: list[str]


NewSessionWorkspaceMode = ExplicitProjectsWorkspaceMode | GitWorktreeWorkspaceMode


@dataclasses.dataclass(frozen=True)
class GitRefPreview:
    """Git refs available from a source Project."""

    refs: tuple[RuntimeGitRefEntry, ...]
    default_branch: str | None
    head_commit: str | None


@dataclasses.dataclass(frozen=True)
class GitRefPreviewAgentNotFound:
    """Agent for Git ref preview was not found."""


@dataclasses.dataclass(frozen=True)
class GitRefPreviewAccessDenied:
    """Requester cannot access the Agent workspace."""


@dataclasses.dataclass(frozen=True)
class GitRefPreviewRuntimeUnavailable:
    """Runtime Runner is not available for Git ref preview."""

    reason: str


GitRefPreviewError = (
    GitRefPreviewAgentNotFound
    | GitRefPreviewAccessDenied
    | GitRefPreviewRuntimeUnavailable
    | InvalidProjectPath
)


SessionInitializationEventCallback = Callable[
    [SessionInitializationEvent], Awaitable[None]
]
SessionInitializationProjectionCallback = Callable[
    [SessionInitializationProjection], Awaitable[None]
]


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupRequest:
    """Cleanup request result."""

    cleanup_requested: bool


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupSessionNotFound:
    """Session for cleanup was not found."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupAccessDenied:
    """Requester cannot clean up this session worktree."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupNotFound:
    """No session Git worktree allocation exists."""


GitWorktreeCleanupRequestError = (
    GitWorktreeCleanupSessionNotFound
    | GitWorktreeCleanupAccessDenied
    | GitWorktreeCleanupNotFound
)


@dataclasses.dataclass(frozen=True)
class GitWorktreeInitializationRetryRequest:
    """Initialization retry request result."""

    retry_requested: bool


@dataclasses.dataclass(frozen=True)
class GitWorktreeInitializationRetrySessionNotFound:
    """Session for initialization retry was not found."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeInitializationRetryAccessDenied:
    """Requester cannot retry this session initialization."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeInitializationRetryNotFound:
    """No session Git worktree initialization exists."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeInitializationRetryUnavailable:
    """Initialization is not retryable in its current state."""

    reason: str


GitWorktreeInitializationRetryRequestError = (
    GitWorktreeInitializationRetrySessionNotFound
    | GitWorktreeInitializationRetryAccessDenied
    | GitWorktreeInitializationRetryNotFound
    | GitWorktreeInitializationRetryUnavailable
)


@dataclasses.dataclass(frozen=True)
class PreparedGitWorktreeInitialization:
    """Prepared durable initialization rows for a worktree session."""

    initialization: SessionInitialization
    create_step: SessionInitializationStep
    allocation: SessionGitWorktree


@dataclasses.dataclass
class SessionGitWorktreeService:
    """Orchestrate session Git worktree allocation and initialization."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    session_initialization_repository: Annotated[
        SessionInitializationRepository, Depends(SessionInitializationRepository)
    ]
    session_git_worktree_repository: Annotated[
        SessionGitWorktreeRepository, Depends(SessionGitWorktreeRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends(AgentProjectCatalogRepository)
    ]
    agent_project_catalog_service: Annotated[
        AgentProjectCatalogService, Depends(AgentProjectCatalogService)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None

    async def preview_git_refs(
        self,
        *,
        agent_id: str,
        user_id: str,
        source_project_path: str,
    ) -> Result[GitRefPreview, GitRefPreviewError]:
        """List Git refs for a source Project after access validation."""
        try:
            normalized_source_path = normalize_session_workspace_path(
                source_project_path
            )
        except ValueError as exc:
            return Failure(
                InvalidProjectPath(path=source_project_path, reason=str(exc))
            )
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(GitRefPreviewAgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(GitRefPreviewAccessDenied())
            runtime = await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            return Failure(
                GitRefPreviewRuntimeUnavailable(reason="Runtime runner is not ready.")
            )
        if self.runner_operations is None:
            return Failure(
                GitRefPreviewRuntimeUnavailable(
                    reason="Runtime runner operations are unavailable."
                )
            )
        try:
            result = await self.runner_operations.list_git_refs(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                source_project_path=normalized_source_path,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            return Failure(
                GitRefPreviewRuntimeUnavailable(reason="Runtime runner is not ready.")
            )
        except RuntimeRunnerOperationFailedError as exc:
            return Failure(GitRefPreviewRuntimeUnavailable(reason=str(exc)))
        return Success(
            GitRefPreview(
                refs=result.refs,
                default_branch=result.default_branch,
                head_commit=result.head_commit,
            )
        )

    async def prepare_git_worktree_initialization(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        session_handle: str,
        source_project_path: str,
        starting_ref: str,
    ) -> Result[PreparedGitWorktreeInitialization, InvalidProjectPath]:
        """Create durable initialization rows for a Git worktree session."""
        del agent_id
        prepared = await self._prepare_worktree_steps(
            session,
            session_id=session_id,
            session_handle=session_handle,
            source_project_path=source_project_path,
            starting_ref=starting_ref,
        )
        match prepared:
            case Success(value):
                return Success(value)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(prepared)

    async def _prepare_worktree_steps(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        session_handle: str,
        source_project_path: str,
        starting_ref: str,
    ) -> Result[PreparedGitWorktreeInitialization, InvalidProjectPath]:
        """Create one worktree allocation and its scoped initialization steps."""
        try:
            normalized_source_path = normalize_session_workspace_path(
                source_project_path
            )
        except ValueError as exc:
            return Failure(
                InvalidProjectPath(path=source_project_path, reason=str(exc))
            )
        if not starting_ref.strip():
            return Failure(
                InvalidProjectPath(
                    path=normalized_source_path,
                    reason="Starting Git ref is required.",
                )
            )
        initialization = (
            await self.session_initialization_repository.create_initialization(
                session,
                SessionInitializationCreate(
                    session_id=session_id,
                    status=SessionInitializationStatus.PENDING,
                    failure_summary=None,
                    started_at=None,
                    completed_at=None,
                    failed_at=None,
                    canceled_at=None,
                    cleaned_at=None,
                ),
            )
        )
        next_sequence = 1
        worktree_id = uuid7().hex
        create_key = _worktree_step_key(
            SessionInitializationStepType.CREATE_GIT_WORKTREE,
            worktree_id,
        )
        register_key = _worktree_step_key(
            SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT,
            worktree_id,
        )
        catalog_key = _worktree_step_key(
            SessionInitializationStepType.UPSERT_PROJECT_CATALOG,
            worktree_id,
        )
        refresh_key = _worktree_step_key(
            SessionInitializationStepType.REFRESH_PROJECT_STATUS,
            worktree_id,
        )
        create_step = await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=next_sequence,
                step_key=create_key,
                step_type=SessionInitializationStepType.CREATE_GIT_WORKTREE,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[],
                resource_descriptors=[
                    {"type": "git_worktree", "worktree_id": worktree_id}
                ],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=next_sequence + 1,
                step_key=register_key,
                step_type=SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[create_key],
                resource_descriptors=[
                    {"type": "git_worktree", "worktree_id": worktree_id}
                ],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=next_sequence + 2,
                step_key=catalog_key,
                step_type=SessionInitializationStepType.UPSERT_PROJECT_CATALOG,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[register_key],
                resource_descriptors=[
                    {"type": "git_worktree", "worktree_id": worktree_id}
                ],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=next_sequence + 3,
                step_key=refresh_key,
                step_type=SessionInitializationStepType.REFRESH_PROJECT_STATUS,
                blocking=False,
                retryable=True,
                depends_on_step_keys=[catalog_key],
                resource_descriptors=[
                    {"type": "git_worktree", "worktree_id": worktree_id}
                ],
            ),
        )
        worktree_path, branch_name = _target_names(
            session_handle=session_handle,
            source_project_path=normalized_source_path,
            path_suffix=1,
            branch_suffix=1,
        )
        allocation = await self.session_git_worktree_repository.create(
            session,
            SessionGitWorktreeCreate(
                id=worktree_id,
                session_id=session_id,
                initialization_id=initialization.id,
                step_id=create_step.id,
                session_workspace_project_id=None,
                source_project_path=normalized_source_path,
                starting_ref=starting_ref.strip(),
                worktree_path=worktree_path,
                branch_name=branch_name,
                branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                status=SessionGitWorktreeStatus.PENDING,
            ),
        )
        await self.session_initialization_repository.append_event(
            session,
            SessionInitializationEventCreate(
                initialization_id=initialization.id,
                step_id=None,
                session_id=session_id,
                kind=SessionInitializationEventKind.INFO,
                command_argv=None,
                content="Git worktree initialization was scheduled.",
                exit_code=None,
            ),
        )
        await self.session_initialization_repository.mark_pending_for_queue(
            session,
            initialization_id=initialization.id,
        )
        return Success(
            PreparedGitWorktreeInitialization(
                initialization=initialization,
                create_step=create_step,
                allocation=allocation,
            )
        )

    async def run_git_worktree_initialization(
        self,
        *,
        agent_id: str,
        session_id: str,
        on_event_appended: SessionInitializationEventCallback | None = None,
        on_projection_updated: SessionInitializationProjectionCallback | None = None,
    ) -> None:
        """Execute pending Git worktree initialization work for a session."""
        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if not allocations:
                raise RuntimeError("SessionGitWorktree row is missing")
            if len(allocations) != 1:
                raise RuntimeError("SessionGitWorktree row count must be 1")
            allocation = allocations[0]
            initialization = (
                await self.session_initialization_repository.get_by_session_id(
                    session,
                    session_id=session_id,
                )
            )
            if initialization is None:
                raise RuntimeError("SessionInitialization row is missing")
            steps = await self.session_initialization_repository.list_steps(
                session,
                initialization_id=initialization.id,
            )

        if _worktree_allocation_is_complete(allocation, steps):
            return
        claimed = await self._claim_initialization_run(session_id=session_id)
        if not claimed:
            return

        allocation_steps = _worktree_steps_for_allocation(
            allocation=allocation,
            steps=steps,
        )
        runtime = await self._get_runtime(agent_id=agent_id)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            await self._fail_initialization(
                allocation=allocation,
                step=allocation_steps.create_step,
                reason="Runtime runner is not ready.",
                on_projection_updated=on_projection_updated,
            )
            return
        if self.runner_operations is None:
            await self._fail_initialization(
                allocation=allocation,
                step=allocation_steps.create_step,
                reason="Runtime runner operations are unavailable.",
                on_projection_updated=on_projection_updated,
            )
            return

        completed = await self._run_one_git_worktree_initialization(
            agent_id=agent_id,
            runtime=runtime,
            allocation=allocation,
            steps=allocation_steps,
            on_event_appended=on_event_appended,
            on_projection_updated=on_projection_updated,
        )
        if not completed:
            return

        async with self.session_manager() as session:
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=allocation.initialization_id,
                status=SessionInitializationStatus.READY,
                failure_summary=None,
                started_at=None,
                completed_at=datetime.now(UTC),
                failed_at=None,
            )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )

    async def _run_one_git_worktree_initialization(
        self,
        *,
        agent_id: str,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
        steps: _WorktreeInitializationSteps,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> bool:
        """Execute initialization steps for one worktree allocation."""
        create_step = steps.create_step
        register_step = steps.register_step
        catalog_step = steps.catalog_step
        refresh_step = steps.refresh_step

        if create_step.status is SessionInitializationStepStatus.COMPLETED:
            if allocation.status is not SessionGitWorktreeStatus.READY:
                await self._fail_initialization(
                    allocation=allocation,
                    step=create_step,
                    reason="Git worktree allocation is not ready.",
                    on_projection_updated=on_projection_updated,
                )
                return False
            create_result = _CreateWorktreeSuccess(
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                base_commit=allocation.base_commit or "",
            )
        else:
            create_result = await self._run_create_worktree_step(
                runtime=runtime,
                allocation=allocation,
                step=create_step,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            if create_result is None:
                return False

        if register_step.status is not SessionInitializationStepStatus.COMPLETED:
            register_ok = await self._complete_backend_step(
                allocation=allocation,
                step=register_step,
                kind="register_project",
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
                action=lambda db: self._create_and_link_workspace_project(
                    db,
                    allocation=allocation,
                    worktree_path=create_result.worktree_path,
                ),
            )
            if not register_ok:
                return False
        if catalog_step.status is not SessionInitializationStepStatus.COMPLETED:
            catalog_ok = await self._complete_backend_step(
                allocation=allocation,
                step=catalog_step,
                kind="upsert_catalog",
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
                action=lambda db: self.agent_project_catalog_repository.upsert_entry(
                    db,
                    agent_id=agent_id,
                    path=create_result.worktree_path,
                ),
            )
            if not catalog_ok:
                return False
        if refresh_step.status is not SessionInitializationStepStatus.COMPLETED:
            await self._refresh_project_status(
                agent_id=agent_id,
                allocation=allocation,
                step=refresh_step,
                path=create_result.worktree_path,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
        return True

    async def _create_and_link_workspace_project(
        self,
        session: AsyncSession,
        *,
        allocation: SessionGitWorktree,
        worktree_path: str,
    ) -> object:
        """Register the worktree Project and link it to the allocation."""
        project = await self.session_workspace_project_repository.create_project(
            session,
            SessionWorkspaceProjectCreate(
                session_id=allocation.session_id,
                path=worktree_path,
            ),
        )
        await self.session_git_worktree_repository.link_workspace_project(
            session,
            worktree_id=allocation.id,
            session_workspace_project_id=project.id,
        )
        return project

    async def mark_cleanup_pending_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> GitWorktreeCleanupRequest:
        """Request cleanup for session-owned Git worktree allocations."""
        allocations = await self.session_git_worktree_repository.list_by_session_id(
            session,
            session_id=session_id,
        )
        cleanup_targets = [
            allocation
            for allocation in allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if not cleanup_targets:
            return GitWorktreeCleanupRequest(cleanup_requested=False)
        pending_allocations: list[SessionGitWorktree] = []
        for allocation in cleanup_targets:
            pending_allocations.append(
                await self.session_git_worktree_repository.mark_cleanup_pending(
                    session,
                    worktree_id=allocation.id,
                )
            )
        await self.session_initialization_repository.update_initialization_status(
            session,
            initialization_id=pending_allocations[0].initialization_id,
            status=SessionInitializationStatus.CLEANUP_REQUIRED,
            failure_summary="Git worktree cleanup is pending.",
            started_at=None,
            completed_at=None,
            failed_at=None,
        )
        return GitWorktreeCleanupRequest(cleanup_requested=True)

    async def request_initialization_retry(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[
        GitWorktreeInitializationRetryRequest,
        GitWorktreeInitializationRetryRequestError,
    ]:
        """Validate access and reset a failed worktree initialization for retry."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(GitWorktreeInitializationRetrySessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(GitWorktreeInitializationRetryAccessDenied())
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if not allocations:
                return Failure(GitWorktreeInitializationRetryNotFound())
            initialization = (
                await self.session_initialization_repository.get_by_session_id(
                    session,
                    session_id=session_id,
                )
            )
            if initialization is None:
                return Failure(GitWorktreeInitializationRetryNotFound())
            if initialization.status is not SessionInitializationStatus.FAILED:
                return Failure(
                    GitWorktreeInitializationRetryUnavailable(
                        reason="Only failed initialization can be retried."
                    )
                )
            steps = await self.session_initialization_repository.list_steps(
                session,
                initialization_id=initialization.id,
            )
            if not any(
                step.status is SessionInitializationStepStatus.FAILED for step in steps
            ):
                return Failure(
                    GitWorktreeInitializationRetryUnavailable(
                        reason="No failed initialization step is available to retry."
                    )
                )
            await self.session_initialization_repository.reset_for_retry(
                session,
                initialization_id=initialization.id,
            )
            for allocation in allocations:
                if allocation.status is not SessionGitWorktreeStatus.READY:
                    await self.session_git_worktree_repository.mark_pending_for_retry(
                        session,
                        worktree_id=allocation.id,
                    )
            await self.session_initialization_repository.append_event(
                session,
                SessionInitializationEventCreate(
                    initialization_id=initialization.id,
                    step_id=None,
                    session_id=session_id,
                    kind=SessionInitializationEventKind.INFO,
                    command_argv=None,
                    content="Git worktree initialization retry was scheduled.",
                    exit_code=None,
                ),
            )
            return Success(GitWorktreeInitializationRetryRequest(retry_requested=True))

    async def request_manual_cleanup(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[GitWorktreeCleanupRequest, GitWorktreeCleanupRequestError]:
        """Validate access and request manual worktree cleanup retry."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(GitWorktreeCleanupSessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(GitWorktreeCleanupAccessDenied())
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if not allocations:
                return Failure(GitWorktreeCleanupNotFound())
            cleanup_targets = [
                allocation
                for allocation in allocations
                if allocation.status is not SessionGitWorktreeStatus.CLEANED
            ]
            if not cleanup_targets:
                return Success(GitWorktreeCleanupRequest(cleanup_requested=False))
            pending_allocations = []
            for allocation in cleanup_targets:
                pending_allocations.append(
                    await self.session_git_worktree_repository.mark_cleanup_pending(
                        session,
                        worktree_id=allocation.id,
                    )
                )
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=pending_allocations[0].initialization_id,
                status=SessionInitializationStatus.CLEANUP_REQUIRED,
                failure_summary="Git worktree cleanup is pending.",
                started_at=None,
                completed_at=None,
                failed_at=None,
            )
            return Success(GitWorktreeCleanupRequest(cleanup_requested=True))

    async def run_cleanup_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        on_event_appended: SessionInitializationEventCallback | None = None,
        on_projection_updated: SessionInitializationProjectionCallback | None = None,
    ) -> None:
        """Run best-effort cleanup for session-owned Git worktrees."""
        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        cleanup_targets = [
            allocation
            for allocation in allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if not cleanup_targets:
            return
        runtime = await self._get_runtime(agent_id=agent_id)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            await self._mark_cleanup_targets_failed(
                allocations=cleanup_targets,
                reason="Runtime runner is not ready.",
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return
        if self.runner_operations is None:
            await self._mark_cleanup_targets_failed(
                allocations=cleanup_targets,
                reason="Runtime runner operations are unavailable.",
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return

        last_cleaned: SessionGitWorktree | None = None
        for allocation in cleanup_targets:
            cleaned = await self._run_cleanup_for_allocation(
                agent_id=agent_id,
                session_id=session_id,
                runtime=runtime,
                allocation=allocation,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            if cleaned is not None:
                last_cleaned = cleaned

        if last_cleaned is None:
            return
        async with self.session_manager() as session:
            remaining = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if any(
                allocation.status is not SessionGitWorktreeStatus.CLEANED
                for allocation in remaining
            ):
                return
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=last_cleaned.initialization_id,
                status=SessionInitializationStatus.CLEANED,
                failure_summary=None,
                started_at=None,
                completed_at=datetime.now(UTC),
                failed_at=None,
            )
        await self._publish_projection(
            allocation=last_cleaned,
            on_projection_updated=on_projection_updated,
        )

    async def _run_cleanup_for_allocation(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> SessionGitWorktree | None:
        """Run cleanup for one session-owned Git worktree allocation."""
        ownership_error = _cleanup_ownership_error(
            allocation=allocation,
            session_id=session_id,
        )
        if ownership_error is not None:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=ownership_error,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return None
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        try:
            await runner_operations.remove_git_worktree(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                source_project_path=allocation.source_project_path,
                worktree_path=allocation.worktree_path,
                force=True,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
            if allocation.branch_created_by is SessionGitWorktreeBranchCreatedBy.AZENTS:
                await runner_operations.delete_git_branch(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    source_project_path=allocation.source_project_path,
                    branch_name=allocation.branch_name,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=None,
                )
            cleaned_at = datetime.now(UTC)
            async with self.session_manager() as session:
                await self.agent_project_catalog_repository.delete_entry_by_path(
                    session,
                    agent_id=agent_id,
                    path=allocation.worktree_path,
                )
                cleaned = await self.session_git_worktree_repository.mark_cleaned(
                    session,
                    worktree_id=allocation.id,
                    cleanup_summary="Git worktree cleanup completed.",
                    cleaned_at=cleaned_at,
                )
            await self._append_event(
                initialization_id=cleaned.initialization_id,
                step_id=None,
                session_id=cleaned.session_id,
                kind=SessionInitializationEventKind.INFO,
                command_argv=None,
                content="Git worktree cleanup completed.",
                exit_code=0,
                on_event_appended=on_event_appended,
            )
            await self._publish_projection(
                allocation=cleaned,
                on_projection_updated=on_projection_updated,
            )
            return cleaned
        except (
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=str(exc) or type(exc).__name__,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return None

    async def _mark_cleanup_targets_failed(
        self,
        *,
        allocations: list[SessionGitWorktree],
        reason: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Mark multiple cleanup targets failed with the same reason."""
        for allocation in allocations:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=reason,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )

    async def _mark_cleanup_failed(
        self,
        *,
        worktree_id: str,
        reason: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Persist a user-safe cleanup failure summary."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            allocation = await self.session_git_worktree_repository.mark_cleanup_failed(
                session,
                worktree_id=worktree_id,
                cleanup_summary=reason,
                failed_at=failed_at,
            )
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=allocation.initialization_id,
                status=SessionInitializationStatus.CLEANUP_REQUIRED,
                failure_summary=f"Git worktree cleanup failed: {reason}",
                started_at=None,
                completed_at=None,
                failed_at=failed_at,
            )
        await self._append_event(
            initialization_id=allocation.initialization_id,
            step_id=None,
            session_id=allocation.session_id,
            kind=SessionInitializationEventKind.FAILED,
            command_argv=None,
            content=f"Git worktree cleanup failed: {reason}",
            exit_code=None,
            on_event_appended=on_event_appended,
        )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )

    async def _claim_initialization_run(self, *, session_id: str) -> bool:
        """Claim a pending initialization queue run if another worker has not."""
        async with self.session_manager() as session:
            get_initialization_for_update = (
                self.session_initialization_repository.get_by_session_id_for_update
            )
            initialization = await get_initialization_for_update(
                session,
                session_id=session_id,
            )
            if initialization is None:
                raise RuntimeError("SessionInitialization row is missing")
            if initialization.status is SessionInitializationStatus.RUNNING:
                return False
            if initialization.status is not SessionInitializationStatus.PENDING:
                return False
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=initialization.id,
                status=SessionInitializationStatus.RUNNING,
                failure_summary=None,
                started_at=datetime.now(UTC),
                completed_at=None,
                failed_at=None,
            )
        return True

    async def _get_runtime(self, *, agent_id: str) -> AgentRuntime | None:
        """Fetch current AgentRuntime."""
        async with self.session_manager() as session:
            return await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )

    async def _run_create_worktree_step(
        self,
        *,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> _CreateWorktreeSuccess | None:
        """Run create_git_worktree with target collision suffix retries."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        await self._mark_initialization_running(allocation=allocation, step=step)
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )
        path_suffix = 1
        branch_suffix = 1
        current = allocation
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            current = await self._choose_available_target(
                current,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
            )
            command_argv = [
                "git",
                "worktree",
                "add",
                "-b",
                current.branch_name,
                current.worktree_path,
                current.starting_ref,
            ]
            await self._append_event(
                initialization_id=current.initialization_id,
                step_id=step.id,
                session_id=current.session_id,
                kind=SessionInitializationEventKind.COMMAND_STARTED,
                command_argv=command_argv,
                content="Starting Git worktree creation.",
                exit_code=None,
                on_event_appended=on_event_appended,
            )
            try:
                result = await runner_operations.create_git_worktree(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    source_project_path=current.source_project_path,
                    worktree_path=current.worktree_path,
                    branch_name=current.branch_name,
                    starting_ref=current.starting_ref,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=self._text_callback(
                        initialization_id=current.initialization_id,
                        step_id=step.id,
                        session_id=current.session_id,
                        on_event_appended=on_event_appended,
                    ),
                )
            except RuntimeRunnerOperationFailedError as exc:
                collision = _collision_kind(str(exc))
                if collision == "branch":
                    branch_suffix += 1
                    continue
                if collision == "path":
                    path_suffix += 1
                    continue
                await self._append_event(
                    initialization_id=current.initialization_id,
                    step_id=step.id,
                    session_id=current.session_id,
                    kind=SessionInitializationEventKind.FAILED,
                    command_argv=None,
                    content=str(exc),
                    exit_code=None,
                    on_event_appended=on_event_appended,
                )
                await self._fail_initialization(
                    allocation=current,
                    step=step,
                    reason=str(exc),
                    on_projection_updated=on_projection_updated,
                )
                return None
            except (
                RuntimeRunnerOperationUnavailable,
                RuntimeRunnerOperationGenerationError,
            ):
                await self._fail_initialization(
                    allocation=current,
                    step=step,
                    reason="Runtime runner is not ready.",
                    on_projection_updated=on_projection_updated,
                )
                return None
            await self._append_event(
                initialization_id=current.initialization_id,
                step_id=step.id,
                session_id=current.session_id,
                kind=SessionInitializationEventKind.COMMAND_COMPLETED,
                command_argv=None,
                content="Git worktree creation completed.",
                exit_code=0,
                on_event_appended=on_event_appended,
            )
            ready_at = datetime.now(UTC)
            async with self.session_manager() as session:
                ready = await self.session_git_worktree_repository.mark_ready(
                    session,
                    worktree_id=current.id,
                    base_commit=result.base_commit,
                    worktree_path=result.worktree_path,
                    branch_name=result.branch_name,
                    ready_at=ready_at,
                )
                descriptors: list[object] = [
                    {
                        "type": "git_worktree",
                        "worktree_id": ready.id,
                        "worktree_path": ready.worktree_path,
                        "branch_name": ready.branch_name,
                        "base_commit": result.base_commit,
                    }
                ]
                await self.session_initialization_repository.update_step_status(
                    session,
                    step_id=step.id,
                    status=SessionInitializationStepStatus.COMPLETED,
                    failure_reason=None,
                    resource_descriptors=descriptors,
                    started_at=None,
                    completed_at=ready_at,
                    failed_at=None,
                )
            await self._publish_projection(
                allocation=current,
                on_projection_updated=on_projection_updated,
            )
            return _CreateWorktreeSuccess(
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                base_commit=result.base_commit,
            )
        await self._fail_initialization(
            allocation=current,
            step=step,
            reason="Could not allocate a unique Git worktree path and branch.",
            on_projection_updated=on_projection_updated,
        )
        return None

    async def _choose_available_target(
        self,
        allocation: SessionGitWorktree,
        *,
        path_suffix: int,
        branch_suffix: int,
    ) -> SessionGitWorktree:
        """Apply DB-visible target suffixing before a runner attempt."""
        current_path_suffix = path_suffix
        current_branch_suffix = branch_suffix
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            worktree_path, branch_name = _target_names(
                session_handle=_handle_from_worktree_path(allocation.worktree_path),
                source_project_path=allocation.source_project_path,
                path_suffix=current_path_suffix,
                branch_suffix=current_branch_suffix,
            )
            async with self.session_manager() as session:
                exists = await self.session_git_worktree_repository.target_exists(
                    session,
                    worktree_path=worktree_path,
                    branch_name=branch_name,
                    excluding_id=allocation.id,
                )
                if not exists:
                    return await self.session_git_worktree_repository.update_target(
                        session,
                        worktree_id=allocation.id,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                    )
            current_path_suffix += 1
            current_branch_suffix += 1
        return allocation

    async def _mark_initialization_running(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
    ) -> None:
        """Mark initialization and create step running."""
        now = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=allocation.initialization_id,
                status=SessionInitializationStatus.RUNNING,
                failure_summary=None,
                started_at=now,
                completed_at=None,
                failed_at=None,
            )
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.RUNNING,
                failure_reason=None,
                resource_descriptors=None,
                started_at=now,
                completed_at=None,
                failed_at=None,
            )
            await self.session_git_worktree_repository.mark_creating(
                session,
                worktree_id=allocation.id,
            )

    def _text_callback(
        self,
        *,
        initialization_id: str,
        step_id: str,
        session_id: str,
        on_event_appended: SessionInitializationEventCallback | None,
    ) -> RuntimeOperationTextCallback:
        """Create a callback that persists streamed Git stdout/stderr."""

        async def callback(delta: RuntimeOperationTextDelta) -> None:
            kind = (
                SessionInitializationEventKind.STDOUT
                if delta.stream == "stdout"
                else SessionInitializationEventKind.STDERR
            )
            await self._append_event(
                initialization_id=initialization_id,
                step_id=step_id,
                session_id=session_id,
                kind=kind,
                command_argv=None,
                content=delta.text,
                exit_code=None,
                on_event_appended=on_event_appended,
            )

        return callback

    async def _complete_backend_step(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        kind: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
        action: Callable[[AsyncSession], Awaitable[object]],
    ) -> bool:
        """Run a blocking backend step and mark initialization failed on errors."""
        now = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.RUNNING,
                failure_reason=None,
                resource_descriptors=None,
                started_at=now,
                completed_at=None,
                failed_at=None,
            )
        await self._append_event(
            initialization_id=allocation.initialization_id,
            step_id=step.id,
            session_id=allocation.session_id,
            kind=SessionInitializationEventKind.INFO,
            command_argv=None,
            content=f"Starting {kind}.",
            exit_code=None,
            on_event_appended=on_event_appended,
        )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )
        try:
            async with self.session_manager() as session:
                await action(session)
                await self.session_initialization_repository.update_step_status(
                    session,
                    step_id=step.id,
                    status=SessionInitializationStepStatus.COMPLETED,
                    failure_reason=None,
                    resource_descriptors=step.resource_descriptors,
                    started_at=None,
                    completed_at=datetime.now(UTC),
                    failed_at=None,
                )
            await self._publish_projection(
                allocation=allocation,
                on_projection_updated=on_projection_updated,
            )
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            await self._fail_backend_step(
                allocation=allocation,
                step=step,
                reason=reason,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return False
        return True

    async def _fail_backend_step(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        reason: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Persist a blocking backend step failure."""
        failed_at = datetime.now(UTC)
        await self._append_event(
            initialization_id=allocation.initialization_id,
            step_id=step.id,
            session_id=allocation.session_id,
            kind=SessionInitializationEventKind.FAILED,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_event_appended=on_event_appended,
        )
        async with self.session_manager() as session:
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.FAILED,
                failure_reason=reason,
                resource_descriptors=None,
                started_at=None,
                completed_at=None,
                failed_at=failed_at,
            )
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=allocation.initialization_id,
                status=SessionInitializationStatus.FAILED,
                failure_summary=reason,
                started_at=None,
                completed_at=None,
                failed_at=failed_at,
            )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )

    async def _refresh_project_status(
        self,
        *,
        agent_id: str,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        path: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Run non-blocking Project catalog status refresh."""
        now = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.RUNNING,
                failure_reason=None,
                resource_descriptors=None,
                started_at=now,
                completed_at=None,
                failed_at=None,
            )
        try:
            result = await self.agent_project_catalog_service.refresh_project_status(
                agent_id=agent_id,
                path=path,
            )
        except Exception as exc:
            await self._warn_non_blocking_step(
                allocation=allocation,
                step=step,
                reason=str(exc) or type(exc).__name__,
                on_event_appended=on_event_appended,
                on_projection_updated=on_projection_updated,
            )
            return
        match result:
            case Success(entry):
                if entry.status is AgentProjectCatalogStatus.AVAILABLE:
                    async with self.session_manager() as session:
                        await self.session_initialization_repository.update_step_status(
                            session,
                            step_id=step.id,
                            status=SessionInitializationStepStatus.COMPLETED,
                            failure_reason=None,
                            resource_descriptors=step.resource_descriptors,
                            started_at=None,
                            completed_at=datetime.now(UTC),
                            failed_at=None,
                        )
                    await self._publish_projection(
                        allocation=allocation,
                        on_projection_updated=on_projection_updated,
                    )
                    return
                await self._warn_non_blocking_step(
                    allocation=allocation,
                    step=step,
                    reason=entry.status_detail or f"Project status is {entry.status}.",
                    on_event_appended=on_event_appended,
                    on_projection_updated=on_projection_updated,
                )
            case Failure(error):
                match error:
                    case InvalidProjectPath():
                        await self._warn_non_blocking_step(
                            allocation=allocation,
                            step=step,
                            reason=error.reason,
                            on_event_appended=on_event_appended,
                            on_projection_updated=on_projection_updated,
                        )
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def _warn_non_blocking_step(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        reason: str,
        on_event_appended: SessionInitializationEventCallback | None,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Persist a non-blocking warning step failure."""
        now = datetime.now(UTC)
        await self._append_event(
            initialization_id=allocation.initialization_id,
            step_id=step.id,
            session_id=allocation.session_id,
            kind=SessionInitializationEventKind.WARNING,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_event_appended=on_event_appended,
        )
        async with self.session_manager() as session:
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.FAILED,
                failure_reason=reason,
                resource_descriptors=step.resource_descriptors,
                started_at=None,
                completed_at=None,
                failed_at=now,
            )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )

    async def _fail_initialization(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        reason: str,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Mark a blocking initialization failure."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_failed(
                session,
                worktree_id=allocation.id,
                failure_summary=reason,
                failed_at=failed_at,
            )
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.FAILED,
                failure_reason=reason,
                resource_descriptors=None,
                started_at=None,
                completed_at=None,
                failed_at=failed_at,
            )
            await self.session_initialization_repository.update_initialization_status(
                session,
                initialization_id=allocation.initialization_id,
                status=SessionInitializationStatus.FAILED,
                failure_summary=reason,
                started_at=None,
                completed_at=None,
                failed_at=failed_at,
            )
        await self._publish_projection(
            allocation=allocation,
            on_projection_updated=on_projection_updated,
        )

    async def _append_event(
        self,
        *,
        initialization_id: str,
        step_id: str | None,
        session_id: str,
        kind: SessionInitializationEventKind,
        command_argv: list[str] | None,
        content: str | None,
        exit_code: int | None,
        on_event_appended: SessionInitializationEventCallback | None,
    ) -> SessionInitializationEvent:
        """Append one initialization event in a short transaction."""
        async with self.session_manager() as session:
            event = await self.session_initialization_repository.append_event(
                session,
                SessionInitializationEventCreate(
                    initialization_id=initialization_id,
                    step_id=step_id,
                    session_id=session_id,
                    kind=kind,
                    command_argv=command_argv,
                    content=content,
                    exit_code=exit_code,
                ),
            )
        if on_event_appended is not None:
            await on_event_appended(event)
        return event

    async def _publish_projection(
        self,
        *,
        allocation: SessionGitWorktree,
        on_projection_updated: SessionInitializationProjectionCallback | None,
    ) -> None:
        """Publish the compact initialization projection when requested."""
        if on_projection_updated is None:
            return
        async with self.session_manager() as session:
            initialization = (
                await self.session_initialization_repository.get_by_session_id(
                    session,
                    session_id=allocation.session_id,
                )
            )
            if initialization is None:
                raise RuntimeError("SessionInitialization row is missing")
            steps = await self.session_initialization_repository.list_steps(
                session,
                initialization_id=allocation.initialization_id,
            )
        await on_projection_updated(
            SessionInitializationProjection(
                initialization=initialization,
                steps=steps,
            )
        )


@dataclasses.dataclass(frozen=True)
class _WorktreeInitializationSteps:
    """Initialization step group for one worktree allocation."""

    create_step: SessionInitializationStep
    register_step: SessionInitializationStep
    catalog_step: SessionInitializationStep
    refresh_step: SessionInitializationStep


@dataclasses.dataclass(frozen=True)
class _CreateWorktreeSuccess:
    """Successful create_git_worktree result."""

    worktree_path: str
    branch_name: str
    base_commit: str


def _worktree_allocation_is_complete(
    allocation: SessionGitWorktree,
    steps: list[SessionInitializationStep],
) -> bool:
    """Return whether the allocation has finished all registration work."""
    if allocation.status is not SessionGitWorktreeStatus.READY:
        return False
    allocation_steps = _worktree_steps_for_allocation(
        allocation=allocation,
        steps=steps,
    )
    if (
        allocation_steps.create_step.status
        is not SessionInitializationStepStatus.COMPLETED
    ):
        return False
    if (
        allocation_steps.register_step.status
        is not SessionInitializationStepStatus.COMPLETED
    ):
        return False
    if (
        allocation_steps.catalog_step.status
        is not SessionInitializationStepStatus.COMPLETED
    ):
        return False
    return allocation_steps.refresh_step.status in {
        SessionInitializationStepStatus.COMPLETED,
        SessionInitializationStepStatus.FAILED,
    }


def _worktree_steps_for_allocation(
    *,
    allocation: SessionGitWorktree,
    steps: list[SessionInitializationStep],
) -> _WorktreeInitializationSteps:
    """Find the initialization steps that belong to one allocation."""
    return _WorktreeInitializationSteps(
        create_step=_worktree_step_for_allocation(
            allocation=allocation,
            steps=steps,
            step_type=SessionInitializationStepType.CREATE_GIT_WORKTREE,
        ),
        register_step=_worktree_step_for_allocation(
            allocation=allocation,
            steps=steps,
            step_type=SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT,
        ),
        catalog_step=_worktree_step_for_allocation(
            allocation=allocation,
            steps=steps,
            step_type=SessionInitializationStepType.UPSERT_PROJECT_CATALOG,
        ),
        refresh_step=_worktree_step_for_allocation(
            allocation=allocation,
            steps=steps,
            step_type=SessionInitializationStepType.REFRESH_PROJECT_STATUS,
        ),
    )


def _worktree_step_for_allocation(
    *,
    allocation: SessionGitWorktree,
    steps: list[SessionInitializationStep],
    step_type: SessionInitializationStepType,
) -> SessionInitializationStep:
    """Find one typed step for an allocation, with legacy single-worktree fallback."""
    matching = [step for step in steps if step.step_type is step_type]
    for step in matching:
        if _step_describes_worktree(step, allocation.id):
            return step
    if len(matching) == 1:
        return matching[0]
    raise RuntimeError("SessionInitializationStep row is missing")


def _step_describes_worktree(
    step: SessionInitializationStep,
    worktree_id: str,
) -> bool:
    """Return whether a step belongs to the worktree allocation."""
    if step.step_key == _worktree_step_key(step.step_type, worktree_id):
        return True
    for descriptor in step.resource_descriptors:
        if (
            isinstance(descriptor, dict)
            and descriptor.get("type") == "git_worktree"
            and descriptor.get("worktree_id") == worktree_id
        ):
            return True
    return False


def _worktree_step_key(
    step_type: SessionInitializationStepType,
    worktree_id: str,
) -> str:
    """Build a stable per-worktree initialization step key."""
    return f"{step_type.value}:{worktree_id}"


def _git_operation_deadline() -> datetime:
    """Return a deadline for one Git runner operation."""
    return datetime.now(UTC) + timedelta(seconds=_GIT_OPERATION_TIMEOUT_SECONDS)


def _target_names(
    *,
    session_handle: str,
    source_project_path: str,
    path_suffix: int,
    branch_suffix: int,
) -> tuple[str, str]:
    repo_leaf = _repo_leaf(source_project_path)
    path_leaf = repo_leaf if path_suffix == 1 else f"{repo_leaf}-{path_suffix}"
    branch_base = f"azents/{session_handle}"
    branch_name = (
        branch_base if branch_suffix == 1 else f"{branch_base}-{branch_suffix}"
    )
    return (
        (_WORKTREE_ROOT / session_handle / path_leaf).as_posix(),
        branch_name,
    )


def _repo_leaf(source_project_path: str) -> str:
    """Return a filesystem-safe source repository leaf."""
    name = PurePosixPath(source_project_path).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")
    return sanitized or "repo"


def _handle_from_worktree_path(worktree_path: str) -> str:
    """Recover the session handle from an allocated worktree path."""
    relative = PurePosixPath(worktree_path).relative_to(_WORKTREE_ROOT)
    return relative.parts[0]


def _cleanup_ownership_error(
    *,
    allocation: SessionGitWorktree,
    session_id: str,
) -> str | None:
    """Return a cleanup safety error when ownership validation fails."""
    if allocation.session_id != session_id:
        return "Cleanup request does not match the owning session."
    try:
        PurePosixPath(allocation.worktree_path).relative_to(_WORKTREE_ROOT)
    except ValueError:
        return "Recorded worktree path is outside the Azents worktree root."
    if not allocation.branch_name:
        return "Recorded Git branch name is missing."
    if allocation.branch_created_by is not SessionGitWorktreeBranchCreatedBy.AZENTS:
        return "Recorded Git branch is not Azents-created."
    return None


def _collision_kind(message: str) -> Literal["branch", "path"] | None:
    """Infer retryable target collision kind from runner failure text."""
    lowered = message.lower()
    if "branch_exists" in lowered or "branch exists" in lowered:
        return "branch"
    if "worktree_path_exists" in lowered or "worktree path exists" in lowered:
        return "path"
    return None
