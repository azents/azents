"""SessionGitWorktreeService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

import pytest
from azcommon.result import Failure, Result, Success
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.session_git_worktree as session_git_worktree_module
from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    LLMProvider,
    RuntimeRunnerState,
    SessionGitWorktreeStatus,
    WorkspaceUserRole,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.action_messages import (
    CreateGitWorktreeAction,
)
from azents.engine.events.types import ActionExecutionResultPayload
from azents.engine.run.input import InputMessage
from azents.engine.run.types import (
    OWNERSHIP_LOST_CANCEL_MESSAGE,
    SHUTDOWN_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent_context import RDBSessionAgentContextGitWorktree
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionCreate,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.agent_session_create_request.repository import (
    AgentSessionCreateRequestRepository,
)
from azents.repos.chat_write_request.repository import ChatWriteRequestRepository
from azents.repos.input_buffer.repository import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import SessionGitWorktree
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileDeleteResult,
    RuntimeFileListResult,
    RuntimeGitCreateWorktreeResult,
    RuntimeGitDeleteBranchResult,
    RuntimeGitRefEntry,
    RuntimeGitRefsResult,
    RuntimeGitRemoveWorktreeResult,
    RuntimeOperationTextCallback,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_session_input import AgentSessionInputService
from azents.services.chat import ChatSessionService
from azents.services.chat.data import (
    SessionAccessDenied,
    SessionWorktreeCleanupIncomplete,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import (
    ActionExecutionHistoryEventCallback,
    ActionExecutionProjectionCallback,
    GitWorktreeCleanupNotFound,
    GitWorktreeCleanupSubagentReadOnly,
    SessionGitWorktreeService,
)
from azents.services.session_workspace_project import InvalidProjectPath
from azents.testing.model_selection import make_test_model_selection_dict

_TEST_INFERENCE_PROFILE = RequestedInferenceProfile(
    model_target_label="Primary",
    reasoning_effort=None,
)


class _AcceptedWorktreeCommit(Protocol):
    """Structural result needed by the post-ready race test."""

    @property
    def accepted(self) -> bool:
        """Return whether the physical worktree result was accepted."""
        ...


@asynccontextmanager
async def _session_manager_double() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder DB session for service-double tests."""
    yield cast(AsyncSession, object())


class _ReadonlyAgentSessionRepository(AgentSessionRepository):
    """AgentSession repository double returning a child subagent session."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Return a subagent session before other collaborators are touched."""
        del session
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


def _readonly_service() -> SessionGitWorktreeService:
    """Build a service that can test read-only checks without DB fixtures."""
    return SessionGitWorktreeService(
        agent_repository=cast(AgentRepository, object()),
        agent_session_repository=_ReadonlyAgentSessionRepository(),
        workspace_user_repository=cast(WorkspaceUserRepository, object()),
        agent_runtime_repository=cast(AgentRuntimeRepository, object()),
        session_git_worktree_repository=cast(SessionGitWorktreeRepository, object()),
        session_workspace_project_repository=cast(
            SessionWorkspaceProjectRepository,
            object(),
        ),
        agent_project_catalog_repository=cast(AgentProjectCatalogRepository, object()),
        agent_project_catalog_service=cast(AgentProjectCatalogService, object()),
        action_execution_repository=cast(ActionExecutionRepository, object()),
        event_transcript_repository=cast(EventTranscriptRepository, object()),
        session_manager=_session_manager_double,
        runner_operations=cast(RuntimeRunnerOperationClient, object()),
    )


