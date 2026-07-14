"""REST chat write service tests."""

import datetime
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import cast

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
    LLMProvider,
    WorkspaceUserRole,
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
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
    ChatWriteRequestCreateResult,
)
from azents.repos.chat_write_request.repository import ChatWriteRequestRepository
from azents.repos.input_buffer.repository import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.services.chat.data import SessionAccessDenied
from azents.services.chat_write import (
    ChatWriteService,
    ChatWriteSessionAccessDenied,
)
from azents.services.exchange_file import ExchangeFileService
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


class _AllowWorkspaceUserRepository(WorkspaceUserRepository):
    """Workspace membership lock double that always authorizes."""

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser:
        """Return a membership sentinel."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        return WorkspaceUser(
            id="workspace-user-1",
            workspace_id=workspace_id,
            user_id=user_id,
            name="Chat write test user",
            locale="en-US",
            role=WorkspaceUserRole.MEMBER,
            created_at=now,
            updated_at=now,
        )


class _RecordingWorkspaceUserRepository(_AllowWorkspaceUserRepository):
    """Membership lock double that records subtree lock ordering."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser:
        """Record the membership lock after every subtree Session lock."""
        self.calls.append("lock_workspace_user")
        return await super().lock_by_workspace_and_user(
            session,
            workspace_id,
            user_id,
        )


