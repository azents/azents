"""Session Git worktree initialization service."""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, TypeVar, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentSessionKind,
    AgentSessionStatus,
    EventKind,
    RuntimeRunnerState,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.events.types import Event
from azents.engine.run.types import (
    OWNERSHIP_LOST_CANCEL_MESSAGE,
    SHUTDOWN_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
)
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
from azents.utils.task_recovery import (
    compensate_then_reraise,
    run_bounded_cancellation_safe,
)

_WORKTREE_ROOT = PurePosixPath("/workspace/agent/.azents/worktrees")
_GIT_OPERATION_TIMEOUT_SECONDS = 300
_MAX_COLLISION_ATTEMPTS = 20
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


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


@dataclasses.dataclass(frozen=True)
class _CreatedWorktreeCommitResult:
    """Post-runner authority check for a physically created worktree."""

    accepted: bool
    failure_execution: ActionExecution | None
    failure_reason: str | None
    cleanup_mode: Literal["none", "allocation", "direct"]


@dataclasses.dataclass(frozen=True)
class _TerminalHistoryCommitResult:
    """Terminal history event plus whether the requested outcome won."""

    event: Event
    requested_status_committed: bool


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
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
    ) -> bool:
        """Register a Project only while action and allocation authority match."""
        current_allocation = await self._lock_ready_action_allocation(
            session,
            execution=execution,
            allocation=allocation,
        )
        if current_allocation is None:
            return False
        linked_project_id = current_allocation.session_workspace_project_id
        if linked_project_id is not None:
            linked_project = (
                await self.session_workspace_project_repository.get_project_by_id(
                    session,
                    linked_project_id,
                )
            )
            if (
                linked_project is None
                or linked_project.session_id != allocation.session_id
                or linked_project.path != worktree_path
            ):
                raise RuntimeError(
                    "Git worktree allocation points to a mismatched Project"
                )
            return True
        project = await self.session_workspace_project_repository.create_project(
            session,
            SessionWorkspaceProjectCreate(
                session_id=allocation.session_id,
                path=worktree_path,
            ),
        )
        linked = (
            await self.session_git_worktree_repository.link_workspace_project_if_ready(
                session,
                worktree_id=allocation.id,
                session_workspace_project_id=project.id,
            )
        )
        if linked is None:
            raise RuntimeError("Locked Git worktree allocation lost ready status")
        return True

    async def _commit_project_registration_once(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
    ) -> bool:
        """Commit or recognize one exact Project registration."""
        async with self.session_manager() as session:
            return await self._create_and_link_workspace_project(
                session,
                execution=execution,
                allocation=allocation,
                worktree_path=worktree_path,
            )

    async def _commit_catalog_registration_once(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
    ) -> bool:
        """Commit one idempotent catalog registration under action authority."""
        async with self.session_manager() as session:
            current = await self._lock_ready_action_allocation(
                session,
                execution=execution,
                allocation=allocation,
            )
            accepted = (
                current is not None and current.session_workspace_project_id is not None
            )
            if accepted:
                await self.agent_project_catalog_repository.upsert_entry(
                    session,
                    agent_id=agent_id,
                    path=worktree_path,
                )
            return accepted

    async def _run_reconciled_action_db_operation(
        self,
        operation: Callable[[], Awaitable[_T]],
        *,
        execution: ActionExecution,
        step: str,
    ) -> _T:
        """Recover an action DB operation whose commit response is ambiguous."""
        try:
            return await operation()
        except asyncio.CancelledError as commit_error:
            try:
                await run_bounded_cancellation_safe(operation)
            except asyncio.CancelledError:
                raise
            except Exception as reconciliation_error:
                raise commit_error from reconciliation_error
            raise commit_error
        except SQLAlchemyError as commit_error:
            try:
                reconciled = await run_bounded_cancellation_safe(operation)
            except asyncio.CancelledError:
                raise
            except Exception as reconciliation_error:
                raise commit_error from reconciliation_error
            logger.warning(
                "Recovered action DB step after an ambiguous commit response",
                extra={
                    "session_id": execution.session_id,
                    "action_execution_id": execution.id,
                    "step": step,
                },
            )
            return reconciled

    async def _lock_ready_action_allocation(
        self,
        session: AsyncSession,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
    ) -> SessionGitWorktree | None:
        """Lock Session, ActionExecution, then allocation and validate authority."""
        return await self._lock_action_allocation(
            session,
            execution=execution,
            allocation=allocation,
            expected_status=SessionGitWorktreeStatus.READY,
        )

    async def _lock_action_allocation(
        self,
        session: AsyncSession,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        expected_status: SessionGitWorktreeStatus,
    ) -> SessionGitWorktree | None:
        """Lock Session, action, and allocation for one expected active state."""
        agent_session = await self.agent_session_repository.lock_by_id(
            session,
            execution.session_id,
        )
        projection = await self.action_execution_repository.lock_projection_by_id(
            session,
            action_execution_id=execution.id,
            session_id=execution.session_id,
        )
        current_allocation = await self.session_git_worktree_repository.lock_by_id(
            session,
            worktree_id=allocation.id,
        )
        current_execution = None if projection is None else projection.execution
        if (
            agent_session is None
            or agent_session.id != allocation.session_id
            or agent_session.status is not AgentSessionStatus.ACTIVE
            or agent_session.owner_generation != execution.owner_generation
            or current_execution is None
            or current_execution.owner_generation != execution.owner_generation
            or current_execution.status is not ActionExecutionStatus.RUNNING
            or current_allocation is None
            or current_allocation.session_id != allocation.session_id
            or current_allocation.action_execution_id != execution.id
            or current_allocation.status is not expected_status
        ):
            return None
        return current_allocation

    async def _ready_action_allocation_is_current(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        require_project_link: bool,
    ) -> bool:
        """Check active post-create authority in a short database scope."""
        async with self.session_manager() as session:
            current = await self._lock_ready_action_allocation(
                session,
                execution=execution,
                allocation=allocation,
            )
            return current is not None and (
                not require_project_link
                or current.session_workspace_project_id is not None
            )

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
            if OWNERSHIP_LOST_CANCEL_MESSAGE in exc.args:
                raise
            cancellation_reason = _action_cancellation_reason(exc)

            async def finalize_cancellation() -> None:
                await run_bounded_cancellation_safe(
                    lambda: self.cancel_action_execution(
                        execution=execution,
                        reason=cancellation_reason,
                        on_history_event_appended=on_history_event_appended,
                    )
                )

            await compensate_then_reraise(
                finalize_cancellation,
                primary_error=exc,
            )

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
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            projection = await self.action_execution_repository.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=session_id,
            )
            current_execution = None if projection is None else projection.execution
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
                or agent_session.owner_generation != owner_generation
                or current_execution is None
                or current_execution.owner_generation != owner_generation
                or current_execution.status is not ActionExecutionStatus.PENDING
            ):
                raise asyncio.CancelledError(OWNERSHIP_LOST_CANCEL_MESSAGE)
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
        if not await self._run_action_refresh_project_status_step(
            agent_id=agent_id,
            execution=execution,
            allocation=allocation,
            path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
            )
        if not await self._run_action_skill_projection_step(
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
        committed = await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )
        if not committed.requested_status_committed:
            await self._reconcile_cleanup_winner_projection(
                agent_id=agent_id,
                session_id=session_id,
                worktree_id=allocation.id,
                worktree_path=create_result.worktree_path,
            )
            # Terminalization removed the live action that made the first cleanup
            # attempt defer physical deletion.
            await self.run_cleanup_for_session(
                agent_id=agent_id,
                session_id=session_id,
                session_workspace_project_id=None,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
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
            selected = await self._choose_available_target(
                current,
                execution=execution,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
            )
            if selected is None:
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=None,
                    reason=("Git worktree allocation changed before Runner creation."),
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            current = selected
            command_argv = [
                "git",
                "worktree",
                "add",
                "-b",
                current.branch_name,
                current.worktree_path,
                current.starting_ref,
            ]
            command_started = await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="create_git_worktree",
                command_argv=command_argv,
                content="Starting Git worktree creation.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            if command_started is None:
                return None
            async with self.session_manager() as session:
                locked = await self._lock_action_allocation(
                    session,
                    execution=execution,
                    allocation=current,
                    expected_status=SessionGitWorktreeStatus.PENDING,
                )
                if locked is None:
                    creating = None
                else:
                    creating = await (
                        self.session_git_worktree_repository.mark_creating_if_pending(
                            session,
                            worktree_id=locked.id,
                        )
                    )
            if creating is None:
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=None,
                    reason=("Git worktree allocation changed before Runner creation."),
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            current = creating
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
                if collision is not None:
                    async with self.session_manager() as session:
                        repository = self.session_git_worktree_repository
                        locked = await self._lock_action_allocation(
                            session,
                            execution=execution,
                            allocation=current,
                            expected_status=SessionGitWorktreeStatus.CREATING,
                        )
                        if locked is None:
                            pending = None
                        else:
                            pending = await (
                                repository.mark_pending_after_collision_if_creating(
                                    session,
                                    worktree_id=locked.id,
                                )
                            )
                    if pending is None:
                        await self._mark_action_execution_failed(
                            execution=execution,
                            allocation=None,
                            reason=(
                                "Git worktree allocation changed during a collision "
                                "retry."
                            ),
                            on_projection_updated=on_projection_updated,
                            on_history_event_appended=on_history_event_appended,
                        )
                        return None
                    current = pending
                    if collision == "branch":
                        branch_suffix += 1
                    else:
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
            commit_result = await self._commit_created_worktree_if_current(
                runtime=runtime,
                execution=execution,
                allocation=current,
                base_commit=result.base_commit,
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
            )
            if not commit_result.accepted:
                if commit_result.failure_execution is not None:
                    await self._mark_action_execution_failed(
                        execution=commit_result.failure_execution,
                        allocation=None,
                        reason=(
                            commit_result.failure_reason
                            or "Git worktree creation authority changed."
                        ),
                        on_projection_updated=on_projection_updated,
                        on_history_event_appended=on_history_event_appended,
                    )
                if commit_result.cleanup_mode == "allocation":
                    await self.run_cleanup_for_session(
                        agent_id=runtime.agent_id,
                        session_id=current.session_id,
                        session_workspace_project_id=None,
                    )
                elif commit_result.cleanup_mode == "direct":
                    await self._cleanup_rejected_created_worktree(
                        runtime=runtime,
                        allocation=current,
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

    async def _commit_created_worktree_if_current(
        self,
        *,
        runtime: AgentRuntime,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        base_commit: str,
        worktree_path: str,
        branch_name: str,
    ) -> _CreatedWorktreeCommitResult:
        """Commit or reconcile one physical worktree result by exact identity."""

        async def commit() -> _CreatedWorktreeCommitResult:
            return await self._commit_created_worktree_once(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                base_commit=base_commit,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )

        try:
            return await commit()
        except asyncio.CancelledError as commit_error:
            try:
                await run_bounded_cancellation_safe(commit)
            except asyncio.CancelledError:
                raise
            except Exception as reconciliation_error:
                raise commit_error from reconciliation_error
            raise commit_error
        except SQLAlchemyError as commit_error:
            try:
                reconciled = await run_bounded_cancellation_safe(commit)
            except asyncio.CancelledError:
                raise
            except Exception as reconciliation_error:
                raise commit_error from reconciliation_error
            logger.warning(
                "Recovered Git worktree state after an ambiguous DB commit response",
                extra={
                    "worktree_id": allocation.id,
                    "action_execution_id": execution.id,
                },
            )
            return reconciled

    async def _commit_created_worktree_once(
        self,
        *,
        runtime: AgentRuntime,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        base_commit: str,
        worktree_path: str,
        branch_name: str,
    ) -> _CreatedWorktreeCommitResult:
        """Accept or fence a result in one fixed-order DB transaction."""
        async with self.session_manager() as session:
            current_runtime = await self.agent_runtime_repository.lock_by_agent_id(
                session,
                runtime.agent_id,
            )
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                execution.session_id,
            )
            projection = await self.action_execution_repository.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=execution.session_id,
            )
            current_allocation = await self.session_git_worktree_repository.lock_by_id(
                session,
                worktree_id=allocation.id,
            )
            current_execution = None if projection is None else projection.execution
            runtime_matches = (
                current_runtime is not None
                and current_runtime.id == runtime.id
                and current_runtime.runner_generation == runtime.runner_generation
                and current_runtime.runner_state is RuntimeRunnerState.READY
            )
            session_matches = (
                agent_session is not None
                and agent_session.id == allocation.session_id
                and agent_session.agent_id == runtime.agent_id
                and agent_session.status is AgentSessionStatus.ACTIVE
                and agent_session.owner_generation == execution.owner_generation
            )
            execution_matches = (
                current_execution is not None
                and current_execution.owner_generation == execution.owner_generation
                and current_execution.status is ActionExecutionStatus.RUNNING
            )
            result_matches_attempt = (
                worktree_path == allocation.worktree_path
                and branch_name == allocation.branch_name
            )
            current_target_matches_attempt = (
                current_allocation is not None
                and current_allocation.worktree_path == allocation.worktree_path
                and current_allocation.branch_name == allocation.branch_name
            )
            durable_ready_matches_result = (
                current_allocation is not None
                and current_allocation.session_id == allocation.session_id
                and current_allocation.action_execution_id == execution.id
                and current_allocation.status is SessionGitWorktreeStatus.READY
                and current_allocation.base_commit == base_commit
                and current_allocation.worktree_path == worktree_path
                and current_allocation.branch_name == branch_name
            )
            if durable_ready_matches_result:
                if runtime_matches and session_matches and execution_matches:
                    return _CreatedWorktreeCommitResult(
                        accepted=True,
                        failure_execution=None,
                        failure_reason=None,
                        cleanup_mode="none",
                    )
                return _CreatedWorktreeCommitResult(
                    accepted=False,
                    failure_execution=(
                        current_execution if execution_matches else None
                    ),
                    failure_reason=(
                        "Git worktree result was already committed before action "
                        "authority changed."
                        if execution_matches
                        else None
                    ),
                    cleanup_mode="none",
                )
            allocation_matches = (
                current_allocation is not None
                and current_allocation.session_id == allocation.session_id
                and current_allocation.action_execution_id == execution.id
                and current_allocation.status is SessionGitWorktreeStatus.CREATING
                and current_target_matches_attempt
            )
            if (
                runtime_matches
                and session_matches
                and execution_matches
                and allocation_matches
                and result_matches_attempt
            ):
                marked_ready = (
                    await self.session_git_worktree_repository.mark_ready_if_creating(
                        session,
                        worktree_id=allocation.id,
                        base_commit=base_commit,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                        ready_at=datetime.now(UTC),
                    )
                )
                if marked_ready is None:
                    raise RuntimeError(
                        "Locked Git worktree allocation lost creating status"
                    )
                return _CreatedWorktreeCommitResult(
                    accepted=True,
                    failure_execution=None,
                    failure_reason=None,
                    cleanup_mode="none",
                )

            cleanup_mode: Literal["none", "allocation", "direct"]
            if current_allocation is None:
                cleanup_mode = "direct"
            elif current_allocation.status is SessionGitWorktreeStatus.READY:
                # A durable winner may share the attempted target. Never compensate it.
                cleanup_mode = "none"
            elif current_target_matches_attempt:
                repository = self.session_git_worktree_repository
                if current_allocation.status is SessionGitWorktreeStatus.CLEANED:
                    reopened = await repository.reopen_cleaned_after_late_create(
                        session,
                        worktree_id=allocation.id,
                    )
                    if reopened is None:
                        raise RuntimeError(
                            "Locked cleaned allocation could not be reopened"
                        )
                else:
                    await repository.mark_cleanup_pending(
                        session,
                        worktree_id=allocation.id,
                    )
                cleanup_mode = "allocation"
            else:
                cleanup_mode = "direct"
            if execution_matches:
                if not result_matches_attempt:
                    failure_reason = (
                        "Runtime runner returned a different Git worktree target. "
                        "Cleanup has been requested only for the allocated target."
                    )
                elif not runtime_matches:
                    failure_reason = (
                        "Runtime runner changed while Git worktree creation was "
                        "in progress. Cleanup has been requested."
                    )
                elif not session_matches:
                    failure_reason = (
                        "Session ownership changed while Git worktree creation was "
                        "in progress. Cleanup has been requested."
                    )
                else:
                    failure_reason = (
                        "Git worktree allocation changed while creation was in "
                        "progress. Cleanup has been requested."
                    )
                return _CreatedWorktreeCommitResult(
                    accepted=False,
                    failure_execution=current_execution,
                    failure_reason=failure_reason,
                    cleanup_mode=cleanup_mode,
                )
            return _CreatedWorktreeCommitResult(
                accepted=False,
                failure_execution=None,
                failure_reason=None,
                cleanup_mode=cleanup_mode,
            )

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
            registered = await self._run_reconciled_action_db_operation(
                lambda: self._commit_project_registration_once(
                    execution=execution,
                    allocation=allocation,
                    worktree_path=worktree_path,
                ),
                execution=execution,
                step="register_project",
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
        if not registered:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason=("Git worktree allocation changed before Project registration."),
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
            accepted = await self._run_reconciled_action_db_operation(
                lambda: self._commit_catalog_registration_once(
                    agent_id=agent_id,
                    execution=execution,
                    allocation=allocation,
                    worktree_path=worktree_path,
                ),
                execution=execution,
                step="upsert_catalog",
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
        if not accepted:
            await self._fail_action_for_lost_post_create_authority(
                agent_id=agent_id,
                execution=execution,
                allocation=allocation,
                worktree_path=worktree_path,
                reason="Git worktree cleanup won before catalog registration.",
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
        allocation: SessionGitWorktree,
        path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
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
        if not await self._ready_action_allocation_is_current(
            execution=execution,
            allocation=allocation,
            require_project_link=True,
        ):
            await self._fail_action_for_lost_post_create_authority(
                agent_id=agent_id,
                execution=execution,
                allocation=allocation,
                worktree_path=path,
                reason="Git worktree cleanup won before catalog refresh.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        try:
            result = await self.agent_project_catalog_service.refresh_project_status(
                agent_id=agent_id,
                path=path,
            )
        except Exception as exc:
            if not await self._ready_action_allocation_is_current(
                execution=execution,
                allocation=allocation,
                require_project_link=True,
            ):
                await self._fail_action_for_lost_post_create_authority(
                    agent_id=agent_id,
                    execution=execution,
                    allocation=allocation,
                    worktree_path=path,
                    reason="Git worktree cleanup won during catalog refresh.",
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return False
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.WARNING,
                step_key="refresh_project_status",
                command_argv=None,
                content=str(exc) or type(exc).__name__,
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            return True
        if not await self._ready_action_allocation_is_current(
            execution=execution,
            allocation=allocation,
            require_project_link=True,
        ):
            await self._fail_action_for_lost_post_create_authority(
                agent_id=agent_id,
                execution=execution,
                allocation=allocation,
                worktree_path=path,
                reason="Git worktree cleanup won during catalog refresh.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        match result:
            case Success(entry):
                if entry.status is AgentProjectCatalogStatus.AVAILABLE:
                    return True
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
        return True

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
    ) -> ActionExecutionEvent | None:
        """Append one recoverable progress event under current action authority."""
        create = ActionExecutionEventCreate(
            id=uuid7().hex,
            action_execution_id=execution.id,
            session_id=execution.session_id,
            kind=kind,
            step_key=step_key,
            command_argv=command_argv,
            content=content,
            exit_code=exit_code,
        )
        event = await self._run_reconciled_action_db_operation(
            lambda: self._commit_action_execution_event_once(
                execution=execution,
                create=create,
            ),
            execution=execution,
            step=f"append_event:{step_key or kind.value}",
        )
        if event is None:
            return None
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        return event

    async def _commit_action_execution_event_once(
        self,
        *,
        execution: ActionExecution,
        create: ActionExecutionEventCreate,
    ) -> ActionExecutionEvent | None:
        """Commit or recognize one exact progress event if authority remains."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                execution.session_id,
            )
            projection = await self.action_execution_repository.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=execution.session_id,
            )
            current_execution = None if projection is None else projection.execution
            if (
                agent_session is None
                or agent_session.status is not AgentSessionStatus.ACTIVE
                or agent_session.owner_generation != execution.owner_generation
                or current_execution is None
                or current_execution.owner_generation != execution.owner_generation
                or current_execution.status is not ActionExecutionStatus.RUNNING
            ):
                return None
            return await self.action_execution_repository.append_event(
                session,
                create,
            )

    async def _publish_action_execution_projection(
        self,
        *,
        execution: ActionExecution,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecutionProjection | None:
        """Publish the current action projection when it still exists."""
        async with self.session_manager() as session:
            repository = self.action_execution_repository
            projection = await repository.get_projection_by_input_buffer_id(
                session,
                input_buffer_id=execution.input_buffer_id,
            )
            if projection is None:
                return None
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
        allocation: SessionGitWorktree | None,
    ) -> _TerminalHistoryCommitResult:
        """Atomically append one terminal snapshot and delete its live row."""
        if status not in {
            ActionExecutionStatus.COMPLETED,
            ActionExecutionStatus.FAILED,
            ActionExecutionStatus.CANCELLED,
        }:
            raise ValueError("ActionExecution terminal status is required")
        external_id = f"action_execution_result:{execution.id}"
        terminal_at = datetime.now(UTC)
        requested_status_committed = False
        async with self.session_manager() as session:
            await self.agent_session_repository.lock_by_id(
                session,
                execution.session_id,
            )
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
                effective_status = status
                effective_failure_summary = failure_summary
                effective_cancellation_summary = cancellation_summary
                locked_allocation: SessionGitWorktree | None = None
                if allocation is not None:
                    locked_allocation = (
                        await self.session_git_worktree_repository.lock_by_id(
                            session,
                            worktree_id=allocation.id,
                        )
                    )
                if status is ActionExecutionStatus.COMPLETED and allocation is not None:
                    completion_authority_matches = (
                        projection.execution.owner_generation
                        == execution.owner_generation
                        and projection.execution.status is ActionExecutionStatus.RUNNING
                        and locked_allocation is not None
                        and locked_allocation.session_id == allocation.session_id
                        and locked_allocation.action_execution_id == execution.id
                        and locked_allocation.status is SessionGitWorktreeStatus.READY
                        and locked_allocation.session_workspace_project_id is not None
                    )
                    if completion_authority_matches:
                        requested_status_committed = True
                        progress_kind = ActionExecutionEventKind.COMPLETED
                        progress_content = "Git worktree action completed."
                        progress_exit_code = 0
                    else:
                        effective_status = ActionExecutionStatus.FAILED
                        effective_failure_summary = (
                            "Git worktree cleanup or action authority changed before "
                            "completion."
                        )
                        effective_cancellation_summary = None
                        progress_kind = ActionExecutionEventKind.FAILED
                        progress_content = effective_failure_summary
                        progress_exit_code = None
                        if locked_allocation is not None:
                            repository = self.session_git_worktree_repository
                            await repository.mark_failed_if_active(
                                session,
                                worktree_id=locked_allocation.id,
                                failure_summary=effective_failure_summary,
                                failed_at=terminal_at,
                            )
                    progress_event = (
                        await self.action_execution_repository.append_event(
                            session,
                            ActionExecutionEventCreate(
                                action_execution_id=execution.id,
                                session_id=execution.session_id,
                                kind=progress_kind,
                                step_key=None,
                                command_argv=None,
                                content=progress_content,
                                exit_code=progress_exit_code,
                            ),
                        )
                    )
                    projection = projection.model_copy(
                        update={"events": [*projection.events, progress_event]}
                    )
                else:
                    requested_status_committed = True
                terminal_execution = projection.execution.model_copy(
                    update={
                        "status": effective_status,
                        "failure_summary": effective_failure_summary,
                        "cancellation_summary": effective_cancellation_summary,
                        "completed_at": (
                            terminal_at
                            if effective_status is ActionExecutionStatus.COMPLETED
                            else None
                        ),
                        "failed_at": (
                            terminal_at
                            if effective_status is ActionExecutionStatus.FAILED
                            else None
                        ),
                        "cancelled_at": (
                            terminal_at
                            if effective_status is ActionExecutionStatus.CANCELLED
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
                    and effective_status is not ActionExecutionStatus.COMPLETED
                    and status is not ActionExecutionStatus.COMPLETED
                ):
                    summary = (
                        effective_failure_summary or effective_cancellation_summary
                    )
                    if summary is None:
                        raise RuntimeError("Terminal allocation summary is missing")
                    if locked_allocation is not None:
                        await (
                            self.session_git_worktree_repository.mark_failed_if_active(
                                session,
                                worktree_id=locked_allocation.id,
                                failure_summary=summary,
                                failed_at=terminal_at,
                            )
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
        return _TerminalHistoryCommitResult(
            event=event,
            requested_status_committed=requested_status_committed,
        )

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
        committed = await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.CANCELLED,
            failure_summary=None,
            cancellation_summary=reason,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )
        return committed.event

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
                committed = await self._commit_action_execution_history_event(
                    execution=execution,
                    status=execution.status,
                    failure_summary=execution.failure_summary,
                    cancellation_summary=execution.cancellation_summary,
                    allocation=None,
                    on_history_event_appended=on_history_event_appended,
                )
                event = committed.event
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

    async def _fail_action_for_lost_post_create_authority(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        reason: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Reconcile cleanup-owned projections and fail the still-live action."""
        await self._reconcile_cleanup_winner_projection(
            agent_id=agent_id,
            session_id=execution.session_id,
            worktree_id=allocation.id,
            worktree_path=worktree_path,
        )
        await self._mark_action_execution_failed(
            execution=execution,
            allocation=None,
            reason=reason,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        # Cleanup may have yielded to the live action before this failure was
        # committed. Retry now that the action fence can admit physical deletion.
        await self.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=execution.session_id,
            session_workspace_project_id=None,
        )

    async def _reconcile_cleanup_winner_projection(
        self,
        *,
        agent_id: str,
        session_id: str,
        worktree_id: str,
        worktree_path: str,
    ) -> None:
        """Remove projections only when cleanup owns the current allocation."""
        async with self.session_manager() as session:
            current = await self.session_git_worktree_repository.lock_by_id(
                session,
                worktree_id=worktree_id,
            )
            if (
                current is None
                or current.status is not SessionGitWorktreeStatus.CLEANED
            ):
                return
            await self.agent_project_catalog_repository.delete_entry_by_path(
                session,
                agent_id=agent_id,
                path=worktree_path,
            )
            project_id = current.session_workspace_project_id
        if self.skill_store is None or project_id is None:
            return
        try:
            await self.skill_store.invalidate_project(
                agent_id,
                session_id,
                project_id=project_id,
                project_path=worktree_path,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to invalidate Skill projection after worktree cleanup",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "worktree_id": worktree_id,
                },
            )

    async def _run_action_skill_projection_step(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Fence Skill projection synchronization before and after external I/O."""
        if not await self._ready_action_allocation_is_current(
            execution=execution,
            allocation=allocation,
            require_project_link=True,
        ):
            await self._fail_action_for_lost_post_create_authority(
                agent_id=agent_id,
                execution=execution,
                allocation=allocation,
                worktree_path=worktree_path,
                reason="Git worktree cleanup won before Skill projection refresh.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        await self._sync_skill_projection_for_project_change(
            agent_id=agent_id,
            session_id=execution.session_id,
        )
        if await self._ready_action_allocation_is_current(
            execution=execution,
            allocation=allocation,
            require_project_link=True,
        ):
            return True
        await self._fail_action_for_lost_post_create_authority(
            agent_id=agent_id,
            execution=execution,
            allocation=allocation,
            worktree_path=worktree_path,
            reason="Git worktree cleanup won during Skill projection refresh.",
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        return False

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
            agent_session_repository=self.agent_session_repository,
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

    async def cleanup_is_complete_for_sessions(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str],
    ) -> bool:
        """Check deletion authority after callers lock the AgentSession rows."""
        for session_id in session_ids:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if any(
                allocation.status is not SessionGitWorktreeStatus.CLEANED
                for allocation in allocations
            ):
                return False
            executions = await self.action_execution_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if any(
                execution.status
                in {ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING}
                for execution in executions
            ):
                return False
        return True

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
            if allocation.status is SessionGitWorktreeStatus.CLEANUP_PENDING
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
            )
            if cleaned is not None:
                last_cleaned = cleaned

        if last_cleaned is None:
            return

    async def _run_cleanup_for_allocation(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
    ) -> SessionGitWorktree | None:
        """Run cleanup for one session-owned Git worktree allocation."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return None
            projection: ActionExecutionProjection | None = None
            if allocation.action_execution_id is not None:
                projection = (
                    await self.action_execution_repository.lock_projection_by_id(
                        session,
                        action_execution_id=allocation.action_execution_id,
                        session_id=session_id,
                    )
                )
            current_allocation = await self.session_git_worktree_repository.lock_by_id(
                session,
                worktree_id=allocation.id,
            )
            if (
                current_allocation is None
                or current_allocation.session_id != session_id
                or current_allocation.status
                is not SessionGitWorktreeStatus.CLEANUP_PENDING
            ):
                return None
            current_execution = None if projection is None else projection.execution
            if current_execution is not None and current_execution.status in {
                ActionExecutionStatus.PENDING,
                ActionExecutionStatus.RUNNING,
            }:
                return None
            allocation = current_allocation
        ownership_error = _cleanup_ownership_error(
            allocation=allocation,
            session_id=session_id,
        )
        if ownership_error is not None:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=ownership_error,
                expected_updated_at=allocation.updated_at,
            )
            return None
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        try:
            await self._remove_worktree_resources(
                runtime=runtime,
                allocation=allocation,
            )
            cleaned_at = datetime.now(UTC)
            async with self.session_manager() as session:
                agent_session = await self.agent_session_repository.lock_by_id(
                    session,
                    allocation.session_id,
                )
                if agent_session is None:
                    raise ValueError("AgentSession not found")
                current_allocation = (
                    await self.session_git_worktree_repository.lock_by_id(
                        session,
                        worktree_id=allocation.id,
                    )
                )
                if current_allocation is None:
                    return None
                if current_allocation.status is SessionGitWorktreeStatus.CLEANED:
                    cleaned = current_allocation
                else:
                    if current_allocation.status not in {
                        SessionGitWorktreeStatus.CLEANUP_PENDING,
                        SessionGitWorktreeStatus.CLEANUP_FAILED,
                    }:
                        return None
                    if current_allocation.updated_at != allocation.updated_at:
                        return None
                    await self.agent_project_catalog_repository.delete_entry_by_path(
                        session,
                        agent_id=agent_id,
                        path=current_allocation.worktree_path,
                    )
                    repository = self.session_git_worktree_repository
                    cleaned = await repository.mark_cleaned_if_cleanup_owned(
                        session,
                        worktree_id=current_allocation.id,
                        cleanup_summary="Git worktree cleanup completed.",
                        cleaned_at=cleaned_at,
                        expected_updated_at=allocation.updated_at,
                    )
                    if cleaned is None:
                        return None
                    if current_allocation.session_workspace_project_id is not None:
                        await self.session_workspace_project_repository.delete_project(
                            session,
                            current_allocation.session_workspace_project_id,
                            session_id=current_allocation.session_id,
                        )
            await self._reconcile_cleanup_winner_projection(
                agent_id=agent_id,
                session_id=session_id,
                worktree_id=cleaned.id,
                worktree_path=cleaned.worktree_path,
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
                expected_updated_at=allocation.updated_at,
            )
            return None

    async def _cleanup_rejected_created_worktree(
        self,
        *,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
    ) -> None:
        """Best-effort cleanup of this attempt without touching a durable winner."""
        try:
            await self._remove_worktree_resources(
                runtime=runtime,
                allocation=allocation,
            )
        except (
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            logger.exception(
                "Failed to clean up a rejected Git worktree result",
                extra={
                    "worktree_id": allocation.id,
                    "session_id": allocation.session_id,
                    "worktree_path": allocation.worktree_path,
                    "branch_name": allocation.branch_name,
                },
            )

    async def _remove_worktree_resources(
        self,
        *,
        runtime: AgentRuntime,
        allocation: SessionGitWorktree,
    ) -> None:
        """Remove only the exact path and branch owned by one allocation attempt."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        await runner_operations.remove_git_worktree(
            runtime_id=runtime.id,
            runner_generation=runtime.runner_generation,
            owner_session_id=allocation.session_id,
            source_project_path=allocation.source_project_path,
            worktree_path=allocation.worktree_path,
            force=False,
            deadline_at=_git_operation_deadline(),
            text_output_callback=None,
        )
        if allocation.branch_created_by is SessionGitWorktreeBranchCreatedBy.AZENTS:
            await runner_operations.delete_git_branch(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=allocation.session_id,
                source_project_path=allocation.source_project_path,
                branch_name=allocation.branch_name,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
        await self._cleanup_empty_session_worktree_parent(
            runtime=runtime,
            allocation=allocation,
        )

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
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            logger.info(
                "Skipped empty session worktree directory cleanup",
                extra={
                    "session_id": allocation.session_id,
                    "worktree_id": allocation.id,
                    "parent_path": parent_path,
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
                expected_updated_at=allocation.updated_at,
            )

    async def _mark_cleanup_failed(
        self,
        *,
        worktree_id: str,
        reason: str,
        expected_updated_at: datetime | None = None,
    ) -> None:
        """Persist a user-safe cleanup failure summary."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_cleanup_failed_if_pending(
                session,
                worktree_id=worktree_id,
                cleanup_summary=reason,
                failed_at=failed_at,
                expected_updated_at=expected_updated_at,
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
        execution: ActionExecution,
        path_suffix: int,
        branch_suffix: int,
    ) -> SessionGitWorktree | None:
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
                locked = await self._lock_action_allocation(
                    session,
                    execution=execution,
                    allocation=allocation,
                    expected_status=SessionGitWorktreeStatus.PENDING,
                )
                if locked is None:
                    return None
                exists = await self.session_git_worktree_repository.target_exists(
                    session,
                    worktree_path=worktree_path,
                    branch_name=branch_name,
                    excluding_id=allocation.id,
                )
                if not exists:
                    repository = self.session_git_worktree_repository
                    return await repository.update_target_if_pending(
                        session,
                        worktree_id=locked.id,
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


def _collision_kind(message: str) -> Literal["branch", "path"] | None:
    """Infer retryable target collision kind from runner failure text."""
    lowered = message.lower()
    if "branch_exists" in lowered or "branch exists" in lowered:
        return "branch"
    if "worktree_path_exists" in lowered or "worktree path exists" in lowered:
        return "path"
    return None
