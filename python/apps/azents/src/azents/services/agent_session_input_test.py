"""AgentSessionInputService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    InputBufferSchedulingMode,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.services.exchange_file import (
    ExchangeFileInputClaimError,
    ExchangeFileService,
    FileRetentionOwnerConflict,
)
from azents.services.model_file import ModelFileService
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.testing.model_selection import make_test_model_selection_dict

from .agent_session_input import (
    AgentSessionInputIdempotencyConflict,
    AgentSessionInputInactiveSession,
    AgentSessionInputService,
    AgentSessionInputSubagentReadOnly,
)
from .input_buffer import (
    InputBufferEnqueue,
    InputBufferEnqueueResult,
    InputBufferService,
)

_TEST_INFERENCE_PROFILE = RequestedInferenceProfile(
    model_target_label="Primary",
    reasoning_effort=None,
)


@asynccontextmanager
async def _session_manager_double() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder DB session for service-double tests."""
    yield cast(AsyncSession, object())


class _RuntimeRepositoryDouble(AgentRuntimeRepository):
    """Runtime repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Ensure runtime."""
        del session, agent_id, default_runtime_provider_id
        self.calls.append("ensure_for_agent")
        now = datetime.datetime.now(datetime.UTC)
        return AgentRuntime(
            id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            created_at=now,
            updated_at=now,
        )


class _ActiveAgentRepositoryDouble(AgentRepository):
    """Repository double that returns a lifecycle-admitted Agent."""

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        """Return a minimal active Agent projection."""
        del session, agent_id
        return cast(
            Agent,
            SimpleNamespace(
                lifecycle_status=AgentLifecycleStatus.ACTIVE,
                workspace_id="workspace-1",
            ),
        )


class _WorkspaceUserRepositoryDouble(WorkspaceUserRepository):
    """Workspace membership repository for admission unit tests."""

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser:
        """Return a locked admitted membership marker."""
        del session, workspace_id, user_id
        return cast(WorkspaceUser, object())


