"""AgentSessionInputService tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from uuid import uuid4

import pytest
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    InputBufferKind,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_session_create_request.data import (
    AgentSessionCreateRequestClaim,
    AgentSessionCreateRequestClaimResult,
    AgentSessionCreateRequestRecord,
)
from azents.repos.agent_session_create_request.repository import (
    AgentSessionCreateRequestRepository,
)
from azents.repos.chat_write_request.repository import ChatWriteRequestRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.input_buffer.repository import InputBufferRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict

from .agent_session_input import (
    AgentSessionCreateRequestConflict,
    AgentSessionInputAccessDenied,
    AgentSessionInputError,
    AgentSessionInputInactiveSession,
    AgentSessionInputRequestConflict,
    AgentSessionInputService,
    AgentSessionInputSubagentReadOnly,
    CreatedAgentSessionInputResult,
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


class _FailingRuntimeRepository(AgentRuntimeRepository):
    """Runtime repository that fails after the create-request claim is written."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Raise the configured transaction-aborting error."""
        del session, agent_id, default_runtime_provider_id
        raise self.error


class _AgentRepositoryDouble(AgentRepository):
    """Agent lock double for new-session replay ordering tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent:
        """Record the Agent authority lock."""
        del session
        self.calls.append("lock_agent")
        return Agent.model_construct(id=agent_id, workspace_id="workspace-1")


class _AllowWorkspaceUserRepository(WorkspaceUserRepository):
    """Workspace membership lock double that always authorizes."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser:
        """Record and allow final-transaction authorization."""
        del session, workspace_id, user_id
        self.calls.append("lock_workspace_user")
        return cast(WorkspaceUser, object())


class _DenyWorkspaceUserRepository(WorkspaceUserRepository):
    """Workspace membership lock double that always denies."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Record and deny final-transaction authorization."""
        del session, workspace_id, user_id
        self.calls.append("lock_workspace_user")
        return None


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


class _MissingAgentSessionRepository(AgentSessionRepository):
    """AgentSession repository for a retained request tombstone."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> None:
        """Record the lookup of an already deleted accepted Session."""
        del session, agent_session_id
        self.calls.append("get_by_id")
        return None


class _CreateRequestReplayRepository(AgentSessionCreateRequestRepository):
    """Completed new-session request authority double."""

    def __init__(self, calls: list[str], input_buffer: InputBuffer) -> None:
        self.calls = calls
        self.input_buffer = input_buffer

    async def claim(
        self,
        session: AsyncSession,
        claim: AgentSessionCreateRequestClaim,
    ) -> AgentSessionCreateRequestClaimResult:
        """Return a completed replay using the requested semantic hash."""
        del session
        self.calls.append("claim_create_request")
        now = datetime.datetime.now(datetime.UTC)
        return AgentSessionCreateRequestClaimResult(
            record=AgentSessionCreateRequestRecord(
                id="create-request-1",
                user_id=claim.user_id,
                agent_id=claim.agent_id,
                client_request_id=claim.client_request_id,
                payload_hash=claim.payload_hash,
                agent_session_id=self.input_buffer.session_id,
                input_buffer_id=self.input_buffer.id,
                input_buffer_snapshot=self.input_buffer.model_dump(mode="json"),
                created_at=now,
                completed_at=now,
            ),
            claimed=False,
        )


class _CreateRequestClaimRepository(AgentSessionCreateRequestRepository):
    """New create-request claim double that records exact abandonment."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.abandoned_request_id: str | None = None

    async def claim(
        self,
        session: AsyncSession,
        claim: AgentSessionCreateRequestClaim,
    ) -> AgentSessionCreateRequestClaimResult:
        """Return a new incomplete authority."""
        del session
        self.calls.append("claim_create_request")
        return AgentSessionCreateRequestClaimResult(
            record=AgentSessionCreateRequestRecord(
                id="create-request-1",
                user_id=claim.user_id,
                agent_id=claim.agent_id,
                client_request_id=claim.client_request_id,
                payload_hash=claim.payload_hash,
                agent_session_id=None,
                input_buffer_id=None,
                input_buffer_snapshot=None,
                created_at=datetime.datetime.now(datetime.UTC),
                completed_at=None,
            ),
            claimed=True,
        )

    async def abandon_pending_claim(
        self,
        session: AsyncSession,
        *,
        request_id: str,
    ) -> None:
        """Record exact pending-claim abandonment."""
        del session
        self.calls.append("abandon_pending_claim")
        self.abandoned_request_id = request_id


