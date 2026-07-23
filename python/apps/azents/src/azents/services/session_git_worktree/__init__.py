"""Session Git worktree initialization service."""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentSessionKind,
    EventKind,
    RuntimeRunnerState,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.events.types import Event
from azents.engine.run.types import SHUTDOWN_CANCEL_MESSAGE, USER_STOP_CANCEL_MESSAGE
from azents.engine.tools.deps import get_skill_state_store
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeGitRefEntry,
    RuntimeOperationTextCallback,
    RuntimeOperationTextDelta,
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
)

_WORKTREE_ROOT = PurePosixPath("/workspace/agent/.azents/worktrees")
_GIT_OPERATION_TIMEOUT_SECONDS = 300
_MAX_COLLISION_ATTEMPTS = 20
logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ExistingProjectWorkspaceItem:
    """Existing Project item selected for a new AgentSession."""

    path: str


@dataclasses.dataclass(frozen=True)
class GitWorktreeWorkspaceItem:
    """Git worktree item selected for a new AgentSession."""

    source_project_path: str
    starting_ref: str


NewSessionWorkspaceItem = ExistingProjectWorkspaceItem | GitWorktreeWorkspaceItem


@dataclasses.dataclass(frozen=True)
class WorkspaceItemsWorkspaceMode:
    """Ordered workspace items selected for a new AgentSession."""

    items: list[NewSessionWorkspaceItem]


@dataclasses.dataclass(frozen=True)
class GitWorktreeWorkspaceMode:
    """Legacy single Git worktree mode selected for a new AgentSession."""

    source_project_path: str
    starting_ref: str


@dataclasses.dataclass(frozen=True)
class ExplicitProjectsWorkspaceMode:
    """Legacy existing explicit Project path mode selected for a new AgentSession."""

    project_paths: list[str]


NewSessionWorkspaceMode = (
    WorkspaceItemsWorkspaceMode
    | ExplicitProjectsWorkspaceMode
    | GitWorktreeWorkspaceMode
)


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


