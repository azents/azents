"""Runtime descriptions stay independent from actual dispatch mutation fences."""

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from azents_runtime_control.provider import RuntimeLifecycleCommandType
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import AgentRuntimeCapability
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.runtime_lifecycle_dispatch.data import (
    RuntimeLifecycleDispatchPreflight,
    RuntimeLifecycleDispatchRejection,
    RuntimeLifecycleDispatchRejectionReason,
    RuntimeLifecycleDispatchRequest,
)
from azents.repos.runtime_lifecycle_dispatch.repository import (
    RuntimeLifecycleDispatchRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["generation", "configuration", "provider"])
async def test_runtime_preflight_is_nonblocking_but_replaced_target_cannot_claim(
    rdb_engine: AsyncEngine, latest_db_schema: None, replacement: str
) -> None:
    """A successful lagged preflight does not authorize dispatch after replacement."""
    writes = create_read_write_session_manager(rdb_engine)
    runtimes = AgentRuntimeRepository()
    async with writes() as session:
        fixture = await _create_agent(session)
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fixture.agent_id)
            .values(runtime_capability=AgentRuntimeCapability.MANAGED)
        )
        runtime = await runtimes.ensure_for_agent(session, fixture.agent_id)
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(runtime_provider_id="original-provider")
        )
    async with writes() as session:
        runtime = await runtimes.get_by_agent_id(session, fixture.agent_id)
    assert runtime is not None
    repository = RuntimeLifecycleDispatchRepository(
        agent_repository=AgentRepository(),
        runtime_repository=runtimes,
        profile_repository=RuntimeProfileRepository(),
        session_manager=writes,
    )
    request = RuntimeLifecycleDispatchRequest(
        runtime=runtime,
        command_type=RuntimeLifecycleCommandType.STOP,
        claim_lifecycle=True,
        required_provider_generation=None,
        required_observed_generation=None,
        required_configuration_sequence=None,
        lifecycle_retry_delay=datetime.timedelta(seconds=1),
    )
    held, release = asyncio.Event(), asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.select(RDBAgent.id)
                .where(RDBAgent.id == fixture.agent_id)
                .with_for_update()
            )
            await session.write_session.execute(
                sa.select(RDBAgentRuntime.id)
                .where(RDBAgentRuntime.id == runtime.id)
                .with_for_update()
            )
            held.set()
            await release.wait()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(held.wait(), timeout=5)
        preflight = await asyncio.wait_for(repository.preflight(request), timeout=5)
        assert isinstance(preflight, RuntimeLifecycleDispatchPreflight)
        assert preflight.runtime_id == runtime.id
        assert not release.is_set()
        release.set()
        await task
        async with writes() as session:
            match replacement:
                case "generation":
                    statement = sa.update(RDBAgentRuntime).values(
                        desired_generation=RDBAgentRuntime.desired_generation + 1
                    )
                case "configuration":
                    statement = sa.update(RDBAgentRuntime).values(
                        configuration_sequence=RDBAgentRuntime.configuration_sequence
                        + 1
                    )
                case "provider":
                    statement = sa.update(RDBAgentRuntime).values(
                        runtime_provider_id="replacement-provider"
                    )
                case _:
                    raise AssertionError("Unsupported replacement case.")
            await session.write_session.execute(
                statement.where(RDBAgentRuntime.id == runtime.id)
            )
        rejected = await repository.claim(preflight, connection_generation=1)
        assert isinstance(rejected, RuntimeLifecycleDispatchRejection)
        assert (
            rejected.reason
            is RuntimeLifecycleDispatchRejectionReason.RUNTIME_SNAPSHOT_CHANGED
        )
    finally:
        release.set()
        await task
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.id == runtime.id)
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
