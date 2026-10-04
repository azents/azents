"""Session Git worktree tool-availability projection tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession
from azents.core.enums import AgentSessionStatus, SessionGitWorktreeStatus
from azents.rdb.session_capabilities import ReadOnlySession, ReadSession, WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import SessionGitWorktree
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderAuthority,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project_operations import (
    SessionWorkspaceProjectOperationsRepository,
)
from azents.repos.skill_state_store import SkillStateStore
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeLifecycleSnapshot,
    RuntimeOperationTarget,
)
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)


class _ProjectionResolver:
    """Typed Runtime projection fake; admission resolution must never be called."""

    def __init__(self, target: RuntimeOperationTarget | None) -> None:
        self.target = target
        self.projection_calls = 0
        self.admission_calls = 0

    async def project_operation_target(
        self, agent_id: str
    ) -> RuntimeOperationTarget | None:
        assert agent_id == "agent-1"
        self.projection_calls += 1
        return self.target

    async def resolve_operation_target(
        self, *args: object, **kwargs: object
    ) -> RuntimeOperationTarget:
        del args, kwargs
        self.admission_calls += 1
        raise AssertionError("availability projection must not admit Runtime work")

    async def get_lifecycle_snapshot(
        self, agent_id: str
    ) -> AgentRuntimeLifecycleSnapshot:
        del agent_id
        raise AssertionError(
            "availability projection must not read lifecycle snapshots"
        )


class _BindingProjection(SessionWorkingFolderBindingService):
    """Typed binding projection fake with admission methods guarded."""

    def __init__(self, authority: SessionWorkingFolderAuthority | None) -> None:
        """Initialize projection-only state without a repository."""
        self.authority = authority
        self.projection_calls = 0
        self.admission_calls = 0

    async def project_bound_authority_for_target(
        self,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority | None:
        assert agent_id == "agent-1"
        assert session_id == "session-1"
        assert runtime_target.workspace_path == "/workspace/agent"
        self.projection_calls += 1
        return self.authority

    async def require_bindable_context(self, **kwargs: object) -> None:
        del kwargs
        self.admission_calls += 1
        raise AssertionError("availability projection must not require binding")


class _AgentSessionProjection(AgentSessionRepository):
    """Repository fake returning one exact Session row."""

    def __init__(
        self, *, agent_id: str = "agent-1", status: AgentSessionStatus
    ) -> None:
        self.agent_id = agent_id
        self.status = status
        self.calls = 0

    async def get_by_id(
        self, session: ReadSession, agent_session_id: str
    ) -> AgentSession | None:
        assert agent_session_id == "session-1"
        self.calls += 1
        return AgentSession.model_construct(
            id=agent_session_id,
            agent_id=self.agent_id,
            status=self.status,
        )


class _AllocationProjection(SessionGitWorktreeRepository):
    """Repository fake returning retained worktree allocations."""

    def __init__(self, allocations: list[SessionGitWorktree]) -> None:
        self.allocations = allocations
        self.calls = 0

    async def list_by_session_id(
        self, session: ReadSession, *, session_id: str
    ) -> list[SessionGitWorktree]:
        assert session_id == "session-1"
        self.calls += 1
        return self.allocations


class _ProjectOperationsProjection(SessionWorkspaceProjectOperationsRepository):
    """Typed unused project-operations dependency."""

    def __init__(self) -> None:
        """Skip production repository dependencies; projection never invokes them."""


class _RunnerProjection(RuntimeRunnerOperationClient):
    """Typed non-null Runner client that is never called by projection."""

    def __init__(self) -> None:
        """Skip production client dependencies; projection only checks presence."""


class _SkillProjection(SkillStateStore):
    """Typed non-null Skill store that is never called by projection."""

    def __init__(self) -> None:
        """Skip production store dependencies; projection only checks presence."""


@asynccontextmanager
async def _read_session_manager() -> AsyncIterator[ReadOnlySession]:
    """Yield an unbound read-only SQLAlchemy session without opening a database."""
    yield ReadOnlySession(AsyncSession())


@asynccontextmanager
async def _reject_write_session_manager() -> AsyncIterator[WriteSession]:
    """Fail if availability projection accidentally enters a write scope."""
    raise AssertionError("availability projection must not enter a write session")
    yield


def _target() -> RuntimeOperationTarget:
    return RuntimeOperationTarget(
        id="runtime-1",
        runtime_capability_version=1,
        desired_generation=1,
        runner_generation=1,
        configuration_sequence=1,
        configuration_digest="a" * 64,
        workspace_path="/workspace/agent",
    )


def _authority() -> SessionWorkingFolderAuthority:
    return SessionWorkingFolderAuthority(
        context_id="context-1",
        agent_id="agent-1",
        agent_runtime_id="runtime-1",
        working_folder_path="/workspace/agent/session-1",
        runtime_capability_version=1,
    )


def _allocation(status: SessionGitWorktreeStatus) -> SessionGitWorktree:
    return SessionGitWorktree.model_construct(
        status=status,
        session_workspace_project_id="project-1",
    )


def _service(
    *,
    resolver: _ProjectionResolver,
    binding: _BindingProjection,
    session_repository: _AgentSessionProjection,
    allocations: list[SessionGitWorktree],
    runner_operations: RuntimeRunnerOperationClient | None = None,
    skill_store: SkillStateStore | None = None,
) -> tuple[SessionGitWorktreeService, _AllocationProjection]:
    allocation_repository = _AllocationProjection(allocations)
    if runner_operations is None:
        runner_operations = _RunnerProjection()
    if skill_store is None:
        skill_store = _SkillProjection()
    service = SessionGitWorktreeService(
        agent_repository=AgentRepository(),
        agent_session_repository=session_repository,
        workspace_user_repository=WorkspaceUserRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        session_git_worktree_repository=allocation_repository,
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        session_workspace_project_operations_repository=_ProjectOperationsProjection(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_catalog_service=AgentProjectCatalogService(
            catalog_repository=AgentProjectCatalogRepository(),
            session_manager=_reject_write_session_manager,
            runtime_target_resolver=resolver,
            runner_operations=runner_operations,
        ),
        action_execution_repository=ActionExecutionRepository(),
        mailbox_item_repository=MailboxRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        session_manager=_reject_write_session_manager,
        read_session_manager=_read_session_manager,
        runtime_target_resolver=resolver,
        session_working_folder_binding_service=binding,
        runner_operations=runner_operations,
        skill_store=skill_store,
    )
    return service, allocation_repository


@pytest.mark.asyncio
async def test_projection_uses_exact_active_session() -> None:
    """One projection call drives both tools for the exact active Session."""
    resolver = _ProjectionResolver(_target())
    binding = _BindingProjection(_authority())
    session_repository = _AgentSessionProjection(status=AgentSessionStatus.ACTIVE)
    service, allocations = _service(
        resolver=resolver,
        binding=binding,
        session_repository=session_repository,
        allocations=[_allocation(SessionGitWorktreeStatus.READY)],
    )

    availability = await service.project_agent_git_worktree_availability(
        agent_id="agent-1", session_id="session-1"
    )

    assert availability.create is True
    assert availability.remove is True
    assert resolver.projection_calls == 1
    assert binding.projection_calls == 1
    assert session_repository.calls == 1
    assert allocations.calls == 1
    assert resolver.admission_calls == 0
    assert binding.admission_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_id", "status"),
    [("agent-2", AgentSessionStatus.ACTIVE), ("agent-1", AgentSessionStatus.ARCHIVED)],
)
async def test_projection_requires_exact_active_session(
    agent_id: str, status: AgentSessionStatus
) -> None:
    """A mismatched or non-active Session exposes neither operation."""
    resolver = _ProjectionResolver(_target())
    binding = _BindingProjection(_authority())
    session_repository = _AgentSessionProjection(agent_id=agent_id, status=status)
    service, allocations = _service(
        resolver=resolver,
        binding=binding,
        session_repository=session_repository,
        allocations=[_allocation(SessionGitWorktreeStatus.READY)],
    )

    availability = await service.project_agent_git_worktree_availability(
        agent_id="agent-1", session_id="session-1"
    )

    assert availability.create is False
    assert availability.remove is False
    assert allocations.calls == 0


@pytest.mark.asyncio
async def test_projection_remove_requires_ready_allocation() -> None:
    """Create remains available while removal requires a retained ready allocation."""
    resolver = _ProjectionResolver(_target())
    binding = _BindingProjection(_authority())
    service, _ = _service(
        resolver=resolver,
        binding=binding,
        session_repository=_AgentSessionProjection(status=AgentSessionStatus.ACTIVE),
        allocations=[_allocation(SessionGitWorktreeStatus.CREATING)],
    )

    availability = await service.project_agent_git_worktree_availability(
        agent_id="agent-1", session_id="session-1"
    )

    assert availability.create is True
    assert availability.remove is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["runtime", "binding", "skill_runner"])
async def test_projection_unavailable_context_exposes_no_tools(failure: str) -> None:
    """Runtime, binding, and skill/Runner gaps do not enter read persistence."""
    resolver = _ProjectionResolver(None if failure == "runtime" else _target())
    binding = _BindingProjection(None if failure == "binding" else _authority())
    service, allocations = _service(
        resolver=resolver,
        binding=binding,
        session_repository=_AgentSessionProjection(status=AgentSessionStatus.ACTIVE),
        allocations=[_allocation(SessionGitWorktreeStatus.READY)],
        runner_operations=_RunnerProjection(),
        skill_store=_SkillProjection(),
    )
    if failure == "skill_runner":
        service.runner_operations = None
        service.skill_store = None

    availability = await service.project_agent_git_worktree_availability(
        agent_id="agent-1", session_id="session-1"
    )

    assert availability.create is False
    assert availability.remove is False
    assert allocations.calls == 0
    assert resolver.admission_calls == 0
    assert binding.admission_calls == 0
