"""REST chat write service tests."""

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeRunState,
    EventKind,
    InputBufferKind,
    LLMProvider,
)
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import (
    EventSessionRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.chat_write import ChatWriteService
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Chat write service test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str) -> str:
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
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
        name="Chat write service test agent",
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
) -> ChatWriteService:
    input_buffer_service = InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
    )
    return ChatWriteService(
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        message_repository=MessageRepository(),
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


class TestChatWriteService:
    """REST chat write service behavior."""

    async def test_edit_allows_rewriting_message_at_model_input_head(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Idle edit rewrites consumed transcript from the target message."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-edit-head",
            )
            user_id = await _create_user(session, "chat-write-edit-head@example.com")
            agent_id = await _create_agent(session, workspace_id, "chat-write-edit")
            runtime = await AgentRuntimeRepository().ensure_for_agent(
                session,
                agent_id,
            )
            agent_session = await AgentSessionRepository().ensure_active(
                session,
                runtime.id,
            )
            session_repo = EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            )
            event_session = await session_repo.ensure_from_legacy_session(
                session,
                agent_session,
            )
            transcript_repo = EventTranscriptRepository()
            target = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=event_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="original").model_dump(
                        mode="json"
                    ),
                ),
            )
            later = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=event_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="later").model_dump(mode="json"),
                ),
            )
            await session_repo.move_model_input_head(
                session,
                event_session.id,
                target.id,
            )

        result = await _service(rdb_session_manager).create_idempotent_edit_input(
            agent_id=agent_id,
            session_id=event_session.id,
            user_id=user_id,
            client_request_id="edit-at-head",
            message_id=target.id,
            text="edited",
            metadata={"source": "chat"},
            attachments=[],
            file_parts=[],
            payload={"message": "edited"},
        )

        assert result.input_buffer is not None
        assert result.input_buffer.kind == InputBufferKind.EDITED_USER_MESSAGE
        assert result.input_buffer.content == "edited"
        async with rdb_session_manager() as session:
            rows = (
                await session.execute(
                    sa.select(RDBEvent).where(RDBEvent.id.in_([target.id, later.id]))
                )
            ).scalars()
            reverted_by_id = {row.id: row.reverted for row in rows}
            assert reverted_by_id == {target.id: True, later.id: True}
            buffers = (
                await session.execute(
                    sa.select(RDBInputBuffer).where(
                        RDBInputBuffer.session_id == event_session.id
                    )
                )
            ).scalars()
            assert [buffer.content for buffer in buffers] == ["edited"]
            runtime_after = await AgentRuntimeRepository().get_by_current_session_id(
                session,
                event_session.id,
            )
            assert runtime_after is not None
            assert runtime_after.run_state == AgentRuntimeRunState.RUNNING