ActionExecutionProjectionCallback = Callable[
    [ActionExecutionProjection], Awaitable[None]
]
ActionExecutionHistoryEventCallback = Callable[[Event], Awaitable[None]]
ActionExecutionRemovedCallback = Callable[[str], Awaitable[None]]


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
class GitWorktreeCleanupSubagentReadOnly:
    """Child subagent sessions do not accept direct cleanup requests."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupNotFound:
    """No session Git worktree allocation exists."""


GitWorktreeCleanupRequestError = (
    GitWorktreeCleanupSessionNotFound
    | GitWorktreeCleanupAccessDenied
    | GitWorktreeCleanupSubagentReadOnly
    | GitWorktreeCleanupNotFound
)


@dataclasses.dataclass(frozen=True)
class GitWorktreeActionExecutionResult:
    """Result of executing one create_git_worktree TurnAction."""

    completed: bool
    context_invalidated: bool


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
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
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
                owner_session_id=None,
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

    async def run_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one worker-owned create_git_worktree TurnAction."""
        try:
            return await self._execute_git_worktree_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                action=action,
                owner_generation=owner_generation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                )
            )
            raise

    async def _execute_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Run the operation after the current worker admitted it."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )

        try:
            normalized_source_path = normalize_session_workspace_path(
                action.source_project_path
            )
        except ValueError as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason=str(exc),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if agent_session is None or agent_session.agent_id != agent_id:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason="Session not found.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        async with self.session_manager() as session:
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
            allocation = await self._ensure_action_worktree_allocation(
                session,
                execution=execution,
                session_id=session_id,
                session_handle=agent_session.handle,
                source_project_path=normalized_source_path,
                starting_ref=action.starting_ref.strip(),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="create_git_worktree",
            command_argv=None,
            content="Starting Git worktree action.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )

        runtime = await self._get_runtime(agent_id=agent_id)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason="Runtime runner is not ready.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        if self.runner_operations is None:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason="Runtime runner operations are unavailable.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )

        if allocation.status in {
            SessionGitWorktreeStatus.FAILED,
            SessionGitWorktreeStatus.CLEANUP_PENDING,
            SessionGitWorktreeStatus.CLEANED,
            SessionGitWorktreeStatus.CLEANUP_FAILED,
        }:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=allocation.failure_summary or "Git worktree allocation failed.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        if allocation.status is SessionGitWorktreeStatus.READY:
            if allocation.base_commit is None:
                raise RuntimeError("Ready worktree allocation has no base commit")
            create_result = _CreateWorktreeSuccess(
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                base_commit=allocation.base_commit,
            )
        else:
            create_result = await self._run_action_create_worktree_step(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            if create_result is None:
                return GitWorktreeActionExecutionResult(
                    completed=True,
                    context_invalidated=False,
                )
        if not await self._run_action_register_project_step(
            agent_id=agent_id,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        if not await self._run_action_catalog_step(
            agent_id=agent_id,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        await self._run_action_refresh_project_status_step(
            agent_id=agent_id,
            execution=execution,
            path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
        )
        await self._sync_skill_projection_for_project_change(
            agent_id=agent_id,
            session_id=session_id,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.COMPLETED,
            step_key=None,
            command_argv=None,
            content="Git worktree action completed.",
            exit_code=0,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            on_history_event_appended=on_history_event_appended,
        )
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=True,
        )

    async def _ensure_action_worktree_allocation(
        self,
        session: AsyncSession,
        *,
        execution: ActionExecution,
        session_id: str,
        session_handle: str,
        source_project_path: str,
        starting_ref: str,
    ) -> SessionGitWorktree:
        """Create or fetch the worktree allocation for an action execution."""
        existing = (
            await self.session_git_worktree_repository.get_by_action_execution_id(
                session,
                action_execution_id=execution.id,
            )
        )
        if existing is not None:
            return existing
        worktree_path, branch_name = _target_names(
            session_handle=session_handle,
            source_project_path=source_project_path,
            path_suffix=1,
            branch_suffix=1,
        )
        return await self.session_git_worktree_repository.create(
            session,
            SessionGitWorktreeCreate(
                id=uuid7().hex,
                session_id=session_id,
                action_execution_id=execution.id,
                session_workspace_project_id=None,
                source_project_path=source_project_path,
                starting_ref=starting_ref,
                worktree_path=worktree_path,
                branch_name=branch_name,
                branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                status=SessionGitWorktreeStatus.PENDING,
            ),
        )

    async def _run_action_create_worktree_step(
        self,
        *,
        runtime: AgentRuntime,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> _CreateWorktreeSuccess | None:
        """Run create_git_worktree for an action execution."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
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
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="create_git_worktree",
                command_argv=command_argv,
                content="Starting Git worktree creation.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                await self.session_git_worktree_repository.mark_creating(
                    session,
                    worktree_id=current.id,
                )
            try:
                result = await runner_operations.create_git_worktree(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    owner_session_id=current.session_id,
                    source_project_path=current.source_project_path,
                    worktree_path=current.worktree_path,
                    branch_name=current.branch_name,
                    starting_ref=current.starting_ref,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=self._action_text_callback(
                        execution=execution,
                        on_projection_updated=on_projection_updated,
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
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=current,
                    reason=str(exc),
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            except (
                RuntimeRunnerOperationUnavailable,
                RuntimeRunnerOperationGenerationError,
            ):
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=current,
                    reason="Runtime runner is not ready.",
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_COMPLETED,
                step_key="create_git_worktree",
                command_argv=None,
                content="Git worktree creation completed.",
                exit_code=0,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                await self.session_git_worktree_repository.mark_ready(
                    session,
                    worktree_id=current.id,
                    base_commit=result.base_commit,
                    worktree_path=result.worktree_path,
                    branch_name=result.branch_name,
                    ready_at=datetime.now(UTC),
                )
            return _CreateWorktreeSuccess(
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                base_commit=result.base_commit,
            )
        await self._mark_action_execution_failed(
            execution=execution,
            allocation=current,
            reason="Could not allocate a unique Git worktree path and branch.",
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        return None

    async def _run_action_register_project_step(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Register the action-created worktree as a session Project."""
        del agent_id
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="register_project",
            command_argv=None,
            content="Starting register_project.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            async with self.session_manager() as session:
                await self._create_and_link_workspace_project(
                    session,
                    allocation=allocation,
                    worktree_path=worktree_path,
                )
        except Exception as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=str(exc) or type(exc).__name__,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        return True

    async def _run_action_catalog_step(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Upsert catalog state for the action-created Project."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="upsert_catalog",
            command_argv=None,
            content="Starting upsert_catalog.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            async with self.session_manager() as session:
                await self.agent_project_catalog_repository.upsert_entry(
                    session,
                    agent_id=agent_id,
                    path=worktree_path,
                )
        except Exception as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=str(exc) or type(exc).__name__,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        return True

    async def _run_action_refresh_project_status_step(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> None:
        """Refresh catalog status and record a warning on non-blocking failure."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="refresh_project_status",
            command_argv=None,
            content="Starting refresh_project_status.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            result = await self.agent_project_catalog_service.refresh_project_status(
                agent_id=agent_id,
                path=path,
            )
        except Exception as exc:
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.WARNING,
                step_key="refresh_project_status",
                command_argv=None,
                content=str(exc) or type(exc).__name__,
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            return
        match result:
            case Success(entry):
                if entry.status is AgentProjectCatalogStatus.AVAILABLE:
                    return
                await self._append_action_execution_event(
                    execution=execution,
                    kind=ActionExecutionEventKind.WARNING,
                    step_key="refresh_project_status",
                    command_argv=None,
                    content=entry.status_detail or f"Project status is {entry.status}.",
                    exit_code=None,
                    on_projection_updated=on_projection_updated,
                )
            case Failure(error):
                match error:
                    case InvalidProjectPath():
                        await self._append_action_execution_event(
                            execution=execution,
                            kind=ActionExecutionEventKind.WARNING,
                            step_key="refresh_project_status",
                            command_argv=None,
                            content=error.reason,
                            exit_code=None,
                            on_projection_updated=on_projection_updated,
                        )
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    def _action_text_callback(
        self,
        *,
        execution: ActionExecution,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> RuntimeOperationTextCallback:
        """Create a callback that persists streamed action stdout/stderr."""

        async def callback(delta: RuntimeOperationTextDelta) -> None:
            kind = (
                ActionExecutionEventKind.STDOUT
                if delta.stream == "stdout"
                else ActionExecutionEventKind.STDERR
            )
            await self._append_action_execution_event(
                execution=execution,
                kind=kind,
                step_key="create_git_worktree",
                command_argv=None,
                content=delta.text,
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )

        return callback

    async def _append_action_execution_event(
        self,
        *,
        execution: ActionExecution,
        kind: ActionExecutionEventKind,
        step_key: str | None,
        command_argv: list[str] | None,
        content: str | None,
        exit_code: int | None,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecutionEvent:
        """Append one action execution event in a short transaction."""
        async with self.session_manager() as session:
            event = await self.action_execution_repository.append_event(
                session,
                ActionExecutionEventCreate(
                    action_execution_id=execution.id,
                    session_id=execution.session_id,
                    kind=kind,
                    step_key=step_key,
                    command_argv=command_argv,
                    content=content,
                    exit_code=exit_code,
                ),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        return event

    async def _publish_action_execution_projection(
        self,
        *,
        execution: ActionExecution,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecutionProjection:
        """Publish the current action execution projection when requested."""
        async with self.session_manager() as session:
            repository = self.action_execution_repository
            projection = await repository.get_projection_by_input_buffer_id(
                session,
                input_buffer_id=execution.input_buffer_id,
            )
            if projection is None:
                raise RuntimeError("ActionExecution projection is missing")
        if on_projection_updated is not None:
            await on_projection_updated(projection)
        return projection

    async def _commit_action_execution_history_event(
        self,
        *,
        execution: ActionExecution,
        status: ActionExecutionStatus,
        failure_summary: str | None,
        cancellation_summary: str | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        allocation: SessionGitWorktree | None = None,
    ) -> Event:
        """Atomically append one terminal snapshot and delete its live row."""
        if status not in {
            ActionExecutionStatus.COMPLETED,
            ActionExecutionStatus.FAILED,
            ActionExecutionStatus.CANCELLED,
        }:
            raise ValueError("ActionExecution terminal status is required")
        external_id = f"action_execution_result:{execution.id}"
        terminal_at = datetime.now(UTC)
        async with self.session_manager() as session:
            projection = await self.action_execution_repository.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=execution.session_id,
            )
            if projection is None:
                existing = await self.event_transcript_repository.get_by_external_id(
                    session,
                    execution.session_id,
                    external_id,
                )
                if existing is None:
                    raise RuntimeError("ActionExecution terminal state is missing")
                event = existing
            else:
                terminal_execution = projection.execution.model_copy(
                    update={
                        "status": status,
                        "failure_summary": failure_summary,
                        "cancellation_summary": cancellation_summary,
                        "completed_at": (
                            terminal_at
                            if status is ActionExecutionStatus.COMPLETED
                            else None
                        ),
                        "failed_at": (
                            terminal_at
                            if status is ActionExecutionStatus.FAILED
                            else None
                        ),
                        "cancelled_at": (
                            terminal_at
                            if status is ActionExecutionStatus.CANCELLED
                            else None
                        ),
                        "updated_at": terminal_at,
                    }
                )
                terminal_projection = projection.model_copy(
                    update={"execution": terminal_execution}
                )
                if (
                    allocation is not None
                    and status is not ActionExecutionStatus.COMPLETED
                ):
                    summary = failure_summary or cancellation_summary
                    if summary is None:
                        raise RuntimeError("Terminal allocation summary is missing")
                    await self.session_git_worktree_repository.mark_failed(
                        session,
                        worktree_id=allocation.id,
                        failure_summary=summary,
                        failed_at=terminal_at,
                    )
                event = await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=execution.session_id,
                        kind=EventKind.ACTION_EXECUTION_RESULT,
                        payload={
                            "action_execution": terminal_projection.model_dump(
                                mode="json", exclude_none=True
                            )
                        },
                        external_id=external_id,
                    ),
                )
                await self.action_execution_repository.delete_by_id(
                    session,
                    action_execution_id=execution.id,
                )
        if on_history_event_appended is not None:
            await on_history_event_appended(event)
        return event

    async def cancel_action_execution(
        self,
        *,
        execution: ActionExecution,
        reason: str,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> Event:
        """Cancel one active operation without re-executing its side effect."""
        async with self.session_manager() as session:
            allocation = (
                await self.session_git_worktree_repository.get_by_action_execution_id(
                    session,
                    action_execution_id=execution.id,
                )
            )
        return await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.CANCELLED,
            failure_summary=None,
            cancellation_summary=reason,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )

    async def cancel_live_action_executions(
        self,
        *,
        session_id: str,
        reason: str,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        on_action_execution_removed: ActionExecutionRemovedCallback | None,
    ) -> list[Event]:
        """Cancel leftover live executions before a processing boundary starts."""
        async with self.session_manager() as session:
            executions = await self.action_execution_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        events: list[Event] = []
        for execution in executions:
            if execution.status in {
                ActionExecutionStatus.PENDING,
                ActionExecutionStatus.RUNNING,
            }:
                event = await self.cancel_action_execution(
                    execution=execution,
                    reason=reason,
                    on_history_event_appended=on_history_event_appended,
                )
            else:
                event = await self._commit_action_execution_history_event(
                    execution=execution,
                    status=execution.status,
                    failure_summary=execution.failure_summary,
                    cancellation_summary=execution.cancellation_summary,
                    on_history_event_appended=on_history_event_appended,
                )
            events.append(event)
            if on_action_execution_removed is not None:
                await on_action_execution_removed(execution.id)
        return events

    async def _mark_action_execution_failed(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree | None,
        reason: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Persist one final failure log and hand it to durable history."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key=None,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )

    async def _sync_skill_projection_for_project_change(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Refresh latest Skill projection after adding a Project source."""
        if self.skill_store is None or self.runner_operations is None:
            return
        projection_service = SkillProjectionService(
            store=self.skill_store,
            session_manager=self.session_manager,
            runner_operations=adapt_runtime_runner_operations(self.runner_operations),
            runtime_repository=self.agent_runtime_repository,
            project_repository=self.session_workspace_project_repository,
        )
        await projection_service.sync_latest(
            agent_id=agent_id,
            session_id=session_id,
            reason="project_change",
        )

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
        for allocation in cleanup_targets:
            await self.session_git_worktree_repository.mark_cleanup_pending(
                session,
                worktree_id=allocation.id,
            )
        return GitWorktreeCleanupRequest(cleanup_requested=True)

    async def list_action_execution_projections(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecutionProjection]:
        """List live action execution projections for a session."""
        return await self.action_execution_repository.list_projections_by_session_id(
            session,
            session_id=session_id,
        )

    async def request_manual_cleanup(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        session_workspace_project_id: str | None,
    ) -> Result[GitWorktreeCleanupRequest, GitWorktreeCleanupRequestError]:
        """Validate access and request manual worktree cleanup retry."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(GitWorktreeCleanupSessionNotFound())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(GitWorktreeCleanupSubagentReadOnly())
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
            if session_workspace_project_id is not None:
                allocations = [
                    allocation
                    for allocation in allocations
                    if allocation.session_workspace_project_id
                    == session_workspace_project_id
                ]
                if not allocations:
                    return Failure(GitWorktreeCleanupNotFound())
            cleanup_targets = [
                allocation
                for allocation in allocations
                if allocation.status is not SessionGitWorktreeStatus.CLEANED
            ]
            if not cleanup_targets:
                return Success(GitWorktreeCleanupRequest(cleanup_requested=False))
            for allocation in cleanup_targets:
                await self.session_git_worktree_repository.mark_cleanup_pending(
                    session,
                    worktree_id=allocation.id,
                )
            return Success(GitWorktreeCleanupRequest(cleanup_requested=True))

    async def run_cleanup_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        session_workspace_project_id: str | None,
    ) -> None:
        """Run best-effort cleanup for session-owned Git worktrees."""
        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        if session_workspace_project_id is not None:
            allocations = [
                allocation
                for allocation in allocations
                if allocation.session_workspace_project_id
                == session_workspace_project_id
            ]
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
            )
            return
        if self.runner_operations is None:
            await self._mark_cleanup_targets_failed(
                allocations=cleanup_targets,
                reason="Runtime runner operations are unavailable.",
            )
            return

        last_cleaned: SessionGitWorktree | None = None
        for allocation in cleanup_targets:
            cleaned = await self._run_cleanup_for_allocation(
                agent_id=agent_id,
                session_id=session_id,
                runtime=runtime,
                allocation=allocation,
                force=False,
            )
            if cleaned is not None:
                last_cleaned = cleaned

        if last_cleaned is None:
            return

    async def run_archive_cleanup_for_root_tree(
        self,
        *,
        agent_id: str,
        root_session_id: str,
        subtree_session_ids: Sequence[str],
    ) -> int:
        """Attempt forced cleanup for one newly archived root SessionAgent tree."""
        allowed_session_ids = set(subtree_session_ids)
        if root_session_id not in allowed_session_ids:
            raise ValueError("Root session must belong to its archive subtree")

        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=root_session_id,
            )
            eligible_allocations: list[SessionGitWorktree] = []
            for allocation in allocations:
                creator_session_id = allocation.created_by_agent_session_id
                if creator_session_id not in allowed_session_ids:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="allocation_outside_root_tree",
                    )
                    await self.session_git_worktree_repository.mark_cleanup_failed(
                        session,
                        worktree_id=allocation.id,
                        cleanup_summary=(
                            "Git worktree allocation belongs outside the archive "
                            "subtree."
                        ),
                        failed_at=datetime.now(UTC),
                    )
                    continue
                eligible_allocations.append(allocation)
                if allocation.status is not SessionGitWorktreeStatus.CLEANED:
                    await self.session_git_worktree_repository.mark_cleanup_pending(
                        session,
                        worktree_id=allocation.id,
                    )

        cleanup_targets = [
            allocation
            for allocation in eligible_allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if cleanup_targets:
            runtime = await self._get_runtime(agent_id=agent_id)
            if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
                for allocation in cleanup_targets:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="runtime_unavailable",
                    )
                await self._mark_cleanup_targets_failed(
                    allocations=cleanup_targets,
                    reason="Runtime runner is not ready.",
                )
                return len(allocations)
            if self.runner_operations is None:
                for allocation in cleanup_targets:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="runner_operations_unavailable",
                    )
                await self._mark_cleanup_targets_failed(
                    allocations=cleanup_targets,
                    reason="Runtime runner operations are unavailable.",
                )
                return len(allocations)

            for allocation in cleanup_targets:
                creator_session_id = allocation.created_by_agent_session_id
                if creator_session_id is None:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="creator_session_missing",
                    )
                    await self._mark_cleanup_failed(
                        worktree_id=allocation.id,
                        reason=(
                            "Git worktree allocation creator AgentSession is missing."
                        ),
                    )
                    continue
                ownership_error = _cleanup_ownership_error(
                    allocation=allocation,
                    session_id=creator_session_id,
                )
                if ownership_error is not None:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="invalid_allocation_ownership",
                    )
                    await self._mark_cleanup_failed(
                        worktree_id=allocation.id,
                        reason=ownership_error,
                    )
                    continue
                try:
                    await self._run_cleanup_for_allocation(
                        agent_id=agent_id,
                        session_id=creator_session_id,
                        runtime=runtime,
                        allocation=allocation,
                        force=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Archived Session Git worktree cleanup failed unexpectedly",
                        extra={
                            "agent_id": agent_id,
                            "root_session_id": root_session_id,
                            "session_id": creator_session_id,
                            "worktree_id": allocation.id,
                            "reason_code": "unexpected_cleanup_failure",
                        },
                    )
                    try:
                        await self._mark_cleanup_failed(
                            worktree_id=allocation.id,
                            reason=("Git worktree cleanup failed: unexpected_error."),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Archived Session Git worktree cleanup failure state "
                            "could not be recorded",
                            extra={
                                "agent_id": agent_id,
                                "root_session_id": root_session_id,
                                "session_id": creator_session_id,
                                "worktree_id": allocation.id,
                            },
                        )
        return len(allocations)

    async def _run_cleanup_for_allocation(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
        force: bool,
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
            )
            return None
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        try:
            removal = await runner_operations.remove_git_worktree(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                source_project_path=allocation.source_project_path,
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                force=force,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
            if allocation.branch_created_by is SessionGitWorktreeBranchCreatedBy.AZENTS:
                await runner_operations.delete_git_branch(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    owner_session_id=session_id,
                    source_project_path=allocation.source_project_path,
                    branch_name=allocation.branch_name,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=None,
                )
            await self._cleanup_empty_session_worktree_parent(
                runtime=runtime,
                allocation=allocation,
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
                    cleanup_summary=_cleanup_terminal_summary(
                        removal_outcome=removal.outcome,
                        force=force,
                    ),
                    cleaned_at=cleaned_at,
                )
                if allocation.session_workspace_project_id is not None:
                    await self.session_workspace_project_repository.delete_project(
                        session,
                        allocation.session_workspace_project_id,
                        session_id=allocation.session_id,
                    )
            return cleaned
        except (
            RuntimeRunnerOperationCanceledError,
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            logger.warning(
                "Git worktree cleanup Runner operation failed",
                exc_info=True,
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "worktree_id": allocation.id,
                    "runner_error_code": (
                        exc.code
                        if isinstance(exc, RuntimeRunnerOperationFailedError)
                        else type(exc).__name__
                    ),
                },
            )
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=_cleanup_operation_failure_summary(exc),
            )
            return None

    async def _cleanup_empty_session_worktree_parent(
        self,
        *,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
    ) -> None:
        """Delete the session worktree directory after its last child is removed."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        parent_path = _session_worktree_parent_path(allocation.worktree_path)
        if parent_path is None:
            return
        try:
            listed = await runner_operations.list_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=allocation.session_id,
                path=parent_path,
                recursive=False,
                deadline_at=_git_operation_deadline(),
            )
            if listed.entries:
                return
            await runner_operations.delete_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=allocation.session_id,
                path=parent_path,
                recursive=False,
                deadline_at=_git_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationCanceledError,
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            logger.info(
                "Skipped empty session worktree directory cleanup",
                extra={
                    "session_id": allocation.session_id,
                    "worktree_id": allocation.id,
                },
            )

    async def _mark_cleanup_targets_failed(
        self,
        *,
        allocations: list[SessionGitWorktree],
        reason: str,
    ) -> None:
        """Mark multiple cleanup targets failed with the same reason."""
        for allocation in allocations:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=reason,
            )

    async def _mark_cleanup_failed(
        self,
        *,
        worktree_id: str,
        reason: str,
    ) -> None:
        """Persist a user-safe cleanup failure summary."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_cleanup_failed(
                session,
                worktree_id=worktree_id,
                cleanup_summary=reason,
                failed_at=failed_at,
            )

    async def _get_runtime(self, *, agent_id: str) -> AgentRuntime | None:
        """Fetch current AgentRuntime."""
        async with self.session_manager() as session:
            return await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )

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


def _action_cancellation_reason(exc: asyncio.CancelledError) -> str:
    """Return the durable operation cancellation reason."""
    reason = str(exc.args[0]) if exc.args else ""
    if reason == USER_STOP_CANCEL_MESSAGE:
        return "Operation cancelled by user stop."
    if reason == SHUTDOWN_CANCEL_MESSAGE:
        return "Operation cancelled after the worker shutdown wait expired."
    return "Operation cancelled during Session ownership handover."


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


def _session_worktree_parent_path(worktree_path: str) -> str | None:
    """Return the session-scoped worktree parent directory for an allocated path."""
    try:
        relative = PurePosixPath(worktree_path).relative_to(_WORKTREE_ROOT)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    return (_WORKTREE_ROOT / relative.parts[0]).as_posix()


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


def _log_archive_cleanup_failure(
    *,
    agent_id: str,
    root_session_id: str,
    allocation: SessionGitWorktree,
    reason_code: str,
) -> None:
    """Log one bounded expected failure from archive-owned worktree cleanup."""
    logger.warning(
        "Archived Session Git worktree cleanup did not complete",
        extra={
            "agent_id": agent_id,
            "root_session_id": root_session_id,
            "session_id": allocation.created_by_agent_session_id,
            "worktree_id": allocation.id,
            "reason_code": reason_code,
        },
    )


def _cleanup_terminal_summary(
    *,
    removal_outcome: Literal["removed", "already_absent"],
    force: bool,
) -> str:
    """Return a stable durable cleanup terminal classification."""
    if removal_outcome == "already_absent":
        return "Git worktree cleanup completed: confirmed_absent."
    if force:
        return "Git worktree cleanup completed: removed_force."
    return "Git worktree cleanup completed: removed."


def _cleanup_operation_failure_summary(
    error: (
        RuntimeRunnerOperationCanceledError
        | RuntimeRunnerOperationFailedError
        | RuntimeRunnerOperationUnavailable
        | RuntimeRunnerOperationGenerationError
    ),
) -> str:
    """Return a bounded cleanup failure without Runner path diagnostics."""
    if isinstance(error, RuntimeRunnerOperationFailedError):
        if error.code == "worktree_ownership_ambiguous":
            return "Git worktree cleanup blocked: ambiguous_target_ownership."
        return "Git worktree cleanup failed: runner_operation_failed."
    if isinstance(error, RuntimeRunnerOperationCanceledError):
        return "Git worktree cleanup failed: runner_operation_failed."
    return "Git worktree cleanup failed: runtime_unavailable."


def _collision_kind(message: str) -> Literal["branch", "path"] | None:
    """Infer retryable target collision kind from runner failure text."""
    lowered = message.lower()
    if "branch_exists" in lowered or "branch exists" in lowered:
        return "branch"
    if "worktree_path_exists" in lowered or "worktree path exists" in lowered:
        return "path"
    return None
