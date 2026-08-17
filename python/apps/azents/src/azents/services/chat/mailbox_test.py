"""ChatSessionService MailboxItem tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import patch

import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolCallPayload,
    UserMessagePayload,
)
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItemCreate
from azents.repos.message import MessageRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTargetResolver
from azents.services.chat.data import PendingMailboxUserMessagePresentation
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.mailbox import MailboxService
from azents.services.model_file import ModelFileService
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
    make_test_model_settings,
)

from . import ChatSessionService
from .data import SessionAccessDenied, SessionNotFound, SubagentSessionReadOnly
from .live_events import LiveEventStore


class _TrackingSessionManager:
    """Reject nested DB sessions and expose the active session count."""

    def __init__(self, delegate: SessionManager[AsyncSession]) -> None:
        self.delegate = delegate
        self.active = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        """Open exactly one delegated DB session at a time."""
        assert self.active == 0
        self.active += 1
        try:
            async with self.delegate() as session:
                yield session
        finally:
            self.active -= 1


class _BoundaryCheckingLiveEventStore:
    """Live store asserting that Redis I/O runs after DB scope closure."""

    def __init__(self, session_manager: _TrackingSessionManager) -> None:
        self.session_manager = session_manager

    async def list_by_session_id(self, session_id: str) -> list[object]:
        """Return no live events after checking the transaction boundary."""
        del session_id
        assert self.session_manager.active == 0
        return []


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Chat buffer test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str) -> str:
    """Create User for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


