"""Completed Engine Runtime Toolkit read tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.engine_runtime_tool_read import EngineRuntimeToolReadRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session_workspace_project import (
    SessionWorkspaceProjectRepository,
)


async def test_runtime_tool_reads_close_transactions_before_returning() -> None:
    """Runtime projections return only after their read transactions close."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False
    transaction_count = 0

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active, transaction_count
        assert not transaction_active
        transaction_active = True
        transaction_count += 1
        try:
            yield session
        finally:
            transaction_active = False

    runtime = SimpleNamespace(id="runtime-1")
    configuration = SimpleNamespace(configuration_sequence=3)
    project = SimpleNamespace(path="/workspace/agent/project")
    runtimes = AsyncMock(spec=AgentRuntimeRepository)
    profiles = AsyncMock(spec=RuntimeProfileRepository)
    projects = AsyncMock(spec=SessionWorkspaceProjectRepository)

    async def get_runtime(
        current_session: WriteSession,
        agent_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert agent_id == "agent-1"
        return runtime

    async def get_configuration(
        current_session: WriteSession,
        *,
        runtime_id: str,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert runtime_id == "runtime-1"
        return configuration

    async def list_projects(
        current_session: WriteSession,
        *,
        session_id: str,
    ) -> list[object]:
        assert transaction_active
        assert current_session is session
        assert session_id == "session-1"
        return [project]

    runtimes.get_by_agent_id.side_effect = get_runtime
    profiles.get_configuration_state.side_effect = get_configuration
    projects.list_projects.side_effect = list_projects
    reads = EngineRuntimeToolReadRepository(
        session_manager=session_manager,
        agent_runtime_repository=runtimes,
        runtime_profile_repository=profiles,
        project_repository=projects,
    )

    behavior = await reads.load_behavior(agent_id="agent-1")
    assert not transaction_active
    assert behavior is not None
    assert behavior.runtime is runtime
    assert behavior.configuration is configuration

    listed = await reads.list_projects(session_id="session-1")
    assert not transaction_active
    assert listed == [project]

    assert await reads.list_projects(session_id="") == []
    assert not transaction_active
    assert transaction_count == 2
