"""REST chat write service tests."""

import datetime

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionRunState,
    EventKind,
    InputBufferKind,
    LLMProvider,
)
from azents.engine.events.types import (
    RunMarkerPayload,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunFailureMetadata,
    FailedRunRetryState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
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
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
    )
    return ChatWriteService(
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


def _failed_run_system_error_payload() -> dict[str, JSONValue]:
    """Build a terminal failed-run system_error payload for tests."""
    now = datetime.datetime.now(datetime.UTC)
    retry_state = FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message="temporary failure",
            internal_message="RuntimeError('temporary failure')",
            error_type="RuntimeError",
            source="engine",
            visibility="internal",
            attempt_number=10,
            occurred_at=now,
        ),
        max_retries=10,
        backoff_seconds=60,
        next_retry_at=now + datetime.timedelta(seconds=60),
    )
    return SystemErrorPayload(
        content="temporary failure",
        severity="error",
        recoverable=True,
        failure=FailedRunFailureMetadata.from_retry_state(
            retry_state,
            finalization_reason="retry_exhausted",
        ),
    ).model_dump(mode="json", exclude_none=True)


class _ExistingWriteRequestRepository(ChatWriteRequestRepository):
    """ChatWriteRequestRepository double returning an existing record."""

    def __init__(self, existing_session_id: str) -> None:
        """Store the existing record session id."""
        self.existing_session_id = existing_session_id

    async def create_idempotent(
        self,
        session: AsyncSession,
        create: ChatWriteRequestCreate,
    ) -> tuple[ChatWriteRequest, bool]:
        """Return an existing idempotency record for another session."""
        del session
        return (
            ChatWriteRequest(
                id="write-request-1",
                session_id=self.existing_session_id,
                user_id=create.user_id,
                client_request_id=create.client_request_id,
                write_type=create.write_type,
                accepted_type=create.accepted_type,
                accepted_id=create.accepted_id,
                history_reload_required=create.history_reload_required,
                payload=create.payload,
                created_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
            ),
            False,
        )


