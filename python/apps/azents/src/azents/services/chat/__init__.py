"""Chat sequencing over completed DB operations and external effects."""

import dataclasses
import datetime
import logging
from typing import (
    Annotated,
    assert_never,
)

from azcommon.logging import bind_extra
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.chat_data import (
    AcknowledgeUnreadTerminalRunError,
    AgentSessionDirectoryPage,
    AgentSessionSidebarSummary,
    ArchiveSessionError,
    ArchiveSessionResult,
    ChatLiveRunOperation,
    ChatLiveRunRetryAttempt,
    ChatLiveRunRetryState,
    ChatLiveRunState,
    ChatLiveStateSnapshot,
    DeleteMailboxItemError,
    EnsureSessionError,
    NewSessionProjectDefaults,
    PaginatedEvents,
    PrepareSessionWorkingFolderError,
    RestoreSessionError,
    SessionAccessError,
    SessionNotFound,
    SetSessionPinnedError,
    SubagentTreeProjection,
    UpdateGoalError,
    UpdateGoalResult,
    UpdateGoalStatusInput,
    UpdateSessionTitleError,
)
from azents.core.chat_projection import (
    _WORKING_FOLDER_CLEANUP_TIMEOUT_SECONDS,
    _require_session_inference_profile,
    _working_folder_cleanup_failure_summary,
    _workspace_items_from_request,
)
from azents.core.enums import (
    AgentRunPhase,
    AgentSessionRunState,
    AgentSessionStatus,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.session_workspace_paths import (
    InvalidProjectPath,
    normalize_agent_workspace_root,
)
from azents.engine.events.action_messages import (
    CreateGitWorktreeAction,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
)
from azents.repos.agent_project_preset.data import AgentProjectPreset
from azents.repos.agent_session.data import (
    AgentSession,
    AgentSessionUnreadTerminalRunProjection,
    SessionWorkingFolderContext,
)
from azents.repos.chat_operations import ChatOperationsRepository
from azents.repos.mailbox.admission_data import (
    MailboxAdmissionResult,
)
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderBindingError,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTargetResolver
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)
from azents.services.session_git_worktree import (
    SessionGitWorktreeService,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)

