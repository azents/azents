"""AgentSessionInputService tests."""

import dataclasses
import datetime

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    InputBufferKind,
    LLMProvider,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import (
    EventSessionRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer, InputBufferCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict

from .agent_session_input import (
    AgentSessionInputInactiveSession,
    AgentSessionInputService,
)
from .input_buffer import (
    InputBufferEnqueue,
    InputBufferEnqueueResult,
    InputBufferService,
)


@dataclasses.dataclass(frozen=True)
class _RuntimeRecord:
    """Runtime record for tests."""

    id: str


@dataclasses.dataclass(frozen=True)
class _AgentSessionRecord:
    """AgentSession record for tests."""

    id: str
    agent_runtime_id: str
    agent_id: str = "agent-1"
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE


class _SessionScope:
    """Session context manager for tests."""

    async def __aenter__(self) -> object:
        """Return fake session object."""
        return object()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        """No cleanup work."""
        del exc_type, exc, traceback


class _SessionManagerDouble:
    """Session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return session scope."""
        return _SessionScope()


class _RuntimeRepositoryDouble:
    """Runtime repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def ensure_for_agent(self, session: object, agent_id: str) -> _RuntimeRecord:
        """Ensure runtime."""
        del session, agent_id
        self.calls.append("ensure_for_agent")
        return _RuntimeRecord(id="runtime-1")

    async def mark_running_for_input_wakeup(
        self,
        session: object,
        session_id: str,
    ) -> None:
        """Record input wake-up running transition."""
        del session, session_id
        self.calls.append("mark_running_for_input_wakeup")


class _AgentSessionRepositoryDouble:
    """AgentSession repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def ensure_active_with_runtime_lock(
        self,
        session: object,
        runtime_id: str,
    ) -> _AgentSessionRecord:
        """Ensure active session with lock."""
        del session
        self.calls.append("ensure_active_with_runtime_lock")
        return _AgentSessionRecord(id="session-1", agent_runtime_id=runtime_id)

    async def get_by_id(
        self,
        session: object,
        agent_session_id: str,
    ) -> _AgentSessionRecord:
        """Fetch session."""
        del session
        self.calls.append("get_by_id")
        return _AgentSessionRecord(
            id=agent_session_id,
            agent_runtime_id="runtime-1",
        )


class _InputBufferServiceDouble:
    """InputBufferService double for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.enqueued: InputBufferEnqueue | None = None
        self.moved: tuple[str, str] | None = None

    async def enqueue(
        self,
        session: object,
        input: InputBufferEnqueue,
    ) -> InputBufferEnqueueResult:
        """Record InputBuffer creation."""
        del session
        self.calls.append("enqueue_input_buffer")
        self.enqueued = input
        input_buffer = InputBuffer(
            id="buffer-1",
            session_id=input.session_id,
            kind=input.kind,
            actor_user_id=input.actor_user_id,
            content=input.content,
            idempotency_key=input.idempotency_key,
            metadata=input.metadata,
            attachments=input.attachments,
            file_parts=input.file_parts,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        return InputBufferEnqueueResult(input_buffer=input_buffer, created=True)

    async def move_by_session_id(
        self,
        session: object,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Record InputBuffer move request."""
        del session
        self.calls.append("move_input_buffer")
        self.moved = (from_session_id, to_session_id)
        return 1


class _EventSessionRepositoryDouble:
    """Event session repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def ensure_from_legacy_session(
        self,
        session: object,
        agent_session: _AgentSessionRecord,
    ) -> None:
        """Record event session ensure call."""
        del session, agent_session
        self.calls.append("ensureevent_session")


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


def _input_buffer_service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> InputBufferService:
    """Create InputBufferService for integration tests."""
    return InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
    )


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="AgentSession input test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


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
        name="AgentSession input test agent",
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


async def _create_user(session: AsyncSession, email: str) -> str:
    """Create User for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


class TestAgentSessionInputService:
    """AgentSessionInputService tests."""

    async def test_create_buffered_agent_input_marks_running_before_return(
        self,
    ) -> None:
        """REST input storage marks runtime running before broker send."""
        calls: list[str] = []
        runtime_repository = _RuntimeRepositoryDouble(calls)
        session_repository = _AgentSessionRepositoryDouble(calls)
        input_buffer_service = _InputBufferServiceDouble(calls)
        event_repository = _EventSessionRepositoryDouble(calls)
        service = AgentSessionInputService(
            agent_runtime_repository=runtime_repository,  # pyright: ignore[reportArgumentType]  # test double.
            agent_session_repository=session_repository,  # pyright: ignore[reportArgumentType]  # test double.
            input_buffer_service=input_buffer_service,  # pyright: ignore[reportArgumentType]  # test double.
            event_session_repository=event_repository,  # pyright: ignore[reportArgumentType]  # test double.
            session_manager=_SessionManagerDouble(),  # pyright: ignore[reportArgumentType]  # test double.
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="restore me",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id="user-1",
        )

        assert isinstance(result, Success)
        value = result.value
        assert value.agent_runtime_id == "runtime-1"
        assert value.agent_session_id == "session-1"
        assert value.input_buffer.id == "buffer-1"
        assert calls == [
            "get_by_id",
            "ensure_for_agent",
            "ensureevent_session",
            "enqueue_input_buffer",
        ]
        assert input_buffer_service.enqueued is not None
        assert input_buffer_service.enqueued.session_id == "session-1"
        assert input_buffer_service.enqueued.content == "restore me"

    async def test_rotate_agent_session_preserves_previous_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """AgentSession rotation preserves previous session as archived."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session, "agent-session-rotate-input"
            )
            agent_id = await _create_agent(
                session, workspace_id, "agent-session-rotate-input"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            first = await AgentSessionRepository().ensure_active(session, runtime.id)

        service = AgentSessionInputService(
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            event_session_repository=EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            ),
            session_manager=rdb_session_manager,
        )

        rotated_id = await service.rotate_agent_session(
            agent_id=agent_id,
            start_reason=AgentSessionStartReason.MANUAL_RESET,
            end_reason=AgentSessionEndReason.MANUAL_RESET,
        )

        async with rdb_session_manager() as session:
            repo = AgentSessionRepository()
            archived = await repo.get_by_id(session, first.id)
            active = await repo.get_by_id(session, rotated_id)
        assert archived is not None
        assert archived.status == AgentSessionStatus.ARCHIVED
        assert archived.end_reason == AgentSessionEndReason.MANUAL_RESET
        assert active is not None
        assert active.status == AgentSessionStatus.ACTIVE
        assert active.start_reason == AgentSessionStartReason.MANUAL_RESET

    async def test_rotate_agent_session_moves_pending_buffers_to_next_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """AgentSession rollover transfers pending buffer to next session."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session, "agent-session-rotate-buffer"
            )
            user_id = await _create_user(session, "rotate-buffer@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "agent-session-rotate-buffer"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = await AgentSessionRepository().ensure_active(
                session, runtime.id
            )
            created = await InputBufferRepository().create(
                session,
                InputBufferCreate(
                    session_id=agent_session.id,
                    kind=InputBufferKind.USER_MESSAGE,
                    actor_user_id=user_id,
                    content="pending before rollover",
                    idempotency_key=None,
                    metadata={"source": "chat"},
                    attachments=[],
                    file_parts=[],
                ),
            )

        service = AgentSessionInputService(
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            event_session_repository=EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            ),
            session_manager=rdb_session_manager,
        )

        rotated_id = await service.rotate_agent_session(
            agent_id=agent_id,
            start_reason=AgentSessionStartReason.COMPACT_ROTATE,
            end_reason=AgentSessionEndReason.COMPACT_ROTATE,
        )

        async with rdb_session_manager() as session:
            old_buffers = await InputBufferRepository().list_by_session_id(
                session, agent_session.id
            )
            new_buffers = await InputBufferRepository().list_by_session_id(
                session, rotated_id
            )

        assert old_buffers == []
        assert [buffer.id for buffer in new_buffers] == [created.id]
        assert new_buffers[0].content == "pending before rollover"

    async def test_buffered_agent_input_rejects_archived_session_after_rollover(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """User input with stale session id is rejected instead of redirected."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session, "agent-session-stale-buffer"
            )
            user_id = await _create_user(session, "stale-buffer@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "agent-session-stale-buffer"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            old_session = await AgentSessionRepository().ensure_active(
                session, runtime.id
            )
            new_session = await AgentSessionRepository().rotate_active(
                session,
                runtime.id,
                start_reason=AgentSessionStartReason.COMPACT_ROTATE,
                end_reason=AgentSessionEndReason.COMPACT_ROTATE,
                now=datetime.datetime.now(datetime.timezone.utc),
            )

        service = AgentSessionInputService(
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            event_session_repository=EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            ),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=old_session.id,
            message=InputMessage(
                text="after rollover",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)

        async with rdb_session_manager() as session:
            old_buffers = await InputBufferRepository().list_by_session_id(
                session, old_session.id
            )
            new_buffers = await InputBufferRepository().list_by_session_id(
                session, new_session.id
            )
        assert old_buffers == []
        assert new_buffers == []

    async def test_create_buffered_agent_input_marks_session_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """REST input storage marks Session running to cover broker loss."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-running")
            user_id = await _create_user(session, "buffered-running@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-running"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = await AgentSessionRepository().ensure_active(
                session, runtime.id
            )

        service = AgentSessionInputService(
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            event_session_repository=EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            ),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="restore me",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
        )
        assert isinstance(result, Success)

        async with rdb_session_manager() as session:
            updated = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )

        assert updated is not None
        assert updated.run_state == AgentSessionRunState.RUNNING
        assert updated.run_heartbeat_at is not None

    async def test_create_buffered_agent_input_dedupes_client_request_id(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Same client_request_id returns same InputBuffer."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-idempotent")
            user_id = await _create_user(session, "buffered-idempotent@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-idempotent"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = await AgentSessionRepository().ensure_active(
                session, runtime.id
            )

        service = AgentSessionInputService(
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            event_session_repository=EventSessionRepository(
                transcript_repo=EventTranscriptRepository()
            ),
            session_manager=rdb_session_manager,
        )

        first = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            client_request_id="client-request-1",
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="retry payload ignored",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            client_request_id="client-request-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        first_value = first.value
        second_value = second.value
        assert second_value.input_buffer.id == first_value.input_buffer.id
        assert second_value.input_buffer.content == "first"
        assert second_value.input_buffer.idempotency_key == "client-request-1"
        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session, agent_session.id
            )
        assert [buffer.id for buffer in buffers] == [first_value.input_buffer.id]