class TestChatWriteService:
    """REST chat write service behavior."""

    async def test_idempotency_record_for_another_session_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject existing idempotency records from another explicit session."""
        service = ChatWriteService(
            agent_session_repository=AgentSessionRepository(),
            chat_write_request_repository=_ExistingWriteRequestRepository(
                "2223456789abcdef0123456789abcdef"
            ),
            message_repository=MessageRepository(),
            input_buffer_service=InputBufferService(
                session_manager=rdb_session_manager,
                input_buffer_repository=InputBufferRepository(),
                exchange_file_service=_ExchangeFileService(),
                model_file_service=_ModelFileService(),
                agent_session_repository=AgentSessionRepository(),
                event_transcript_repository=EventTranscriptRepository(),
            ),
            session_manager=rdb_session_manager,
        )

        try:
            async with rdb_session_manager() as session:
                await service._create_idempotent_record(  # pyright: ignore[reportPrivateUsage]  # Pin explicit-session idempotency guard directly.
                    session,
                    session_id="3333456789abcdef0123456789abcdef",
                    user_id="user-1",
                    client_request_id="same-client-request",
                    write_type=ChatWriteRequestType.COMMAND,
                    accepted_type=ChatWriteRequestType.COMMAND,
                    accepted_id="command-1",
                    history_reload_required=True,
                    payload={"command": "compact"},
                )
        except ValueError as exc:
            assert str(exc) == "Client request ID already used for another session"
        else:
            raise AssertionError("Expected ValueError")

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
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            transcript_repo = EventTranscriptRepository()
            target = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="original").model_dump(
                        mode="json"
                    ),
                ),
            )
            later = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="later").model_dump(mode="json"),
                ),
            )
            await AgentSessionRepository().move_model_input_head(
                session,
                agent_session.id,
                target.id,
            )

        result = await _service(rdb_session_manager).create_idempotent_edit_input(
            agent_id=agent_id,
            session_id=agent_session.id,
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
                        RDBInputBuffer.session_id == agent_session.id
                    )
                )
            ).scalars()
            assert [buffer.content for buffer in buffers] == ["edited"]
            session_after = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            assert session_after is not None
            assert session_after.run_state == AgentSessionRunState.RUNNING

    async def test_failed_run_retry_reverts_latest_failed_error_and_marks_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Manual failed-run retry soft-reverts terminal failure output."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-failed-run-retry",
            )
            user_id = await _create_user(
                session,
                "chat-write-failed-run-retry@example.com",
            )
            agent_id = await _create_agent(session, workspace_id, "failed-run-retry")
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            transcript_repo = EventTranscriptRepository()
            user_event = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="do the task").model_dump(
                        mode="json"
                    ),
                ),
            )
            failed_event = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.SYSTEM_ERROR,
                    payload=_failed_run_system_error_payload(),
                ),
            )
            marker = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.RUN_MARKER,
                    payload=RunMarkerPayload(
                        run_id="run-1".rjust(32, "0"),
                        status="failed",
                        error="temporary failure",
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )

        result = await _service(rdb_session_manager).create_idempotent_failed_run_retry(
            agent_id=agent_id,
            session_id=agent_session.id,
            user_id=user_id,
            client_request_id="retry-failed-run",
            failed_event_id=failed_event.id,
            payload={"failed_event_id": failed_event.id},
        )

        assert result.request.created is True
        assert result.failed_event_id == failed_event.id
        async with rdb_session_manager() as session:
            rows = (
                await session.execute(
                    sa.select(RDBEvent).where(
                        RDBEvent.id.in_([user_event.id, failed_event.id, marker.id])
                    )
                )
            ).scalars()
            reverted_by_id = {row.id: row.reverted for row in rows}
            assert reverted_by_id == {
                user_event.id: False,
                failed_event.id: True,
                marker.id: True,
            }
            session_after = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            assert session_after is not None
            assert session_after.run_state == AgentSessionRunState.RUNNING

        repeated = await _service(
            rdb_session_manager
        ).create_idempotent_failed_run_retry(
            agent_id=agent_id,
            session_id=agent_session.id,
            user_id=user_id,
            client_request_id="retry-failed-run",
            failed_event_id=failed_event.id,
            payload={"failed_event_id": failed_event.id},
        )

        assert repeated.request.created is False
        assert repeated.failed_event_id == failed_event.id

    async def test_failed_run_retry_rejects_stale_failed_error(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Manual retry rejects a failed-run card that has newer visible history."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-failed-run-stale",
            )
            user_id = await _create_user(
                session,
                "chat-write-failed-run-stale@example.com",
            )
            agent_id = await _create_agent(session, workspace_id, "failed-run-stale")
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            transcript_repo = EventTranscriptRepository()
            failed_event = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.SYSTEM_ERROR,
                    payload=_failed_run_system_error_payload(),
                ),
            )
            await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="newer context").model_dump(
                        mode="json"
                    ),
                ),
            )

        try:
            await _service(rdb_session_manager).create_idempotent_failed_run_retry(
                agent_id=agent_id,
                session_id=agent_session.id,
                user_id=user_id,
                client_request_id="retry-stale-failed-run",
                failed_event_id=failed_event.id,
                payload={"failed_event_id": failed_event.id},
            )
        except ValueError as exc:
            assert str(exc) == "Failed-run error is no longer the latest visible event"
        else:
            raise AssertionError("Expected ValueError")

    async def test_idempotent_command_key_is_session_scoped(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Allow the same client request ID in a different explicit session."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-idempotent-session",
            )
            user_id = await _create_user(
                session,
                "chat-write-idempotent-session@example.com",
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "chat-write-idempotent-session",
            )
            first = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )

        service = _service(rdb_session_manager)
        payload: dict[str, object] = {"command": "compact"}
        await service.create_idempotent_pending_command(
            agent_id=agent_id,
            session_id=first.id,
            user_id=user_id,
            client_request_id="same-client-request",
            command_name="compact",
            payload=payload,
        )

        async with rdb_session_manager() as session:
            second = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                ),
            )

        result = await service.create_idempotent_pending_command(
            agent_id=agent_id,
            session_id=second.id,
            user_id=user_id,
            client_request_id="same-client-request",
            command_name="compact",
            payload=payload,
        )

        assert result.request.created is True
        assert result.request.session_id == second.id
        assert result.command_id is not None
