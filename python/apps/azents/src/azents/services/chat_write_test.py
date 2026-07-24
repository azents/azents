"""REST chat write service tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import sqlalchemy as sa
from azcommon.result import Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
    LLMProvider,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
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
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.message import MessageRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.chat_write import ChatWriteService
from azents.services.exchange_file import (
    ExchangeFileInputClaimError,
    ExchangeFileService,
)
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import (
    make_test_model_selection_dict,
)


@asynccontextmanager
async def _session_manager_double() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder DB session for service-double tests."""
    yield cast(AsyncSession, object())


class _SubagentLockRepository(AgentSessionRepository):
    """AgentSessionRepository double returning a locked subagent session."""

    def __init__(self, calls: list[str]) -> None:
        """Store call log."""
        self.calls = calls

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Return a subagent AgentSession for idle-control lock attempts."""
        del session
        self.calls.append("lock_by_id")
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            owner_generation=0,
            inference_state=None,
            id=agent_session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="subagent-session",
            session_kind=AgentSessionKind.SUBAGENT,
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=now,
            started_at=now,
            created_at=now,
            updated_at=now,
        )


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


class _WorkspaceUserRepository:
    """Workspace membership double for write-admission tests."""

    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str]] = []

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> object | None:
        """Return current membership according to the test-controlled state."""
        del session
        self.calls.append((workspace_id, user_id))
        return object() if self.allowed else None


def _service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    workspace_user_repository: WorkspaceUserRepository | None = None,
) -> ChatWriteService:
    input_buffer_service = InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=cast(ModelFileService, object()),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        vfs_projection_service=None,
        external_channel_repository=ExternalChannelRepository(),
    )
    return ChatWriteService(
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=(
            workspace_user_repository
            or cast(WorkspaceUserRepository, _WorkspaceUserRepository())
        ),
        agent_run_repository=AgentRunRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        message_repository=MessageRepository(),
        exchange_file_service=_ExchangeFileService(),
        input_buffer_service=input_buffer_service,
        session_manager=rdb_session_manager,
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""

    async def claim_input_attachments(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        attachment_uris: list[str],
    ) -> Result[None, ExchangeFileInputClaimError]:
        """Accept all test attachment claims."""
        del session, agent_id, session_id, user_id, attachment_uris
        return Success(None)


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
                requester_user_id=create.requester_user_id,
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


def _control_session(
    *,
    run_state: AgentSessionRunState = AgentSessionRunState.IDLE,
    pending_command_id: str | None = None,
) -> AgentSession:
    """Build a minimal active root Session for authorization-order tests."""
    return AgentSession.model_construct(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_kind=AgentSessionKind.ROOT,
        status=AgentSessionStatus.ACTIVE,
        run_state=run_state,
        pending_command_id=pending_command_id,
    )


def _existing_record(
    *,
    write_type: ChatWriteRequestType,
    payload: dict[str, object],
    accepted_id: str = "accepted-1",
) -> ChatWriteRequest:
    """Build a replayable accepted request record."""
    return ChatWriteRequest(
        id="request-1",
        session_id="session-1",
        requester_user_id="user-1",
        client_request_id="request-1",
        write_type=write_type,
        accepted_type=write_type,
        accepted_id=accepted_id,
        history_reload_required=True,
        payload=payload,
        created_at=datetime.datetime(2026, 7, 24, tzinfo=datetime.UTC),
    )


class _ControlAgentSessionRepository:
    """Record authorization/control ordering without a database."""

    def __init__(
        self,
        session: AgentSession,
        *,
        subtree: list[AgentSession] | None = None,
    ) -> None:
        self.session = session
        self.subtree = subtree or [session]
        self.lock_calls = 0
        self.tree_lock_calls = 0
        self.stop_requests: list[str] = []

    async def lock_by_id(
        self,
        db_session: AsyncSession,
        session_id: str,
    ) -> AgentSession:
        del db_session
        assert session_id == self.session.id
        self.lock_calls += 1
        return self.session

    async def get_root_session_agent_by_session_id(
        self,
        db_session: AsyncSession,
        session_id: str,
    ) -> object:
        del db_session
        assert session_id == self.session.id
        return SimpleNamespace(agent_session_id=self.session.id)

    async def lock_root_tree_sessions(
        self,
        db_session: AsyncSession,
        *,
        root_session_id: str,
    ) -> list[AgentSession]:
        del db_session
        assert root_session_id == self.session.id
        self.tree_lock_calls += 1
        return self.subtree

    async def request_stop(
        self,
        db_session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str,
    ) -> AgentSession:
        del db_session, stop_request_id, stop_requester_user_id
        self.stop_requests.append(session_id)
        return self.session


class _ControlAgentRepository:
    """Return one active Agent whose Workspace matches the Session."""

    async def get_by_id(self, db_session: AsyncSession, agent_id: str) -> object:
        del db_session
        assert agent_id == "agent-1"
        return SimpleNamespace(
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
            workspace_id="workspace-1",
        )


class _ControlWorkspaceUserRepository:
    """Toggle requester authorization after route-level prevalidation."""

    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    async def get_by_workspace_and_user(
        self,
        db_session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> object | None:
        del db_session
        assert (workspace_id, user_id) == ("workspace-1", "user-1")
        self.calls += 1
        return object() if self.allowed else None


class _ControlWriteRequestRepository:
    """Record whether an accepted identity was consulted after authorization."""

    def __init__(self, existing: ChatWriteRequest | None) -> None:
        self.existing = existing
        self.lookup_calls = 0

    async def get_by_client_request_id(
        self,
        db_session: AsyncSession,
        *,
        session_id: str,
        requester_user_id: str,
        client_request_id: str,
    ) -> ChatWriteRequest | None:
        del db_session
        assert (session_id, requester_user_id, client_request_id) == (
            "session-1",
            "user-1",
            "request-1",
        )
        self.lookup_calls += 1
        return self.existing


class _ControlInputBufferService:
    """Fail if a replay reaches mutable pending-input inspection."""

    async def list_by_session_id(
        self,
        db_session: AsyncSession,
        session_id: str,
    ) -> list[InputBuffer]:
        del db_session, session_id
        raise AssertionError("Mutable pending-input state was inspected before replay")


def _control_service(
    *,
    membership_allowed: bool,
    existing: ChatWriteRequest | None = None,
    control_session: AgentSession | None = None,
    subtree: list[AgentSession] | None = None,
) -> tuple[
    ChatWriteService,
    _ControlWorkspaceUserRepository,
    _ControlWriteRequestRepository,
    _ControlAgentSessionRepository,
]:
    """Build a service that pins public-control admission ordering."""
    workspace_users = _ControlWorkspaceUserRepository(allowed=membership_allowed)
    writes = _ControlWriteRequestRepository(existing)
    sessions = _ControlAgentSessionRepository(
        control_session or _control_session(),
        subtree=subtree,
    )
    service = ChatWriteService(
        agent_repository=cast(AgentRepository, _ControlAgentRepository()),
        agent_session_repository=cast(AgentSessionRepository, sessions),
        workspace_user_repository=cast(WorkspaceUserRepository, workspace_users),
        agent_run_repository=cast(AgentRunRepository, object()),
        chat_write_request_repository=cast(ChatWriteRequestRepository, writes),
        message_repository=cast(MessageRepository, object()),
        exchange_file_service=cast(ExchangeFileService, object()),
        input_buffer_service=cast(InputBufferService, _ControlInputBufferService()),
        session_manager=_session_manager_double,
    )
    return service, workspace_users, writes, sessions


class TestChatWriteService:
    """REST chat write service behavior."""

    async def test_edit_reauthorizes_before_idempotency_lookup(
        self,
    ) -> None:
        """A revoked requester cannot inspect an accepted edit replay."""
        service, workspace_users, writes, _ = _control_service(
            membership_allowed=False,
            existing=_existing_record(
                write_type=ChatWriteRequestType.EDIT_MESSAGE,
                payload={"message": "edited"},
            ),
        )

        try:
            await service.create_idempotent_edit_input(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
                client_request_id="request-1",
                message_id="message-1",
                text="edited",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=ModelReasoningEffort.HIGH,
                ),
                metadata={},
                attachments=[],
                file_parts=[],
                payload={"message": "edited"},
            )
        except ValueError as exc:
            assert str(exc) == "Requester does not have session access"
        else:
            raise AssertionError("Expected ValueError")

        assert workspace_users.calls == 1
        assert writes.lookup_calls == 0

    async def test_pending_command_reauthorizes_before_idempotency_lookup(
        self,
    ) -> None:
        """A revoked requester cannot inspect an accepted command replay."""
        service, workspace_users, writes, _ = _control_service(
            membership_allowed=False,
            existing=_existing_record(
                write_type=ChatWriteRequestType.COMMAND,
                payload={"command": "compact"},
            ),
        )

        try:
            await service.create_idempotent_pending_command(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
                client_request_id="request-1",
                command_name="compact",
                payload={"command": "compact"},
            )
        except ValueError as exc:
            assert str(exc) == "Requester does not have session access"
        else:
            raise AssertionError("Expected ValueError")

        assert workspace_users.calls == 1
        assert writes.lookup_calls == 0

    async def test_failed_run_retry_reauthorizes_before_idempotency_lookup(
        self,
    ) -> None:
        """A revoked requester cannot inspect an accepted retry replay."""
        service, workspace_users, writes, _ = _control_service(
            membership_allowed=False,
            existing=_existing_record(
                write_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                payload={"failed_event_id": "failed-event-1"},
                accepted_id="failed-event-1",
            ),
        )

        try:
            await service.create_idempotent_failed_run_retry(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
                client_request_id="request-1",
                failed_event_id="failed-event-1",
                payload={"failed_event_id": "failed-event-1"},
            )
        except ValueError as exc:
            assert str(exc) == "Requester does not have session access"
        else:
            raise AssertionError("Expected ValueError")

        assert workspace_users.calls == 1
        assert writes.lookup_calls == 0

    async def test_stop_reauthorizes_before_root_tree_lock(
        self,
    ) -> None:
        """A revoked requester cannot enumerate or stop a root Session tree."""
        service, workspace_users, writes, sessions = _control_service(
            membership_allowed=False,
        )

        try:
            await service.request_session_stop(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
            )
        except ValueError as exc:
            assert str(exc) == "Requester does not have session access"
        else:
            raise AssertionError("Expected ValueError")

        assert workspace_users.calls == 1
        assert writes.lookup_calls == 0
        assert sessions.tree_lock_calls == 0
        assert sessions.stop_requests == []

    async def test_replays_before_transient_idle_and_pending_input_checks(
        self,
    ) -> None:
        """An authorized replay remains stable after the Session becomes running."""
        running = _control_session(
            run_state=AgentSessionRunState.RUNNING,
            pending_command_id="pending-command-1",
        )
        command_service, command_users, command_writes, _ = _control_service(
            membership_allowed=True,
            control_session=running,
            existing=_existing_record(
                write_type=ChatWriteRequestType.COMMAND,
                payload={"command": "compact"},
            ),
        )
        command = await command_service.create_idempotent_pending_command(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            client_request_id="request-1",
            command_name="compact",
            payload={"command": "compact"},
        )

        edit_service, edit_users, edit_writes, _ = _control_service(
            membership_allowed=True,
            control_session=running,
            existing=_existing_record(
                write_type=ChatWriteRequestType.EDIT_MESSAGE,
                payload={"message": "edited"},
            ),
        )
        edit = await edit_service.create_idempotent_edit_input(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            client_request_id="request-1",
            message_id="message-1",
            text="edited",
            inference_profile=RequestedInferenceProfile(
                model_target_label="Primary",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            metadata={},
            attachments=[],
            file_parts=[],
            payload={"message": "edited"},
        )

        retry_service, retry_users, retry_writes, _ = _control_service(
            membership_allowed=True,
            control_session=running,
            existing=_existing_record(
                write_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                payload={"failed_event_id": "failed-event-1"},
                accepted_id="failed-event-1",
            ),
        )
        retry = await retry_service.create_idempotent_failed_run_retry(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            client_request_id="request-1",
            failed_event_id="failed-event-1",
            payload={"failed_event_id": "failed-event-1"},
        )

        assert command.request.created is False
        assert command.command_id is None
        assert edit.request.created is False
        assert edit.input_buffer is None
        assert retry.request.created is False
        assert retry.failed_event_id == "failed-event-1"
        assert command_users.calls == edit_users.calls == retry_users.calls == 1
        assert command_writes.lookup_calls == edit_writes.lookup_calls == 1
        assert retry_writes.lookup_calls == 1

    async def test_stop_rejects_a_mismatched_root_tree_before_side_effects(
        self,
    ) -> None:
        """A corrupt tree cannot broaden stop effects beyond the locked root."""
        mismatched_child = AgentSession.model_construct(
            id="child-session-1",
            workspace_id="workspace-2",
            agent_id="agent-1",
        )
        service, _, _, sessions = _control_service(
            membership_allowed=True,
            subtree=[_control_session(), mismatched_child],
        )

        try:
            await service.request_session_stop(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
            )
        except ValueError as exc:
            assert str(exc) == "Session subtree is outside the root tree"
        else:
            raise AssertionError("Expected ValueError")

        assert sessions.tree_lock_calls == 1
        assert sessions.stop_requests == []

    async def test_pending_command_rejects_subagent_session_before_write(
        self,
    ) -> None:
        """Direct REST control writes cannot target child subagent sessions."""
        calls: list[str] = []
        service = ChatWriteService(
            agent_repository=cast(AgentRepository, object()),
            agent_session_repository=_SubagentLockRepository(calls),
            workspace_user_repository=cast(
                WorkspaceUserRepository,
                _WorkspaceUserRepository(),
            ),
            agent_run_repository=cast(AgentRunRepository, object()),
            chat_write_request_repository=cast(ChatWriteRequestRepository, object()),
            message_repository=cast(MessageRepository, object()),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=cast(InputBufferService, object()),
            session_manager=_session_manager_double,
        )

        try:
            await service.create_idempotent_pending_command(
                agent_id="agent-1",
                session_id="subagent-session",
                user_id="user-1",
                client_request_id="subagent-command",
                command_name="compact",
                payload={"command": "compact"},
            )
        except ValueError as exc:
            assert str(exc) == "Subagent sessions are read-only"
        else:
            raise AssertionError("Expected ValueError")
        assert calls == ["lock_by_id"]

    async def test_idempotency_record_for_another_session_is_rejected(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject existing idempotency records from another explicit session."""
        service = ChatWriteService(
            agent_repository=AgentRepository(),
            agent_session_repository=AgentSessionRepository(),
            workspace_user_repository=cast(
                WorkspaceUserRepository,
                _WorkspaceUserRepository(),
            ),
            agent_run_repository=AgentRunRepository(),
            chat_write_request_repository=_ExistingWriteRequestRepository(
                "2223456789abcdef0123456789abcdef"
            ),
            message_repository=MessageRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=InputBufferService(
                session_manager=rdb_session_manager,
                input_buffer_repository=InputBufferRepository(),
                exchange_file_service=_ExchangeFileService(),
                model_file_service=cast(ModelFileService, object()),
                agent_session_repository=AgentSessionRepository(),
                event_transcript_repository=EventTranscriptRepository(),
                agent_run_repository=AgentRunRepository(),
                action_execution_repository=ActionExecutionRepository(),
                vfs_projection_service=None,
                external_channel_repository=ExternalChannelRepository(),
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

    async def test_stop_request_targets_session_agent_subtree(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Stop requests cover the requested SessionAgent subtree."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-stop-subtree",
            )
            user_id = await _create_user(
                session,
                "chat-write-stop-subtree@example.com",
            )
            agent_id = await _create_agent(session, workspace_id, "chat-write-stop")
            session_repo = AgentSessionRepository()
            root_session = (
                await session_repo.ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session
            root_agent = await session_repo.get_session_agent_by_session_id(
                session,
                root_session.id,
            )
            assert root_agent is not None
            child_agent = await session_repo.create_child_session_agent(
                session,
                parent_session_agent_id=root_agent.id,
                name="child",
                agent_type="default",
                title="child",
                last_task_message="work",
            )
            await session_repo.mark_running(session, root_session.id)
            await session_repo.mark_running(session, child_agent.agent_session_id)

        result = await _service(rdb_session_manager).request_session_stop(
            agent_id=agent_id,
            session_id=root_session.id,
            user_id=user_id,
        )

        assert result.runtime_was_running is True
        assert result.stopped_session_ids == [
            root_session.id,
            child_agent.agent_session_id,
        ]
        async with rdb_session_manager() as session:
            root_after = await AgentSessionRepository().get_by_id(
                session,
                root_session.id,
            )
            child_after = await AgentSessionRepository().get_by_id(
                session,
                child_agent.agent_session_id,
            )
            assert root_after is not None
            assert child_after is not None
            assert root_after.stop_request_id == result.stop_request_id
            assert child_after.stop_request_id == result.stop_request_id

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
            ).session
            transcript_repo = EventTranscriptRepository()
            target = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(
                        sender_user_id=None, content="original"
                    ).model_dump(mode="json"),
                ),
            )
            later = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(
                        sender_user_id=None, content="later"
                    ).model_dump(mode="json"),
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
            inference_profile=RequestedInferenceProfile(
                model_target_label="Primary",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            metadata={"source": "chat"},
            attachments=[],
            file_parts=[],
            payload={"message": "edited"},
        )

        assert result.input_buffer is not None
        assert result.input_buffer.kind == InputBufferKind.USER_MESSAGE
        assert result.input_buffer.content == "edited"
        assert result.input_buffer.requested_model_target_label == "Primary"
        assert (
            result.input_buffer.requested_reasoning_effort == ModelReasoningEffort.HIGH
        )
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
            ).session
            transcript_repo = EventTranscriptRepository()
            user_event = await transcript_repo.append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(
                        sender_user_id=None, content="do the task"
                    ).model_dump(mode="json"),
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
            run_repo = AgentRunRepository()
            original_run = await run_repo.create(
                session,
                AgentRunCreate(
                    session_id=agent_session.id,
                    parent_agent_run_id=None,
                ),
            )
            await run_repo.associate_input_events(
                session,
                run_id=original_run.id,
                event_ids=[user_event.id],
            )
            await run_repo.mark_terminal(
                session,
                original_run.id,
                AgentRunStatus.FAILED,
                ended_at=datetime.datetime.now(datetime.UTC),
                terminal_result_event_id=failed_event.id,
                terminal_result_message="temporary failure",
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
            associated_runs = await AgentRunRepository().list_by_input_event_id(
                session,
                event_id=user_event.id,
            )
            assert len(associated_runs) == 2
            assert associated_runs[0].id == original_run.id
            retry_run = associated_runs[1]
            assert retry_run.status == AgentRunStatus.PENDING
            assert retry_run.parent_agent_run_id == original_run.parent_agent_run_id
            session_after = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            assert session_after is not None
            assert session_after.run_state == AgentSessionRunState.RUNNING
            assert session_after.inference_state is None

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
        async with rdb_session_manager() as session:
            associated_runs = await AgentRunRepository().list_by_input_event_id(
                session,
                event_id=user_event.id,
            )
            assert len(associated_runs) == 2

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
            ).session
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
                    payload=UserMessagePayload(
                        sender_user_id=None, content="newer context"
                    ).model_dump(mode="json"),
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
            first = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session

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
