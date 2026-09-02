"""AgentSessionInputService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
    RuntimeRunnerState,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
    WorkspaceUserRole,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    SessionAppliedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
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
from azents.repos.agent_session.data import (
    AgentSession,
    AgentSessionCreate,
    SessionWorkingFolderContext,
)
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItem
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.toolkit_state import ToolkitStateRepository
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
from azents.testing.turn_action import make_test_turn_action_capabilities

from .agent_session_input import (
    AgentSessionInputError,
    AgentSessionInputIdempotencyConflict,
    AgentSessionInputInactiveSession,
    AgentSessionInputInvalidInferenceProfile,
    AgentSessionInputService,
    AgentSessionInputSubagentReadOnly,
    CreatedAgentSessionInputResult,
)
from .mailbox import (
    MailboxAdmissionResult,
    MailboxEnqueue,
    MailboxService,
)

_TEST_INFERENCE_PROFILE = RequestedInferenceProfile(
    model_target_label="default",
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
            terminal_delete_acknowledgement_kind=None,
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
                id="agent-1",
                lifecycle_status=AgentLifecycleStatus.ACTIVE,
                workspace_id="workspace-1",
                runtime_capability=AgentRuntimeCapability.MANAGED,
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
        self.applied_inference_profile: SessionAppliedInferenceProfile | None = None
        self.applied_profile_calls: list[SessionAppliedInferenceProfile] = []

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        """Lock and fetch session."""
        del session
        self.calls.append("get_by_id")
        return self._build_session(agent_session_id)

    def _build_session(self, agent_session_id: str) -> AgentSession:
        """Build the current in-memory Session projection."""
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            owner_generation=0,
            inference_state=None,
            applied_inference_profile=self.applied_inference_profile,
            id=agent_session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="test-session-handle",
            session_kind=self.session_kind,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=now,
            last_activity_at=now,
            pinned=False,
            started_at=now,
            created_at=now,
            updated_at=now,
        )

    async def set_applied_inference_profile(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
    ) -> AgentSession:
        """Persist applied profile in memory for input-admission tests."""
        del session
        self.applied_inference_profile = SessionAppliedInferenceProfile(
            model_target_label=model_target_label,
            reasoning_effort=reasoning_effort,
        )
        self.applied_profile_calls.append(self.applied_inference_profile)
        return self._build_session(session_id)

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Record wake transition."""
        del session, session_id
        self.calls.append("mark_running_for_input_wakeup")

    async def get_working_folder_context_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionWorkingFolderContext:
        """Return the stable context used by adoption enqueue tests."""
        del session, session_id
        return SessionWorkingFolderContext(
            id="context-1",
            agent_id="agent-1",
            agent_runtime_id="runtime-1",
            working_folder_path="/workspace/agent/.azents/sessions/test-session-handle",
            binding_state=SessionWorkingFolderBindingState.BOUND,
            invalidated_by_removal_id=None,
            invalidated_at=None,
            cleanup_status=SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED,
        )


class _MailboxServiceDouble(MailboxService):
    """MailboxService double for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.enqueued: MailboxEnqueue | None = None
        self.moved: tuple[str, str] | None = None

    async def enqueue(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        """Record MailboxItem creation."""
        del session
        self.calls.append("enqueue_mailbox_item")
        self.enqueued = input
        mailbox_item = MailboxItem(
            id="buffer-1",
            session_id=input.session_id,
            kind=input.kind,
            scheduling_mode=input.scheduling_mode,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=input.sender_user_id,
            order_group="buffer-1",
            order_sequence=0,
            content=input.content,
            idempotency_key=input.idempotency_key,
            metadata=input.metadata,
            attachments=input.attachments,
            file_parts=input.file_parts,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        return MailboxAdmissionResult(mailbox_item=mailbox_item, created=True)

    async def move_by_session_id(
        self,
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Record MailboxItem move request."""
        del session
        self.calls.append("move_mailbox_item")
        self.moved = (from_session_id, to_session_id)
        return 1

    async def has_seen_action_type(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        action_type: str,
    ) -> bool:
        """Treat unit-test sessions as already initialized."""
        del session, session_id, action_type
        return True


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
        agent_repository=AgentRepository(),
        automatic_project_repository=AgentAutomaticProjectRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
    )