class _InputBufferRepositoryDouble(InputBufferRepository):
    """InputBuffer lookup double for new-session replay ordering tests."""

    def __init__(self, calls: list[str], input_buffer: InputBuffer) -> None:
        self.calls = calls
        self.input_buffer = input_buffer

    async def get_by_id(
        self,
        session: AsyncSession,
        buffer_id: str,
    ) -> InputBuffer | None:
        """Return the replayed pending input."""
        del session
        self.calls.append("get_input_buffer")
        if buffer_id != self.input_buffer.id:
            return None
        return self.input_buffer


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
            requested_model_target_label=None,
            requested_reasoning_effort=None,
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
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        toolkit_state_repository=ToolkitStateRepository(),
    )


def _agent_session_input_service(
    session_manager: SessionManager[AsyncSession],
) -> AgentSessionInputService:
    """Create the concrete AgentSession input service for integration tests."""
    return AgentSessionInputService(
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        input_buffer_repository=InputBufferRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        input_buffer_service=_input_buffer_service(session_manager),
        session_manager=session_manager,
    )


def _committing_session_manager(
    rdb_engine: AsyncEngine,
) -> SessionManager[AsyncSession]:
    """Create independent production-like transactions for concurrency tests."""

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

    return session_manager


async def _cleanup_committed_test_scope(
    rdb_engine: AsyncEngine,
    *,
    workspace_handle: str,
    user_id: str | None,
) -> None:
    """Delete independently committed test rows in FK-safe ownership order."""
    async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
        # Workspace deletion cascades through AgentSession/InputBuffer and Agent
        # ownership, including the create-request row's Agent FK.  Only then can
        # the InputBuffer actor's RESTRICT FK no longer block User deletion.
        await WorkspaceRepository().delete_by_handle(session, workspace_handle)
        await session.flush()
        if user_id is not None:
            await UserRepository().delete(session, user_id)
        await session.commit()


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
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=runtime_repository,
            agent_session_repository=session_repository,
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_AllowWorkspaceUserRepository(calls),
            input_buffer_service=input_buffer_service,
            session_manager=rdb_session_manager,
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
        )

        assert isinstance(result, Success)
        value = result.value
        assert value.agent_runtime_id == "runtime-1"
        assert value.agent_session_id == "session-1"
        assert value.input_buffer.id == "buffer-1"
        assert calls == [
            "get_by_id",
            "lock_workspace_user",
            "ensure_for_agent",
            "enqueue_input_buffer",
            "mark_running_for_input_wakeup",
        ]
        assert input_buffer_service.enqueued is not None
        assert input_buffer_service.enqueued.session_id == "session-1"
        assert input_buffer_service.enqueued.content == "restore me"

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
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_AllowWorkspaceUserRepository(calls),
            input_buffer_service=input_buffer_service,
            session_manager=_session_manager_double,
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="blocked",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputSubagentReadOnly)
        assert calls == ["get_by_id", "lock_workspace_user"]
        assert input_buffer_service.enqueued is None

    async def test_new_session_replay_locks_session_before_membership(self) -> None:
        """A replay keeps Session -> WorkspaceUser order used by normal writes."""
        calls: list[str] = []
        now = datetime.datetime.now(datetime.UTC)
        input_buffer = InputBuffer(
            id="buffer-1",
            session_id="session-1",
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label=_TEST_INFERENCE_PROFILE.model_target_label,
            requested_reasoning_effort=None,
            actor_user_id="user-1",
            content="restore me",
            idempotency_key="request-1",
            metadata={"source": "chat"},
            action=None,
            attachments=[],
            file_parts=[],
            created_at=now,
        )
        service = AgentSessionInputService(
            agent_repository=_AgentRepositoryDouble(calls),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=_RuntimeRepositoryDouble(calls),
            agent_session_repository=_AgentSessionRepositoryDouble(calls),
            agent_session_create_request_repository=(
                _CreateRequestReplayRepository(calls, input_buffer)
            ),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=_InputBufferRepositoryDouble(
                calls,
                input_buffer,
            ),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_AllowWorkspaceUserRepository(calls),
            input_buffer_service=_InputBufferServiceDouble(calls),
            session_manager=_session_manager_double,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id="agent-1",
            message=InputMessage(
                text="restore me",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="request-1",
        )

        assert isinstance(result, Success)
        assert result.value.agent_session.id == "session-1"
        assert result.value.input_buffer.id == "buffer-1"
        assert calls == [
            "lock_agent",
            "claim_create_request",
            "get_by_id",
            "get_input_buffer",
            "lock_workspace_user",
            "ensure_for_agent",
            "mark_running_for_input_wakeup",
        ]

    async def test_new_session_membership_denial_releases_only_new_claim(
        self,
    ) -> None:
        """Final authorization denial abandons the request claimed by this call."""
        calls: list[str] = []
        create_request_repository = _CreateRequestClaimRepository(calls)
        service = AgentSessionInputService(
            agent_repository=_AgentRepositoryDouble(calls),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=_RuntimeRepositoryDouble(calls),
            agent_session_repository=_AgentSessionRepositoryDouble(calls),
            agent_session_create_request_repository=create_request_repository,
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_DenyWorkspaceUserRepository(calls),
            input_buffer_service=_InputBufferServiceDouble(calls),
            session_manager=_session_manager_double,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id="agent-1",
            message=InputMessage(
                text="denied",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="request-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputAccessDenied)
        assert create_request_repository.abandoned_request_id == "create-request-1"
        assert calls == [
            "lock_agent",
            "claim_create_request",
            "lock_workspace_user",
            "abandon_pending_claim",
        ]

    async def test_new_session_replay_rejects_deleted_accepted_session(self) -> None:
        """A retained create authority never recreates its deleted Session."""
        calls: list[str] = []
        now = datetime.datetime.now(datetime.UTC)
        input_buffer = InputBuffer(
            id="buffer-1",
            session_id="session-1",
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label=_TEST_INFERENCE_PROFILE.model_target_label,
            requested_reasoning_effort=None,
            actor_user_id="user-1",
            content="restore me",
            idempotency_key="request-1",
            metadata={"source": "chat"},
            action=None,
            attachments=[],
            file_parts=[],
            created_at=now,
        )
        service = AgentSessionInputService(
            agent_repository=_AgentRepositoryDouble(calls),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=_RuntimeRepositoryDouble(calls),
            agent_session_repository=_MissingAgentSessionRepository(calls),
            agent_session_create_request_repository=(
                _CreateRequestReplayRepository(calls, input_buffer)
            ),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=_AllowWorkspaceUserRepository(calls),
            input_buffer_service=_InputBufferServiceDouble(calls),
            session_manager=_session_manager_double,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id="agent-1",
            message=InputMessage(
                text="restore me",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id="user-1",
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="request-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)
        assert calls == [
            "lock_agent",
            "claim_create_request",
            "get_by_id",
            "lock_workspace_user",
        ]

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
            primary = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
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
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="first draft message",
                user_id=user_id,
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
            client_request_id="draft-client-1",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        assert created.agent_id == agent_id
        assert created.primary_kind is None
        assert result.value.input_buffer.session_id == created.id
        assert result.value.input_buffer.content == "first draft message"
        assert result.value.input_buffer.idempotency_key == "draft-client-1"
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

    async def test_new_session_request_retry_reuses_semantic_result_snapshot(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Timestamp changes and consumed input still return the first result."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "new-session-request-retry",
            )
            user_id = await _create_user(
                session,
                "new-session-request-retry@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "new-session-request-retry",
            )
        service = _agent_session_input_service(rdb_session_manager)
        first = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="create once",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat", "timestamp": "2026-07-15T01:00:00Z"},
                attachments=["exchange://attachment-1"],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[
                "/workspace/agent/app/.",
                "/workspace/agent/app",
            ],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/source/.",
                    starting_ref=" main ",
                )
            ],
            client_request_id="new-session-request-1",
        )
        second = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="create once",
                user_id=user_id,
                headers=[],
                metadata={"source": "retry", "timestamp": "2026-07-15T01:01:00Z"},
                attachments=["exchange://attachment-1"],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=["/workspace/agent/app"],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/source",
                    starting_ref="main",
                )
            ],
            client_request_id="new-session-request-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        assert second.value.agent_session.id == first.value.agent_session.id
        assert second.value.input_buffer == first.value.input_buffer
        assert first.value.input_buffer_pending is True
        assert second.value.input_buffer_pending is True

        async with rdb_session_manager() as session:
            pending = await InputBufferRepository().list_by_session_id(
                session,
                first.value.agent_session.id,
            )
        assert [buffer.kind for buffer in pending] == [
            InputBufferKind.ACTION_MESSAGE,
            InputBufferKind.USER_MESSAGE,
        ]
        assert pending[1].id == first.value.input_buffer.id
        assert pending[0].action == {
            "type": "create_git_worktree",
            "source_project_path": "/workspace/agent/source",
            "starting_ref": "main",
        }

        async with rdb_session_manager() as session:
            deleted = await InputBufferRepository().delete_by_session_id(
                session,
                first.value.agent_session.id,
            )
            await AgentSessionRepository().mark_idle(
                session,
                first.value.agent_session.id,
            )
        assert deleted == 2

        third = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="create once",
                user_id=user_id,
                headers=[],
                metadata={"timestamp": "2026-07-15T01:02:00Z"},
                attachments=["exchange://attachment-1"],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=["/workspace/agent/app"],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/source",
                    starting_ref="main",
                )
            ],
            client_request_id="new-session-request-1",
        )
        assert isinstance(third, Success)
        assert third.value.agent_session.id == first.value.agent_session.id
        assert third.value.input_buffer == first.value.input_buffer
        assert third.value.input_buffer_pending is False

        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                first.value.agent_session.id,
            )
            current = await AgentSessionRepository().get_by_id(
                session,
                first.value.agent_session.id,
            )
        assert len(sessions) == 2
        assert buffers == []
        assert current is not None
        assert current.run_state is AgentSessionRunState.IDLE

    async def test_new_session_request_rejects_payload_mismatch(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """The same global request key cannot create a different Session payload."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "new-session-request-mismatch",
            )
            user_id = await _create_user(
                session,
                "new-session-request-mismatch@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "new-session-request-mismatch",
            )
        service = _agent_session_input_service(rdb_session_manager)
        first = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="original",
                user_id=user_id,
                headers=[],
                metadata={"timestamp": "first"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="new-session-mismatch-1",
        )
        second = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="changed",
                user_id=user_id,
                headers=[],
                metadata={"timestamp": "retry"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="new-session-mismatch-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Failure)
        assert isinstance(second.error, AgentSessionCreateRequestConflict)
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
        assert len(sessions) == 2

    async def test_new_session_request_survives_deleted_accepted_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A deleted result remains a tombstone and cannot be created again."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "new-session-request-deleted-result",
            )
            user_id = await _create_user(
                session,
                "new-session-request-deleted-result@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "new-session-request-deleted-result",
            )
        service = _agent_session_input_service(rdb_session_manager)
        message = InputMessage(
            text="create only once",
            user_id=user_id,
            headers=[],
            metadata={"timestamp": "first"},
            attachments=[],
        )
        first = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="new-session-deleted-result-1",
        )
        assert isinstance(first, Success)

        async with rdb_session_manager() as session:
            await AgentSessionRepository().delete_by_id(
                session,
                first.value.agent_session.id,
            )

        retry = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="new-session-deleted-result-1",
        )

        assert isinstance(retry, Failure)
        assert isinstance(retry.error, AgentSessionInputInactiveSession)
        async with rdb_session_manager() as session:
            authority = await AgentSessionCreateRequestRepository().get_by_key(
                session,
                user_id=user_id,
                agent_id=agent_id,
                client_request_id="new-session-deleted-result-1",
            )
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
        assert authority is not None
        assert authority.agent_session_id == first.value.agent_session.id
        assert len(sessions) == 1
        assert sessions[0].primary_kind is AgentSessionPrimaryKind.TEAM_PRIMARY

    async def test_concurrent_new_session_request_commits_once(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Concurrent global claims return one Session and one first input."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        workspace_handle = f"new-session-concurrent-{suffix}"
        user_id: str | None = None
        try:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                workspace_id = await _create_workspace(
                    session,
                    workspace_handle,
                )
                user_id = await _create_user(
                    session,
                    f"new-session-concurrent-{suffix}@example.com",
                )
                await _add_workspace_user(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                agent_id = await _create_agent(
                    session,
                    workspace_id,
                    f"new-session-concurrent-{suffix}",
                )
                await session.commit()
            assert user_id is not None
            created_user_id = user_id
            session_manager = _committing_session_manager(rdb_engine)
            service = _agent_session_input_service(session_manager)

            async def create(
                timestamp: str,
            ) -> Result[
                CreatedAgentSessionInputResult,
                AgentSessionInputError,
            ]:
                return await service.create_team_session_with_buffered_input(
                    agent_id=agent_id,
                    message=InputMessage(
                        text="concurrent create",
                        user_id=created_user_id,
                        headers=[],
                        metadata={"timestamp": timestamp},
                        attachments=[],
                    ),
                    inference_profile=_TEST_INFERENCE_PROFILE,
                    user_id=created_user_id,
                    existing_project_paths=[],
                    setup_actions=[],
                    client_request_id="concurrent-create-1",
                )

            # TaskGroup drains or cancels both independent transactions before
            # cleanup even if one side raises unexpectedly.
            async with asyncio.TaskGroup() as task_group:
                first_task = task_group.create_task(create("first"))
                second_task = task_group.create_task(create("retry"))
            first = first_task.result()
            second = second_task.result()

            assert isinstance(first, Success)
            assert isinstance(second, Success)
            assert first.value.agent_session.id == second.value.agent_session.id
            assert first.value.input_buffer.id == second.value.input_buffer.id
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                sessions = await AgentSessionRepository().list_active_by_agent_id(
                    session,
                    agent_id,
                )
                buffers = await InputBufferRepository().list_by_session_id(
                    session,
                    first.value.agent_session.id,
                )
                request = await AgentSessionCreateRequestRepository().get_by_key(
                    session,
                    user_id=created_user_id,
                    agent_id=agent_id,
                    client_request_id="concurrent-create-1",
                )
            assert len(sessions) == 2
            assert [buffer.id for buffer in buffers] == [first.value.input_buffer.id]
            assert request is not None
            assert request.agent_session_id == first.value.agent_session.id
            assert request.input_buffer_id == first.value.input_buffer.id
        finally:
            await _cleanup_committed_test_scope(
                rdb_engine,
                workspace_handle=workspace_handle,
                user_id=user_id,
            )

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
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session, workspace_id, "agent-session-stale-buffer"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            old_session = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=runtime.workspace_id,
                agent_id=runtime.agent_id,
            )
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
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
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
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "subagent-readonly")
            root_session = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
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
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=child_agent.agent_session_id,
            message=InputMessage(
                text="direct child input",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
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
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
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
            inference_profile=_TEST_INFERENCE_PROFILE,
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

    async def test_existing_input_rechecks_revoked_workspace_membership(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """The final input transaction rejects a revoked Workspace member."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-revoked")
            user_id = await _create_user(session, "buffered-revoked@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "buffered-chat-revoked",
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

        result = await _agent_session_input_service(
            rdb_session_manager
        ).create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="must not enqueue",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="revoked-input",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputAccessDenied)
        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                agent_session.id,
            )
            unchanged = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
        assert buffers == []
        assert unchanged is not None
        assert unchanged.run_state is AgentSessionRunState.IDLE

    async def test_new_session_rechecks_workspace_membership_before_create(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A rejected create releases its claim so membership recovery can retry."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "draft-session-revoked")
            user_id = await _create_user(session, "draft-revoked@example.com")
            agent_id = await _create_agent(session, workspace_id, "draft-revoked")

        service = _agent_session_input_service(rdb_session_manager)
        message = InputMessage(
            text="must not create",
            user_id=user_id,
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        )
        result = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="revoked-create",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputAccessDenied)
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            abandoned = await AgentSessionCreateRequestRepository().get_by_key(
                session,
                user_id=user_id,
                agent_id=agent_id,
                client_request_id="revoked-create",
            )
        assert sessions == []
        assert abandoned is None

        async with rdb_session_manager() as session:
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
        recovered = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            client_request_id="revoked-create",
        )
        assert isinstance(recovered, Success)
        async with rdb_session_manager() as session:
            completed = await AgentSessionCreateRequestRepository().get_by_key(
                session,
                user_id=user_id,
                agent_id=agent_id,
                client_request_id="revoked-create",
            )
        assert completed is not None
        assert completed.agent_session_id == recovered.value.agent_session.id
        assert completed.input_buffer_id == recovered.value.input_buffer.id

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("runtime failure"), asyncio.CancelledError("cancelled")],
        ids=["exception", "cancellation"],
    )
    async def test_new_session_claim_rolls_back_on_abrupt_exit(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        error: BaseException,
    ) -> None:
        """Exceptions and cancellation cannot commit an incomplete create claim."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "draft-session-rollback")
            user_id = await _create_user(session, "draft-rollback@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "draft-rollback")

        service = dataclasses.replace(
            _agent_session_input_service(rdb_session_manager),
            agent_runtime_repository=_FailingRuntimeRepository(error),
        )
        with pytest.raises(type(error), match=str(error)):
            await service.create_team_session_with_buffered_input(
                agent_id=agent_id,
                message=InputMessage(
                    text="roll back",
                    user_id=user_id,
                    headers=[],
                    metadata={"source": "chat"},
                    attachments=[],
                ),
                inference_profile=_TEST_INFERENCE_PROFILE,
                user_id=user_id,
                existing_project_paths=[],
                setup_actions=[],
                client_request_id="rollback-create",
            )

        async with rdb_session_manager() as session:
            request = await AgentSessionCreateRequestRepository().get_by_key(
                session,
                user_id=user_id,
                agent_id=agent_id,
                client_request_id="rollback-create",
            )
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
        assert request is None
        assert sessions == []

    async def test_existing_session_requests_survive_buffer_consumption(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Message and TurnAction retries keep their durable accepted identity."""
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
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
            chat_write_request_repository=ChatWriteRequestRepository(),
            input_buffer_repository=InputBufferRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-request-1",
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-request-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        first_value = first.value
        second_value = second.value
        assert second_value.input_buffer.id == first_value.input_buffer.id
        assert second_value.input_buffer.content == "first"
        assert second_value.input_buffer_pending is True
        assert second_value.input_buffer.idempotency_key == "client-request-1"

        conflict = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="different payload",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-request-1",
        )
        assert isinstance(conflict, Failure)
        assert isinstance(conflict.error, AgentSessionInputRequestConflict)

        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session, agent_session.id
            )
        assert [buffer.id for buffer in buffers] == [first_value.input_buffer.id]

        async with rdb_session_manager() as session:
            deleted = await InputBufferRepository().delete_by_session_and_id(
                session,
                agent_session.id,
                first_value.input_buffer.id,
            )
            await AgentSessionRepository().mark_idle(session, agent_session.id)
        assert deleted is True

        consumed_retry = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-request-1",
        )
        assert isinstance(consumed_retry, Success)
        assert consumed_retry.value.input_buffer.id == first_value.input_buffer.id
        assert consumed_retry.value.input_buffer_pending is False
        async with rdb_session_manager() as session:
            recovered_session = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
        assert recovered_session is not None
        assert recovered_session.run_state is AgentSessionRunState.IDLE

        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/source",
            starting_ref="refs/heads/main",
        ).model_dump(mode="json")
        first_action = await service.create_buffered_agent_action_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            action=action,
            message=InputMessage(
                text="",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-action-request-1",
        )
        assert isinstance(first_action, Success)
        async with rdb_session_manager() as session:
            deleted_action = await InputBufferRepository().delete_by_session_and_id(
                session,
                agent_session.id,
                first_action.value.input_buffer.id,
            )
            await AgentSessionRepository().mark_idle(session, agent_session.id)
        assert deleted_action is True

        consumed_action_retry = await service.create_buffered_agent_action_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            action=action,
            message=InputMessage(
                text="",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            client_request_id="client-action-request-1",
        )
        assert isinstance(consumed_action_retry, Success)
        assert (
            consumed_action_retry.value.input_buffer.id
            == first_action.value.input_buffer.id
        )
        assert consumed_action_retry.value.input_buffer_pending is False