class _StopSubtreeRepository(AgentSessionRepository):
    """Subtree stop repository double with deliberately unsorted IDs."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    @staticmethod
    def _session(
        session_id: str, *, stop_request_id: str | None = None
    ) -> AgentSession:
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            id=session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle=session_id,
            inference_state=None,
            session_kind=AgentSessionKind.ROOT,
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=now,
            started_at=now,
            run_state=AgentSessionRunState.RUNNING,
            owner_generation=0,
            stop_requested_at=now if stop_request_id is not None else None,
            stop_request_id=stop_request_id,
            created_at=now,
            updated_at=now,
        )

    async def list_session_agent_subtree_session_ids(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
    ) -> list[str]:
        """Record the root tree fence and return child before parent."""
        del session
        assert agent_session_id == "session-b"
        self.calls.append("lock_root_session_agent")
        return ["session-b", "session-a"]

    async def lock_by_ids(
        self,
        session: AsyncSession,
        *,
        agent_session_ids: Sequence[str],
    ) -> dict[str, AgentSession]:
        """Record deterministic Session lock acquisition."""
        del session
        sessions: dict[str, AgentSession] = {}
        for agent_session_id in sorted(set(agent_session_ids)):
            self.calls.append(f"lock_session:{agent_session_id}")
            sessions[agent_session_id] = self._session(agent_session_id)
        return sessions

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        user_id: str | None,
    ) -> AgentSession:
        """Record the mutation after membership authorization."""
        del session, user_id
        self.calls.append(f"request_stop:{session_id}")
        return self._session(session_id, stop_request_id=stop_request_id)


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


async def _create_user(
    session: AsyncSession,
    email: str,
    *,
    workspace_id: str | None = None,
) -> str:
    user = await UserRepository().create(session, UserCreate(email=email))
    if workspace_id is not None:
        created = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Chat write test user",
                locale="en-US",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(created, Success)
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
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        toolkit_state_repository=ToolkitStateRepository(),
    )
    return ChatWriteService(
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AgentRunRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        message_repository=MessageRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
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
    ) -> ChatWriteRequestCreateResult:
        """Return an existing idempotency record for another session."""
        del session
        return ChatWriteRequestCreateResult(
            record=ChatWriteRequest(
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
            created=False,
        )


class TestChatWriteService:
    """REST chat write service behavior."""

    async def test_stop_locks_entire_subtree_before_membership(self) -> None:
        """Parent stop cannot invert child Session -> WorkspaceUser write order."""
        calls: list[str] = []
        service = ChatWriteService(
            agent_session_repository=_StopSubtreeRepository(calls),
            agent_run_repository=cast(AgentRunRepository, object()),
            chat_write_request_repository=cast(ChatWriteRequestRepository, object()),
            message_repository=cast(MessageRepository, object()),
            workspace_user_repository=_RecordingWorkspaceUserRepository(calls),
            input_buffer_service=cast(InputBufferService, object()),
            session_manager=_session_manager_double,
        )

        result = await service.request_session_stop(
            session_id="session-b",
            user_id="user-1",
        )

        assert isinstance(result, Success)
        assert result.value.stopped_session_ids == ["session-b", "session-a"]
        assert calls == [
            "lock_root_session_agent",
            "lock_session:session-a",
            "lock_session:session-b",
            "lock_workspace_user",
            "request_stop:session-b",
            "request_stop:session-a",
        ]

    async def test_pending_command_rejects_subagent_session_before_write(
        self,
    ) -> None:
        """Direct REST control writes cannot target child subagent sessions."""
        calls: list[str] = []
        service = ChatWriteService(
            agent_session_repository=_SubagentLockRepository(calls),
            agent_run_repository=cast(AgentRunRepository, object()),
            chat_write_request_repository=cast(ChatWriteRequestRepository, object()),
            message_repository=cast(MessageRepository, object()),
            workspace_user_repository=_AllowWorkspaceUserRepository(),
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
            agent_session_repository=AgentSessionRepository(),
            agent_run_repository=AgentRunRepository(),
            chat_write_request_repository=_ExistingWriteRequestRepository(
                "2223456789abcdef0123456789abcdef"
            ),
            message_repository=MessageRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=InputBufferService(
                session_manager=rdb_session_manager,
                input_buffer_repository=InputBufferRepository(),
                exchange_file_service=_ExchangeFileService(),
                model_file_service=_ModelFileService(),
                agent_session_repository=AgentSessionRepository(),
                event_transcript_repository=EventTranscriptRepository(),
                agent_run_repository=AgentRunRepository(),
                action_execution_repository=ActionExecutionRepository(),
                toolkit_state_repository=ToolkitStateRepository(),
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
                workspace_id=workspace_id,
            )
            agent_id = await _create_agent(session, workspace_id, "chat-write-stop")
            session_repo = AgentSessionRepository()
            root_session = await session_repo.ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
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
            grandchild_agent = await session_repo.create_child_session_agent(
                session,
                parent_session_agent_id=child_agent.id,
                name="grandchild",
                agent_type="default",
                title="grandchild",
                last_task_message="nested work",
            )
            await session_repo.mark_running(session, root_session.id)
            await session_repo.mark_running(session, child_agent.agent_session_id)
            await session_repo.mark_running(
                session,
                grandchild_agent.agent_session_id,
            )

        result = await _service(rdb_session_manager).request_session_stop(
            session_id=root_session.id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        accepted = result.value
        assert accepted.runtime_was_running is True
        assert accepted.stopped_session_ids == [
            root_session.id,
            child_agent.agent_session_id,
            grandchild_agent.agent_session_id,
        ]
        assert accepted.stop_request_ids_by_session == {
            root_session.id: accepted.stop_request_id,
            child_agent.agent_session_id: accepted.stop_request_id,
            grandchild_agent.agent_session_id: accepted.stop_request_id,
        }
        async with rdb_session_manager() as session:
            root_after = await AgentSessionRepository().get_by_id(
                session,
                root_session.id,
            )
            child_after = await AgentSessionRepository().get_by_id(
                session,
                child_agent.agent_session_id,
            )
            grandchild_after = await AgentSessionRepository().get_by_id(
                session,
                grandchild_agent.agent_session_id,
            )
            assert root_after is not None
            assert child_after is not None
            assert grandchild_after is not None
            assert root_after.stop_request_id == accepted.stop_request_id
            assert child_after.stop_request_id == accepted.stop_request_id
            assert grandchild_after.stop_request_id == accepted.stop_request_id

    async def test_stop_request_signals_only_sessions_with_committed_intent(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An idle descendant cannot receive a delayed signal for a future Run."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-stop-running-only",
            )
            user_id = await _create_user(
                session,
                "chat-write-stop-running-only@example.com",
                workspace_id=workspace_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "chat-write-stop-running-only",
            )
            session_repo = AgentSessionRepository()
            root_session = await session_repo.ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            root_agent = await session_repo.get_session_agent_by_session_id(
                session,
                root_session.id,
            )
            assert root_agent is not None
            idle_child = await session_repo.create_child_session_agent(
                session,
                parent_session_agent_id=root_agent.id,
                name="idle-child",
                agent_type="default",
                title="idle-child",
                last_task_message="waiting",
            )
            await session_repo.mark_running(session, root_session.id)

        result = await _service(rdb_session_manager).request_session_stop(
            session_id=root_session.id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        assert result.value.stopped_session_ids == [root_session.id]
        async with rdb_session_manager() as session:
            child_after = await AgentSessionRepository().get_by_id(
                session,
                idle_child.agent_session_id,
            )
        assert child_after is not None
        assert child_after.stop_request_id is None

    async def test_stop_request_rechecks_revoked_membership_before_mutation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A stale API access check cannot authorize a stop after membership revoke."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-stop-revoked-member",
            )
            user_id = await _create_user(
                session,
                "chat-write-stop-revoked-member@example.com",
                workspace_id=workspace_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "chat-write-stop-revoked-member",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            await AgentSessionRepository().mark_running(session, agent_session.id)
            membership = await WorkspaceUserRepository().get_by_workspace_and_user(
                session,
                workspace_id,
                user_id,
            )
            assert membership is not None
            await WorkspaceUserRepository().delete(session, membership.id)

        result = await _service(rdb_session_manager).request_session_stop(
            session_id=agent_session.id,
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)
        async with rdb_session_manager() as session:
            unchanged = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
        assert unchanged is not None
        assert unchanged.stop_request_id is None

    async def test_stop_request_repairs_idle_session_with_active_run(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An active durable Run remains stoppable if Session run_state drifted."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-stop-active-run",
            )
            user_id = await _create_user(
                session,
                "chat-write-stop-active-run@example.com",
                workspace_id=workspace_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "chat-write-stop-active-run",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            active_run = await AgentRunRepository().create_pending(
                session,
                session_id=agent_session.id,
                parent_agent_run_id=None,
            )
            assert agent_session.run_state == AgentSessionRunState.IDLE

        result = await _service(rdb_session_manager).request_session_stop(
            session_id=agent_session.id,
            user_id=user_id,
        )
        assert isinstance(result, Success)
        accepted = result.value

        assert accepted.stopped_session_ids == [agent_session.id]
        repeated = await _service(rdb_session_manager).request_session_stop(
            session_id=agent_session.id,
            user_id=user_id,
        )
        assert isinstance(repeated, Success)
        async with rdb_session_manager() as session:
            stopped = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            stopped_run = await AgentRunRepository().get_by_id(
                session,
                active_run.id,
            )
        assert stopped is not None
        assert stopped.stop_request_id == accepted.stop_request_id
        assert repeated.value.stop_request_ids_by_session == {
            agent_session.id: accepted.stop_request_id
        }
        assert stopped_run is not None
        assert stopped_run.stop_requested_at == stopped.stop_requested_at

    async def test_command_rechecks_revoked_membership_before_mutation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A stale API access check cannot authorize a command after revoke."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "chat-write-command-revoked-member",
            )
            user_id = await _create_user(
                session,
                "chat-write-command-revoked-member@example.com",
                workspace_id=workspace_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "chat-write-command-revoked-member",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            )
            membership = await WorkspaceUserRepository().get_by_workspace_and_user(
                session,
                workspace_id,
                user_id,
            )
            assert membership is not None
            await WorkspaceUserRepository().delete(session, membership.id)

        with pytest.raises(ChatWriteSessionAccessDenied):
            await _service(rdb_session_manager).create_idempotent_pending_command(
                agent_id=agent_id,
                session_id=agent_session.id,
                user_id=user_id,
                client_request_id="revoked-command",
                command_name="compact",
                payload={"command": "compact"},
            )

        async with rdb_session_manager() as session:
            unchanged = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            request = await ChatWriteRequestRepository().get_by_client_request_id(
                session,
                session_id=agent_session.id,
                user_id=user_id,
                client_request_id="revoked-command",
            )
        assert unchanged is not None
        assert unchanged.pending_command_id is None
        assert request is None

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
            user_id = await _create_user(
                session,
                "chat-write-edit-head@example.com",
                workspace_id=workspace_id,
            )
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
        repeated = await _service(rdb_session_manager).create_idempotent_edit_input(
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
            metadata={"source": "chat", "timestamp": "retry"},
            attachments=[],
            file_parts=[],
            payload={"message": "edited"},
        )
        assert repeated.request.created is False
        assert repeated.input_buffer is not None
        assert repeated.input_buffer.id == result.input_buffer.id
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
                workspace_id=workspace_id,
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
        assert repeated.wake_needed is True
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
                workspace_id=workspace_id,
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
                workspace_id=workspace_id,
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
        first_result = await service.create_idempotent_pending_command(
            agent_id=agent_id,
            session_id=first.id,
            user_id=user_id,
            client_request_id="same-client-request",
            command_name="compact",
            payload=payload,
        )
        repeated = await service.create_idempotent_pending_command(
            agent_id=agent_id,
            session_id=first.id,
            user_id=user_id,
            client_request_id="same-client-request",
            command_name="compact",
            payload=payload,
        )
        assert repeated.request.created is False
        assert repeated.command_id == first_result.command_id

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