async def _add_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
) -> None:
    """Create WorkspaceUser for tests."""
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user_id,
            name="Chat buffer user",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(result, Success)


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create Agent for tests."""

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Chat buffer test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


def _service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> ChatSessionService:
    """Create ChatSessionService for tests."""
    mailbox_item_service = MailboxService(
        session_manager=rdb_session_manager,
        mailbox_item_repository=MailboxRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=cast(ModelFileService, object()),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_run_repository=AgentRunRepository(),
        scheduled_task_repository=ScheduledTaskRepository(),
        scheduled_task_cycle_repository=ScheduledTaskCycleRepository(
            toolkit_state_repository=ToolkitStateRepository(),
        ),
        action_execution_repository=ActionExecutionRepository(),
        vfs_projection_service=None,
        external_channel_repository=ExternalChannelRepository(),
    )
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        session_git_worktree_repository=SessionGitWorktreeRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        root_agent_session_creation_service=RootAgentSessionCreationService(
            agent_session_repository=AgentSessionRepository(),
            agent_repository=AgentRepository(),
            automatic_project_repository=AgentAutomaticProjectRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        ),
        archived_session_retention_repository=ArchivedSessionRetentionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        mailbox_item_service=mailbox_item_service,
        session_git_worktree_service=cast(SessionGitWorktreeService, object()),
        lifecycle_orchestrator=get_session_lifecycle_orchestrator(),
        external_channel_lifecycle_service=cast(
            ExternalChannelLifecycleService,
            object(),
        ),
        session_manager=rdb_session_manager,
        runtime_target_resolver=cast(RuntimeOperationTargetResolver, object()),
        session_working_folder_binding_service=cast(
            SessionWorkingFolderBindingService,
            object(),
        ),
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


async def _create_session_with_buffer(
    session: AsyncSession,
    *,
    handle: str,
    slug: str,
) -> tuple[str, str, str]:
    """Create accessible AgentSession and MailboxItem."""
    workspace_id = await _create_workspace(session, handle)
    user_id = await _create_user(session, f"{handle}@example.com")
    await _add_workspace_user(session, workspace_id=workspace_id, user_id=user_id)
    agent_id = await _create_agent(session, workspace_id, slug)
    runtime_repository = AgentRuntimeRepository()
    runtime = await runtime_repository.ensure_for_agent(session, agent_id)
    await runtime_repository.record_runner_state(
        session,
        runtime.id,
        RuntimeRunnerState.UNKNOWN,
        1,
        expected_desired_generation=runtime.desired_generation,
        workspace_path="/workspace/agent",
    )
    agent_session = (
        await AgentSessionRepository().ensure_team_primary_for_agent(
            session, workspace_id=runtime.workspace_id, agent_id=runtime.agent_id
        )
    ).session
    mailbox_item = await MailboxRepository().create(
        session,
        MailboxItemCreate(
            session_id=agent_session.id,
            kind=MailboxItemKind.USER_MESSAGE,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label="main",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            sender_user_id=user_id,
            order_group=None,
            order_sequence=0,
            content="pending input",
            idempotency_key=None,
            metadata={"source": "chat"},
            action=None,
            attachments=[],
            file_parts=[],
        ),
    )
    return agent_session.id, user_id, mailbox_item.id


class TestChatSessionMailboxItem:
    """ChatSessionService MailboxItem behavior tests."""

    async def test_list_live_events_includes_pending_buffers(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Live event list returns pending buffer projection."""
        async with rdb_session_manager() as session:
            session_id, user_id, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-buffer-list",
                slug="chat-buffer-list",
            )

        result = await _service(rdb_session_manager).list_live_events(
            session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        envelope = result.value.mailbox_items[0]
        assert envelope.mailbox_item_id == buffer_id
        assert envelope.items[0].mailbox_item_id == buffer_id
        presentation = envelope.items[0].presentation
        assert isinstance(presentation, PendingMailboxUserMessagePresentation)
        assert presentation.type == "user_message"
        assert presentation.requested_inference_profile is not None
        assert presentation.requested_inference_profile.model_target_label == "main"
        assert presentation.requested_inference_profile.reasoning_effort == (
            ModelReasoningEffort.HIGH
        )
        assert result.value.partial_history_events == []
        assert result.value.session_run_state == AgentSessionRunState.IDLE

    async def test_list_live_events_closes_db_before_live_store_io(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Live output reads Redis only after its single DB snapshot closes."""
        async with rdb_session_manager() as session:
            session_id, user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-live-db-boundary",
                slug="chat-live-db-boundary",
            )
        tracking_manager = _TrackingSessionManager(rdb_session_manager)

        result = await _service(
            cast(SessionManager[AsyncSession], tracking_manager)
        ).list_live_events(
            session_id,
            user_id=user_id,
            live_event_store=cast(
                LiveEventStore,
                _BoundaryCheckingLiveEventStore(tracking_manager),
            ),
        )

        assert isinstance(result, Success)
        assert tracking_manager.active == 0

    async def test_list_live_events_running_run_overrides_idle_session_state(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A running AgentRun is authoritative over stale Session idle state."""
        async with rdb_session_manager() as session:
            session_id, user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-live-running-run",
                slug="chat-live-running-run",
            )
            now = datetime.datetime.now(datetime.UTC)
            await AgentSessionRepository().set_inference_state(
                session,
                session_id=session_id,
                inference_state=SessionInferenceState(
                    model_target_label="main",
                    model_selection=make_test_model_selection(),
                    model_settings=make_test_model_settings(),
                    reasoning_effort=ModelReasoningEffort.HIGH,
                    effective_context_window_tokens=100_000,
                    effective_auto_compaction_threshold_tokens=80_000,
                    resolved_at=now,
                ),
            )
            run_repository = AgentRunRepository()
            run = await run_repository.create(
                session,
                AgentRunCreate(
                    session_id=session_id,
                    scheduled_task_cycle_id=None,
                    parent_agent_run_id=None,
                    phase=AgentRunPhase.WAITING_FOR_MODEL,
                ),
            )
            active_call_started_at = now + datetime.timedelta(seconds=1)
            run = await run_repository.update_phase(
                session,
                run.id,
                AgentRunPhase.EXECUTING_TOOLS,
                active_tool_calls=[
                    ActiveToolCall(
                        call_id="call-1",
                        name="bash",
                        arguments='{"cmd":"sleep"}',
                        started_at=active_call_started_at,
                        owner_generation=1,
                        wire_dialect="json_function",
                    )
                ],
            )
            retry_state = FailedRunRetryState.from_attempt(
                FailedRunAttempt(
                    user_message="temporary failure",
                    internal_message=None,
                    error_type="RuntimeError",
                    source="engine",
                    visibility="internal",
                    attempt_number=2,
                    occurred_at=now,
                ),
                max_retries=10,
                backoff_seconds=2,
                next_retry_at=now + datetime.timedelta(seconds=2),
            )
            run = await AgentRunRepository().update_retry_state(
                session,
                run.id,
                retry_state,
            )

        with patch("azents.services.chat.logger.warning") as warning:
            result = await _service(rdb_session_manager).list_live_events(
                session_id,
                user_id=user_id,
            )

        assert isinstance(result, Success)
        assert result.value.run is not None
        assert result.value.run.run_id == run.id
        assert result.value.run.phase == AgentRunPhase.EXECUTING_TOOLS
        assert result.value.run.status == AgentRunStatus.RUNNING
        tool_events = {
            event.payload.call_id: event
            for event in result.value.partial_history_events
            if isinstance(event.payload, ClientToolCallPayload)
        }
        assert set(tool_events) == {"call-1"}
        active_event = tool_events["call-1"]
        assert isinstance(active_event.payload, ClientToolCallPayload)
        assert active_event.created_at == active_call_started_at
        assert active_event.payload.arguments == '{"cmd":"sleep"}'
        active_artifact = active_event.payload.native_artifact
        assert active_artifact is not None
        assert active_artifact.item["source"] == "active_tool_call"
        assert result.value.run.inference_profile.model_target_label == "main"
        assert (
            result.value.run.inference_profile.reasoning_effort
            == ModelReasoningEffort.HIGH
        )
        assert result.value.run.retry is not None
        assert result.value.run.retry.status == "waiting"
        assert result.value.run.retry.last_error_message == "temporary failure"
        assert result.value.run.retry.failed_attempt_count == 2
        assert result.value.run.retry.max_retries == 10
        assert result.value.run.retry.backoff_seconds == 2
        assert result.value.run.retry.next_retry_at == (
            run.retry_state.next_retry_at.isoformat() if run.retry_state else None
        )
        assert len(result.value.run.retry.attempts) == 1
        assert result.value.run.retry.attempts[0].attempt_number == 2
        assert result.value.run.retry.attempts[0].user_message == "temporary failure"
        assert result.value.session_run_state == AgentSessionRunState.RUNNING
        warning.assert_called_once_with(
            "Active AgentRun contradicts persisted Session run state",
            extra={
                "session_id": session_id,
                "run_id": run.id,
                "run_status": AgentRunStatus.RUNNING,
                "session_run_state": AgentSessionRunState.IDLE,
            },
        )

    async def test_list_live_events_projects_compacting_as_one_live_operation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A compacting Run restores one stable context-preparation operation."""
        async with rdb_session_manager() as session:
            session_id, user_id, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-live-compacting-operation",
                slug="chat-live-compacting-operation",
            )
            await MailboxRepository().delete_by_session_and_id(
                session,
                session_id,
                buffer_id,
            )
            now = datetime.datetime.now(datetime.UTC)
            await AgentSessionRepository().set_inference_state(
                session,
                session_id=session_id,
                inference_state=SessionInferenceState(
                    model_target_label="main",
                    model_selection=make_test_model_selection(),
                    model_settings=make_test_model_settings(),
                    reasoning_effort=ModelReasoningEffort.HIGH,
                    effective_context_window_tokens=100_000,
                    effective_auto_compaction_threshold_tokens=80_000,
                    resolved_at=now,
                ),
            )
            run = await AgentRunRepository().create(
                session,
                AgentRunCreate(
                    session_id=session_id,
                    scheduled_task_cycle_id=None,
                    parent_agent_run_id=None,
                    phase=AgentRunPhase.COMPACTING,
                ),
            )

        result = await _service(rdb_session_manager).list_live_events(
            session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        assert result.value.run is not None
        assert result.value.run.run_id == run.id
        assert result.value.run.operation is not None
        assert result.value.run.operation.kind == "preparing_context"
        assert result.value.run.operation.operation_id == (
            f"{run.id}:preparing-context"
        )
        assert result.value.run.operation.status == "running"
        assert result.value.session_run_state == AgentSessionRunState.RUNNING

    async def test_flushed_mailbox_item_remains_in_message_history(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Flushed buffer remains as user input in history event."""
        async with rdb_session_manager() as session:
            session_id, user_id, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-buffer-flushed-history",
                slug="chat-buffer-flushed-history",
            )

        mailbox_item_service = MailboxService(
            session_manager=rdb_session_manager,
            mailbox_item_repository=MailboxRepository(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=cast(ModelFileService, object()),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            scheduled_task_repository=ScheduledTaskRepository(),
            scheduled_task_cycle_repository=ScheduledTaskCycleRepository(
                toolkit_state_repository=ToolkitStateRepository(),
            ),
            action_execution_repository=ActionExecutionRepository(),
            vfs_projection_service=None,
            external_channel_repository=ExternalChannelRepository(),
        )
        promoted = await mailbox_item_service.flush_session_mailbox_items(
            session_id=session_id,
            owner_generation=0,
            model="test-model",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )
        assert promoted.inserted_count == 1
        assert promoted.deleted_buffer_ids == [buffer_id]
        assert promoted.user_messages[0].external_id == f"{buffer_id}:user_message"

        result = await _service(rdb_session_manager).list_history_events(
            session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        assert len(result.value.items) == 1
        event = result.value.items[0]
        assert event.kind == "user_message"
        assert isinstance(event.payload, UserMessagePayload)
        assert event.payload.content == "pending input"

    async def test_delete_mailbox_item_is_idempotent(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Pending buffer deletion succeeds even for missing row."""
        async with rdb_session_manager() as session:
            session_id, user_id, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-buffer-delete",
                slug="chat-buffer-delete",
            )

        service = _service(rdb_session_manager)
        first = await service.delete_mailbox_item(
            session_id, buffer_id, user_id=user_id
        )
        second = await service.delete_mailbox_item(
            session_id, buffer_id, user_id=user_id
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        async with rdb_session_manager() as session:
            assert await MailboxRepository().get_by_id(session, buffer_id) is None

    async def test_delete_mailbox_item_checks_session_access(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """User who is not session member cannot delete pending buffer."""
        async with rdb_session_manager() as session:
            session_id, _, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-buffer-denied",
                slug="chat-buffer-denied",
            )
            other_user_id = await _create_user(
                session, "chat-buffer-denied-other@example.com"
            )

        result = await _service(rdb_session_manager).delete_mailbox_item(
            session_id,
            buffer_id,
            user_id=other_user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)

    async def test_prepare_session_working_folder_enqueues_pathless_retry_idempotently(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Explicit folder retries enqueue one server-authoritative action."""
        async with rdb_session_manager() as session:
            session_id, user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-folder-prepare",
                slug="chat-folder-prepare",
            )
            agent_session = await AgentSessionRepository().get_by_id(
                session,
                session_id,
            )
            assert agent_session is not None
            agent_id = agent_session.agent_id
            other_user_id = await _create_user(
                session,
                "chat-folder-prepare-other@example.com",
            )

        service = _service(rdb_session_manager)
        first = await service.prepare_session_working_folder(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id="retry-1",
        )
        second = await service.prepare_session_working_folder(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id="retry-1",
        )
        denied = await service.prepare_session_working_folder(
            agent_id=agent_id,
            session_id=session_id,
            user_id=other_user_id,
            client_request_id="retry-2",
        )
        wrong_agent = await service.prepare_session_working_folder(
            agent_id="f" * 32,
            session_id=session_id,
            user_id=user_id,
            client_request_id="retry-3",
        )

        assert isinstance(first, Success)
        assert first.value.created is True
        item = first.value.mailbox_item
        assert item.kind is MailboxItemKind.ACTION_MESSAGE
        assert item.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
        assert item.sender_user_id is None
        assert item.content == ""
        assert item.action == {"type": "create_session_working_folder"}
        assert item.idempotency_key == (
            f"session-working-folder:prepare:{session_id}:retry-1"
        )
        assert isinstance(second, Success)
        assert second.value.created is False
        assert second.value.mailbox_item.id == item.id
        live_result = await service.list_live_events(session_id, user_id=user_id)
        assert isinstance(live_result, Success)
        assert all(
            mailbox_item.mailbox_item_id != item.id
            for mailbox_item in live_result.value.mailbox_items
        )
        assert isinstance(denied, Failure)
        assert isinstance(denied.error, SessionNotFound)
        assert isinstance(wrong_agent, Failure)
        assert isinstance(wrong_agent.error, SessionNotFound)

    async def test_prepare_session_working_folder_rejects_invalid_sessions(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Only active root Sessions accept explicit folder preparation retries."""
        async with rdb_session_manager() as session:
            inactive_id, inactive_user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-folder-prepare-inactive",
                slug="chat-folder-prepare-inactive",
            )
            inactive = await AgentSessionRepository().get_by_id(session, inactive_id)
            assert inactive is not None
            await session.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == inactive_id)
                .values(status=AgentSessionStatus.ARCHIVED)
            )

            root_id, subagent_user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-folder-prepare-subagent",
                slug="chat-folder-prepare-subagent",
            )
            root = await AgentSessionRepository().get_by_id(session, root_id)
            assert root is not None
            root_agent = await AgentSessionRepository().get_session_agent_by_session_id(
                session,
                root_id,
            )
            assert root_agent is not None
            child = await AgentSessionRepository().create_child_session_agent(
                session,
                parent_session_agent_id=root_agent.id,
                name="folder-retry-child",
                agent_type="default",
                title="Folder retry child",
                last_task_message=None,
            )
            subagent_id = child.agent_session_id
            subagent = await AgentSessionRepository().get_by_id(session, subagent_id)
            assert subagent is not None

        service = _service(rdb_session_manager)
        inactive_result = await service.prepare_session_working_folder(
            agent_id=inactive.agent_id,
            session_id=inactive_id,
            user_id=inactive_user_id,
            client_request_id="retry-inactive",
        )
        subagent_result = await service.prepare_session_working_folder(
            agent_id=subagent.agent_id,
            session_id=subagent_id,
            user_id=subagent_user_id,
            client_request_id="retry-subagent",
        )

        assert isinstance(inactive_result, Failure)
        assert isinstance(inactive_result.error, SessionNotFound)
        assert isinstance(subagent_result, Failure)
        assert isinstance(subagent_result.error, SubagentSessionReadOnly)
