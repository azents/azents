"""ChatSessionService InputBuffer tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    InputBufferKind,
    LLMProvider,
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
from azents.engine.tools.goal import GoalState
from azents.engine.tools.todo import TodoState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer.data import InputBufferCreate
from azents.repos.input_buffer.repository import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
)

from . import (
    ChatSessionService,
    _list_live_events_best_effort,  # pyright: ignore[reportPrivateUsage]  # Pin bounded non-durable Redis fallback.
)
from .data import SessionAccessDenied
from .live_events import LiveEventStore


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
    input_buffer_service = InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        toolkit_state_repository=ToolkitStateRepository(),
    )
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=input_buffer_service,
        session_manager=rdb_session_manager,
        toolkit_state_repository=ToolkitStateRepository(),
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _TrackingSessionManager:
    """Track concurrent service-owned DB sessions."""

    def __init__(self, delegate: SessionManager[AsyncSession] | None = None) -> None:
        self.delegate = delegate
        self.active_sessions = 0
        self.max_active_sessions = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession, None]:
        """Delegate to the real manager while tracking session lifetime."""
        self.active_sessions += 1
        self.max_active_sessions = max(
            self.max_active_sessions,
            self.active_sessions,
        )
        try:
            if self.delegate is None:
                yield cast(AsyncSession, object())
            else:
                async with self.delegate() as session:
                    yield session
        finally:
            self.active_sessions -= 1


class _SessionClosedLiveEventStore:
    """Assert Redis-like reads start after the DB snapshot session closes."""

    def __init__(self, tracker: _TrackingSessionManager) -> None:
        self.tracker = tracker
        self.called = False

    async def list_by_session_id(self, session_id: str) -> list[object]:
        """Return no partial events after checking the session boundary."""
        del session_id
        assert self.tracker.active_sessions == 0
        self.called = True
        return []


class _HangingLiveEventStore:
    """Non-durable store whose Redis read never returns."""

    async def list_by_session_id(self, session_id: str) -> list[object]:
        """Block forever after accepting the read."""
        del session_id
        await asyncio.Event().wait()
        return []


async def test_live_event_read_timeout_falls_back_to_no_partial_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis stalls omit only non-durable partials from the DB-backed snapshot."""
    monkeypatch.setattr(
        "azents.services.chat._LIVE_EVENT_READ_TIMEOUT_SECONDS",
        0.01,
    )

    events = await asyncio.wait_for(
        _list_live_events_best_effort(
            cast(LiveEventStore, _HangingLiveEventStore()),
            session_id="session-1",
        ),
        timeout=1,
    )

    assert events == []


async def _create_session_with_buffer(
    session: AsyncSession,
    *,
    handle: str,
    slug: str,
) -> tuple[str, str, str]:
    """Create accessible AgentSession and InputBuffer."""
    workspace_id = await _create_workspace(session, handle)
    user_id = await _create_user(session, f"{handle}@example.com")
    await _add_workspace_user(session, workspace_id=workspace_id, user_id=user_id)
    agent_id = await _create_agent(session, workspace_id, slug)
    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session, workspace_id=runtime.workspace_id, agent_id=runtime.agent_id
    )
    input_buffer = await InputBufferRepository().create(
        session,
        InputBufferCreate(
            session_id=agent_session.id,
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label="main",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            actor_user_id=user_id,
            content="pending input",
            idempotency_key=None,
            metadata={"source": "chat"},
            action=None,
            attachments=[],
            file_parts=[],
        ),
    )
    return agent_session.id, user_id, input_buffer.id


