"""Session Git worktree initialization service."""

import dataclasses
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, assert_never

from azcommon.result import Failure, Result, Success
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
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_initialization.data import (
    SessionInitialization,
    SessionInitializationCreate,
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
        create_step = await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=1,
                step_key=SessionInitializationStepType.CREATE_GIT_WORKTREE.value,
                step_type=SessionInitializationStepType.CREATE_GIT_WORKTREE,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[],
                resource_descriptors=[],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=2,
                step_key=SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT.value,
                step_type=SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[create_step.step_key],
                resource_descriptors=[],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=3,
                step_key=SessionInitializationStepType.UPSERT_PROJECT_CATALOG.value,
                step_type=SessionInitializationStepType.UPSERT_PROJECT_CATALOG,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[
                    SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT.value
                ],
                resource_descriptors=[],
            ),
        )
        await self.session_initialization_repository.create_step(
            session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=4,
                step_key=SessionInitializationStepType.REFRESH_PROJECT_STATUS.value,
                step_type=SessionInitializationStepType.REFRESH_PROJECT_STATUS,
                blocking=False,
                retryable=True,
                depends_on_step_keys=[
                    SessionInitializationStepType.UPSERT_PROJECT_CATALOG.value
                ],
                resource_descriptors=[],
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
                session_id=session_id,
                initialization_id=initialization.id,
                step_id=create_step.id,
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
        await self.session_initialization_repository.update_initialization_status(
            session,
            initialization_id=initialization.id,
            status=SessionInitializationStatus.PENDING,
            failure_summary=None,
            started_at=None,
            completed_at=None,
            failed_at=None,
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
    ) -> None:
        """Execute the prepared Git worktree initialization."""
        async with self.session_manager() as session:
            allocation = await self.session_git_worktree_repository.get_by_session_id(
                session,
                session_id=session_id,
            )
            if allocation is None:
                raise RuntimeError("SessionGitWorktree row is missing")
            steps = await self.session_initialization_repository.list_steps(
                session,
                initialization_id=allocation.initialization_id,
            )
        step_by_type = {step.step_type: step for step in steps}
        create_step = step_by_type[SessionInitializationStepType.CREATE_GIT_WORKTREE]
        register_step = step_by_type[
            SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT
        ]
        catalog_step = step_by_type[
            SessionInitializationStepType.UPSERT_PROJECT_CATALOG
        ]
        refresh_step = step_by_type[
            SessionInitializationStepType.REFRESH_PROJECT_STATUS
        ]

        runtime = await self._get_runtime(agent_id=agent_id)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            await self._fail_initialization(
                allocation=allocation,
                step=create_step,
                reason="Runtime runner is not ready.",
            )
            return
        if self.runner_operations is None:
            await self._fail_initialization(
                allocation=allocation,
                step=create_step,
                reason="Runtime runner operations are unavailable.",
            )
            return

        create_result = await self._run_create_worktree_step(
            runtime=runtime,
            allocation=allocation,
            step=create_step,
        )
        if create_result is None:
            return
        register_ok = await self._complete_backend_step(
            allocation=allocation,
            step=register_step,
            kind="register_project",
            action=lambda db: self.session_workspace_project_repository.create_project(
                db,
                SessionWorkspaceProjectCreate(
                    session_id=allocation.session_id,
                    path=create_result.worktree_path,
                ),
            ),
        )
        if not register_ok:
            return
        catalog_ok = await self._complete_backend_step(
            allocation=allocation,
            step=catalog_step,
            kind="upsert_catalog",
            action=lambda db: self.agent_project_catalog_repository.upsert_entry(
                db,
                agent_id=agent_id,
                path=create_result.worktree_path,
            ),
        )
        if not catalog_ok:
            return
        await self._refresh_project_status(
            agent_id=agent_id,
            allocation=allocation,
            step=refresh_step,
            path=create_result.worktree_path,
        )
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
    ) -> _CreateWorktreeSuccess | None:
        """Run create_git_worktree with target collision suffix retries."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        await self._mark_initialization_running(allocation=allocation, step=step)
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
                )
                await self._fail_initialization(
                    allocation=current,
                    step=step,
                    reason=str(exc),
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
            return _CreateWorktreeSuccess(
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                base_commit=result.base_commit,
            )
        await self._fail_initialization(
            allocation=current,
            step=step,
            reason="Could not allocate a unique Git worktree path and branch.",
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
            )

        return callback

    async def _complete_backend_step(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        kind: str,
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
            await self.session_initialization_repository.append_event(
                session,
                SessionInitializationEventCreate(
                    initialization_id=allocation.initialization_id,
                    step_id=step.id,
                    session_id=allocation.session_id,
                    kind=SessionInitializationEventKind.INFO,
                    command_argv=None,
                    content=f"Starting {kind}.",
                    exit_code=None,
                ),
            )
        try:
            async with self.session_manager() as session:
                await action(session)
                await self.session_initialization_repository.update_step_status(
                    session,
                    step_id=step.id,
                    status=SessionInitializationStepStatus.COMPLETED,
                    failure_reason=None,
                    resource_descriptors=[],
                    started_at=None,
                    completed_at=datetime.now(UTC),
                    failed_at=None,
                )
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            await self._fail_backend_step(
                allocation=allocation,
                step=step,
                reason=reason,
            )
            return False
        return True

    async def _fail_backend_step(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        reason: str,
    ) -> None:
        """Persist a blocking backend step failure."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_initialization_repository.append_event(
                session,
                SessionInitializationEventCreate(
                    initialization_id=allocation.initialization_id,
                    step_id=step.id,
                    session_id=allocation.session_id,
                    kind=SessionInitializationEventKind.FAILED,
                    command_argv=None,
                    content=reason,
                    exit_code=None,
                ),
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

    async def _refresh_project_status(
        self,
        *,
        agent_id: str,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        path: str,
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
                            resource_descriptors=[],
                            started_at=None,
                            completed_at=datetime.now(UTC),
                            failed_at=None,
                        )
                    return
                await self._warn_non_blocking_step(
                    allocation=allocation,
                    step=step,
                    reason=entry.status_detail or f"Project status is {entry.status}.",
                )
            case Failure(error):
                match error:
                    case InvalidProjectPath():
                        await self._warn_non_blocking_step(
                            allocation=allocation,
                            step=step,
                            reason=error.reason,
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
    ) -> None:
        """Persist a non-blocking warning step failure."""
        now = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_initialization_repository.append_event(
                session,
                SessionInitializationEventCreate(
                    initialization_id=allocation.initialization_id,
                    step_id=step.id,
                    session_id=allocation.session_id,
                    kind=SessionInitializationEventKind.WARNING,
                    command_argv=None,
                    content=reason,
                    exit_code=None,
                ),
            )
            await self.session_initialization_repository.update_step_status(
                session,
                step_id=step.id,
                status=SessionInitializationStepStatus.FAILED,
                failure_reason=reason,
                resource_descriptors=[],
                started_at=None,
                completed_at=None,
                failed_at=now,
            )

    async def _fail_initialization(
        self,
        *,
        allocation: SessionGitWorktree,
        step: SessionInitializationStep,
        reason: str,
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
    ) -> None:
        """Append one initialization event in a short transaction."""
        async with self.session_manager() as session:
            await self.session_initialization_repository.append_event(
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


@dataclasses.dataclass(frozen=True)
class _CreateWorktreeSuccess:
    """Successful create_git_worktree result."""

    worktree_path: str
    branch_name: str
    base_commit: str


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


def _collision_kind(message: str) -> Literal["branch", "path"] | None:
    """Infer retryable target collision kind from runner failure text."""
    lowered = message.lower()
    if "branch_exists" in lowered or "branch exists" in lowered:
        return "branch"
    if "worktree_path_exists" in lowered or "worktree path exists" in lowered:
        return "path"
    return None