class _AgentSessionRepositoryDouble(AgentSessionRepository):
    """AgentSession repository for tests."""

    def __init__(
        self,
        calls: list[str],
        *,
        session_kind: AgentSessionKind = AgentSessionKind.ROOT,
    ) -> None:
        self.calls = calls
        self.session_kind = session_kind

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        """Lock and fetch session."""
        del session
        self.calls.append("get_by_id")
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            owner_generation=0,
            inference_state=None,
            id=agent_session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="test-session-handle",
            session_kind=self.session_kind,
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

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Record wake transition."""
        del session, session_id
        self.calls.append("mark_running_for_input_wakeup")


class _InputBufferServiceDouble(InputBufferService):
    """InputBufferService double for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.enqueued: InputBufferEnqueue | None = None
        self.moved: tuple[str, str] | None = None

    async def enqueue(
        self,
        session: AsyncSession,
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
            scheduling_mode=input.scheduling_mode,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=input.sender_user_id,
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
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Record InputBuffer move request."""
        del session
        self.calls.append("move_input_buffer")
        self.moved = (from_session_id, to_session_id)
        return 1


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


class _RejectingExchangeFileService(_ExchangeFileService):
    """Reject attachment claims as cross-root conflicts."""

    async def claim_input_attachments(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        attachment_uris: list[str],
    ) -> Result[None, ExchangeFileInputClaimError]:
        """Reject claims after input enqueue to exercise transaction rollback."""
        del session, agent_id, session_id, user_id, attachment_uris
        return Failure(FileRetentionOwnerConflict())


def _root_agent_session_creation_service() -> RootAgentSessionCreationService:
    """Build root Session creation service for tests."""
    return RootAgentSessionCreationService(
        agent_session_repository=AgentSessionRepository(),
        automatic_project_repository=AgentAutomaticProjectRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
    )


def _input_buffer_service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> InputBufferService:
    """Create InputBufferService for integration tests."""
    return InputBufferService(
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
            name="AgentSession input user",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(result, Success)


class TestAgentSessionInputService:
    """AgentSessionInputService tests."""

    async def test_create_buffered_agent_input_marks_running_before_return(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """REST input storage marks runtime running before broker send."""
        calls: list[str] = []
        runtime_repository = _RuntimeRepositoryDouble(calls)
        session_repository = _AgentSessionRepositoryDouble(calls)
        input_buffer_service = _InputBufferServiceDouble(calls)
        service = AgentSessionInputService(
            agent_repository=_ActiveAgentRepositoryDouble(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=runtime_repository,
            agent_session_repository=session_repository,
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_WorkspaceUserRepositoryDouble(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=input_buffer_service,
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="restore me",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            request_payload={"request": "test"},
        )

        assert isinstance(result, Success)
        value = result.value
        assert value.agent_runtime_id == "runtime-1"
        assert value.agent_session_id == "session-1"
        assert value.input_buffer is not None
        assert value.input_buffer.id == "buffer-1"
        assert calls == [
            "get_by_id",
            "ensure_for_agent",
            "enqueue_input_buffer",
            "mark_running_for_input_wakeup",
        ]
        assert input_buffer_service.enqueued is not None
        assert input_buffer_service.enqueued.session_id == "session-1"
        assert (
            input_buffer_service.enqueued.scheduling_mode
            == InputBufferSchedulingMode.WAKE_SESSION
        )
        assert input_buffer_service.enqueued.content == "restore me"

    async def test_attachment_claim_failure_rolls_back_buffer_acceptance(self) -> None:
        """A cross-root claim conflict cannot leave a pending input behind."""
        calls: list[str] = []
        db_session = AsyncMock(spec=AsyncSession)

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield db_session

        input_buffer_service = _InputBufferServiceDouble(calls)
        service = AgentSessionInputService(
            agent_repository=_ActiveAgentRepositoryDouble(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=_RuntimeRepositoryDouble(calls),
            agent_session_repository=_AgentSessionRepositoryDouble(calls),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_WorkspaceUserRepositoryDouble(),
            exchange_file_service=_RejectingExchangeFileService(),
            input_buffer_service=input_buffer_service,
            session_manager=session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="conflicting attachment",
                headers=[],
                metadata={"source": "chat"},
                attachments=["exchange://workspace-1/file-1"],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            request_payload={"request": "test"},
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, FileRetentionOwnerConflict)
        db_session.rollback.assert_awaited_once()
        assert calls == [
            "get_by_id",
            "ensure_for_agent",
            "enqueue_input_buffer",
        ]
        assert input_buffer_service.enqueued is not None

    async def test_create_buffered_agent_input_rejects_subagent_before_wake(
        self,
    ) -> None:
        """Do not enqueue direct input or wake runtime for a child subagent."""
        calls: list[str] = []
        runtime_repository = _RuntimeRepositoryDouble(calls)
        session_repository = _AgentSessionRepositoryDouble(
            calls,
            session_kind=AgentSessionKind.SUBAGENT,
        )
        input_buffer_service = _InputBufferServiceDouble(calls)
        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=runtime_repository,
            agent_session_repository=session_repository,
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_WorkspaceUserRepositoryDouble(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=input_buffer_service,
            session_manager=_session_manager_double,
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="blocked",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            request_payload={"request": "test"},
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputSubagentReadOnly)
        assert calls == ["get_by_id"]
        assert input_buffer_service.enqueued is None

    async def test_create_team_session_with_buffered_input_bootstraps_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """First draft input creates a session with explicit Projects."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "draft-session-input")
            user_id = await _create_user(session, "draft-session-input@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "draft-session-input")
            primary = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session
            await SessionWorkspaceProjectRepository().create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=primary.id,
                    path="/workspace/agent/project-a",
                ),
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="first draft message",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[
                "/workspace/agent/project-a/nested",
                "/workspace/agent/project-a/nested",
            ],
            setup_actions=[],
            request_payload={"request": "draft-client-1"},
            client_request_id="draft-client-1",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        assert created.agent_id == agent_id
        assert created.primary_kind is None
        input_buffer = result.value.input_buffer
        assert input_buffer is not None
        assert input_buffer.session_id == created.id
        assert input_buffer.content == "first draft message"
        assert input_buffer.idempotency_key == "draft-client-1"
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=created.id,
            )
            defaults = await AgentProjectDefaultRepository().list_defaults(
                session,
                agent_id=agent_id,
            )
            catalog_entries = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
            updated = await AgentSessionRepository().get_by_id(session, created.id)

        assert [item.primary_kind for item in sessions] == [
            AgentSessionPrimaryKind.TEAM_PRIMARY,
            None,
        ]
        assert [project.path for project in projects] == [
            "/workspace/agent/project-a/nested"
        ]
        assert [default.path for default in defaults] == [
            "/workspace/agent/project-a/nested"
        ]
        assert [entry.path for entry in catalog_entries] == [
            "/workspace/agent/project-a/nested"
        ]
        assert updated is not None
        assert updated.run_state == AgentSessionRunState.RUNNING

    async def test_new_session_retry_reuses_admitted_session_and_input(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """One Agent-scoped client request creates exactly one Session and input."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "draft-session-idempotent",
            )
            user_id = await _create_user(
                session,
                "draft-session-idempotent@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "draft-session-idempotent",
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )
        message = InputMessage(
            text="one durable first message",
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        )
        request_payload: dict[str, object] = {
            "agent_id": agent_id,
            "client_request_id": "draft-session-request",
            "message": message.text,
        }

        first = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload=request_payload,
            client_request_id="draft-session-request",
        )
        second = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload=request_payload,
            client_request_id="draft-session-request",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        assert first.value.created is True
        assert second.value.created is False
        assert second.value.agent_session.id == first.value.agent_session.id
        assert (
            second.value.accepted_input_buffer_id
            == first.value.accepted_input_buffer_id
        )
        assert second.value.input_buffer is not None
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                first.value.agent_session.id,
            )
        assert len(sessions) == 2
        assert [item.id for item in buffers] == [first.value.accepted_input_buffer_id]

    async def test_new_session_retry_rejects_changed_payload(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An Agent-scoped client key cannot create a second changed Session."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "draft-session-idempotency-conflict",
            )
            user_id = await _create_user(
                session,
                "draft-session-idempotency-conflict@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "draft-session-idempotency-conflict",
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )
        message = InputMessage(
            text="original",
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        )
        first = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"message": "original"},
            client_request_id="draft-session-conflict",
        )
        conflict = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"message": "changed"},
            client_request_id="draft-session-conflict",
        )

        assert isinstance(first, Success)
        assert isinstance(conflict, Failure)
        assert isinstance(conflict.error, AgentSessionInputIdempotencyConflict)
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
        assert len(sessions) == 2

    async def test_new_session_attachment_conflict_rolls_back_session_and_input(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """First-message claim failure removes the new Session and InputBuffer."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "draft-session-claim-conflict",
            )
            user_id = await _create_user(
                session,
                "draft-session-claim-conflict@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "draft-session-claim-conflict",
            )
            primary = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_RejectingExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="first draft message",
                headers=[],
                metadata={"source": "chat"},
                attachments=["exchange://workspace-1/file-1"],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"request": "draft-claim-conflict"},
            client_request_id="draft-claim-conflict",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, FileRetentionOwnerConflict)
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            primary_buffers = await InputBufferRepository().list_by_session_id(
                session,
                primary.id,
            )
        assert [item.id for item in sessions] == [primary.id]
        assert primary_buffers == []

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
            old_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=runtime.workspace_id,
                    agent_id=runtime.agent_id,
                )
            ).session
            await AgentSessionRepository().archive(
                session,
                old_session.id,
                ended_at=datetime.datetime.now(datetime.timezone.utc),
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=old_session.id,
            message=InputMessage(
                text="after rollover",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "test"},
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)

        async with rdb_session_manager() as session:
            old_buffers = await InputBufferRepository().list_by_session_id(
                session, old_session.id
            )
        assert old_buffers == []

    async def test_buffered_agent_input_rejects_subagent_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Direct human input cannot be enqueued into a child subagent session."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "subagent-input-readonly")
            user_id = await _create_user(session, "subagent-readonly@example.com")
            agent_id = await _create_agent(session, workspace_id, "subagent-readonly")
            root_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session
            root_agent = await AgentSessionRepository().get_session_agent_by_session_id(
                session,
                root_session.id,
            )
            assert root_agent is not None
            child_agent = await AgentSessionRepository().create_child_session_agent(
                session,
                parent_session_agent_id=root_agent.id,
                name="child",
                agent_type="default",
                title="Child",
                last_task_message=None,
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=child_agent.agent_session_id,
            message=InputMessage(
                text="direct child input",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "test"},
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputSubagentReadOnly)
        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                child_agent.agent_session_id,
            )
        assert buffers == []

    async def test_create_buffered_agent_input_marks_session_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """REST input storage marks Session running to cover broker loss."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-running")
            user_id = await _create_user(session, "buffered-running@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-running"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=runtime.workspace_id,
                    agent_id=runtime.agent_id,
                )
            ).session

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="restore me",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "test"},
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

    async def test_agent_decommission_fence_wins_before_input_admission(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Admission waits for an Agent lifecycle update and then fails closed."""
        del latest_db_schema
        suffix = uuid4().hex[:8]

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                else:
                    await session.commit()

        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"input-agent-fence-{suffix}",
            )
            user_id = await _create_user(
                setup_session,
                f"input-agent-fence-{suffix}@example.com",
            )
            await _add_workspace_user(
                setup_session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"input-agent-fence-{suffix}",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    setup_session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session
            await setup_session.commit()

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(session_manager),
            session_manager=session_manager,
        )

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as decommission_session:
            decommissioned = await AgentRepository().mark_decommissioning(
                decommission_session,
                agent_id,
            )
            assert decommissioned is not None
            admission_task = asyncio.create_task(
                service.create_buffered_agent_input(
                    agent_id=agent_id,
                    agent_session_id=agent_session.id,
                    message=InputMessage(
                        text="must not cross the decommission fence",
                        headers=[],
                        metadata={"source": "chat"},
                        attachments=[],
                    ),
                    inference_profile=_TEST_INFERENCE_PROFILE,
                    user_id=user_id,
                    request_payload={"request": "agent-fence"},
                    client_request_id="agent-fence",
                )
            )
            await asyncio.sleep(0.1)
            assert not admission_task.done()
            await decommission_session.commit()
            result = await asyncio.wait_for(admission_task, timeout=5)

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)
        async with session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                agent_session.id,
            )
        assert buffers == []

    async def test_create_buffered_agent_input_dedupes_client_request_id(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Same client_request_id returns same InputBuffer."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-idempotent")
            user_id = await _create_user(session, "buffered-idempotent@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-idempotent"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=runtime.workspace_id,
                    agent_id=runtime.agent_id,
                )
            ).session

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        first = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "test"},
            client_request_id="client-request-1",
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="retry payload ignored",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "test"},
            client_request_id="client-request-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        first_value = first.value
        second_value = second.value
        assert first_value.input_buffer is not None
        assert second_value.input_buffer is None
        assert second_value.accepted_input_buffer_id == first_value.input_buffer.id
        assert second_value.created is False
        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session, agent_session.id
            )
        assert [buffer.id for buffer in buffers] == [first_value.input_buffer.id]

    async def test_buffered_input_idempotency_is_scoped_to_requester(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Different requesters sharing a client key retain independent inputs."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "buffered-chat-requester-idempotency",
            )
            first_user_id = await _create_user(
                session,
                "buffered-requester-first@example.com",
            )
            second_user_id = await _create_user(
                session,
                "buffered-requester-second@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=first_user_id,
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=second_user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "buffered-chat-requester-idempotency",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            root_agent_session_creation_service=_root_agent_session_creation_service(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            exchange_file_service=_ExchangeFileService(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        shared_client_request_id = "shared-client-request"
        first_message = InputMessage(
            text="first requester payload",
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        )
        second_message = InputMessage(
            text="second requester payload",
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        )
        first = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=first_message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=first_user_id,
            request_payload={"content": first_message.text},
            client_request_id=shared_client_request_id,
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=second_message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=second_user_id,
            request_payload={"content": second_message.text},
            client_request_id=shared_client_request_id,
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        assert first.value.input_buffer is not None
        assert second.value.input_buffer is not None
        assert (
            first.value.accepted_input_buffer_id
            != second.value.accepted_input_buffer_id
        )

        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                agent_session.id,
            )

        assert {
            (buffer.id, buffer.sender_user_id, buffer.content) for buffer in buffers
        } == {
            (
                first.value.accepted_input_buffer_id,
                first_user_id,
                first_message.text,
            ),
            (
                second.value.accepted_input_buffer_id,
                second_user_id,
                second_message.text,
            ),
        }
        assert len({buffer.idempotency_key for buffer in buffers}) == 2

        first_retry = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=first_message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=first_user_id,
            request_payload={"content": first_message.text},
            client_request_id=shared_client_request_id,
        )
        assert isinstance(first_retry, Success)
        assert first_retry.value.created is False
        assert first_retry.value.input_buffer is not None
        assert (
            first_retry.value.accepted_input_buffer_id
            == first.value.accepted_input_buffer_id
        )

        async with rdb_session_manager() as session:
            deleted = await InputBufferRepository().delete_by_session_and_id(
                session,
                agent_session.id,
                first.value.accepted_input_buffer_id,
            )
        assert deleted

        first_post_promotion_retry = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=first_message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=first_user_id,
            request_payload={"content": first_message.text},
            client_request_id=shared_client_request_id,
        )

        assert isinstance(first_post_promotion_retry, Success)
        assert first_post_promotion_retry.value.created is False
        assert first_post_promotion_retry.value.input_buffer is None
        assert (
            first_post_promotion_retry.value.accepted_input_buffer_id
            == first.value.accepted_input_buffer_id
        )
