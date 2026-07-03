"""ChatSessionService InputBuffer tests."""

import datetime

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionRunState,
    InputBufferKind,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.engine.events.types import UserMessagePayload
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBufferCreate
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatSessionService
from .data import SessionAccessDenied


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
    )
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_run_repository=AgentRunRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=input_buffer_service,
        session_manager=rdb_session_manager,
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


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
        assert result.value.partial_history_events == []
        assert result.value.session_run_state == AgentSessionRunState.IDLE

    async def test_list_live_events_includes_running_run_state(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Live event list returns running run state."""
        async with rdb_session_manager() as session:
            session_id, user_id, _ = await _create_session_with_buffer(
                session,
                handle="chat-live-running-run",
                slug="chat-live-running-run",
            )
            await AgentSessionRepository().mark_running(session, session_id)
            run = await AgentRunRepository().create(
                session,
                AgentRunCreate(
                    session_id=session_id,
                    phase=AgentRunPhase.WAITING_FOR_MODEL,
                ),
            )
            now = datetime.datetime.now(datetime.UTC)
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

        result = await _service(rdb_session_manager).list_live_events(
            session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        assert result.value.run is not None
        assert result.value.run.run_id == run.id
        assert result.value.run.phase == AgentRunPhase.WAITING_FOR_MODEL
        assert result.value.run.status == AgentRunStatus.RUNNING
        assert result.value.run.retry is not None
        assert result.value.run.retry.status == "waiting"
        assert result.value.run.retry.last_error_message == "temporary failure"
        assert result.value.run.retry.failed_attempt_count == 2
        assert result.value.run.retry.max_retries == 10
        assert result.value.run.retry.backoff_seconds == 2
        assert result.value.run.retry.next_retry_at == (
            run.retry_state.next_retry_at.isoformat() if run.retry_state else None
        )
        assert result.value.session_run_state == AgentSessionRunState.RUNNING

    async def test_flushed_input_buffer_remains_in_message_history(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Flushed buffer remains as user input in history event."""
        async with rdb_session_manager() as session:
            session_id, user_id, _ = await _create_session_with_buffer(
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
        )
        promoted = await input_buffer_service.flush_session_input_buffers(
            session_id=session_id,
            model="test-model",
        )
        assert promoted.inserted_count == 1
        assert promoted.deleted_buffer_ids == [promoted.user_messages[0].external_id]

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
