"""Deletion waiting is a description; acknowledgement recording is exact."""

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import RuntimeTerminalDeleteAcknowledgementKind
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_runtime_removal import RDBAgentRuntimeRemovalOperation
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.services.agent_runtime_removal.service_test import _service


@pytest.mark.asyncio
async def test_pending_delete_observation_nonblocking_and_replaced_ack_rejected(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Waiting does not take owner/resource locks or accept an older generation ack."""
    writes = create_read_write_session_manager(rdb_engine)
    removals = AgentRuntimeRemovalRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with writes() as session:
        fixture = await _create_agent(session)
        runtime = await AgentRuntimeRepository().ensure_for_agent(
            session, fixture.agent_id
        )
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(desired_generation=5, terminal_delete_requested_generation=5)
        )
        await removals.create_or_get_active(
            session,
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            requested_by_workspace_user_id="workspace-user-1",
            idempotency_key="wait-delete",
            expected_capability_version=1,
            committed_capability_version=2,
            agent_runtime_id=runtime.id,
            confirmed_at=now,
            destructive_scope_version=1,
            active_root_session_count=0,
            active_subagent_count=0,
            active_run_count=0,
            queued_runtime_action_count=0,
        )
        operation = await removals.claim_due(
            session,
            now=now,
            lease_owner="worker",
            lease_until=now + datetime.timedelta(minutes=5),
        )
        assert operation is not None
        assert await removals.record_physical_delete_target(
            session,
            operation_id=operation.id,
            lease_owner="worker",
            expected_attempt=operation.attempt_count,
            required=True,
            target_generation=5,
            requested_at=now,
            now=now,
        )
    async with writes() as session:
        operation = await removals.get_by_id(session, operation.id)
    assert operation is not None
    service = _service(writes)
    held, release = asyncio.Event(), asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.select(RDBAgentRuntimeRemovalOperation.id)
                .where(RDBAgentRuntimeRemovalOperation.id == operation.id)
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
        assert not await asyncio.wait_for(
            service._delete_runtime(operation=operation, lease_owner="worker"),
            timeout=5,
        )
        assert not release.is_set()
        release.set()
        await task
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == runtime.id)
                .values(
                    desired_generation=6,
                    terminal_delete_acknowledged_generation=5,
                    terminal_delete_acknowledgement_kind=RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT,
                    terminal_delete_acknowledged_at=now,
                )
            )
        assert not await service._delete_runtime(
            operation=operation, lease_owner="worker"
        )
        async with writes() as session:
            current = await removals.get_by_id(session, operation.id)
        assert current is not None
        assert current.target_terminal_delete_generation == 5
        assert current.physical_delete_acknowledged_at is None
    finally:
        release.set()
        await task
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentRuntimeRemovalOperation).where(
                    RDBAgentRuntimeRemovalOperation.id == operation.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.id == runtime.id)
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
