"""Real PostgreSQL completion, attribution, rollback and foreign-scope evidence."""

import dataclasses
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from azents.core.agent_deletion import (
    AgentAvatarDeletionEvidence,
    AgentDeletionParticipantFailure,
)
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.core.enums import AgentDecommissionStatus, ExchangeFileOrigin
from azents.core.runtime_profile import (
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission.lease_test import _create_job
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_deletion_fence import deletion_context
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.runtime_profile.repository import RuntimeProfileRepository

_NOW = datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC)


async def _finalizing(session: WriteSession) -> AgentDecommissionJob:
    fixture = await _create_job(session)
    repository = AgentDecommissionRepository()
    job = await repository.claim_due(
        session,
        now=_NOW,
        lease_owner="owner",
        lease_until=_NOW + datetime.timedelta(minutes=15),
    )
    assert job is not None and job.id == fixture.job_id
    assert await repository.set_status(
        session,
        job_id=job.id,
        lease_owner="owner",
        expected_attempt=job.attempt_count,
        status=AgentDecommissionStatus.FINALIZING,
        now=_NOW,
    )
    return job


async def _finalize(
    session: WriteSession,
    job: AgentDecommissionJob,
    evidence: AgentAvatarDeletionEvidence,
) -> bool:
    return await AgentDecommissionFinalizerRepository(
        get_agent_deletion_registry()
    ).finalize(
        session,
        job_id=job.id,
        agent_id=job.agent_id,
        lease_owner="owner",
        expected_attempt=job.attempt_count,
        avatar_evidence=evidence,
        now=_NOW,
    )


@pytest.mark.parametrize(
    "boundary",
    [None, "agent.avatar/cleanup", "agent.runtime/verify", "unknown.previous/verify"],
)
async def test_completion_atomically_clears_all_prior_failure_evidence(
    rdb_session: WriteSession, boundary: str | None
) -> None:
    job = await _finalizing(rdb_session)
    other = await _create_agent(rdb_session)
    runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, job.agent_id)
    await rdb_session.write_session.execute(
        sa.update(RDBAgentDecommissionJob)
        .where(RDBAgentDecommissionJob.id == job.id)
        .values(
            failure_boundary_key=boundary,
            last_error_kind="RuntimeError",
            last_error_summary="Private diagnostic",
        )
    )
    evidence = AgentAvatarDeletionEvidence(
        deletion_context(job, lease_owner="owner"), ()
    )
    assert await _finalize(rdb_session, job, evidence)
    assert not await _finalize(rdb_session, job, evidence)
    assert await rdb_session.read_session.get(RDBAgent, job.agent_id) is None
    assert await rdb_session.read_session.get(RDBAgentRuntime, runtime.id) is None
    assert await rdb_session.read_session.get(RDBAgent, other.agent_id) is not None
    current = await AgentDecommissionRepository().get_by_agent_id(
        rdb_session, job.agent_id
    )
    assert current is not None and current.status is AgentDecommissionStatus.COMPLETED
    assert current.completed_at == _NOW
    assert current.failure_boundary_key is None
    assert current.last_error_kind is None and current.last_error_summary is None
    assert current.lease_owner is None and current.lease_until is None


@pytest.mark.parametrize(
    "mismatch", ["job", "agent", "workspace", "owner", "attempt", "keys"]
)
async def test_avatar_evidence_is_bound_to_current_attempt_and_targets(
    rdb_session: WriteSession, mismatch: str
) -> None:
    job = await _finalizing(rdb_session)
    context = deletion_context(job, lease_owner="owner")
    contexts = {
        "job": dataclasses.replace(context, job_id="other"),
        "agent": dataclasses.replace(context, agent_id="other"),
        "workspace": dataclasses.replace(context, workspace_id="other"),
        "owner": dataclasses.replace(context, lease_owner="other"),
        "attempt": dataclasses.replace(context, expected_attempt=0),
        "keys": context,
    }
    evidence = AgentAvatarDeletionEvidence(
        contexts[mismatch], ("old/avatar",) if mismatch == "keys" else ()
    )
    with pytest.raises(AgentDeletionParticipantFailure) as caught:
        await _finalize(rdb_session, job, evidence)
    assert caught.value.boundary_key == "agent.avatar/verify"
    assert await rdb_session.read_session.get(RDBAgent, job.agent_id) is not None
    current = await AgentDecommissionRepository().get_by_agent_id(
        rdb_session, job.agent_id
    )
    assert current is not None and current.status is AgentDecommissionStatus.FINALIZING