from .live_events import (
    LiveEventStore,
    active_tool_call_to_live_event,
    mailbox_item_is_publicly_presentable,
    mailbox_item_to_pending_projection,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ChatSessionService:
    """Retain external preparation and post-commit effects without live sessions."""

    operations: Annotated[ChatOperationsRepository, Depends(ChatOperationsRepository)]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService,
        Depends(SessionGitWorktreeService),
    ]
    external_channel_lifecycle_service: Annotated[
        ExternalChannelLifecycleService,
        Depends(ExternalChannelLifecycleService),
    ]
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency
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

    async def get_team_primary_session(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[AgentSession, EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_team_primary_session(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Result[AgentSession, SessionAccessError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_session(
            session_id,
            user_id=user_id,
        )

    async def get_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSession, SessionNotFound]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_agent_session(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def get_agent_session_with_unread_terminal_run(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSessionUnreadTerminalRunProjection, SessionNotFound]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_agent_session_with_unread_terminal_run(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def acknowledge_agent_session_unread_terminal_run(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        through_run_id: str,
    ) -> Result[None, AcknowledgeUnreadTerminalRunError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.acknowledge_agent_session_unread_terminal_run(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            through_run_id=through_run_id,
        )

    async def get_subagent_tree(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[SubagentTreeProjection, SessionAccessError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_subagent_tree(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def list_agent_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def list_agent_sessions_with_unread_terminal_run(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSessionUnreadTerminalRunProjection], EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_agent_sessions_with_unread_terminal_run(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def list_agent_user_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_agent_user_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def list_agent_session_directory(
        self,
        *,
        agent_id: str,
        user_id: str,
        status: AgentSessionStatus,
        offset: int,
        limit: int,
    ) -> Result[AgentSessionDirectoryPage, EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_agent_session_directory(
            agent_id=agent_id,
            user_id=user_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def get_agent_session_sidebar_summary(
        self,
        *,
        agent_id: str,
        user_id: str,
        recent_limit: int,
    ) -> Result[AgentSessionSidebarSummary, EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_agent_session_sidebar_summary(
            agent_id=agent_id,
            user_id=user_id,
            recent_limit=recent_limit,
        )

    async def list_agent_project_presets(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentProjectPreset], EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_agent_project_presets(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def get_new_session_project_defaults(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[NewSessionProjectDefaults, EnsureSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def set_session_pinned(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        pinned: bool,
    ) -> Result[
        AgentSession,
        SetSessionPinnedError,
    ]:
        """Sequence one completed Chat database operation."""
        return await self.operations.set_session_pinned(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            pinned=pinned,
        )

    async def list_archived_agent_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], SessionNotFound]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_archived_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )

    async def restore_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSession, RestoreSessionError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.restore_agent_session(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def update_session_title(
        self,
        *,
        session_id: str,
        user_id: str,
        title: str | None,
    ) -> Result[AgentSession, UpdateSessionTitleError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.update_session_title(
            session_id=session_id,
            user_id=user_id,
            title=title,
        )

    async def list_sessions(
        self, user_id: str, workspace_id: str
    ) -> list[AgentSession]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_sessions(
            user_id,
            workspace_id,
        )

    async def list_history_events(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> Result[PaginatedEvents, SessionAccessError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.list_history_events(
            session_id,
            user_id=user_id,
            limit=limit,
            before=before,
            after=after,
        )

    async def update_goal(
        self,
        session_id: str,
        *,
        user_id: str,
        objective: str | None,
    ) -> Result[UpdateGoalResult, UpdateGoalError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.update_goal(
            session_id,
            user_id=user_id,
            objective=objective,
        )

    async def update_goal_status(
        self,
        session_id: str,
        *,
        user_id: str,
        input: UpdateGoalStatusInput,
    ) -> Result[UpdateGoalResult, UpdateGoalError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.update_goal_status(
            session_id,
            user_id=user_id,
            input=input,
        )

    async def delete_mailbox_item(
        self,
        session_id: str,
        buffer_id: str,
        *,
        user_id: str,
    ) -> Result[None, DeleteMailboxItemError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.delete_mailbox_item(
            session_id,
            buffer_id,
            user_id=user_id,
        )

    async def prepare_session_working_folder(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
    ) -> Result[MailboxAdmissionResult, PrepareSessionWorkingFolderError]:
        """Sequence one completed Chat database operation."""
        return await self.operations.prepare_session_working_folder(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id=client_request_id,
        )

    async def create_team_session(
        self,
        *,
        agent_id: str,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
    ) -> Result[AgentSession, EnsureSessionError | InvalidProjectPath]:
        """Prepare Runtime paths between completed authority operations."""
        prepared = await self.operations.prepare_team_session_creation(
            agent_id=agent_id, user_id=user_id
        )
        if isinstance(prepared, Failure):
            return Failure(prepared.error)
        workspace_id = prepared.value
        if existing_project_paths or setup_actions:
            try:
                runtime = await self.runtime_target_resolver.resolve_operation_target(
                    agent_id,
                )
                workspace_root = normalize_agent_workspace_root(
                    runtime.workspace_path
                ).as_posix()
            except (RuntimeStorageError, ValueError) as exc:
                return Failure(InvalidProjectPath(path="", reason=str(exc)))
            workspace_items_result = _workspace_items_from_request(
                existing_project_paths=existing_project_paths,
                setup_actions=setup_actions,
                workspace_root=workspace_root,
            )
        else:
            workspace_items_result = Success([])
        match workspace_items_result:
            case Success(workspace_items):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(workspace_items_result)

        return await self.operations.finalize_team_session_creation(
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=workspace_id,
            workspace_items=workspace_items,
        )

    async def archive_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str | None,
    ) -> Result[ArchiveSessionResult, ArchiveSessionError]:
        """Apply terminal/provider/Runtime effects only after archive commit."""
        result = await self.operations.archive_agent_session(
            agent_id=agent_id, session_id=session_id, user_id=user_id
        )
        if isinstance(result, Failure):
            return result
        prepared = result.value
        session_ids = list(prepared.subtree_session_ids)
        working_folder_context = prepared.working_folder_context
        archive_cleanup_plans = prepared.cleanup_plans
        publisher = self.terminal_invalidation_publisher
        publish = publisher.publish_agent_session_terminal_invalidation
        for archived_session_id in session_ids:
            await publish(archived_session_id)
        try:
            run_archive_cleanup = (
                self.session_git_worktree_service.run_archive_cleanup_for_root_tree
            )
            await run_archive_cleanup(
                agent_id=agent_id,
                root_session_id=session_id,
                subtree_session_ids=session_ids,
            )
        except Exception:
            logger.exception(
                "Archived Session Git worktree cleanup failed",
                extra={
                    "agent_id": agent_id,
                    "root_session_id": session_id,
                },
            )
        assert working_folder_context is not None
        await self._run_archive_working_folder_cleanup(
            agent_id=agent_id,
            root_session_id=session_id,
            context=working_folder_context,
        )
        cleanup_requested = (
            await self.external_channel_lifecycle_service.consume_archive_cleanup(
                archive_cleanup_plans
            )
            > 0
        )
        return Success(
            ArchiveSessionResult(
                archived_session_id=session_id,
                cleanup_requested=cleanup_requested,
            )
        )

    async def _run_archive_working_folder_cleanup(
        self,
        *,
        agent_id: str,
        root_session_id: str,
        context: SessionWorkingFolderContext,
    ) -> None:
        """Delete one committed Session folder and terminalize its bounded result."""
        if (
            context.binding_state is not SessionWorkingFolderBindingState.BOUND
            or context.cleanup_status is not SessionWorkingFolderCleanupStatus.PENDING
        ):
            return
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=agent_id,
                session_id=root_session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding = await binding_service.resolve_bound_authority_for_target(
                agent_id=agent_id,
                session_id=root_session_id,
                runtime_target=runtime,
            )
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            await self._complete_working_folder_cleanup(
                context_id=context.id,
                status=SessionWorkingFolderCleanupStatus.FAILED,
                summary="Session working-folder cleanup failed: runtime_unavailable.",
            )
            return
        working_folder_path = binding.working_folder_path

        runner_operations = self.runner_operations
        if runner_operations is None:
            await self._complete_working_folder_cleanup(
                context_id=context.id,
                status=SessionWorkingFolderCleanupStatus.FAILED,
                summary=(
                    "Session working-folder cleanup failed: "
                    "runner_operations_unavailable."
                ),
            )
            return
        try:
            target = await runner_operations.stat_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=root_session_id,
                path=working_folder_path,
                deadline_at=(
                    datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(
                        seconds=_WORKING_FOLDER_CLEANUP_TIMEOUT_SECONDS
                    )
                ),
            )
            if target.kind == "missing":
                await self._complete_working_folder_cleanup(
                    context_id=context.id,
                    status=SessionWorkingFolderCleanupStatus.SUCCEEDED,
                    summary=(
                        "Session working-folder cleanup completed: already_absent."
                    ),
                )
                return
            if target.kind not in {"directory", "symlink"}:
                await self._complete_working_folder_cleanup(
                    context_id=context.id,
                    status=SessionWorkingFolderCleanupStatus.FAILED,
                    summary=(
                        "Session working-folder cleanup failed: invalid_target_kind."
                    ),
                )
                return
            await runner_operations.delete_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=root_session_id,
                path=working_folder_path,
                recursive=True,
                deadline_at=(
                    datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(
                        seconds=_WORKING_FOLDER_CLEANUP_TIMEOUT_SECONDS
                    )
                ),
            )
        except RuntimeRunnerOperationFailedError as error:
            if error.code == "NOT_FOUND":
                await self._complete_working_folder_cleanup(
                    context_id=context.id,
                    status=SessionWorkingFolderCleanupStatus.SUCCEEDED,
                    summary=(
                        "Session working-folder cleanup completed: already_absent."
                    ),
                )
                return
            await self._complete_working_folder_cleanup(
                context_id=context.id,
                status=SessionWorkingFolderCleanupStatus.FAILED,
                summary=_working_folder_cleanup_failure_summary(error),
            )
            return
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            await self._complete_working_folder_cleanup(
                context_id=context.id,
                status=SessionWorkingFolderCleanupStatus.FAILED,
                summary="Session working-folder cleanup failed: runtime_unavailable.",
            )
            return
        except Exception:
            logger.exception(
                "Archived Session working-folder cleanup failed unexpectedly",
                extra={
                    "agent_id": agent_id,
                    "root_session_id": root_session_id,
                    "context_id": context.id,
                },
            )
            await self._complete_working_folder_cleanup(
                context_id=context.id,
                status=SessionWorkingFolderCleanupStatus.FAILED,
                summary="Session working-folder cleanup failed: unexpected_error.",
            )
            return
        await self._complete_working_folder_cleanup(
            context_id=context.id,
            status=SessionWorkingFolderCleanupStatus.SUCCEEDED,
            summary="Session working-folder cleanup completed: deleted.",
        )

    async def _complete_working_folder_cleanup(
        self,
        *,
        context_id: str,
        status: SessionWorkingFolderCleanupStatus,
        summary: str,
    ) -> None:
        """Persist one post-commit folder cleanup result without archive rollback."""
        L = bind_extra(logger, {"context_id": context_id, "cleanup_status": status})
        try:
            completed = await self.operations.complete_working_folder_cleanup(
                context_id=context_id, status=status, summary=summary
            )
            if not completed:
                L.error(
                    "Archived Session working-folder cleanup terminal state was lost",
                )
        except Exception:
            L.exception(
                "Archived Session working-folder cleanup terminal state failed",
            )

    async def auto_archive_once(self, *, limit: int = 100) -> dict[str, int]:
        """Archive one bounded batch of inactive, non-pinned root Sessions."""
        candidates = await self.operations.list_auto_archive_candidates(limit=limit)
        archived = 0
        skipped = 0
        for candidate in candidates:
            result = await self.archive_agent_session(
                agent_id=candidate.agent_id,
                session_id=candidate.id,
                user_id=None,
            )
            match result:
                case Success():
                    archived += 1
                case Failure():
                    skipped += 1
                case _:
                    assert_never(result)
        return {"scanned": len(candidates), "archived": archived, "skipped": skipped}

    async def list_live_events(
        self,
        session_id: str,
        *,
        user_id: str,
        live_event_store: LiveEventStore | None = None,
    ) -> Result[ChatLiveStateSnapshot, SessionAccessError]:
        """Read volatile live events after the durable snapshot transaction closes."""
        result = await self.operations.capture_live_state(session_id, user_id=user_id)
        if isinstance(result, Failure):
            return result
        durable = result.value
        agent_session = durable.agent_session
        run = durable.run
        goal = durable.goal
        todo = durable.todo
        action_executions = list(durable.action_executions)
        mailbox_items_projection = [
            mailbox_item_to_pending_projection(item)
            for item in durable.mailbox_items
            if mailbox_item_is_publicly_presentable(item)
        ]
        session_run_state = agent_session.run_state
        inference_profile = (
            None if run is None else _require_session_inference_profile(agent_session)
        )
        partial_history_events = []
        if live_event_store is not None:
            partial_history_events = await live_event_store.list_by_session_id(
                session_id
            )
        partial_history_events = [
            event
            for event in partial_history_events
            if not isinstance(event.payload, ClientToolCallPayload)
        ]
        if run is not None:
            partial_history_events.extend(
                active_tool_call_to_live_event(session_id, active)
                for active in run.active_tool_calls
            )
        partial_history_events.sort(key=lambda event: (event.created_at, event.id))
        live_run = None
        if run is not None:
            assert inference_profile is not None
            if session_run_state != AgentSessionRunState.RUNNING:
                logger.warning(
                    "Active AgentRun contradicts persisted Session run state",
                    extra={
                        "session_id": session_id,
                        "run_id": run.id,
                        "run_status": run.status,
                        "session_run_state": session_run_state,
                    },
                )
            session_run_state = AgentSessionRunState.RUNNING
            live_run = ChatLiveRunState(
                run_id=run.id,
                phase=run.phase,
                status=run.status,
                inference_profile=inference_profile,
                using_fallback=(
                    agent_session.inference_state is not None
                    and agent_session.inference_state.using_fallback
                ),
                model_call_started_at=run.model_call_started_at,
                operation=(
                    ChatLiveRunOperation(
                        kind="preparing_context",
                        operation_id=f"{run.id}:preparing-context",
                        status="running",
                    )
                    if run.phase == AgentRunPhase.COMPACTING
                    else None
                ),
                retry=None
                if run.retry_state is None
                else ChatLiveRunRetryState(
                    error_kind=run.retry_state.error_kind,
                    status=run.retry_state.status,
                    last_error_message=run.retry_state.last_user_message,
                    failed_attempt_count=run.retry_state.failed_attempt_count,
                    max_retries=run.retry_state.max_retries,
                    backoff_seconds=run.retry_state.backoff_seconds,
                    next_retry_at=run.retry_state.next_retry_at.isoformat(),
                    attempts=[
                        ChatLiveRunRetryAttempt(
                            attempt_number=attempt.attempt_number,
                            user_message=attempt.user_message,
                            error_type=attempt.error_type,
                            source=attempt.source,
                            failed_at=attempt.failed_at.isoformat(),
                            backoff_seconds=attempt.backoff_seconds,
                            next_retry_at=attempt.next_retry_at.isoformat(),
                            retryability=attempt.retryability,
                            failure_code=attempt.failure_code,
                            truncated=attempt.truncated,
                        )
                        for attempt in run.retry_state.public_attempts()
                    ],
                ),
            )
        return Success(
            ChatLiveStateSnapshot(
                partial_history_events=partial_history_events,
                mailbox_items=mailbox_items_projection,
                run=live_run,
                session_run_state=session_run_state,
                todo=todo,
                goal=goal,
                action_executions=action_executions,
            )
        )
