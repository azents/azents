"""Durable unresolved failures are independent from scheduler claims and waits."""

import datetime

import pytest
import sqlalchemy as sa

from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.lease_test import _create_job


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_failure_latch_survives_reclaim_wait_and_unrelated_success(
    rdb_session: WriteSession, legacy: bool
) -> None:
    _, agent_id, job_id = await _create_job(rdb_session)
    repository = AgentDecommissionRepository()
    now = datetime.datetime.now(datetime.UTC)
    if legacy:
        await rdb_session.write_session.execute(
            sa.update(RDBAgentDecommissionJob)
            .where(RDBAgentDecommissionJob.id == job_id)
            .values(last_error_kind="RuntimeError", last_error_summary="Old error")
        )
    first = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="worker",
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert first is not None and first.id == job_id
    assert await repository.mark_retry(
        rdb_session,
        job_id=job_id,
        lease_owner="worker",
        expected_attempt=first.attempt_count,
        next_attempt_at=now,
        failure_boundary_key="agent.avatar/cleanup",
        error_kind="OSError",
        error_summary="Object-store diagnostic",
        now=now,
    )
    second = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="worker",
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert second is not None and second.last_error_kind == "OSError"
    expected_key = None if legacy else "agent.avatar/cleanup"
    assert second.failure_boundary_key == expected_key
    assert await repository.mark_retry(
        rdb_session,
        job_id=job_id,
        lease_owner="worker",
        expected_attempt=second.attempt_count,
        next_attempt_at=now,
        failure_boundary_key="agent.files/cleanup",
        error_kind="EarlierFailure",
        error_summary="A different earlier participant failed",
        now=now,
    )
    third = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="worker",
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert third is not None and third.failure_boundary_key == expected_key
    for boundary, attempt in (
        ("agent.files/cleanup", third.attempt_count),
        ("agent.avatar/cleanup", first.attempt_count),
    ):
        await repository.clear_failure_boundary(
            rdb_session,
            job_id=job_id,
            lease_owner="worker",
            expected_attempt=attempt,
            boundary_key=boundary,
            now=now,
        )
    assert await repository.schedule_wait(
        rdb_session,
        job_id=job_id,
        lease_owner="worker",
        expected_attempt=third.attempt_count,
        next_attempt_at=now,
        now=now,
    )
    waiting = await repository.get_by_agent_id(rdb_session, agent_id)
    assert waiting is not None and waiting.failure_boundary_key == expected_key
    assert waiting.last_error_kind == "EarlierFailure"
    recovered = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="worker",
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert recovered is not None
    await repository.clear_failure_boundary(
        rdb_session,
        job_id=job_id,
        lease_owner="worker",
        expected_attempt=recovered.attempt_count,
        boundary_key="agent.avatar/cleanup",
        now=now,
    )
    current = await repository.get_by_agent_id(rdb_session, agent_id)
    assert current is not None and current.failure_boundary_key is None
    assert current.last_error_kind == ("EarlierFailure" if legacy else None)
    assert (current.last_error_summary is not None) is legacy


@pytest.mark.asyncio
async def test_expected_wait_does_not_create_failure(rdb_session: WriteSession) -> None:
    _, agent_id, job_id = await _create_job(rdb_session)
    repository = AgentDecommissionRepository()
    now = datetime.datetime.now(datetime.UTC)
    job = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="worker",
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert job is not None
    assert await repository.schedule_wait(
        rdb_session,
        job_id=job_id,
        lease_owner="worker",
        expected_attempt=job.attempt_count,
        next_attempt_at=now,
        now=now,
    )
    current = await repository.get_by_agent_id(rdb_session, agent_id)
    assert current is not None
    assert current.failure_boundary_key is None
    assert current.last_error_kind is None
    assert current.last_error_summary is None
