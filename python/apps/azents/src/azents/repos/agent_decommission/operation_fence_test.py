"""Every completed Agent cleanup mutation rejects a reclaimed attempt in PostgreSQL."""

import datetime
from unittest.mock import Mock

import pytest

from azents.core.agent_deletion import AgentDeletionOwnershipLost
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.core.enums import (
    AgentDecommissionStatus,
    ExchangeFileOrigin,
    ExchangeFileStatus,
)
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.lease_test import _create_job
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository


def _operations(
    manager: SessionManager[WriteSession],
) -> AgentDecommissionOperationsRepository:
    return AgentDecommissionOperationsRepository(
        session_manager=manager,
        read_session_manager=manager,
        agent_repository=AgentRepository(),
        decommission_repository=AgentDecommissionRepository(),
        finalizer_repository=AgentDecommissionFinalizerRepository(
            get_agent_deletion_registry()
        ),
        agent_session_repository=Mock(spec=AgentSessionRepository),
        agent_run_repository=Mock(),
        retention_repository=Mock(),
        runtime_repository=AgentRuntimeRepository(),
        exchange_file_repository=ExchangeFileRepository(),
        lifecycle_repository=Mock(),
        external_channel_repository=Mock(),
    )


@pytest.mark.parametrize("new_owner", ["owner", "replacement"])
@pytest.mark.parametrize(
    "operation",
    [
        "prepare_files",
        "blob_receipt",
        "finish_files",
        "channels",
        "retire_root",
        "avatar",
        "runtime_ack",
        "recovery",
        "phase",
        "preflight",
    ],
)
async def test_reclaimed_attempt_cannot_publish_cleanup(
    rdb_session_manager: SessionManager[WriteSession], new_owner: str, operation: str
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    repository = AgentDecommissionRepository()
    async with rdb_session_manager() as session:
        fixture = await _create_job(session)
        stale = await repository.claim_due(
            session,
            now=now,
            lease_owner="owner",
            lease_until=now + datetime.timedelta(seconds=1),
        )
        assert stale is not None and stale.id == fixture.job_id
        later = now + datetime.timedelta(seconds=2)
        current = await repository.claim_due(
            session,
            now=later,
            lease_owner=new_owner,
            lease_until=later + datetime.timedelta(minutes=15),
        )
        assert current is not None and current.attempt_count == stale.attempt_count + 1
    operations = _operations(rdb_session_manager)
    with pytest.raises(AgentDeletionOwnershipLost):
        match operation:
            case "prepare_files":
                await operations.prepare_files(job=stale, lease_owner="owner")
            case "blob_receipt":
                await operations.mark_blob_deleted(
                    job=stale,
                    lease_owner="owner",
                    file_id="file",
                    object_key="immutable/key",
                )
            case "finish_files":
                await operations.finish_files(job=stale, lease_owner="owner")
            case "channels":
                await operations.cleanup_channels(job=stale, lease_owner="owner")
            case "retire_root":
                await operations.retire_root_tree(
                    job=stale, lease_owner="owner", root_session_id="root"
                )
            case "avatar":
                await operations.read_avatar(job=stale, lease_owner="owner")
            case "runtime_ack":
                await operations.runtime_acknowledged(job=stale, lease_owner="owner")
            case "recovery":
                await operations.clear_failure_boundary(
                    job=stale, lease_owner="owner", boundary_key="agent.files/cleanup"
                )
            case "phase":
                await operations.advance_status(
                    job=stale,
                    lease_owner="owner",
                    status=AgentDecommissionStatus.FINALIZING,
                )
            case "preflight":
                await operations.require_owned(job=stale, lease_owner="owner")
            case _:
                raise AssertionError(operation)
    async with rdb_session_manager() as session:
        preserved = await repository.get_by_agent_id(session, fixture.agent_id)
        assert preserved == current
        assert await AgentRepository().get_by_id(session, fixture.agent_id) is not None


async def test_native_file_cleanup_requires_exact_receipts_and_preserves_other_agent(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        fixture = await _create_job(session)
        other = await _create_agent(session)
        file_ids: list[str] = []
        for owner in (fixture, other):
            file = RDBExchangeFile(
                workspace_id=owner.workspace_id,
                agent_id=owner.agent_id,
                origin_type=ExchangeFileOrigin.UPLOAD,
                filename="input.txt",
                media_type="text/plain",
                size_bytes=1,
                sha256="a" * 64,
                created_by_user_id=None,
                provenance_kind=None,
                source_user_id=None,
                source_agent_id=None,
                source_run_id=None,
                source_tool_name=None,
                source_provider=None,
                source_exchange_file_id=None,
                retention_root_session_id=None,
                retention_bound_at=None,
                expires_at=now + datetime.timedelta(days=1),
            )
            file.object_key = f"immutable/{owner.agent_id}"
            session.write_session.add(file)
            await session.write_session.flush()
            file_ids.append(file.id)
        job = await AgentDecommissionRepository().claim_due(
            session,
            now=now,
            lease_owner="owner",
            lease_until=now + datetime.timedelta(minutes=15),
        )
        assert job is not None
    operations = _operations(rdb_session_manager)
    targets = await operations.prepare_files(job=job, lease_owner="owner")
    assert len(targets) == 1 and targets[0].id == file_ids[0]
    await operations.finish_files(job=job, lease_owner="owner")
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBExchangeFile, file_ids[0]) is not None
    with pytest.raises(RuntimeError, match="blob target changed"):
        await operations.mark_blob_deleted(
            job=job,
            lease_owner="owner",
            file_id=targets[0].id,
            object_key="different/key",
        )
    await operations.mark_blob_deleted(
        job=job,
        lease_owner="owner",
        file_id=targets[0].id,
        object_key=targets[0].object_key,
    )
    await operations.finish_files(job=job, lease_owner="owner")
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBExchangeFile, file_ids[0]) is None
        preserved = await session.read_session.get(RDBExchangeFile, file_ids[1])
        assert preserved is not None
        assert preserved.status is ExchangeFileStatus.AVAILABLE
        assert preserved.blob_deleted_at is None