def _mailbox_item_service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> MailboxService:
    """Create MailboxService for integration tests."""
    return MailboxService(
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
        turn_action_capabilities=make_test_turn_action_capabilities(
            rdb_session_manager
        ),
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


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
    *,
    workspace_path: str | None = "/workspace/agent",
    runtime_capability: AgentRuntimeCapability = AgentRuntimeCapability.MANAGED,
) -> str:
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
        runtime_capability=runtime_capability,
        shell_enabled=runtime_capability is AgentRuntimeCapability.MANAGED,
    )
    session.add(agent)
    await session.flush()
    session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id))
    await session.flush()
    if runtime_capability is AgentRuntimeCapability.MANAGED:
        runtime_repository = AgentRuntimeRepository()
        runtime = await runtime_repository.ensure_for_agent(session, agent.id)
        if workspace_path is not None:
            await runtime_repository.record_runner_state(
                session,
                runtime.id,
                RuntimeRunnerState.UNKNOWN,
                1,
                expected_desired_generation=runtime.desired_generation,
                workspace_path=workspace_path,
            )
    return agent.id


async def _cleanup_committed_agent_fixture(
    session: AsyncSession,
    *,
    workspace_id: str | None,
    user_id: str | None,
    agent_id: str | None,
) -> None:
    """Remove the committed fixture used by the cross-transaction fence test."""
    if agent_id is not None:
        await session.execute(
            sa.update(RDBSessionAgentContext)
            .where(RDBSessionAgentContext.agent_id == agent_id)
            .values(root_session_agent_id=None)
        )
        await session.execute(
            sa.delete(RDBSessionAgent).where(
                RDBSessionAgent.agent_session_id.in_(
                    sa.select(RDBAgentSession.id).where(
                        RDBAgentSession.agent_id == agent_id
                    )
                )
            )
        )
        await session.execute(
            sa.delete(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == agent_id
            )
        )
        await session.execute(
            sa.delete(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
        )
        await session.execute(
            sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent_id)
        )
        await session.execute(
            sa.delete(RDBAgentDecommissionJob).where(
                RDBAgentDecommissionJob.agent_id == agent_id
            )
        )
        await session.execute(sa.delete(RDBAgent).where(RDBAgent.id == agent_id))
    if workspace_id is not None:
        await session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
        )
    if user_id is not None:
        await session.execute(sa.delete(RDBUser).where(RDBUser.id == user_id))


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

    async def test_create_buffered_agent_input_delegates_wake_to_mailbox_service(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Delegate the durable REST input wake transition to MailboxService."""
        calls: list[str] = []
        runtime_repository = _RuntimeRepositoryDouble(calls)
        session_repository = _AgentSessionRepositoryDouble(calls)
        mailbox_item_service = _MailboxServiceDouble(calls)
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
            mailbox_item_service=mailbox_item_service,
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
        assert value.mailbox_item is not None
        assert value.mailbox_item.id == "buffer-1"
        assert calls == [
            "get_by_id",
            "ensure_for_agent",
            "enqueue_mailbox_item",
        ]
        assert mailbox_item_service.enqueued is not None
        assert mailbox_item_service.enqueued.session_id == "session-1"
        assert (
            mailbox_item_service.enqueued.scheduling_mode
            == MailboxSchedulingMode.WAKE_SESSION
        )
        assert mailbox_item_service.enqueued.content == "restore me"

    async def test_invalid_profile_rejects_before_mailbox_and_applied_state(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Invalid Human profile admission leaves Session and mailbox unchanged."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "invalid-profile-admission",
            )
            user_id = await _create_user(
                session,
                "invalid-profile-admission@example.com",
            )
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "invalid-profile-admission",
            )
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )
            ).session
            initial_buffers = await MailboxRepository().list_by_session_id(
                session,
                agent_session.id,
            )
            initial_runtime_ids = list(
                await session.scalars(
                    sa.select(RDBAgentRuntime.id).where(
                        RDBAgentRuntime.agent_id == agent_id
                    )
                )
            )
            initial_context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    session,
                    session_id=agent_session.id,
                )
            )
        assert initial_context is not None
        assert initial_context.binding_state is SessionWorkingFolderBindingState.PENDING

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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="must not be admitted",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=RequestedInferenceProfile(
                model_target_label="missing",
                reasoning_effort=None,
            ),
            user_id=user_id,
            request_payload={"request": "invalid-profile"},
            client_request_id="invalid-profile-request",
        )

        assert isinstance(result, Failure)
        assert result.error == AgentSessionInputInvalidInferenceProfile(
            reason="Model target label is not available"
        )
        async with rdb_session_manager() as session:
            updated = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
            buffers = await MailboxRepository().list_by_session_id(
                session,
                agent_session.id,
            )
            runtime_ids = list(
                await session.scalars(
                    sa.select(RDBAgentRuntime.id).where(
                        RDBAgentRuntime.agent_id == agent_id
                    )
                )
            )
            write_request = await ChatWriteRequestRepository().get_by_client_request_id(
                session,
                session_id=agent_session.id,
                requester_user_id=user_id,
                client_request_id="invalid-profile-request",
            )
            updated_context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    session,
                    session_id=agent_session.id,
                )
            )
        assert updated is not None
        assert updated.applied_inference_profile is None
        assert updated_context == initial_context
        assert buffers == initial_buffers
        assert runtime_ids == initial_runtime_ids
        assert write_request is None

    async def test_attachment_claim_failure_rolls_back_buffer_acceptance(self) -> None:
        """A cross-root claim conflict cannot leave a pending input behind."""
        calls: list[str] = []
        db_session = AsyncMock(spec=AsyncSession)

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield db_session

        mailbox_item_service = _MailboxServiceDouble(calls)
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
            mailbox_item_service=mailbox_item_service,
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
            "enqueue_mailbox_item",
        ]
        assert mailbox_item_service.enqueued is not None

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
        mailbox_item_service = _MailboxServiceDouble(calls)
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
            mailbox_item_service=mailbox_item_service,
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
        assert mailbox_item_service.enqueued is None

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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
        mailbox_item = result.value.mailbox_item
        assert mailbox_item is not None
        assert mailbox_item.session_id == created.id
        assert mailbox_item.content == "first draft message"
        assert mailbox_item.idempotency_key == "draft-client-1"
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

    async def test_create_two_user_sessions_with_buffered_input(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Owner can admit multiple User Sessions on one Agent."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "user-session-multi")
            user_id = await _create_user(session, "user-session-multi@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "user-session-multi")
            await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        first = await service.create_user_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="first private",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"request": "user-1"},
            client_request_id="user-1",
        )
        second = await service.create_user_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="second private",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"request": "user-2"},
            client_request_id="user-2",
        )

        assert isinstance(first, Success), first
        assert isinstance(second, Success), second
        assert first.value.agent_session.id != second.value.agent_session.id
        assert first.value.agent_session.product_mode is AgentSessionProductMode.USER
        assert second.value.agent_session.product_mode is AgentSessionProductMode.USER
        assert first.value.agent_session.associated_user_id == user_id
        assert second.value.agent_session.associated_user_id == user_id
        async with rdb_session_manager() as session:
            owner_list = (
                await AgentSessionRepository().list_active_user_by_agent_and_user(
                    session,
                    agent_id=agent_id,
                    associated_user_id=user_id,
                )
            )
            team_list = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
        assert {item.id for item in owner_list} == {
            first.value.agent_session.id,
            second.value.agent_session.id,
        }
        assert all(
            item.product_mode is AgentSessionProductMode.TEAM for item in team_list
        )

    async def test_runtime_free_session_queues_only_user_input(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runtime-free Session creation omits Runtime working-folder actions."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "runtime-free-input")
            user_id = await _create_user(session, "runtime-free-input@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "runtime-free-input",
                runtime_capability=AgentRuntimeCapability.NONE,
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_user_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="runtime-free input",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
            request_payload={"request": "runtime-free-input"},
            client_request_id="runtime-free-input",
        )

        assert isinstance(result, Success)
        assert result.value.agent_runtime_id is None
        async with rdb_session_manager() as session:
            buffers = await MailboxRepository().list_by_session_id(
                session,
                result.value.agent_session.id,
            )
        assert len(buffers) == 1
        assert buffers[0].kind is MailboxItemKind.USER_MESSAGE
        assert buffers[0].action is None

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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
            second.value.accepted_mailbox_item_id
            == first.value.accepted_mailbox_item_id
        )
        assert second.value.mailbox_item is not None
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            buffers = await MailboxRepository().list_by_session_id(
                session,
                first.value.agent_session.id,
            )
        assert len(sessions) == 2
        assert len(buffers) == 2
        setup_buffer, user_buffer = buffers
        assert setup_buffer.kind is MailboxItemKind.ACTION_MESSAGE
        assert setup_buffer.scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
        assert setup_buffer.sender_user_id is None
        assert setup_buffer.action == {"type": "create_session_working_folder"}
        assert user_buffer.id == first.value.accepted_mailbox_item_id

    async def test_concurrent_new_session_creation_converges_without_advisory_lock(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Parallel first-message creators share one Agent-scoped idempotency winner."""
        del latest_db_schema

        @asynccontextmanager
        async def independent_session_manager() -> AsyncGenerator[AsyncSession]:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                else:
                    await session.commit()

        agent_id: str | None = None
        user_id: str | None = None
        workspace_id: str | None = None
        try:
            async with independent_session_manager() as session:
                workspace_id = await _create_workspace(
                    session,
                    "draft-session-concurrent",
                )
                user_id = await _create_user(
                    session,
                    "draft-session-concurrent@example.com",
                )
                await _add_workspace_user(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                agent_id = await _create_agent(
                    session,
                    workspace_id,
                    "draft-session-concurrent",
                )

            assert agent_id is not None
            assert user_id is not None
            assert workspace_id is not None

            def _service() -> AgentSessionInputService:
                return AgentSessionInputService(
                    agent_repository=AgentRepository(),
                    agent_project_preset_repository=AgentProjectPresetRepository(),
                    agent_project_catalog_repository=AgentProjectCatalogRepository(),
                    agent_project_default_repository=AgentProjectDefaultRepository(),
                    agent_runtime_repository=AgentRuntimeRepository(),
                    agent_session_repository=AgentSessionRepository(),
                    root_agent_session_creation_service=(
                        _root_agent_session_creation_service()
                    ),
                    chat_write_request_repository=ChatWriteRequestRepository(),
                    session_workspace_project_repository=(
                        SessionWorkspaceProjectRepository()
                    ),
                    workspace_user_repository=WorkspaceUserRepository(),
                    exchange_file_service=_ExchangeFileService(),
                    mailbox_item_service=_mailbox_item_service(
                        independent_session_manager
                    ),
                    session_manager=independent_session_manager,
                )

            message = InputMessage(
                text="concurrent first message",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            )
            request_payload: dict[str, object] = {
                "agent_id": agent_id,
                "client_request_id": "draft-session-concurrent",
                "message": message.text,
            }

            async def _create() -> Result[
                CreatedAgentSessionInputResult, AgentSessionInputError
            ]:
                return await _service().create_team_session_with_buffered_input(
                    agent_id=agent_id or "",
                    message=message,
                    inference_profile=_TEST_INFERENCE_PROFILE,
                    user_id=user_id or "",
                    existing_project_paths=[],
                    setup_actions=[],
                    request_payload=request_payload,
                    client_request_id="draft-session-concurrent",
                )

            first, second = await asyncio.gather(_create(), _create())

            assert isinstance(first, Success), first
            assert isinstance(second, Success), second
            first_value = first.value
            second_value = second.value
            assert {first_value.created, second_value.created} == {True, False}
            assert first_value.agent_session.id == second_value.agent_session.id
            assert (
                first_value.accepted_mailbox_item_id
                == second_value.accepted_mailbox_item_id
            )
            async with independent_session_manager() as session:
                sessions = await AgentSessionRepository().list_active_by_agent_id(
                    session,
                    agent_id,
                )
                buffers = await MailboxRepository().list_by_session_id(
                    session,
                    first_value.agent_session.id,
                )
            assert len(sessions) == 2
            assert len(buffers) == 2
        finally:
            async with independent_session_manager() as session:
                if agent_id is not None:
                    await session.execute(
                        sa.text(
                            "DELETE FROM chat_write_requests "
                            "WHERE creation_agent_id = :agent_id "
                            "OR session_id IN (SELECT id FROM agent_sessions "
                            "WHERE agent_id = :agent_id)"
                        ),
                        {"agent_id": agent_id},
                    )
                    await session.execute(
                        sa.text(
                            "DELETE FROM mailbox_items WHERE session_id IN "
                            "(SELECT id FROM agent_sessions WHERE agent_id = :agent_id)"
                        ),
                        {"agent_id": agent_id},
                    )
                await _cleanup_committed_agent_fixture(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    agent_id=agent_id,
                )

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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
        """First-message claim failure removes the new Session and MailboxItem."""
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
            primary_buffers = await MailboxRepository().list_by_session_id(
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
            old_buffers = await MailboxRepository().list_by_session_id(
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
            buffers = await MailboxRepository().list_by_session_id(
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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

    async def test_existing_session_input_adopts_working_folder_setup_once(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Legacy-style active Session input queues one setup action before wake."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "folder-adoption")
            user_id = await _create_user(session, "folder-adoption@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "folder-adoption")
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=agent_id,
                    title=None,
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        first = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first legacy input",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "folder-adoption-first"},
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="second legacy input",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            request_payload={"request": "folder-adoption-second"},
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        async with rdb_session_manager() as session:
            buffers = await MailboxRepository().list_by_session_id(
                session,
                agent_session.id,
            )
            context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    session,
                    session_id=agent_session.id,
                )
            )
        assert context is not None
        assert len(buffers) == 3
        setup, first_input, second_input = buffers
        assert setup.kind is MailboxItemKind.ACTION_MESSAGE
        assert setup.scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
        assert setup.sender_user_id is None
        assert setup.action == {"type": "create_session_working_folder"}
        assert setup.idempotency_key == f"session-working-folder:adoption:{context.id}"
        assert [item.content for item in (first_input, second_input)] == [
            "first legacy input",
            "second legacy input",
        ]

    async def test_agent_decommission_fence_wins_before_input_admission(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Admission waits for an Agent lifecycle update and then fails closed."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        workspace_id: str | None = None
        user_id: str | None = None
        agent_id: str | None = None

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

        try:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as setup_session:
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
                mailbox_item_service=_mailbox_item_service(session_manager),
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
                admission_started = asyncio.Event()

                async def create_input() -> object:
                    admission_started.set()
                    return await service.create_buffered_agent_input(
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

                admission_task = asyncio.create_task(create_input())
                try:
                    await asyncio.wait_for(admission_started.wait(), timeout=5)
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(
                            asyncio.shield(admission_task),
                            timeout=0.1,
                        )
                    await decommission_session.commit()
                    result = await asyncio.wait_for(admission_task, timeout=5)
                finally:
                    if not admission_task.done():
                        admission_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await admission_task

            assert isinstance(result, Failure)
            assert isinstance(result.error, AgentSessionInputInactiveSession)
            async with session_manager() as session:
                buffers = await MailboxRepository().list_by_session_id(
                    session,
                    agent_session.id,
                )
            assert buffers == []
        finally:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as session:
                await _cleanup_committed_agent_fixture(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    agent_id=agent_id,
                )
                await session.commit()

    async def test_create_buffered_agent_input_dedupes_client_request_id(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Same client_request_id returns same MailboxItem."""
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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
        assert isinstance(first, Success)
        async with rdb_session_manager() as session:
            await AgentSessionRepository().mark_idle(
                session,
                agent_session.id,
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

        assert isinstance(second, Success)
        first_value = first.value
        second_value = second.value
        assert first_value.mailbox_item is not None
        assert second_value.mailbox_item is not None
        assert second_value.accepted_mailbox_item_id == first_value.mailbox_item.id
        assert second_value.mailbox_item.id == first_value.mailbox_item.id
        assert second_value.created is False
        async with rdb_session_manager() as session:
            buffers = await MailboxRepository().list_by_session_id(
                session, agent_session.id
            )
            replayed_session = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )
        assert len(buffers) == 2
        assert replayed_session is not None
        assert replayed_session.run_state is AgentSessionRunState.RUNNING
        setup_buffer, user_buffer = buffers
        assert setup_buffer.kind is MailboxItemKind.ACTION_MESSAGE
        assert setup_buffer.scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
        assert setup_buffer.sender_user_id is None
        assert setup_buffer.action == {"type": "create_session_working_folder"}
        assert user_buffer.id == first_value.mailbox_item.id

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
            mailbox_item_service=_mailbox_item_service(rdb_session_manager),
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
        assert first.value.mailbox_item is not None
        assert second.value.mailbox_item is not None
        assert (
            first.value.accepted_mailbox_item_id
            != second.value.accepted_mailbox_item_id
        )

        async with rdb_session_manager() as session:
            buffers = await MailboxRepository().list_by_session_id(
                session,
                agent_session.id,
            )

        setup_buffers = [
            buffer
            for buffer in buffers
            if buffer.kind is MailboxItemKind.ACTION_MESSAGE
        ]
        user_buffers = [
            buffer
            for buffer in buffers
            if buffer.kind is not MailboxItemKind.ACTION_MESSAGE
        ]
        assert len(setup_buffers) == 1
        assert setup_buffers[0].action == {"type": "create_session_working_folder"}
        assert {
            (buffer.id, buffer.sender_user_id, buffer.content)
            for buffer in user_buffers
        } == {
            (
                first.value.accepted_mailbox_item_id,
                first_user_id,
                first_message.text,
            ),
            (
                second.value.accepted_mailbox_item_id,
                second_user_id,
                second_message.text,
            ),
        }
        assert len({buffer.idempotency_key for buffer in user_buffers}) == 2

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
        assert first_retry.value.mailbox_item is not None
        assert (
            first_retry.value.accepted_mailbox_item_id
            == first.value.accepted_mailbox_item_id
        )

        async with rdb_session_manager() as session:
            deleted = await MailboxRepository().delete_by_session_and_id(
                session,
                agent_session.id,
                first.value.accepted_mailbox_item_id,
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
        assert first_post_promotion_retry.value.mailbox_item is None
        assert (
            first_post_promotion_retry.value.accepted_mailbox_item_id
            == first.value.accepted_mailbox_item_id
        )