async def test_foreign_file_provenance_blocks_without_deleting_foreign_owner(
    rdb_session: WriteSession,
) -> None:
    job = await _finalizing(rdb_session)
    other = await _create_agent(rdb_session)
    file = RDBExchangeFile(
        workspace_id=other.workspace_id,
        agent_id=other.agent_id,
        origin_type=ExchangeFileOrigin.UPLOAD,
        filename="foreign.txt",
        media_type="text/plain",
        size_bytes=1,
        sha256="a" * 64,
        source_agent_id=job.agent_id,
        created_by_user_id=None,
        provenance_kind=None,
        source_user_id=None,
        source_run_id=None,
        source_tool_name=None,
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id=None,
        retention_bound_at=None,
        expires_at=_NOW + datetime.timedelta(days=1),
    )
    file.object_key = f"foreign/{uuid4().hex}"
    rdb_session.write_session.add(file)
    await rdb_session.write_session.flush()
    with pytest.raises(AgentDeletionParticipantFailure) as caught:
        await _finalize(
            rdb_session,
            job,
            AgentAvatarDeletionEvidence(deletion_context(job, lease_owner="owner"), ()),
        )
    assert (
        caught.value.boundary_key
        == "agent.files/verify:exchange_files(source_agent_id)"
    )
    assert await rdb_session.read_session.get(RDBAgent, job.agent_id) is not None
    assert await rdb_session.read_session.get(RDBAgent, other.agent_id) is not None
    preserved = await rdb_session.read_session.get(RDBExchangeFile, file.id)
    assert preserved is not None and preserved.source_agent_id == job.agent_id


async def test_late_actual_fk_failure_rolls_back_runtime_and_tombstone(
    rdb_session: WriteSession,
) -> None:
    job = await _finalizing(rdb_session)
    runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, job.agent_id)
    # Simulate a newly installed restrictive edge not yet in this binary's registry.
    # The outer fixture rolls back this test-owned schema and all rows.
    table = f"deletion_test_blocker_{uuid4().hex}"
    await rdb_session.write_session.execute(
        sa.text(
            f'CREATE TABLE "{table}" '
            "(agent_id varchar(32) REFERENCES agents(id) ON DELETE RESTRICT)"
        )
    )
    await rdb_session.write_session.execute(
        sa.text(f'INSERT INTO "{table}" (agent_id) VALUES (:agent_id)'),
        {"agent_id": job.agent_id},
    )
    with pytest.raises(IntegrityError):
        async with rdb_session.write_session.begin_nested():
            await _finalize(
                rdb_session,
                job,
                AgentAvatarDeletionEvidence(
                    deletion_context(job, lease_owner="owner"), ()
                ),
            )
    assert await rdb_session.read_session.get(RDBAgent, job.agent_id) is not None
    assert await rdb_session.read_session.get(RDBAgentRuntime, runtime.id) is not None
    current = await AgentDecommissionRepository().get_by_agent_id(
        rdb_session, job.agent_id
    )
    assert current is not None and current.status is AgentDecommissionStatus.FINALIZING
    assert current.completed_at is None and current.lease_owner == "owner"


