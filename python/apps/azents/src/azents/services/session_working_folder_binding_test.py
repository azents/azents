"""Session working-folder binding authority tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import (
    AgentSession,
    AgentSessionCreate,
    SessionAgent,
    SessionWorkingFolderContext,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentSessionProductMode,
    AgentSessionStatus,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.runtime_capabilities import RuntimeCapabilitySnapshot
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import (
    AgentSessionRepository,
    LockedSessionWorkingFolderBinding,
)
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.session_working_folder_binding import (
    SessionWorkingFolderBindingRepository,
)
from azents.repos.session_working_folder_binding.data import SessionWorkingFolderTarget
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.testing.types import require_instance


def _context(
    state: SessionWorkingFolderBindingState,
    *,
    path: str | None = None,
    runtime_id: str | None = "runtime-1",
) -> SessionWorkingFolderContext:
    """Create one binding context fixture."""
    return SessionWorkingFolderContext(
        id="context-1",
        agent_id="agent-1",
        agent_runtime_id=runtime_id,
        working_folder_path=path,
        binding_state=state,
        invalidated_by_removal_id=(
            "removal-1"
            if state is SessionWorkingFolderBindingState.INVALIDATED
            else None
        ),
        invalidated_at=(
            datetime.datetime.now(datetime.UTC)
            if state is SessionWorkingFolderBindingState.INVALIDATED
            else None
        ),
        cleanup_status=SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED,
    )


def _target() -> RuntimeOperationTarget:
    """Create current Runner-backed Runtime evidence."""
    return RuntimeOperationTarget(
        id="runtime-1",
        runtime_capability_version=4,
        desired_generation=3,
        runner_generation=3,
        configuration_sequence=1,
        configuration_digest="a" * 64,
        workspace_path="/workspace/agent",
    )


def _service() -> SessionWorkingFolderBindingService:
    """Create a service with deterministic repository doubles."""
    agent_repository = AsyncMock()
    agent_repository.lock_by_id.return_value = Agent.model_construct(
        id="agent-1",
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_capability_version=4,
    )
    agent_session_repository = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[WriteSession]:
        yield AsyncMock(spec=AsyncSession)

    return SessionWorkingFolderBindingService(
        repository=SessionWorkingFolderBindingRepository(
            agent_repository=agent_repository,
            agent_session_repository=agent_session_repository,
            session_manager=session_manager,
            read_session_manager=session_manager,
        ),
    )


@pytest.mark.asyncio
async def test_pending_context_binds_from_current_runner_workspace() -> None:
    """Current Runtime evidence performs the one allowed pending bind."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )
    pending = _context(SessionWorkingFolderBindingState.PENDING)
    expected_path = "/workspace/agent/.azents/sessions/root-handle"
    repository.lock_working_folder_binding_by_session_id.return_value = (
        LockedSessionWorkingFolderBinding(
            context=pending,
            root_session_handle="root-handle",
        )
    )
    repository.bind_pending_working_folder.return_value = pending.model_copy(
        update={
            "binding_state": SessionWorkingFolderBindingState.BOUND,
            "working_folder_path": expected_path,
        }
    )

    authority = await service.resolve_authority(
        agent_id="agent-1",
        session_id="session-1",
        capability_snapshot=RuntimeCapabilitySnapshot(
            state=AgentRuntimeCapability.MANAGED,
            version=4,
        ),
        runtime_target=_target(),
    )

    assert authority == SessionWorkingFolderAuthority(
        context_id="context-1",
        agent_id="agent-1",
        agent_runtime_id="runtime-1",
        working_folder_path=expected_path,
        runtime_capability_version=4,
    )
    repository.bind_pending_working_folder.assert_awaited_once()