class _RuntimeRepository(AgentRuntimeRepository):
    """Runtime repository double returning a ready Runner."""

    def __init__(
        self,
        *,
        locked_runtime_id: str = "runtime-1",
        locked_runner_generation: int = 7,
        locked_runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
    ) -> None:
        self.locked_runtime_id = locked_runtime_id
        self.locked_runner_generation = locked_runner_generation
        self.locked_runner_state = locked_runner_state

    @staticmethod
    def _runtime(
        agent_id: str,
        *,
        runtime_id: str,
        runner_generation: int,
        runner_state: RuntimeRunnerState,
    ) -> AgentRuntime:
        """Build a runtime projection for one read phase."""
        now = datetime.datetime.now(datetime.UTC)
        return AgentRuntime(
            id=runtime_id,
            workspace_id="workspace-1",
            agent_id=agent_id,
            runner_state=runner_state,
            runner_generation=runner_generation,
            created_at=now,
            updated_at=now,
        )

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Return a ready runtime."""
        del session
        return self._runtime(
            agent_id,
            runtime_id="runtime-1",
            runner_generation=7,
            runner_state=RuntimeRunnerState.READY,
        )

    async def lock_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Return the configured post-runner runtime projection."""
        del session
        return self._runtime(
            agent_id,
            runtime_id=self.locked_runtime_id,
            runner_generation=self.locked_runner_generation,
            runner_state=self.locked_runner_state,
        )

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Return a ready runtime for first-message creation."""
        del default_runtime_provider_id
        runtime = await self.get_by_agent_id(session, agent_id)
        assert runtime is not None
        return runtime


class _RunnerOperations(RuntimeRunnerOperationClient):
    """Runner operation double for Git worktree operations."""

    def __init__(
        self,
        failures: list[str] | None = None,
        cleanup_failures: list[str] | None = None,
    ) -> None:
        self.failures = list(failures or [])
        self.cleanup_failures = list(cleanup_failures or [])
        self.calls: list[dict[str, object]] = []

    async def list_git_refs(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_project_path: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRefsResult:
        """Return deterministic Git refs."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "list_git_refs",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
            }
        )
        return RuntimeGitRefsResult(
            refs=(
                RuntimeGitRefEntry(
                    name="main",
                    ref="refs/heads/main",
                    type="branch",
                    target="abc123",
                    default=True,
                ),
            ),
            default_branch="main",
            head_commit="abc123",
            final_cursor="cursor-refs",
        )

    async def create_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_project_path: str,
        worktree_path: str,
        branch_name: str,
        starting_ref: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitCreateWorktreeResult:
        """Record the attempt and optionally fail with a semantic error."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "create_git_worktree",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "worktree_path": worktree_path,
                "branch_name": branch_name,
                "starting_ref": starting_ref,
            }
        )
        if self.failures:
            raise RuntimeRunnerOperationFailedError(self.failures.pop(0))
        return RuntimeGitCreateWorktreeResult(
            base_commit="abc123",
            worktree_path=worktree_path,
            branch_name=branch_name,
            final_cursor="cursor-1",
        )

    async def remove_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_project_path: str,
        worktree_path: str,
        force: bool,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRemoveWorktreeResult:
        """Record worktree removal."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "remove_git_worktree",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "worktree_path": worktree_path,
                "force": force,
            }
        )
        if self.cleanup_failures:
            raise RuntimeRunnerOperationFailedError(self.cleanup_failures.pop(0))
        return RuntimeGitRemoveWorktreeResult(
            worktree_path=worktree_path,
            final_cursor="cursor-remove",
        )

    async def delete_git_branch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_project_path: str,
        branch_name: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitDeleteBranchResult:
        """Record branch deletion."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "delete_git_branch",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "branch_name": branch_name,
            }
        )
        return RuntimeGitDeleteBranchResult(
            branch_name=branch_name,
            final_cursor="cursor-branch",
        )

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileListResult:
        """Record directory listing for parent cleanup."""
        del deadline_at, exclude_patterns
        self.calls.append(
            {
                "operation": "list_files",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "path": path,
                "recursive": recursive,
            }
        )
        return RuntimeFileListResult(entries=(), final_cursor="cursor-list")

    async def delete_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileDeleteResult:
        """Record empty parent directory deletion."""
        del deadline_at
        self.calls.append(
            {
                "operation": "delete_file",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "path": path,
                "recursive": recursive,
            }
        )
        return RuntimeFileDeleteResult(path=path, final_cursor="cursor-delete")


class _CatalogRefreshService(AgentProjectCatalogService):
    """Catalog status refresh double."""

    def __init__(self, status: AgentProjectCatalogStatus) -> None:
        self.status = status

    async def refresh_project_status(
        self,
        *,
        agent_id: str,
        path: str,
    ) -> Result[AgentProjectCatalogEntry, InvalidProjectPath]:
        """Return the configured status without touching the runner."""
        now = datetime.datetime.now(datetime.UTC)
        status_detail = (
            None if self.status is AgentProjectCatalogStatus.AVAILABLE else "Not ready."
        )
        return Success(
            AgentProjectCatalogEntry(
                id="catalog-1",
                agent_id=agent_id,
                path=path,
                status=self.status,
                status_detail=status_detail,
                checked_at=now,
                created_at=now,
                updated_at=now,
            )
        )


class _FailingCatalogRepository(AgentProjectCatalogRepository):
    """Catalog repository double that fails upsert."""

    async def upsert_entry(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> AgentProjectCatalogEntry:
        """Fail catalog upsert."""
        del session, agent_id, path
        raise RuntimeError("catalog upsert failed")


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService test double."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService test double."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


async def _create_agent_context(
    session: AsyncSession, slug: str
) -> tuple[str, str, str]:
    """Create workspace, user, and agent fixtures."""
    workspace = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name=f"Worktree {slug}", handle=f"worktree-{slug}"),
    )
    assert isinstance(workspace, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, f"worktree-{slug}")
    assert workspace_id is not None
    user = await UserRepository().create(
        session,
        UserCreate(email=f"{slug}@example.com"),
    )
    member = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Worktree User",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(member, Success)
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
        name=f"Worktree {slug}",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model",
        ),
    )
    session.add(agent)
    await session.flush()
    return workspace_id, user.id, agent.id


def _service(
    session_manager: SessionManager[AsyncSession],
    runner: _RunnerOperations,
    *,
    catalog_repository: AgentProjectCatalogRepository | None = None,
    runtime_repository: AgentRuntimeRepository | None = None,
    refresh_status: AgentProjectCatalogStatus = AgentProjectCatalogStatus.AVAILABLE,
) -> SessionGitWorktreeService:
    """Build the service under test."""
    return SessionGitWorktreeService(
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        agent_runtime_repository=runtime_repository or _RuntimeRepository(),
        session_git_worktree_repository=SessionGitWorktreeRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        agent_project_catalog_repository=catalog_repository
        or AgentProjectCatalogRepository(),
        agent_project_catalog_service=_CatalogRefreshService(refresh_status),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        session_manager=session_manager,
        runner_operations=runner,
    )


async def _create_ready_action_allocation(
    session_manager: SessionManager[AsyncSession],
    service: SessionGitWorktreeService,
    *,
    slug: str,
    input_buffer_id: str,
) -> tuple[str, ActionExecution, SessionGitWorktree]:
    """Create one active action with an exact ready allocation."""
    async with session_manager() as session:
        workspace_id, _, agent_id = await _create_agent_context(session, slug)
        agent_session = await AgentSessionRepository().create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/repo",
            starting_ref="main",
        )
        execution = await ActionExecutionRepository().create(
            session,
            ActionExecutionCreate(
                id=None,
                session_id=agent_session.id,
                input_buffer_id=input_buffer_id,
                action_type=action.type,
                action=action.model_dump(mode="json"),
                status=ActionExecutionStatus.PENDING,
                owner_generation=agent_session.owner_generation,
            ),
        )
    async with session_manager() as session:
        running = await ActionExecutionRepository().mark_running(
            session,
            action_execution_id=execution.id,
            started_at=datetime.datetime.now(datetime.UTC),
        )
        allocation = await service._ensure_action_worktree_allocation(  # pyright: ignore[reportPrivateUsage]
            session,
            execution=running,
            session_id=agent_session.id,
            session_handle=agent_session.handle,
            source_project_path=action.source_project_path,
            starting_ref=action.starting_ref,
        )
        creating = await SessionGitWorktreeRepository().mark_creating_if_pending(
            session,
            worktree_id=allocation.id,
        )
        assert creating is not None
        ready = await SessionGitWorktreeRepository().mark_ready_if_creating(
            session,
            worktree_id=creating.id,
            base_commit="abc123",
            worktree_path=creating.worktree_path,
            branch_name=creating.branch_name,
            ready_at=datetime.datetime.now(datetime.UTC),
        )
        assert ready is not None
    return agent_id, running, ready


def _input_service(
    session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
) -> AgentSessionInputService:
    """Build AgentSessionInputService for setup action enqueue tests."""
    del worktree_service
    return AgentSessionInputService(
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_runtime_repository=_RuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_session_create_request_repository=AgentSessionCreateRequestRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        input_buffer_repository=InputBufferRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        input_buffer_service=_input_buffer_service(session_manager),
        session_manager=session_manager,
    )


def _input_buffer_service(
    session_manager: SessionManager[AsyncSession],
) -> InputBufferService:
    """Build the concrete input-buffer collaborator used by service tests."""
    return InputBufferService(
        session_manager=session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        toolkit_state_repository=ToolkitStateRepository(),
    )


def _chat_service(
    session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
) -> ChatSessionService:
    """Build ChatSessionService with the real deletion repositories."""
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
        toolkit_state_repository=ToolkitStateRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=_input_buffer_service(session_manager),
        session_manager=session_manager,
        session_git_worktree_service=worktree_service,
    )


async def _execute_first_setup_action(
    rdb_session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
    *,
    agent_id: str,
    session_id: str,
) -> str:
    """Promote and execute the first pending setup action."""
    async with rdb_session_manager() as session:
        pending = await InputBufferRepository().list_for_flush(
            session,
            session_id,
            limit=1,
        )
    expected_buffer_id = pending[0].id
    promoted = await _input_buffer_service(
        rdb_session_manager
    ).flush_session_input_buffers(
        session_id=session_id,
        model=None,
        required_inference_profile=None,
        expected_buffer_id=expected_buffer_id,
        owner_generation=0,
        prepared_inference_state=None,
        profile_resolution_failure=None,
        active_run_id=None,
        limit=1,
        include_action_messages=True,
    )
    assert promoted.events == []
    worktree_action = promoted.worktree_action
    assert worktree_action is not None
    assert worktree_action.execution is not None
    await worktree_service.run_git_worktree_action(
        agent_id=agent_id,
        session_id=session_id,
        execution=worktree_action.execution,
        action=worktree_action.action,
        owner_generation=worktree_action.execution.owner_generation,
    )
    return worktree_action.buffer.id


async def _create_ready_worktree_session(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    slug: str,
    runner: _RunnerOperations,
) -> tuple[SessionGitWorktreeService, str, str, str]:
    """Create a ready worktree session through the first-message path."""
    async with rdb_session_manager() as session:
        _, user_id, agent_id = await _create_agent_context(session, slug)
    worktree_service = _service(rdb_session_manager, runner)
    input_service = _input_service(rdb_session_manager, worktree_service)
    result = await input_service.create_team_session_with_buffered_input(
        agent_id=agent_id,
        message=InputMessage(
            text=f"start {slug}",
            user_id=user_id,
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        ),
        inference_profile=_TEST_INFERENCE_PROFILE,
        user_id=user_id,
        existing_project_paths=[],
        setup_actions=[
            CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
        ],
        client_request_id=f"worktree-{slug}",
    )
    assert isinstance(result, Success)
    session_id = result.value.agent_session.id
    await _execute_first_setup_action(
        rdb_session_manager,
        worktree_service,
        agent_id=agent_id,
        session_id=session_id,
    )
    async with rdb_session_manager() as session:
        await AgentSessionRepository().mark_idle(session, session_id)
    return worktree_service, user_id, agent_id, session_id


class TestSessionGitWorktreeService:
    """Session Git worktree service tests."""

    async def test_manual_cleanup_rejects_subagent_session(self) -> None:
        """Do not allow direct worktree cleanup mutations for child subagents."""
        result = await _readonly_service().request_manual_cleanup(
            agent_id="agent-1",
            session_id="subagent-session",
            user_id="user-1",
            session_workspace_project_id=None,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeCleanupSubagentReadOnly)

    async def test_run_git_worktree_action_registers_project_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """create_git_worktree TurnAction execution creates a Project boundary."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(session, "action")
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000002",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert result.context_invalidated is True
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert len(allocations) == 1
        assert allocations[0].action_execution_id is None
        assert allocations[0].status is SessionGitWorktreeStatus.READY
        assert [project.path for project in projects] == [allocations[0].worktree_path]
        assert projection is None
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1
        terminal_payload = terminal_events[0].payload
        assert isinstance(terminal_payload, ActionExecutionResultPayload)
        terminal_execution = terminal_payload.action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "completed"
        assert runner.calls == [
            {
                "operation": "create_git_worktree",
                "runtime_id": "runtime-1",
                "runner_generation": 7,
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": allocations[0].worktree_path,
                "branch_name": allocations[0].branch_name,
                "starting_ref": "main",
            }
        ]

    async def test_ready_commit_response_loss_reconciles_exact_identity(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A lost DB response retries by allocation identity without cleanup."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-ready-response-loss",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000019",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        async with rdb_session_manager() as session:
            execution = await ActionExecutionRepository().mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.datetime.now(datetime.UTC),
            )
            allocation = await service._ensure_action_worktree_allocation(  # pyright: ignore[reportPrivateUsage]
                session,
                execution=execution,
                session_id=agent_session.id,
                session_handle=agent_session.handle,
                source_project_path=action.source_project_path,
                starting_ref=action.starting_ref,
            )
            creating = await SessionGitWorktreeRepository().mark_creating_if_pending(
                session,
                worktree_id=allocation.id,
            )
            runtime = await _RuntimeRepository().get_by_agent_id(session, agent_id)
        assert creating is not None
        assert runtime is not None
        commit_once = service._commit_created_worktree_once  # pyright: ignore[reportPrivateUsage]
        attempts = 0

        async def lose_first_response(
            *,
            runtime: AgentRuntime,
            execution: ActionExecution,
            allocation: SessionGitWorktree,
            base_commit: str,
            worktree_path: str,
            branch_name: str,
        ) -> _AcceptedWorktreeCommit:
            nonlocal attempts
            result = await commit_once(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                base_commit=base_commit,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("commit response lost")
            return result

        monkeypatch.setattr(
            service,
            "_commit_created_worktree_once",
            lose_first_response,
        )

        committed = await service._commit_created_worktree_if_current(  # pyright: ignore[reportPrivateUsage]
            runtime=runtime,
            execution=execution,
            allocation=creating,
            base_commit="abc123",
            worktree_path=creating.worktree_path,
            branch_name=creating.branch_name,
        )

        async with rdb_session_manager() as session:
            current = await SessionGitWorktreeRepository().get_by_id_for_session(
                session,
                worktree_id=creating.id,
                session_id=agent_session.id,
            )
        assert committed.accepted is True
        assert attempts == 2
        assert current is not None
        assert current.status is SessionGitWorktreeStatus.READY
        assert runner.calls == []

    async def test_project_registration_commit_response_loss_is_reconciled(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A committed Project link remains successful after response loss."""
        service = _service(rdb_session_manager, _RunnerOperations())
        _, execution, allocation = await _create_ready_action_allocation(
            rdb_session_manager,
            service,
            slug="project-registration-response-loss",
            input_buffer_id="01900000000070008000000000000070",
        )
        commit_once = service._commit_project_registration_once  # pyright: ignore[reportPrivateUsage]
        attempts = 0

        async def lose_first_response(
            *,
            execution: ActionExecution,
            allocation: SessionGitWorktree,
            worktree_path: str,
        ) -> bool:
            nonlocal attempts
            result = await commit_once(
                execution=execution,
                allocation=allocation,
                worktree_path=worktree_path,
            )
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("commit response lost")
            return result

        monkeypatch.setattr(
            service,
            "_commit_project_registration_once",
            lose_first_response,
        )

        registered = await service._run_action_register_project_step(  # pyright: ignore[reportPrivateUsage]
            agent_id="unused",
            execution=execution,
            allocation=allocation,
            worktree_path=allocation.worktree_path,
            on_projection_updated=None,
            on_history_event_appended=None,
        )

        async with rdb_session_manager() as session:
            current = await SessionGitWorktreeRepository().get_by_id_for_session(
                session,
                worktree_id=allocation.id,
                session_id=allocation.session_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=allocation.session_id,
            )
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
        assert registered is True
        assert attempts == 2
        assert current is not None
        assert current.status is SessionGitWorktreeStatus.READY
        assert current.session_workspace_project_id is not None
        assert [project.path for project in projects] == [allocation.worktree_path]
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.RUNNING

    async def test_catalog_registration_commit_response_loss_is_reconciled(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A committed catalog upsert remains successful after response loss."""
        service = _service(rdb_session_manager, _RunnerOperations())
        agent_id, execution, allocation = await _create_ready_action_allocation(
            rdb_session_manager,
            service,
            slug="catalog-registration-response-loss",
            input_buffer_id="01900000000070008000000000000071",
        )
        registered = await service._commit_project_registration_once(  # pyright: ignore[reportPrivateUsage]
            execution=execution,
            allocation=allocation,
            worktree_path=allocation.worktree_path,
        )
        assert registered is True
        commit_once = service._commit_catalog_registration_once  # pyright: ignore[reportPrivateUsage]
        attempts = 0

        async def lose_first_response(
            *,
            agent_id: str,
            execution: ActionExecution,
            allocation: SessionGitWorktree,
            worktree_path: str,
        ) -> bool:
            nonlocal attempts
            result = await commit_once(
                agent_id=agent_id,
                execution=execution,
                allocation=allocation,
                worktree_path=worktree_path,
            )
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("commit response lost")
            return result

        monkeypatch.setattr(
            service,
            "_commit_catalog_registration_once",
            lose_first_response,
        )

        cataloged = await service._run_action_catalog_step(  # pyright: ignore[reportPrivateUsage]
            agent_id=agent_id,
            execution=execution,
            allocation=allocation,
            worktree_path=allocation.worktree_path,
            on_projection_updated=None,
            on_history_event_appended=None,
        )

        async with rdb_session_manager() as session:
            current = await SessionGitWorktreeRepository().get_by_id_for_session(
                session,
                worktree_id=allocation.id,
                session_id=allocation.session_id,
            )
            catalog = await AgentProjectCatalogRepository().get_entry_by_path(
                session,
                agent_id=agent_id,
                path=allocation.worktree_path,
            )
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
        assert cataloged is True
        assert attempts == 2
        assert current is not None
        assert current.status is SessionGitWorktreeStatus.READY
        assert catalog is not None
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.RUNNING

    async def test_progress_event_rollback_retries_one_exact_identity(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A rolled-back event flush retries without losing action progress."""
        service = _service(rdb_session_manager, _RunnerOperations())
        _, execution, _ = await _create_ready_action_allocation(
            rdb_session_manager,
            service,
            slug="progress-event-rollback",
            input_buffer_id="01900000000070008000000000000072",
        )
        append_once = service.action_execution_repository.append_event
        attempts = 0

        async def roll_back_first_flush(
            session: AsyncSession,
            create: ActionExecutionEventCreate,
        ) -> ActionExecutionEvent:
            nonlocal attempts
            event = await append_once(session, create)
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("event transaction rolled back")
            return event

        monkeypatch.setattr(
            service.action_execution_repository,
            "append_event",
            roll_back_first_flush,
        )

        event = await service._append_action_execution_event(  # pyright: ignore[reportPrivateUsage]
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="rollback_test",
            command_argv=None,
            content="Rollback-safe progress.",
            exit_code=None,
            on_projection_updated=None,
        )

        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
        assert event is not None
        assert attempts == 2
        assert projection is not None
        assert [stored.id for stored in projection.events] == [event.id]

    async def test_progress_event_commit_response_loss_is_reconciled(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A committed event response loss resolves the preallocated identity."""
        service = _service(rdb_session_manager, _RunnerOperations())
        _, execution, _ = await _create_ready_action_allocation(
            rdb_session_manager,
            service,
            slug="progress-event-response-loss",
            input_buffer_id="01900000000070008000000000000073",
        )
        commit_once = service._commit_action_execution_event_once  # pyright: ignore[reportPrivateUsage]
        attempts = 0

        async def lose_first_response(
            *,
            execution: ActionExecution,
            create: ActionExecutionEventCreate,
        ) -> ActionExecutionEvent | None:
            nonlocal attempts
            event = await commit_once(execution=execution, create=create)
            attempts += 1
            if attempts == 1:
                raise SQLAlchemyError("event commit response lost")
            return event

        monkeypatch.setattr(
            service,
            "_commit_action_execution_event_once",
            lose_first_response,
        )

        event = await service._append_action_execution_event(  # pyright: ignore[reportPrivateUsage]
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="response_loss_test",
            command_argv=None,
            content="Response-loss-safe progress.",
            exit_code=None,
            on_projection_updated=None,
        )

        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
        assert event is not None
        assert attempts == 2
        assert projection is not None
        assert [stored.id for stored in projection.events] == [event.id]

    async def test_progress_event_cancellation_reconciles_then_propagates(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancellation after commit preserves one event and still propagates."""
        service = _service(rdb_session_manager, _RunnerOperations())
        _, execution, _ = await _create_ready_action_allocation(
            rdb_session_manager,
            service,
            slug="progress-event-cancellation",
            input_buffer_id="01900000000070008000000000000074",
        )
        commit_once = service._commit_action_execution_event_once  # pyright: ignore[reportPrivateUsage]
        first_commit_completed = asyncio.Event()
        never: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        attempts = 0

        async def wait_after_first_commit(
            *,
            execution: ActionExecution,
            create: ActionExecutionEventCreate,
        ) -> ActionExecutionEvent | None:
            nonlocal attempts
            event = await commit_once(execution=execution, create=create)
            attempts += 1
            if attempts == 1:
                first_commit_completed.set()
                await never
            return event

        monkeypatch.setattr(
            service,
            "_commit_action_execution_event_once",
            wait_after_first_commit,
        )
        task = asyncio.create_task(
            service._append_action_execution_event(  # pyright: ignore[reportPrivateUsage]
                execution=execution,
                kind=ActionExecutionEventKind.STEP_STARTED,
                step_key="cancellation_test",
                command_argv=None,
                content="Cancellation-safe progress.",
                exit_code=None,
                on_projection_updated=None,
            )
        )
        await asyncio.wait_for(first_commit_completed.wait(), timeout=2)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
        assert attempts == 2
        assert projection is not None
        assert len(projection.events) == 1
        assert projection.events[0].step_key == "cancellation_test"
        assert projection.execution.status is ActionExecutionStatus.RUNNING

    async def test_created_worktree_is_rejected_after_runtime_generation_changes(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A runner result from a replaced generation is cleanup-only, not ready."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-runtime-race",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000012",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(
            rdb_session_manager,
            runner,
            runtime_repository=_RuntimeRepository(locked_runner_generation=8),
        )

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert result.context_invalidated is False
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
            live_execution = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANED
        assert projects == []
        assert live_execution is None
        terminal_payloads = [
            event.payload
            for event in events
            if isinstance(event.payload, ActionExecutionResultPayload)
        ]
        assert len(terminal_payloads) == 1
        terminal_execution = terminal_payloads[0].action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "failed"
        assert "Runtime runner changed" in str(terminal_execution["failure_summary"])

    async def test_late_created_worktree_reopens_completed_cleanup(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A create result arriving after cleanup is removed by a new cleanup epoch."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-cancel-race",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000013",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        create_git_worktree = runner.create_git_worktree

        async def cancel_before_return(
            *,
            runtime_id: str,
            runner_generation: int,
            owner_session_id: str | None,
            source_project_path: str,
            worktree_path: str,
            branch_name: str,
            starting_ref: str,
            deadline_at: datetime.datetime,
            text_output_callback: RuntimeOperationTextCallback | None,
        ) -> RuntimeGitCreateWorktreeResult:
            created = await create_git_worktree(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                source_project_path=source_project_path,
                worktree_path=worktree_path,
                branch_name=branch_name,
                starting_ref=starting_ref,
                deadline_at=deadline_at,
                text_output_callback=text_output_callback,
            )
            await service.cancel_action_execution(
                execution=execution,
                reason="Operation cancelled during Session ownership handover.",
                on_history_event_appended=None,
            )
            async with rdb_session_manager() as session:
                request = await service.mark_cleanup_pending_for_session(
                    session,
                    session_id=agent_session.id,
                )
            assert request.cleanup_requested is True
            await service.run_cleanup_for_session(
                agent_id=agent_id,
                session_id=agent_session.id,
                session_workspace_project_id=None,
            )
            return created

        monkeypatch.setattr(runner, "create_git_worktree", cancel_before_return)

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert result.context_invalidated is False
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANED
        assert projects == []
        terminal_payloads = [
            event.payload
            for event in events
            if isinstance(event.payload, ActionExecutionResultPayload)
        ]
        assert len(terminal_payloads) == 1
        terminal_execution = terminal_payloads[0].action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "cancelled"
        assert [
            call["operation"]
            for call in runner.calls
            if call["operation"] == "remove_git_worktree"
        ] == ["remove_git_worktree", "remove_git_worktree"]

    async def test_created_worktree_does_not_override_cleanup_request(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cleanup requested during the runner call wins over its late result."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-cleanup-race",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000014",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        create_git_worktree = runner.create_git_worktree

        async def request_cleanup_before_return(
            *,
            runtime_id: str,
            runner_generation: int,
            owner_session_id: str | None,
            source_project_path: str,
            worktree_path: str,
            branch_name: str,
            starting_ref: str,
            deadline_at: datetime.datetime,
            text_output_callback: RuntimeOperationTextCallback | None,
        ) -> RuntimeGitCreateWorktreeResult:
            created = await create_git_worktree(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                source_project_path=source_project_path,
                worktree_path=worktree_path,
                branch_name=branch_name,
                starting_ref=starting_ref,
                deadline_at=deadline_at,
                text_output_callback=text_output_callback,
            )
            async with rdb_session_manager() as session:
                request = await service.mark_cleanup_pending_for_session(
                    session,
                    session_id=agent_session.id,
                )
            assert request.cleanup_requested is True
            return created

        monkeypatch.setattr(
            runner,
            "create_git_worktree",
            request_cleanup_before_return,
        )

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert result.context_invalidated is False
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
            live_execution = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANED
        assert projects == []
        assert live_execution is None
        terminal_payloads = [
            event.payload
            for event in events
            if isinstance(event.payload, ActionExecutionResultPayload)
        ]
        assert len(terminal_payloads) == 1
        terminal_execution = terminal_payloads[0].action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "failed"
        assert "allocation changed" in str(terminal_execution["failure_summary"])

    @pytest.mark.parametrize("race_phase", ["target", "creating"])
    async def test_cleanup_before_runner_claim_skips_external_call(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
        race_phase: str,
    ) -> None:
        """Cleanup wins target/creating CAS races before Runner is called."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                f"action-pre-runner-{race_phase}",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000015",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        repository = service.session_git_worktree_repository
        if race_phase == "target":
            update_target = repository.update_target_if_pending

            async def cleanup_before_target_update(
                session: AsyncSession,
                *,
                worktree_id: str,
                worktree_path: str,
                branch_name: str,
            ) -> object:
                await repository.mark_cleanup_pending(
                    session,
                    worktree_id=worktree_id,
                )
                return await update_target(
                    session,
                    worktree_id=worktree_id,
                    worktree_path=worktree_path,
                    branch_name=branch_name,
                )

            monkeypatch.setattr(
                repository,
                "update_target_if_pending",
                cleanup_before_target_update,
            )
        else:
            mark_creating = repository.mark_creating_if_pending

            async def cleanup_before_creating(
                session: AsyncSession,
                *,
                worktree_id: str,
            ) -> object:
                await repository.mark_cleanup_pending(
                    session,
                    worktree_id=worktree_id,
                )
                return await mark_creating(
                    session,
                    worktree_id=worktree_id,
                )

            monkeypatch.setattr(
                repository,
                "mark_creating_if_pending",
                cleanup_before_creating,
            )

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert runner.calls == []
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_PENDING

    async def test_cancel_before_runner_claim_prevents_stale_external_call(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A terminalized action cannot claim its allocation or call Runner."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-cancel-before-runner",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000026",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        choose_target = service._choose_available_target  # pyright: ignore[reportPrivateUsage]  # Pause at the exact DB-to-Runner ownership boundary.
        target_selected = asyncio.Event()
        release_stale_task = asyncio.Event()

        async def pause_after_target_selection(
            allocation: SessionGitWorktree,
            *,
            execution: ActionExecution,
            path_suffix: int,
            branch_suffix: int,
        ) -> SessionGitWorktree | None:
            selected = await choose_target(
                allocation,
                execution=execution,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
            )
            target_selected.set()
            await release_stale_task.wait()
            return selected

        monkeypatch.setattr(
            service,
            "_choose_available_target",
            pause_after_target_selection,
        )
        action_task = asyncio.create_task(
            service.run_git_worktree_action(
                agent_id=agent_id,
                session_id=agent_session.id,
                execution=execution,
                action=action,
                owner_generation=execution.owner_generation,
            )
        )
        await target_selected.wait()

        await service.cancel_action_execution(
            execution=execution,
            reason="Cancelled by successor ownership.",
            on_history_event_appended=None,
        )
        release_stale_task.set()
        result = await action_task

        assert result.completed is True
        assert result.context_invalidated is False
        assert runner.calls == []
        async with rdb_session_manager() as session:
            live_execution = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert live_execution is None
        assert allocations[0].status is SessionGitWorktreeStatus.FAILED
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1

    async def test_cleanup_after_ready_blocks_project_registration(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cleanup between ready commit and registration leaves no Project row."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-register-cleanup-race",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000017",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        commit_created = service._commit_created_worktree_if_current  # pyright: ignore[reportPrivateUsage]  # Insert cleanup exactly after the ready commit.

        async def cleanup_after_ready(
            *,
            runtime: AgentRuntime,
            execution: ActionExecution,
            allocation: SessionGitWorktree,
            base_commit: str,
            worktree_path: str,
            branch_name: str,
        ) -> _AcceptedWorktreeCommit:
            result = await commit_created(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                base_commit=base_commit,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            assert result.accepted is True
            async with rdb_session_manager() as session:
                request = await service.mark_cleanup_pending_for_session(
                    session,
                    session_id=agent_session.id,
                )
            assert request.cleanup_requested is True
            return result

        monkeypatch.setattr(
            service,
            "_commit_created_worktree_if_current",
            cleanup_after_ready,
        )

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_PENDING
        assert projects == []

    @pytest.mark.parametrize(
        "race_phase",
        ["catalog", "refresh", "skill", "completion"],
    )
    async def test_cleanup_wins_post_registration_lifecycle_boundaries(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
        race_phase: str,
    ) -> None:
        """No post-registration action step revives cleanup-owned projections."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                f"action-lifecycle-{race_phase}",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000018",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)

        async def complete_cleanup() -> None:
            async with rdb_session_manager() as session:
                request = await service.mark_cleanup_pending_for_session(
                    session,
                    session_id=agent_session.id,
                )
            assert request.cleanup_requested is True
            await service.run_cleanup_for_session(
                agent_id=agent_id,
                session_id=agent_session.id,
                session_workspace_project_id=None,
            )

        if race_phase == "catalog":
            run_catalog = service._run_action_catalog_step  # pyright: ignore[reportPrivateUsage]  # Insert cleanup at the catalog boundary.

            async def cleanup_before_catalog(
                *,
                agent_id: str,
                execution: ActionExecution,
                allocation: SessionGitWorktree,
                worktree_path: str,
                on_projection_updated: ActionExecutionProjectionCallback | None,
                on_history_event_appended: (ActionExecutionHistoryEventCallback | None),
            ) -> bool:
                await complete_cleanup()
                return await run_catalog(
                    agent_id=agent_id,
                    execution=execution,
                    allocation=allocation,
                    worktree_path=worktree_path,
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )

            monkeypatch.setattr(
                service,
                "_run_action_catalog_step",
                cleanup_before_catalog,
            )
        elif race_phase == "refresh":
            refresh = service.agent_project_catalog_service.refresh_project_status

            async def cleanup_during_refresh(
                *,
                agent_id: str,
                path: str,
            ) -> Result[AgentProjectCatalogEntry, InvalidProjectPath]:
                result = await refresh(
                    agent_id=agent_id,
                    path=path,
                )
                await complete_cleanup()
                return result

            monkeypatch.setattr(
                service.agent_project_catalog_service,
                "refresh_project_status",
                cleanup_during_refresh,
            )
        elif race_phase == "skill":
            sync_skills = service._sync_skill_projection_for_project_change  # pyright: ignore[reportPrivateUsage]  # Insert cleanup during external projection sync.

            async def cleanup_during_skill_sync(
                *,
                agent_id: str,
                session_id: str,
            ) -> None:
                await sync_skills(
                    agent_id=agent_id,
                    session_id=session_id,
                )
                await complete_cleanup()

            monkeypatch.setattr(
                service,
                "_sync_skill_projection_for_project_change",
                cleanup_during_skill_sync,
            )
        else:
            commit_terminal = service._commit_action_execution_history_event  # pyright: ignore[reportPrivateUsage]  # Insert cleanup immediately before terminal locking.

            async def cleanup_before_completion(
                *,
                execution: ActionExecution,
                status: ActionExecutionStatus,
                failure_summary: str | None,
                cancellation_summary: str | None,
                on_history_event_appended: (ActionExecutionHistoryEventCallback | None),
                allocation: SessionGitWorktree | None,
            ) -> object:
                if status is ActionExecutionStatus.COMPLETED:
                    await complete_cleanup()
                return await commit_terminal(
                    execution=execution,
                    status=status,
                    failure_summary=failure_summary,
                    cancellation_summary=cancellation_summary,
                    on_history_event_appended=on_history_event_appended,
                    allocation=allocation,
                )

            monkeypatch.setattr(
                service,
                "_commit_action_execution_history_event",
                cleanup_before_completion,
            )

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        assert result.context_invalidated is False
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANED
        assert catalog == []
        terminal_payloads = [
            event.payload
            for event in events
            if isinstance(event.payload, ActionExecutionResultPayload)
        ]
        assert len(terminal_payloads) == 1
        terminal_execution = terminal_payloads[0].action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "failed"

    async def test_failure_terminalization_preserves_cleanup_winner(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failure snapshot cannot rewrite cleanup-owned allocation state."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-failure-cleanup-race",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000016",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)

        async def cleanup_then_fail(**kwargs: object) -> object:
            del kwargs
            async with rdb_session_manager() as session:
                request = await service.mark_cleanup_pending_for_session(
                    session,
                    session_id=agent_session.id,
                )
            assert request.cleanup_requested is True
            raise RuntimeRunnerOperationFailedError("runner failed")

        monkeypatch.setattr(runner, "create_git_worktree", cleanup_then_fail)

        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            execution=execution,
            action=action,
            owner_generation=execution.owner_generation,
        )

        assert result.completed is True
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_PENDING

    async def test_running_action_handover_cancels_without_reexecution(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handover snapshots uncertain work without repeating its side effect."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-interrupted",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000003",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        interrupted_runner = _RunnerOperations()

        async def interrupt_create(**kwargs: object) -> object:
            del kwargs
            raise RuntimeError("worker interrupted")

        monkeypatch.setattr(
            interrupted_runner,
            "create_git_worktree",
            interrupt_create,
        )
        with pytest.raises(RuntimeError, match="worker interrupted"):
            await _service(
                rdb_session_manager,
                interrupted_runner,
            ).run_git_worktree_action(
                agent_id=agent_id,
                session_id=agent_session.id,
                execution=execution,
                action=action,
                owner_generation=execution.owner_generation,
            )

        async with rdb_session_manager() as session:
            interrupted = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert interrupted is not None
        assert interrupted.status is ActionExecutionStatus.RUNNING
        assert allocations[0].status is SessionGitWorktreeStatus.CREATING

        recovery_runner = _RunnerOperations()
        recovered_events = await _service(
            rdb_session_manager,
            recovery_runner,
        ).cancel_live_action_executions(
            session_id=agent_session.id,
            reason="Operation cancelled during Session ownership handover.",
            on_history_event_appended=None,
            on_action_execution_removed=None,
        )

        assert len(recovered_events) == 1
        assert recovery_runner.calls == []
        async with rdb_session_manager() as session:
            recovered = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            recovered_allocations = (
                await SessionGitWorktreeRepository().list_by_session_id(
                    session,
                    session_id=agent_session.id,
                )
            )
        assert recovered is None
        assert recovered_allocations[0].status is SessionGitWorktreeStatus.FAILED
        payload = recovered_events[0].payload
        assert isinstance(payload, ActionExecutionResultPayload)
        terminal_execution = payload.action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "cancelled"
        assert terminal_execution["cancellation_summary"] == (
            "Operation cancelled during Session ownership handover."
        )

    @pytest.mark.parametrize(
        ("cancel_message", "expected_summary"),
        [
            (USER_STOP_CANCEL_MESSAGE, "Operation cancelled by user stop."),
            (
                SHUTDOWN_CANCEL_MESSAGE,
                "Operation cancelled after the worker shutdown wait expired.",
            ),
        ],
    )
    async def test_task_cancellation_hands_live_action_to_durable_snapshot(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
        cancel_message: str,
        expected_summary: str,
    ) -> None:
        """Stop and shutdown cancellation preserve one terminal snapshot."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-user-stop",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000004",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        operation_started = asyncio.Event()

        async def block_create(**kwargs: object) -> object:
            del kwargs
            operation_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        monkeypatch.setattr(runner, "create_git_worktree", block_create)
        service = _service(rdb_session_manager, runner)
        task = asyncio.create_task(
            service.run_git_worktree_action(
                agent_id=agent_id,
                session_id=agent_session.id,
                execution=execution,
                action=action,
                owner_generation=execution.owner_generation,
            )
        )
        await operation_started.wait()
        async with rdb_session_manager() as session:
            request = await service.mark_cleanup_pending_for_session(
                session,
                session_id=agent_session.id,
            )
        assert request.cleanup_requested is True
        task.cancel(cancel_message)
        with pytest.raises(asyncio.CancelledError):
            await task

        async with rdb_session_manager() as session:
            live_execution = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert live_execution is None
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_PENDING
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1
        payload = terminal_events[0].payload
        assert isinstance(payload, ActionExecutionResultPayload)
        terminal_execution = payload.action_execution["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "cancelled"
        assert terminal_execution["cancellation_summary"] == expected_summary

    async def test_cancellation_cleanup_timeout_preserves_primary_cancellation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A wedged durable handoff is bounded without replacing cancellation."""
        service = _service(
            cast(SessionManager[AsyncSession], _session_manager_double),
            _RunnerOperations(),
        )
        now = datetime.datetime.now(datetime.UTC)
        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/repo",
            starting_ref="main",
        )
        execution = ActionExecution(
            id="01900000000070008000000000000034",
            session_id="01900000000070008000000000000035",
            input_buffer_id="01900000000070008000000000000036",
            action_type=action.type,
            action=action.model_dump(mode="json"),
            status=ActionExecutionStatus.PENDING,
            owner_generation=1,
            failure_summary=None,
            cancellation_summary=None,
            started_at=None,
            completed_at=None,
            failed_at=None,
            cancelled_at=None,
            created_at=now,
            updated_at=now,
        )
        cleanup_started = asyncio.Event()

        async def cancelled_execution(**kwargs: object) -> object:
            del kwargs
            raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE)

        async def hanging_cleanup(**kwargs: object) -> object:
            del kwargs
            cleanup_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        original_bounded = session_git_worktree_module.run_bounded_cancellation_safe

        async def run_with_short_deadline(operation: object) -> object:
            return await original_bounded(
                cast(Any, operation),
                timeout_seconds=0.01,
            )

        monkeypatch.setattr(
            service,
            "_execute_git_worktree_action",
            cancelled_execution,
        )
        monkeypatch.setattr(service, "cancel_action_execution", hanging_cleanup)
        monkeypatch.setattr(
            session_git_worktree_module,
            "run_bounded_cancellation_safe",
            run_with_short_deadline,
        )

        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(
                service.run_git_worktree_action(
                    agent_id="agent-1",
                    session_id=execution.session_id,
                    execution=execution,
                    action=action,
                    owner_generation=execution.owner_generation,
                ),
                timeout=1,
            )

        assert cleanup_started.is_set()
        assert cancelled.value.args == (USER_STOP_CANCEL_MESSAGE,)

    async def test_ownership_loss_cancellation_performs_no_durable_cleanup_writes(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stale worker must leave live action state untouched for its successor."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(
                session,
                "action-ownership-loss",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000024",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations()
        operation_started = asyncio.Event()

        async def block_create(**kwargs: object) -> object:
            del kwargs
            operation_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        monkeypatch.setattr(runner, "create_git_worktree", block_create)
        service = _service(rdb_session_manager, runner)
        task = asyncio.create_task(
            service.run_git_worktree_action(
                agent_id=agent_id,
                session_id=agent_session.id,
                execution=execution,
                action=action,
                owner_generation=execution.owner_generation,
            )
        )
        await operation_started.wait()
        async with rdb_session_manager() as session:
            projection_before = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
            allocations_before = (
                await SessionGitWorktreeRepository().list_by_session_id(
                    session,
                    session_id=agent_session.id,
                )
            )
            history_before = (
                await EventTranscriptRepository().list_recent_by_session_id(
                    session,
                    agent_session.id,
                    limit=20,
                )
            )
        assert projection_before is not None
        assert len(allocations_before) == 1

        task.cancel(OWNERSHIP_LOST_CANCEL_MESSAGE)
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)

        async with rdb_session_manager() as session:
            projection_after = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=execution.input_buffer_id,
                )
            )
            allocations_after = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            history_after = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                agent_session.id,
                limit=20,
            )
        assert projection_after == projection_before
        assert allocations_after == allocations_before
        assert history_after == history_before

    async def test_session_delete_waits_for_live_create_and_durable_cleanup(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Deletion cannot cascade an allocation while Runner creation is live."""
        async with rdb_session_manager() as session:
            workspace_id, user_id, agent_id = await _create_agent_context(
                session,
                "delete-live-create",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action = CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=agent_session.id,
                    input_buffer_id="01900000000070008000000000000025",
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=agent_session.owner_generation,
                ),
            )
        runner = _RunnerOperations(cleanup_failures=["worktree remove failed"])
        create_started = asyncio.Event()
        release_create = asyncio.Event()
        create_git_worktree = runner.create_git_worktree

        async def block_create(
            *,
            runtime_id: str,
            runner_generation: int,
            owner_session_id: str | None,
            source_project_path: str,
            worktree_path: str,
            branch_name: str,
            starting_ref: str,
            deadline_at: datetime.datetime,
            text_output_callback: RuntimeOperationTextCallback | None,
        ) -> RuntimeGitCreateWorktreeResult:
            create_started.set()
            await release_create.wait()
            return await create_git_worktree(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                source_project_path=source_project_path,
                worktree_path=worktree_path,
                branch_name=branch_name,
                starting_ref=starting_ref,
                deadline_at=deadline_at,
                text_output_callback=text_output_callback,
            )

        monkeypatch.setattr(runner, "create_git_worktree", block_create)
        worktree_service = _service(rdb_session_manager, runner)
        chat_service = _chat_service(rdb_session_manager, worktree_service)
        action_task = asyncio.create_task(
            worktree_service.run_git_worktree_action(
                agent_id=agent_id,
                session_id=agent_session.id,
                execution=execution,
                action=action,
                owner_generation=execution.owner_generation,
            )
        )
        await create_started.wait()

        first_delete = await chat_service.delete_session(
            agent_session.id,
            user_id=user_id,
        )

        assert isinstance(first_delete, Failure)
        assert isinstance(first_delete.error, SessionWorktreeCleanupIncomplete)
        assert not any(
            call["operation"] == "remove_git_worktree" for call in runner.calls
        )
        async with rdb_session_manager() as session:
            assert (
                await AgentSessionRepository().get_by_id(session, agent_session.id)
                is not None
            )
            live_execution = await ActionExecutionRepository().get_by_id(
                session,
                action_execution_id=execution.id,
            )
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert live_execution is not None
        assert live_execution.status is ActionExecutionStatus.RUNNING
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_PENDING

        release_create.set()
        action_result = await action_task
        assert action_result.completed is True
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
        assert allocations[0].status is SessionGitWorktreeStatus.CLEANUP_FAILED

        second_delete = await chat_service.delete_session(
            agent_session.id,
            user_id=user_id,
        )

        assert isinstance(second_delete, Success)
        async with rdb_session_manager() as session:
            assert (
                await AgentSessionRepository().get_by_id(session, agent_session.id)
                is None
            )

    async def test_session_delete_rechecks_membership_after_runner_cleanup(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A membership revoked during external cleanup blocks the final delete."""
        async with rdb_session_manager() as session:
            workspace_id, user_id, agent_id = await _create_agent_context(
                session,
                "delete-membership-revoked",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )

        worktree_service = _service(rdb_session_manager, _RunnerOperations())

        async def revoke_membership_during_cleanup(
            *,
            agent_id: str,
            session_id: str,
            session_workspace_project_id: str | None,
        ) -> None:
            del agent_id, session_id, session_workspace_project_id
            async with rdb_session_manager() as session:
                membership = await WorkspaceUserRepository().get_by_workspace_and_user(
                    session,
                    workspace_id,
                    user_id,
                )
                assert membership is not None
                await WorkspaceUserRepository().delete(session, membership.id)

        monkeypatch.setattr(
            worktree_service,
            "run_cleanup_for_session",
            revoke_membership_during_cleanup,
        )
        chat_service = _chat_service(rdb_session_manager, worktree_service)

        result = await chat_service.delete_session(
            agent_session.id,
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)
        async with rdb_session_manager() as session:
            assert (
                await AgentSessionRepository().get_by_id(session, agent_session.id)
                is not None
            )

    async def test_session_delete_rechecks_membership_before_cleanup_admission(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A winning revoke prevents cleanup state and every Runner side effect."""
        runner = _RunnerOperations()
        worktree_service, user_id, _, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="delete-membership-revoked-before-cleanup",
            runner=runner,
        )
        chat_service = _chat_service(rdb_session_manager, worktree_service)
        original_get_session = chat_service.get_session

        async def get_session_then_revoke(
            requested_session_id: str,
            *,
            user_id: str,
        ) -> object:
            result = await original_get_session(
                requested_session_id,
                user_id=user_id,
            )
            assert isinstance(result, Success)
            async with rdb_session_manager() as session:
                membership = await WorkspaceUserRepository().get_by_workspace_and_user(
                    session,
                    result.value.workspace_id,
                    user_id,
                )
                assert membership is not None
                await WorkspaceUserRepository().delete(session, membership.id)
            return result

        monkeypatch.setattr(chat_service, "get_session", get_session_then_revoke)

        result = await chat_service.delete_session(session_id, user_id=user_id)

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)
        assert not any(
            call["operation"] in {"remove_git_worktree", "delete_git_branch"}
            for call in runner.calls
        )
        async with rdb_session_manager() as session:
            assert await AgentSessionRepository().get_by_id(session, session_id)
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=session_id,
            )
        assert len(allocations) == 1
        assert allocations[0].status is SessionGitWorktreeStatus.READY

    async def test_preview_git_refs_lists_source_project_refs(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Git ref preview validates access and calls the Runtime Runner."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "preview")
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)

        result = await service.preview_git_refs(
            agent_id=agent_id,
            user_id=user_id,
            source_project_path="/workspace/agent/repo",
        )

        assert isinstance(result, Success)
        assert result.value.default_branch == "main"
        assert result.value.refs[0].ref == "refs/heads/main"
        assert runner.calls == [
            {
                "operation": "list_git_refs",
                "runtime_id": "runtime-1",
                "runner_generation": 7,
                "source_project_path": "/workspace/agent/repo",
            }
        ]

    async def test_valid_first_message_worktree_registers_project_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Valid worktree action creates Project and catalog rows."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "ready")
        runner = _RunnerOperations()
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start worktree",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-ready",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        async with rdb_session_manager() as session:
            projects_before_action = (
                await SessionWorkspaceProjectRepository().list_projects(
                    session,
                    session_id=created.id,
                )
            )
        assert projects_before_action == []

        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=created.id,
        )
        async with rdb_session_manager() as session:
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=created.id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )

        project_paths = [project.path for project in projects]
        assert project_paths == [runner.calls[-1]["worktree_path"]]
        assert "/workspace/agent/repo" not in project_paths
        assert [entry.path for entry in catalog] == [runner.calls[-1]["worktree_path"]]

    async def test_invalid_ref_fails_action_and_keeps_input_pending(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner invalid ref failure leaves the action failed and input pending."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "invalid-ref")
        runner = _RunnerOperations(failures=["invalid_ref: unknown revision"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start invalid",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="missing",
                )
            ],
            client_request_id="worktree-invalid",
        )

        assert isinstance(result, Success)
        input_buffer_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=input_buffer_id,
                )
            )
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                result.value.agent_session.id,
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                result.value.agent_session.id,
                limit=20,
            )
        assert projection is None
        assert [buffer.content for buffer in buffers] == ["start invalid"]
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1
        terminal_payload = terminal_events[0].payload
        assert isinstance(terminal_payload, ActionExecutionResultPayload)
        terminal_projection = terminal_payload.action_execution
        terminal_execution = terminal_projection["execution"]
        assert isinstance(terminal_execution, dict)
        assert terminal_execution["status"] == "failed"

    async def test_branch_collision_suffixes_final_branch(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Branch collision retries with an independently suffixed branch name."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "branch")
        runner = _RunnerOperations(failures=["branch_exists: branch exists"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start branch",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-branch",
        )

        assert isinstance(result, Success)
        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        first_branch = runner.calls[0]["branch_name"]
        second_branch = runner.calls[1]["branch_name"]
        assert isinstance(first_branch, str)
        assert isinstance(second_branch, str)
        assert first_branch.startswith("azents/")
        assert second_branch.endswith("-2")

    async def test_path_collision_suffixes_final_worktree_path(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Path collision retries with an independently suffixed path leaf."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "path")
        runner = _RunnerOperations(failures=["worktree_path_exists: path exists"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start path",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-path",
        )

        assert isinstance(result, Success)
        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        first_path = runner.calls[0]["worktree_path"]
        second_path = runner.calls[1]["worktree_path"]
        assert isinstance(first_path, str)
        assert isinstance(second_path, str)
        assert first_path.endswith("/repo")
        assert second_path.endswith("/repo-2")

    async def test_catalog_upsert_failure_blocks_initialization(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Catalog upsert failure marks the action execution failed."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "catalog")
        runner = _RunnerOperations()
        worktree_service = _service(
            rdb_session_manager,
            runner,
            catalog_repository=_FailingCatalogRepository(),
        )
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start catalog",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-catalog",
        )

        assert isinstance(result, Success)
        input_buffer_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=input_buffer_id,
                )
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                result.value.agent_session.id,
                limit=20,
            )
        assert projection is None
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1
        payload = terminal_events[0].payload
        assert isinstance(payload, ActionExecutionResultPayload)
        execution_value = payload.action_execution["execution"]
        assert isinstance(execution_value, dict)
        assert execution_value["status"] == "failed"

    async def test_status_refresh_warning_does_not_block_ready(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Non-blocking status refresh warning keeps action execution completed."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "warning")
        runner = _RunnerOperations()
        worktree_service = _service(
            rdb_session_manager,
            runner,
            refresh_status=AgentProjectCatalogStatus.UNAVAILABLE,
        )
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start warning",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-warning",
        )

        assert isinstance(result, Success)
        input_buffer_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_input_buffer_id(
                    session,
                    input_buffer_id=input_buffer_id,
                )
            )
            events = await EventTranscriptRepository().list_recent_by_session_id(
                session,
                result.value.agent_session.id,
                limit=20,
            )
        assert projection is None
        terminal_events = [
            event for event in events if event.kind is EventKind.ACTION_EXECUTION_RESULT
        ]
        assert len(terminal_events) == 1
        payload = terminal_events[0].payload
        assert isinstance(payload, ActionExecutionResultPayload)
        execution_value = payload.action_execution["execution"]
        event_values = payload.action_execution["events"]
        assert isinstance(execution_value, dict)
        assert isinstance(event_values, list)
        assert execution_value["status"] == "completed"
        assert any(
            isinstance(event_value, dict) and event_value.get("kind") == "warning"
            for event_value in event_values
        )

    async def test_archive_cleanup_request_only_marks_pending(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Archive-time cleanup request does not run Git cleanup inline."""
        runner = _RunnerOperations()
        worktree_service, _, _, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="archive-cleanup",
            runner=runner,
        )

        async with rdb_session_manager() as session:
            request = await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert request.cleanup_requested is True
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_PENDING
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]

    async def test_cleanup_removes_worktree_branch_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup removes Git resources and deletes the catalog entry."""
        runner = _RunnerOperations()
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-success",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED
        assert catalog == []
        assert projects == []
        assert [call["operation"] for call in runner.calls] == [
            "create_git_worktree",
            "remove_git_worktree",
            "delete_git_branch",
            "list_files",
            "delete_file",
        ]
        remove_call = runner.calls[1]
        assert remove_call["force"] is False

    async def test_cleanup_deletes_project_linked_after_stale_snapshot(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup finalization reloads the latest linked Project under lock."""
        runner = _RunnerOperations()
        service, _, agent_id, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-late-project-link",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=session_id,
            )
            runtime = await _RuntimeRepository().get_by_agent_id(
                session,
                agent_id,
            )
            await service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
        assert runtime is not None
        assert allocations[0].session_workspace_project_id is not None
        stale_allocation = allocations[0].model_copy(
            update={"session_workspace_project_id": None}
        )

        cleaned = await service._run_cleanup_for_allocation(  # pyright: ignore[reportPrivateUsage]  # Exercise stale pre-link cleanup snapshot.
            agent_id=agent_id,
            session_id=session_id,
            runtime=runtime,
            allocation=stale_allocation,
        )

        assert cleaned is not None
        async with rdb_session_manager() as session:
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=session_id,
            )
        assert projects == []

    async def test_late_create_epoch_invalidates_inflight_cleanup_finalization(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A late create proof forces a second delete before CLEANED is committed."""
        runner = _RunnerOperations()
        service, _, agent_id, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-create-epoch",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
        remove_resources = service._remove_worktree_resources  # pyright: ignore[reportPrivateUsage]
        remove_attempts = 0

        async def bump_cleanup_epoch_after_remove(
            *,
            runtime: AgentRuntime,
            allocation: SessionGitWorktree,
        ) -> None:
            nonlocal remove_attempts
            await remove_resources(runtime=runtime, allocation=allocation)
            remove_attempts += 1
            if remove_attempts == 1:
                async with rdb_session_manager() as session:
                    await SessionGitWorktreeRepository().mark_cleanup_pending(
                        session,
                        worktree_id=allocation.id,
                    )

        monkeypatch.setattr(
            service,
            "_remove_worktree_resources",
            bump_cleanup_epoch_after_remove,
        )

        await service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )
        async with rdb_session_manager() as session:
            pending = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=session_id,
            )
        assert pending is not None
        assert pending.status is SessionGitWorktreeStatus.CLEANUP_PENDING
        assert len(projects) == 1

        await service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )
        async with rdb_session_manager() as session:
            cleaned = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=session_id,
            )
        assert cleaned is not None
        assert cleaned.status is SessionGitWorktreeStatus.CLEANED
        assert projects == []
        assert remove_attempts == 2

    async def test_late_cleanup_failure_does_not_overwrite_cleaned(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A slower duplicate cleanup failure cannot revive a cleaned row."""
        runner = _RunnerOperations()
        service, _, agent_id, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-late-failure",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
        await service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )
        async with rdb_session_manager() as session:
            cleaned = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert cleaned is not None
        assert cleaned.status is SessionGitWorktreeStatus.CLEANED

        await service._mark_cleanup_failed(  # pyright: ignore[reportPrivateUsage]  # Simulate a slower duplicate cleanup result.
            worktree_id=cleaned.id,
            reason="late duplicate failure",
        )

        async with rdb_session_manager() as session:
            retried = await SessionGitWorktreeRepository().mark_cleanup_pending(
                session,
                worktree_id=cleaned.id,
            )
            current = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert retried.status is SessionGitWorktreeStatus.CLEANED
        assert current is not None
        assert current.status is SessionGitWorktreeStatus.CLEANED
        assert current.cleanup_summary == "Git worktree cleanup completed."

    async def test_manual_cleanup_rejects_ordinary_project_target(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Project-targeted cleanup cannot delete ordinary Project rows."""
        runner = _RunnerOperations()
        (
            worktree_service,
            user_id,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-ordinary-project",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            ordinary_project = await SessionWorkspaceProjectRepository().create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=session_id,
                    path="/workspace/agent/ordinary",
                ),
            )

        result = await worktree_service.request_manual_cleanup(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            session_workspace_project_id=ordinary_project.id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeCleanupNotFound)
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]

    async def test_cleanup_failure_marks_failed_without_raising(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup failures are recorded without blocking callers."""
        runner = _RunnerOperations(cleanup_failures=["worktree remove failed"])
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-failure",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_FAILED
        assert allocation.cleanup_summary == "worktree remove failed"
        remove_call = runner.calls[1]
        assert remove_call["force"] is False
        assert len(catalog) == 1

    async def test_manual_cleanup_retry_succeeds_after_failure(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Manual cleanup retry can recover a previously failed cleanup."""
        runner = _RunnerOperations(cleanup_failures=["first cleanup failed"])
        (
            worktree_service,
            user_id,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-retry",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        retry = await worktree_service.request_manual_cleanup(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            session_workspace_project_id=None,
        )
        assert isinstance(retry, Success)
        assert retry.value.cleanup_requested is True
        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED

    async def test_cleanup_rejects_path_without_matching_ownership_boundary(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup never deletes a path outside the recorded Azents root boundary."""
        runner = _RunnerOperations()
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-ownership",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            assert allocation is not None
            row = await session.get(RDBSessionAgentContextGitWorktree, allocation.id)
            assert row is not None
            row.worktree_path = "/workspace/agent/user-owned/repo"
            await session.flush()
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_FAILED
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]