@pytest.mark.parametrize("old_restrict_fk", [False, True])
async def test_runtime_deletion_preserves_recreation_history(
    rdb_session: WriteSession, old_restrict_fk: bool
) -> None:
    """The incident's exact historical edge blocks old schemas, not current ones."""
    if old_restrict_fk:
        # Install the old edge before fixtures enqueue deferred FK trigger events.
        # The enclosing test transaction rolls this schema change back as well.
        await rdb_session.write_session.execute(
            sa.text(
                "ALTER TABLE runtime_recreation_operation_items ADD CONSTRAINT "
                "runtime_recreation_operation_items_runtime_id_fkey "
                "FOREIGN KEY (runtime_id) REFERENCES agent_runtimes(id) "
                "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"
            )
        )
    job = await _finalizing(rdb_session)
    other = await _create_agent(rdb_session)
    runtimes = AgentRuntimeRepository()
    target = await runtimes.ensure_for_agent(rdb_session, job.agent_id)
    other_runtime = await runtimes.ensure_for_agent(rdb_session, other.agent_id)
    history = RuntimeProfileRepository()
    operation = await history.create_recreation_operation(
        rdb_session,
        target_kind=RuntimeRecreationTargetKind.PROVIDER,
        target_id="historical-provider",
        target_version="historical-revision",
        concurrency_limit=2,
        actor_user_id=None,
        actor_workspace_user_id=None,
    )
    await history.add_recreation_items(
        rdb_session,
        operation_id=operation.id,
        items=[
            (target.id, 1, "a" * 64, 0),
            (other_runtime.id, 2, "b" * 64, 1),
        ],
    )
    claimed = await history.claim_recreation_items(
        rdb_session, operation_id=operation.id, limit=2
    )
    assert len(claimed) == 2
    for item in claimed:
        failed = item.runtime_id == target.id
        assert await history.finish_recreation_item(
            rdb_session,
            item_id=item.id,
            expected_attempt=item.attempt,
            status=(
                RuntimeRecreationItemStatus.FAILED
                if failed
                else RuntimeRecreationItemStatus.SUCCEEDED
            ),
            failure_code="provider_failed" if failed else None,
            failure_message="Historical provider failure" if failed else None,
        )
    before_operation = await history.get_recreation_operation(
        rdb_session, operation_id=operation.id
    )
    assert before_operation is not None
    assert (
        before_operation.status
        is RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES
    )
    assert (
        before_operation.total_count,
        before_operation.pending_count,
        before_operation.running_count,
        before_operation.succeeded_count,
        before_operation.skipped_count,
        before_operation.failed_count,
    ) == (2, 0, 0, 1, 0, 1)
    before_items = await history.list_recreation_items(
        rdb_session, operation_id=operation.id, offset=0, limit=10
    )
    if old_restrict_fk:
        with pytest.raises(IntegrityError, match="runtime_id_fkey"):
            async with rdb_session.write_session.begin_nested():
                await _finalize(
                    rdb_session,
                    job,
                    AgentAvatarDeletionEvidence(
                        deletion_context(job, lease_owner="owner"), ()
                    ),
                )
    else:
        assert await _finalize(
            rdb_session,
            job,
            AgentAvatarDeletionEvidence(deletion_context(job, lease_owner="owner"), ()),
        )
    # Force fresh persisted evidence instead of comparing already-loaded ORM state.
    rdb_session.write_session.expire_all()
    assert (
        await rdb_session.read_session.get(RDBAgent, job.agent_id) is not None
    ) is old_restrict_fk
    assert (
        await rdb_session.read_session.get(RDBAgentRuntime, target.id) is not None
    ) is old_restrict_fk
    assert await rdb_session.read_session.get(RDBAgent, other.agent_id) is not None
    assert await runtimes.get_by_agent_id(rdb_session, other.agent_id) == other_runtime
    assert (
        await history.get_recreation_operation(rdb_session, operation_id=operation.id)
        == before_operation
    )
    assert (
        await history.list_recreation_items(
            rdb_session, operation_id=operation.id, offset=0, limit=10
        )
        == before_items
    )
