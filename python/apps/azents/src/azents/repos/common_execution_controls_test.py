"""Profile-free execution controls preserve common ownership and lifecycle fences."""

import datetime

import pytest
import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.session_execution_record_test import _internal_session
from azents.repos.worker_session_data import WorkerIdleDisposition
from azents.repos.worker_session_test import worker_repository


async def test_internal_execution_controls_require_no_conversation_or_tree(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A common Worker can claim, heartbeat, stop, idle and claim start once."""
    async with rdb_session_manager() as session:
        session_id = await _internal_session(session)
    worker = worker_repository(rdb_session_manager)
    generation = await worker.claim_owner_generation(session_id)
    await worker.mark_session_running(session_id)
    await worker.heartbeat_session(session_id, owner_generation=generation)
    now = datetime.datetime.now(datetime.UTC)
    assert await worker.claim_lifecycle_start(
        session_id, owner_generation=generation, now=now
    )
    assert not await worker.claim_lifecycle_start(
        session_id, owner_generation=generation, now=now
    )
    async with rdb_session_manager() as session:
        snapshot = await SessionExecutionRepository().load_common_snapshot(
            session, session_id=session_id, owner_generation=generation
        )
        assert snapshot.inference_state is None
        assert snapshot.lifecycle_root_session_id is None
        assert snapshot.run_state is AgentSessionRunState.RUNNING
        assert await AgentSessionRepository().get_by_id(session, session_id) is None
        assert (
            await session.read_session.scalar(
                sa.select(RDBSessionAgent.id).where(
                    RDBSessionAgent.agent_session_id == session_id
                )
            )
            is None
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(stop_requested_at=now, stop_request_id="internal-stop")
        )
    assert await worker.has_stop_request(session_id)
    transition = await worker.mark_session_idle(session_id, owner_generation=generation)
    assert transition.disposition is WorkerIdleDisposition.IDLE
    assert not await worker.has_stop_request(session_id)
    async with rdb_session_manager() as session:
        record = await SessionExecutionRecordRepository().get_by_id(session, session_id)
        assert record is not None
        assert record.run_state is AgentSessionRunState.IDLE
        assert record.lifecycle_started_at == now
    newer = await worker.claim_owner_generation(session_id)
    assert newer == generation + 1
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await worker.heartbeat_session(session_id, owner_generation=generation)


@pytest.mark.parametrize("invalid", ["stale", "idle", "archived", "agent"])
async def test_internal_snapshot_preserves_execution_admission(
    rdb_session: WriteSession, invalid: str
) -> None:
    """Private execution retains the same owner, status and Agent checks."""
    session_id = await _internal_session(rdb_session)
    records = SessionExecutionRecordRepository()
    generation = await records.claim_owner_generation(rdb_session, session_id)
    await records.mark_running(rdb_session, session_id)
    if invalid == "stale":
        generation += 1
    elif invalid == "idle":
        await records.mark_idle(rdb_session, session_id)
    elif invalid == "archived":
        await rdb_session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(status=AgentSessionStatus.ARCHIVED)
        )
    else:
        record = await records.get_by_id(rdb_session, session_id)
        assert record is not None
        await rdb_session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == record.agent_id)
            .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
        )
    with pytest.raises(CanonicalExecutionSnapshotError):
        await SessionExecutionRepository().load_common_snapshot(
            rdb_session, session_id=session_id, owner_generation=generation
        )


@pytest.mark.parametrize("invalid_root", ["archived", "foreign"])
async def test_common_root_admission_preserves_scope_and_archive_fence(
    rdb_session: WriteSession, invalid_root: str
) -> None:
    """Common lineage cannot admit archived or cross-owner lifecycle roots."""
    session_id = await _internal_session(rdb_session)
    records = SessionExecutionRecordRepository()
    generation = await records.claim_owner_generation(rdb_session, session_id)
    await records.mark_running(rdb_session, session_id)
    root_id = await _internal_session(rdb_session)
    if invalid_root == "archived":
        current = await records.get_by_id(rdb_session, session_id)
        assert current is not None
        await rdb_session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_id)
            .values(
                status=AgentSessionStatus.ARCHIVED,
                workspace_id=current.workspace_id,
                agent_id=current.agent_id,
            )
        )
    await rdb_session.write_session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id == session_id)
        .values(lifecycle_root_session_id=root_id)
    )
    with pytest.raises(ValueError, match="Root AgentSession"):
        await records.claim_owner_generation(rdb_session, session_id)
    with pytest.raises(CanonicalExecutionSnapshotError, match="Root AgentSession"):
        await SessionExecutionRepository().load_common_snapshot(
            rdb_session, session_id=session_id, owner_generation=generation
        )
    current = await records.get_by_id(rdb_session, session_id)
    assert current is not None
    assert current.owner_generation == generation
