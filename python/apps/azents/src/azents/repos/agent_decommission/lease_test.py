"""Decommission completion keeps attempt and current resource identity exact."""

import datetime
from typing import NamedTuple
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    AgentDecommissionStatus,
    AgentLifecycleStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.runtime_profile.repository_test import _create_provider


class _DecommissionFixture(NamedTuple):
    workspace_id: str
    agent_id: str
    job_id: str


async def _create_job(session: WriteSession) -> _DecommissionFixture:
    fixture = await _create_agent(session)
    await session.write_session.execute(
        sa.update(RDBAgent)
        .where(RDBAgent.id == fixture.agent_id)
        .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
    )
    job = await AgentDecommissionRepository().create_or_get(
        session,
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        requested_by_workspace_user_id="workspace-user-1",
    )
    return _DecommissionFixture(fixture.workspace_id, fixture.agent_id, job.id)


@pytest.mark.asyncio
async def test_same_worker_reclaim_cannot_finalize_or_retry_old_decommission(
    rdb_session: WriteSession,
) -> None:
    """A reclaimed attempt is independent of the scheduler's stable owner label."""
    _, agent_id, job_id = await _create_job(rdb_session)
    repository = AgentDecommissionRepository()
    now = datetime.datetime.now(datetime.UTC)
    first = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="scheduler",
        lease_until=now + datetime.timedelta(seconds=1),
    )
    assert first is not None and first.id == job_id
    later = now + datetime.timedelta(seconds=2)
    winner = await repository.claim_due(
        rdb_session,
        now=later,
        lease_owner="scheduler",
        lease_until=later + datetime.timedelta(minutes=1),
    )
    assert winner is not None and winner.id == first.id
    assert winner.attempt_count == first.attempt_count + 1
    assert not await repository.set_status(
        rdb_session,
        job_id=job_id,
        lease_owner="scheduler",
        expected_attempt=first.attempt_count,
        status=AgentDecommissionStatus.FINALIZING,
        now=later,
    )
    assert not await repository.mark_retry(
        rdb_session,
        job_id=job_id,
        lease_owner="scheduler",
        expected_attempt=first.attempt_count,
        next_attempt_at=later,
        error_kind="obsolete",
        error_summary="Obsolete attempt.",
        now=later,
    )
    assert await repository.set_status(
        rdb_session,
        job_id=job_id,
        lease_owner="scheduler",
        expected_attempt=winner.attempt_count,
        status=AgentDecommissionStatus.FINALIZING,
        now=later,
    )
    assert not await AgentDecommissionFinalizerRepository().finalize(
        rdb_session,
        job_id=job_id,
        agent_id=agent_id,
        lease_owner="scheduler",
        expected_attempt=first.attempt_count,
        now=later,
    )
    assert await rdb_session.read_session.get(RDBAgent, agent_id) is not None
    current = await repository.get_by_agent_id(rdb_session, agent_id)
    assert current is not None and current.attempt_count == winner.attempt_count
    assert current.status is AgentDecommissionStatus.FINALIZING


@pytest.mark.asyncio
@pytest.mark.parametrize("desired,ack", [(5, 4), (6, 5), (5, 5)])
async def test_decommission_requires_current_terminal_delete_ack(
    rdb_engine: AsyncEngine, latest_db_schema: None, desired: int, ack: int
) -> None:
    """Only an exact current acknowledgement permits Agent deletion."""
    writes = create_read_write_session_manager(rdb_engine)
    now = datetime.datetime.now(datetime.UTC)
    async with writes() as session:
        workspace_id, agent_id, job_id = await _create_job(session)
        provider_id = await _create_provider(
            session, logical_id=f"decommission-{uuid4().hex}"
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                runtime_provider_resource_id=provider_id,
                desired_generation=desired,
                terminal_delete_requested_generation=5,
                terminal_delete_acknowledged_generation=ack,
                terminal_delete_acknowledged_at=now,
                terminal_delete_acknowledgement_kind=RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT,
            )
        )
        repository = AgentDecommissionRepository()
        claimed = await repository.claim_due(
            session,
            now=now,
            lease_owner="scheduler",
            lease_until=now + datetime.timedelta(minutes=1),
        )
        assert claimed is not None
        assert await repository.set_status(
            session,
            job_id=job_id,
            lease_owner="scheduler",
            expected_attempt=claimed.attempt_count,
            status=AgentDecommissionStatus.FINALIZING,
            now=now,
        )
    try:
        if desired != 5 or ack != 5:
            with pytest.raises(
                RuntimeError, match="terminal deletion is not acknowledged"
            ):
                async with writes() as session:
                    await AgentDecommissionFinalizerRepository().finalize(
                        session,
                        job_id=job_id,
                        agent_id=agent_id,
                        lease_owner="scheduler",
                        expected_attempt=claimed.attempt_count,
                        now=now,
                    )
            async with writes() as session:
                assert await session.read_session.get(RDBAgent, agent_id) is not None
        else:
            async with writes() as session:
                assert await AgentDecommissionFinalizerRepository().finalize(
                    session,
                    job_id=job_id,
                    agent_id=agent_id,
                    lease_owner="scheduler",
                    expected_attempt=claimed.attempt_count,
                    now=now,
                )
            async with writes() as session:
                assert await session.read_session.get(RDBAgent, agent_id) is None
                assert (
                    await session.read_session.get(RDBAgentRuntime, runtime.id) is None
                )
    finally:
        async with writes() as session:
            for model, predicate in (
                (RDBAgentDecommissionJob, RDBAgentDecommissionJob.id == job_id),
                (RDBAgentRuntime, RDBAgentRuntime.id == runtime.id),
                (RDBAgent, RDBAgent.id == agent_id),
                (RDBRuntimeProvider, RDBRuntimeProvider.id == provider_id),
                (RDBWorkspace, RDBWorkspace.id == workspace_id),
            ):
                await session.write_session.execute(sa.delete(model).where(predicate))