async def test_list_live_events_closes_db_before_all_detached_store_reads() -> None:
    """Live/Goal/Todo reads start only after the DB snapshot session closes."""
    tracker = _TrackingSessionManager()
    live_event_store = _SessionClosedLiveEventStore(tracker)
    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.return_value = SimpleNamespace(
        status=AgentSessionStatus.ACTIVE,
        workspace_id="workspace-1",
        agent_id="agent-1",
        run_state=AgentSessionRunState.IDLE,
    )
    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = object()
    input_buffer_service = AsyncMock()
    input_buffer_service.list_by_session_id.return_value = []
    agent_run_repository = AsyncMock()
    agent_run_repository.get_running_by_session_id.return_value = None
    action_execution_repository = AsyncMock()
    action_execution_repository.list_projections_by_session_id.return_value = []
    service = ChatSessionService(
        message_repository=cast(Any, object()),
        agent_repository=cast(Any, object()),
        agent_project_preset_repository=cast(Any, object()),
        agent_project_catalog_repository=cast(Any, object()),
        agent_project_default_repository=cast(Any, object()),
        agent_run_repository=agent_run_repository,
        action_execution_repository=action_execution_repository,
        event_transcript_repository=cast(Any, object()),
        agent_session_repository=agent_session_repository,
        workspace_user_repository=workspace_user_repository,
        session_workspace_project_repository=cast(Any, object()),
        input_buffer_service=input_buffer_service,
        session_manager=cast(SessionManager[AsyncSession], tracker),
        toolkit_state_repository=ToolkitStateRepository(),
    )

    async def load_goal(agent_id: str, session_id: str) -> GoalState:
        del agent_id, session_id
        assert tracker.active_sessions == 0
        return GoalState()

    async def load_todo(agent_id: str, session_id: str) -> TodoState:
        del agent_id, session_id
        assert tracker.active_sessions == 0
        return TodoState()

    with (
        patch("azents.services.chat.GoalStateStore") as goal_store_type,
        patch("azents.services.chat.TodoStateStore") as todo_store_type,
    ):
        goal_store_type.return_value.load = AsyncMock(side_effect=load_goal)
        todo_store_type.return_value.load = AsyncMock(side_effect=load_todo)
        result = await service.list_live_events(
            "session-1",
            user_id="user-1",
            live_event_store=cast(LiveEventStore, live_event_store),
        )

    assert isinstance(result, Success)
    assert result.value.partial_history_events == []
    assert result.value.input_buffer_events == []
    assert result.value.session_run_state == AgentSessionRunState.IDLE
    assert live_event_store.called
    assert tracker.active_sessions == 0
    assert tracker.max_active_sessions == 1


class TestChatSessionInputBuffer:
    """ChatSessionService InputBuffer behavior tests."""

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
        assert [event.id for event in result.value.input_buffer_events] == [buffer_id]
        payload = result.value.input_buffer_events[0].payload
        assert isinstance(payload, UserMessagePayload)
        assert payload.applied_inference_profile is not None
        assert payload.applied_inference_profile.model_target_label == "main"
        assert payload.applied_inference_profile.model_display_name is None
        assert payload.applied_inference_profile.reasoning_effort == (
            ModelReasoningEffort.HIGH
        )
        assert result.value.partial_history_events == []
        assert result.value.session_run_state == AgentSessionRunState.IDLE

    async def test_list_live_events_closes_db_before_live_and_state_stores(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Redis and Goal/Todo reads do not overlap the DB snapshot session."""
        async with rdb_session_manager() as session:
            session_id, user_id, buffer_id = await _create_session_with_buffer(
                session,
                handle="chat-live-session-boundary",
                slug="chat-live-session-boundary",
            )
        tracker = _TrackingSessionManager(rdb_session_manager)
        live_event_store = _SessionClosedLiveEventStore(tracker)

        result = await _service(
            cast(SessionManager[AsyncSession], tracker)
        ).list_live_events(
            session_id,
            user_id=user_id,
            live_event_store=cast(LiveEventStore, live_event_store),
        )

        assert isinstance(result, Success)
        assert [event.id for event in result.value.input_buffer_events] == [buffer_id]
        assert live_event_store.called
        assert tracker.active_sessions == 0
        assert tracker.max_active_sessions == 1

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

    async def test_flushed_input_buffer_remains_in_message_history(
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

        input_buffer_service = InputBufferService(
            session_manager=rdb_session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=_ModelFileService(),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
            toolkit_state_repository=ToolkitStateRepository(),
        )
        promoted = await input_buffer_service.flush_session_input_buffers(
            session_id=session_id,
            model="test-model",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            owner_generation=0,
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

    async def test_delete_input_buffer_is_idempotent(
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
        first = await service.delete_input_buffer(
            session_id, buffer_id, user_id=user_id
        )
        second = await service.delete_input_buffer(
            session_id, buffer_id, user_id=user_id
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        async with rdb_session_manager() as session:
            assert await InputBufferRepository().get_by_id(session, buffer_id) is None

    async def test_delete_input_buffer_checks_session_access(
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

        result = await _service(rdb_session_manager).delete_input_buffer(
            session_id,
            buffer_id,
            user_id=other_user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)
