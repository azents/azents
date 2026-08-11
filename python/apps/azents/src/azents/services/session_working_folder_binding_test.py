"""Session working-folder binding authority tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.runtime_capabilities import RuntimeCapabilitySnapshot
from azents.repos.agent.data import Agent
from azents.repos.agent_session import LockedSessionWorkingFolderBinding
from azents.repos.agent_session.data import SessionWorkingFolderContext
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)


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
        configuration_revision_id="revision-1",
        configuration_digest="a" * 64,
        workspace_path="/workspace/agent",
    )


def _service() -> SessionWorkingFolderBindingService:
    """Create a service with deterministic repository doubles."""
    agent_repository = AsyncMock()
    agent_repository.lock_by_id.return_value = cast(
        Agent,
        SimpleNamespace(
            id="agent-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
            runtime_capability_version=4,
        ),
    )
    agent_session_repository = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession]:
        yield AsyncMock(spec=AsyncSession)

    return SessionWorkingFolderBindingService(
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        session_manager=session_manager,
    )


@pytest.mark.asyncio
async def test_pending_context_binds_from_current_runner_workspace() -> None:
    """Current Runtime evidence performs the one allowed pending bind."""
    service = _service()
    repository = cast(Any, service.agent_session_repository)
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
            shell_enabled=True,
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
    repository = cast(Any, service.agent_session_repository)
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
    cast(Any, service.agent_repository).lock_by_id.assert_awaited_once_with(
        transaction,
        "agent-1",
    )
    repository.lock_working_folder_binding_by_session_id.assert_awaited_once_with(
        transaction,
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_stale_capability_fails_before_context_lock() -> None:
    """A changed Agent capability version cannot bind or reuse a path."""
    service = _service()
    repository = cast(Any, service.agent_session_repository)

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
                shell_enabled=True,
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
    repository = cast(Any, service.agent_session_repository)
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
                shell_enabled=True,
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
    repository = cast(Any, service.agent_session_repository)
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
    repository = cast(Any, service.agent_session_repository)
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