@pytest.mark.asyncio
async def test_in_transaction_resolution_uses_caller_owned_session() -> None:
    """Final write fencing retains the caller transaction's Agent/context locks."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )
    expected_path = "/workspace/agent/.azents/sessions/root-handle"
    repository.lock_working_folder_binding_by_session_id.return_value = (
        LockedSessionWorkingFolderBinding(
            context=_context(
                SessionWorkingFolderBindingState.BOUND,
                path=expected_path,
            ),
            root_session_handle="root-handle",
        )
    )
    transaction = AsyncMock(spec=AsyncSession)

    authority = await service.resolve_bound_authority_in_transaction(
        transaction,
        agent_id="agent-1",
        session_id="session-1",
        runtime_target=_target(),
    )

    assert authority.working_folder_path == expected_path
    agent_repository = require_instance(service.repository.agent_repository, AsyncMock)
    agent_repository.lock_by_id.assert_awaited_once_with(transaction, "agent-1")
    repository.lock_working_folder_binding_by_session_id.assert_awaited_once_with(
        transaction,
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_stale_capability_fails_before_context_lock() -> None:
    """A changed Agent capability version cannot bind or reuse a path."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )

    with pytest.raises(
        SessionWorkingFolderBindingError,
        match="binding is unavailable",
    ) as error:
        await service.resolve_authority(
            agent_id="agent-1",
            session_id="session-1",
            capability_snapshot=RuntimeCapabilitySnapshot(
                state=AgentRuntimeCapability.MANAGED,
                version=3,
            ),
            runtime_target=_target(),
        )

    assert error.value.reason_code == "runtime_capability_stale"
    repository.lock_working_folder_binding_by_session_id.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "reason_code"),
    [
        (SessionWorkingFolderBindingState.NONE, "binding_none"),
        (SessionWorkingFolderBindingState.INVALIDATED, "binding_invalidated"),
    ],
)
async def test_terminal_unbound_contexts_never_gain_authority(
    state: SessionWorkingFolderBindingState,
    reason_code: str,
) -> None:
    """Runtime-free and invalidated contexts cannot bind after Runtime evidence."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )
    repository.lock_working_folder_binding_by_session_id.return_value = (
        LockedSessionWorkingFolderBinding(
            context=_context(
                state,
                runtime_id=(
                    None
                    if state is SessionWorkingFolderBindingState.NONE
                    else "runtime-1"
                ),
            ),
            root_session_handle="root-handle",
        )
    )

    with pytest.raises(SessionWorkingFolderBindingError) as error:
        await service.resolve_authority(
            agent_id="agent-1",
            session_id="session-1",
            capability_snapshot=RuntimeCapabilitySnapshot(
                state=AgentRuntimeCapability.MANAGED,
                version=4,
            ),
            runtime_target=_target(),
        )

    assert error.value.reason_code == reason_code
    repository.bind_pending_working_folder.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "reason_code"),
    [
        (SessionWorkingFolderBindingState.NONE, "binding_none"),
        (SessionWorkingFolderBindingState.INVALIDATED, "binding_invalidated"),
    ],
)
async def test_terminal_states_fail_preflight_before_runtime_resolution(
    state: SessionWorkingFolderBindingState,
    reason_code: str,
) -> None:
    """Terminal contexts are rejected by the Runtime-I/O-free preflight."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )
    repository.lock_working_folder_binding_by_session_id.return_value = (
        LockedSessionWorkingFolderBinding(
            context=_context(
                state,
                runtime_id=(
                    None
                    if state is SessionWorkingFolderBindingState.NONE
                    else "runtime-1"
                ),
            ),
            root_session_handle="root-handle",
        )
    )

    with pytest.raises(SessionWorkingFolderBindingError) as error:
        await service.require_bindable_context(
            agent_id="agent-1",
            session_id="session-1",
        )

    assert error.value.reason_code == reason_code
    repository.bind_pending_working_folder.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_context_fails_bound_only_preflight() -> None:
    """Read-only and cleanup surfaces cannot start Runtime for pending contexts."""
    service = _service()
    repository = require_instance(
        service.repository.agent_session_repository,
        AsyncMock,
    )
    repository.lock_working_folder_binding_by_session_id.return_value = (
        LockedSessionWorkingFolderBinding(
            context=_context(SessionWorkingFolderBindingState.PENDING),
            root_session_handle="root-handle",
        )
    )

    with pytest.raises(SessionWorkingFolderBindingError) as error:
        await service.require_bound_context(
            agent_id="agent-1",
            session_id="session-1",
        )

    assert error.value.reason_code == "binding_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "bound",
        "pending",
        "invalidated",
        "missing",
        "runtime-mismatch",
        "capability-stale",
        "path-mismatch",
        "root-mismatch",
    ],
)
async def test_retained_binding_projection_never_locks_or_binds(case: str) -> None:
    """Lagged folder evidence is either a retained description or absent."""

    service = _service()
    agents = require_instance(service.repository.agent_repository, AsyncMock)
    agents.get_by_id.return_value = Agent.model_construct(
        id="agent-1",
        workspace_id="workspace-1",
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_capability_version=5 if case == "capability-stale" else 4,
    )
    sessions = require_instance(service.repository.agent_session_repository, AsyncMock)
    state = (
        SessionWorkingFolderBindingState.PENDING
        if case == "pending"
        else SessionWorkingFolderBindingState.INVALIDATED
        if case == "invalidated"
        else SessionWorkingFolderBindingState.BOUND
    )
    context = _context(
        state,
        path="/wrong"
        if case == "path-mismatch"
        else "/workspace/agent/.azents/sessions/root-handle",
        runtime_id="other" if case == "runtime-mismatch" else "runtime-1",
    )
    sessions.get_working_folder_context_by_session_id.return_value = (
        None if case == "missing" else context
    )
    sessions.get_root_session_agent_by_session_id.return_value = (
        SessionAgent.model_construct(
            context_id="other" if case == "root-mismatch" else "context-1",
            agent_session_id="root-session",
        )
    )
    sessions.get_by_id.return_value = AgentSession.model_construct(
        agent_id="agent-1",
        workspace_id="workspace-1",
        status=AgentSessionStatus.ACTIVE,
        handle="root-handle",
    )
    projected = await service.project_bound_authority_for_target(
        agent_id="agent-1", session_id="child-session", runtime_target=_target()
    )
    assert (projected is not None) == (case == "bound")
    if projected is not None:
        assert (
            projected.working_folder_path
            == "/workspace/agent/.azents/sessions/root-handle"
        )
    agents.lock_by_id.assert_not_awaited()
    sessions.lock_working_folder_binding_by_session_id.assert_not_awaited()
    sessions.bind_pending_working_folder.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_binding_projection_runs_in_real_read_only_transaction(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Actual projection getters emit legal read-only SQL, not Agent locks."""

    repository = SessionWorkingFolderBindingRepository(
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        session_manager=create_read_write_session_manager(rdb_engine),
        read_session_manager=create_read_only_session_manager(rdb_engine),
    )
    assert (
        await repository.project_bound_authority(
            agent_id="missing",
            session_id="missing",
            target=SessionWorkingFolderBindingService.target_evidence(_target()),
        )
        is None
    )


@pytest.mark.asyncio
async def test_bound_projection_finishes_while_agent_and_context_are_locked(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A successful RO projection does not wait on another transaction's row locks."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    sessions = AgentSessionRepository()
    repository = SessionWorkingFolderBindingRepository(
        agent_repository=AgentRepository(),
        agent_session_repository=sessions,
        session_manager=writes,
        read_session_manager=reads,
    )
    async with writes() as session:
        workspace_id = await _create_workspace(session, f"projection-{uuid4().hex}")
        agent_id = await _create_agent(session, workspace_id, "bound-projection")
        root = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        runtime = await AgentRuntimeRepository().get_by_agent_id(session, agent_id)
        assert runtime is not None
        target = SessionWorkingFolderTarget(
            id=runtime.id,
            capability_snapshot_version=1,
            runtime_target_capability_version=1,
            workspace_path="/runtime",
        )
        bound = await repository.resolve_authority_in_session(
            session,
            agent_id=agent_id,
            session_id=root.id,
            target=target,
            bind_pending=True,
        )
    locked = asyncio.Event()
    release = asyncio.Event()

    async def hold_rows() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.select(RDBAgent).where(RDBAgent.id == agent_id).with_for_update()
            )
            await session.write_session.execute(
                sa.select(RDBSessionAgentContext)
                .where(RDBSessionAgentContext.id == bound.context_id)
                .with_for_update()
            )
            locked.set()
            await release.wait()

    holder = asyncio.create_task(hold_rows())
    try:
        await locked.wait()
        projected = await asyncio.wait_for(
            repository.project_bound_authority(
                agent_id=agent_id,
                session_id=root.id,
                target=target,
            ),
            timeout=5,
        )
        assert projected == bound
        assert not release.is_set()
    finally:
        release.set()
        await holder
        async with writes() as session:
            # Break the nullable context/root FK before deleting this test's tree.
            await session.write_session.execute(
                sa.update(RDBSessionAgentContext)
                .where(RDBSessionAgentContext.id == bound.context_id)
                .values(root_session_agent_id=None)
            )
            await session.write_session.execute(
                sa.delete(RDBSessionAgent).where(
                    RDBSessionAgent.context_id == bound.context_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBSessionAgentContext).where(
                    RDBSessionAgentContext.id == bound.context_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.workspace_id == workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
