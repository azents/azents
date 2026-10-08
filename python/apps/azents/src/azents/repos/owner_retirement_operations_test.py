"""PostgreSQL retirement atomicity, lease authority and completed-scope evidence."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.broker.types import SessionStopSignal
from azents.core.agent_session_data import AgentSession, AgentSessionCreate
from azents.core.enums import (
    AgentDecommissionStatus,
    AgentRuntimeCapability,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    OwnerLifecycleStatus,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.session_lifecycle import (
    SessionArchiveMutation,
    SessionLifecycleTransitionContext,
)
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import RDBArchivedSessionPurgeJob
from azents.rdb.models.owner_lifecycle import RDBOwnerLifecycleJob
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.memory import MemoryRepository
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.repos.owner_lifecycle_operations import OwnerLifecycleOperationsRepository
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.services.agent_decommission import AgentDecommissionService
from azents.services.owner_lifecycle import OwnerLifecycleService
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


def _lifecycle() -> SessionLifecycleOperationsRepository:
    return SessionLifecycleOperationsRepository(
        registry=get_session_lifecycle_registry(),
        agent_session_repository=AgentSessionRepository(),
        lifecycle_target_repository=LifecycleTargetRepository(),
        retention_repository=ArchivedSessionRetentionRepository(),
        external_channel_repository=ExternalChannelLifecycleRepository.create(),
        scheduled_task_repository=ScheduledTaskLifecycleRepository.create(),
    )


def _owner(
    write: SessionManager[WriteSession],
    read: SessionManager[ReadSession],
) -> OwnerLifecycleOperationsRepository:
    return OwnerLifecycleOperationsRepository(
        session_manager=write,
        read_session_manager=read,
        owner_lifecycle_repository=OwnerLifecycleRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AgentRunRepository(),
        memory_repository=MemoryRepository(),
        user_repository=UserRepository(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        mailbox_repository=MailboxRepository(),
        exchange_file_repository=ExchangeFileRepository(),
        external_channel_repository=ExternalChannelRepository.create(),
        lifecycle_repository=_lifecycle(),
    )


def _decommission(
    write: SessionManager[WriteSession],
    read: SessionManager[ReadSession],
) -> AgentDecommissionOperationsRepository:
    return AgentDecommissionOperationsRepository(
        session_manager=write,
        read_session_manager=read,
        agent_repository=AgentRepository(),
        decommission_repository=AgentDecommissionRepository(),
        finalizer_repository=AgentDecommissionFinalizerRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=AgentRunRepository(),
        retention_repository=ArchivedSessionRetentionRepository(),
        runtime_repository=AgentRuntimeRepository(),
        exchange_file_repository=ExchangeFileRepository(),
        lifecycle_repository=_lifecycle(),
        external_channel_repository=ExternalChannelLifecycleRepository.create(),
    )


@dataclasses.dataclass(frozen=True)
class _Subject:
    user_id: str
    workspace_id: str
    agent_id: str
    session_id: str


async def _subject(manager: SessionManager[WriteSession]) -> _Subject:
    suffix = uuid4().hex[:12]
    async with manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email=f"retirement-{suffix}@example.com"),
            verified_at=datetime.datetime.now(datetime.UTC),
        )
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="Retirement regression", handle=f"retirement-{suffix}"
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session, f"retirement-{suffix}"
        )
        assert workspace_id is not None
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Retirement regression",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection,
                lightweight_model_selection=selection,
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        root = await AgentSessionRepository().create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent.id,
                title=None,
                product_mode=AgentSessionProductMode.USER,
                associated_user_id=user.id,
            ),
        )
        return _Subject(
            user_id=user.id,
            workspace_id=workspace_id,
            agent_id=agent.id,
            session_id=root.id,
        )


async def _owner_job(
    manager: SessionManager[WriteSession],
    subject: _Subject,
) -> OwnerLifecycleJob:
    now = datetime.datetime.now(datetime.UTC)
    async with manager() as session:
        created = await OwnerLifecycleRepository().create_or_get_membership_archive(
            session,
            workspace_id=subject.workspace_id,
            user_id=subject.user_id,
        )
        claimed = await OwnerLifecycleRepository().claim_due(
            session,
            now=now,
            lease_owner="retirement-owner",
            lease_until=now + datetime.timedelta(minutes=15),
        )
        assert claimed is not None and claimed.id == created.id
        return claimed


async def _decommission_job(
    manager: SessionManager[WriteSession],
    subject: _Subject,
) -> AgentDecommissionJob:
    now = datetime.datetime.now(datetime.UTC)
    async with manager() as session:
        created = await AgentDecommissionRepository().create_or_get(
            session,
            agent_id=subject.agent_id,
            workspace_id=subject.workspace_id,
            requested_by_workspace_user_id=uuid4().hex,
        )
        claimed = await AgentDecommissionRepository().claim_due(
            session,
            now=now,
            lease_owner="retirement-owner",
            lease_until=now + datetime.timedelta(minutes=15),
        )
        assert claimed is not None and claimed.id == created.id
        return claimed


class _FailingOwner(OwnerLifecycleRepository):
    def __init__(self, *, cancel: bool) -> None:
        self.cancel = cancel

    async def set_status(
        self,
        session: WriteSession,
        *,
        job_id: str,
        lease_owner: str,
        status: OwnerLifecycleStatus,
        now: datetime.datetime,
    ) -> bool:
        await super().set_status(
            session, job_id=job_id, lease_owner=lease_owner, status=status, now=now
        )
        if self.cancel:
            raise asyncio.CancelledError("injected retirement cancellation")
        raise RuntimeError("injected retirement failure")


@pytest.mark.parametrize("cancel", [False, True])
async def test_owner_retirement_job_failure_rolls_back_archive_stop_and_purge_job(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    subject = await _subject(rdb_session_manager)
    job = await _owner_job(rdb_session_manager, subject)
    operations = dataclasses.replace(
        _owner(rdb_session_manager, rdb_session_manager),
        owner_lifecycle_repository=_FailingOwner(cancel=cancel),
    )
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await operations.retire_root_tree(
            job=job,
            lease_owner="retirement-owner",
            root_session_id=subject.session_id,
            immediate_purge=False,
        )
    async with rdb_session_manager() as session:
        root = await AgentSessionRepository().get_by_id(session, subject.session_id)
        assert root is not None and root.status is AgentSessionStatus.ACTIVE
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert row is not None and row.stop_request_id is None
        assert not await session.read_session.scalar(
            sa.select(
                sa.exists().where(
                    RDBArchivedSessionPurgeJob.root_session_id == subject.session_id
                )
            )
        )
        observed = await session.read_session.get(RDBOwnerLifecycleJob, job.id)
        assert observed is not None and observed.status is job.status


@pytest.mark.parametrize("domain", ["owner", "decommission"])
async def test_lost_job_lease_rolls_back_actual_root_mutations(
    rdb_session_manager: SessionManager[WriteSession],
    domain: str,
) -> None:
    subject = await _subject(rdb_session_manager)
    if domain == "owner":
        job = await _owner_job(rdb_session_manager, subject)
        with pytest.raises(RuntimeError, match="lease was lost"):
            await _owner(rdb_session_manager, rdb_session_manager).retire_root_tree(
                job=job,
                lease_owner="stale-owner",
                root_session_id=subject.session_id,
                immediate_purge=False,
            )
    else:
        decommission_job = await _decommission_job(rdb_session_manager, subject)
        with pytest.raises(RuntimeError, match="lease was lost"):
            await _decommission(
                rdb_session_manager, rdb_session_manager
            ).retire_root_tree(
                job=decommission_job,
                lease_owner="stale-owner",
                root_session_id=subject.session_id,
            )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert (
            row is not None
            and row.status is AgentSessionStatus.ACTIVE
            and row.stop_request_id is None
        )
        assert not await session.read_session.scalar(
            sa.select(
                sa.exists().where(
                    RDBArchivedSessionPurgeJob.root_session_id == subject.session_id
                )
            )
        )


class _FailingUser(UserRepository):
    async def delete(self, session: WriteSession, user_id: str) -> None:
        await super().delete(session, user_id)
        raise RuntimeError("injected final User deletion failure")


@pytest.mark.parametrize("already_archived", [False, True])
async def test_account_purge_accelerates_shared_job_and_preserves_archive_boundary(
    rdb_session_manager: SessionManager[WriteSession],
    already_archived: bool,
) -> None:
    """Keep the original archive boundary while advancing purge eligibility."""
    subject = await _subject(rdb_session_manager)
    original_archive_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        days=3
    )
    if already_archived:
        async with rdb_session_manager() as session:
            await _lifecycle().archive(
                session,
                SessionArchiveMutation(
                    context=SessionLifecycleTransitionContext(
                        transition_id=uuid4().hex,
                        root_session_id=subject.session_id,
                        subtree_session_ids=(subject.session_id,),
                    ),
                    archived_at=original_archive_at,
                ),
            )
    before = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        repository = OwnerLifecycleRepository()
        created = await repository.create_or_get_account_purge(
            session, user_id=subject.user_id
        )
        job = await repository.claim_due(
            session,
            now=before,
            lease_owner="retirement-owner",
            lease_until=before + datetime.timedelta(minutes=15),
        )
        assert job is not None and job.id == created.id
    outcome = await _owner(rdb_session_manager, rdb_session_manager).retire_root_tree(
        job=job,
        lease_owner="retirement-owner",
        root_session_id=subject.session_id,
        immediate_purge=True,
    )
    assert outcome.retired
    after = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        root = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert root is not None
        assert root.status is AgentSessionStatus.ARCHIVED
        assert root.archive_retention_days_snapshot == 0
        assert root.purge_after is not None and before <= root.purge_after <= after
        assert root.ended_at == root.archived_at
        if already_archived:
            assert root.archived_at == original_archive_at
        else:
            assert root.archived_at == root.purge_after
        purge = (
            await session.read_session.scalars(
                sa.select(RDBArchivedSessionPurgeJob).where(
                    RDBArchivedSessionPurgeJob.root_session_id == subject.session_id
                )
            )
        ).one()
        assert purge.eligible_at == root.purge_after
        assert purge.policy_revision == root.archive_policy_revision


async def test_account_finalization_rolls_back_job_and_actual_user_deletion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        user = await UserRepository().create_with_verified_primary_email(
            session,
            UserCreate(email="retirement-account@example.com"),
            verified_at=now,
        )
        created = await OwnerLifecycleRepository().create_or_get_account_purge(
            session, user_id=user.id
        )
        claimed = await OwnerLifecycleRepository().claim_due(
            session,
            now=now,
            lease_owner="retirement-owner",
            lease_until=now + datetime.timedelta(minutes=15),
        )
        assert claimed is not None and claimed.id == created.id
    operations = dataclasses.replace(
        _owner(rdb_session_manager, rdb_session_manager), user_repository=_FailingUser()
    )
    with pytest.raises(RuntimeError, match="User deletion"):
        await operations.finalize_account(job=claimed, lease_owner="retirement-owner")
    async with rdb_session_manager() as session:
        assert await UserRepository().get(session, user.id) is not None
        observed = await session.read_session.get(RDBOwnerLifecycleJob, claimed.id)
        assert (
            observed is not None
            and observed.completed_at is None
            and observed.lease_owner == "retirement-owner"
        )


class _FailingBroker:
    def __init__(self, active: list[bool]) -> None:
        self.active = active

    async def send_message(self, signal: SessionStopSignal) -> None:
        assert not self.active[0]
        assert signal.session_id
        raise RuntimeError("injected committed stop publication failure")


class _Cleanup:
    def __init__(self, active: list[bool]) -> None:
        self.active = active

    async def consume_archive_cleanup(
        self, plans: tuple[ProviderEffectPlan, ...]
    ) -> None:
        assert not self.active[0]
        assert not plans


async def test_broker_failure_is_postcommit_and_does_not_compensate_archive(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    subject = await _subject(rdb_session_manager)
    job = await _owner_job(rdb_session_manager, subject)
    active = [False]

    @asynccontextmanager
    async def tracked() -> AsyncIterator[WriteSession]:
        async with rdb_session_manager() as session:
            active[0] = True
            try:
                yield session
            finally:
                active[0] = False

    service = OwnerLifecycleService(
        operation_repository=_owner(tracked, tracked),
        external_channel_lifecycle_service=_Cleanup(active),
        broker=_FailingBroker(active),
    )
    with pytest.raises(RuntimeError, match="publication failure"):
        await service._retire_root_tree(
            job=job,
            lease_owner="retirement-owner",
            root_session_id=subject.session_id,
            immediate_purge=False,
        )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert (
            row is not None
            and row.status is AgentSessionStatus.ARCHIVED
            and row.stop_request_id is None
        )
        assert await session.read_session.scalar(
            sa.select(
                sa.exists().where(
                    RDBArchivedSessionPurgeJob.root_session_id == subject.session_id
                )
            )
        )


async def test_descriptive_reads_use_native_postgres_read_only_scopes(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    del latest_db_schema
    write = create_read_write_session_manager(rdb_engine)
    read = create_read_only_session_manager(rdb_engine)
    owner = _owner(write, read)
    decommission = _decommission(write, read)
    missing = uuid4().hex
    assert await owner.membership_roots(workspace_id=missing, user_id=missing) == ()
    assert await owner.account_roots(user_id=missing) == ()
    assert not await owner.remaining_user_sessions(user_id=missing)
    assert await decommission.list_roots(agent_id=missing) == ()
    assert not await decommission.runtime_bound(agent_id=missing)


class _CancelledStop(AgentSessionRepository):
    async def request_stop(
        self,
        session: WriteSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> AgentSession | None:
        result = await super().request_stop(
            session,
            session_id=session_id,
            stop_request_id=stop_request_id,
            stop_requester_user_id=stop_requester_user_id,
        )
        assert result is not None
        raise asyncio.CancelledError("injected actual stop cancellation")


async def test_cancellation_after_actual_running_stop_write_rolls_back(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    subject = await _subject(rdb_session_manager)
    job = await _owner_job(rdb_session_manager, subject)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == subject.session_id,
            )
            .values(run_state=AgentSessionRunState.RUNNING)
        )
    operations = dataclasses.replace(
        _owner(rdb_session_manager, rdb_session_manager),
        agent_session_repository=_CancelledStop(),
    )
    with pytest.raises(asyncio.CancelledError, match="actual stop"):
        await operations.retire_root_tree(
            job=job,
            lease_owner="retirement-owner",
            root_session_id=subject.session_id,
            immediate_purge=False,
        )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert (
            row is not None
            and row.run_state is AgentSessionRunState.RUNNING
            and row.stop_request_id is None
        )


class _FailingCleanup:
    def __init__(self, active: list[bool]) -> None:
        self.active = active

    async def consume_archive_cleanup(self, plans: Sequence[ProviderEffectPlan]) -> int:
        del plans
        assert not self.active[0]
        raise RuntimeError("injected postcommit provider cleanup failure")


async def test_decommission_provider_failure_keeps_committed_cleanup_phase(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    subject = await _subject(rdb_session_manager)
    job = await _decommission_job(rdb_session_manager, subject)
    active = [False]

    @asynccontextmanager
    async def tracked() -> AsyncIterator[WriteSession]:
        async with rdb_session_manager() as session:
            active[0] = True
            try:
                yield session
            finally:
                active[0] = False

    service = object.__new__(AgentDecommissionService)
    service.operation_repository = _decommission(tracked, tracked)
    service.external_channel_lifecycle_service = _FailingCleanup(active)
    with pytest.raises(RuntimeError, match="postcommit provider"):
        await service._cleanup_agent_external_roots(
            job=job, lease_owner="retirement-owner"
        )
    async with rdb_session_manager() as session:
        observed = await session.read_session.get(RDBAgentDecommissionJob, job.id)
        assert (
            observed is not None
            and observed.status is AgentDecommissionStatus.FINALIZING
        )


async def test_same_lease_owner_stale_attempt_cannot_mutate_or_finalize(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """An older claim cannot act after the same scheduler identity reclaims work."""
    subject = await _subject(rdb_session_manager)
    job = await _decommission_job(rdb_session_manager, subject)
    operations = _decommission(rdb_session_manager, rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentDecommissionJob)
            .where(
                RDBAgentDecommissionJob.id == job.id,
            )
            .values(
                attempt_count=job.attempt_count + 1,
                status=AgentDecommissionStatus.FINALIZING,
            )
        )
    assert not await operations.set_status(
        job_id=job.id,
        lease_owner="retirement-owner",
        expected_attempt=job.attempt_count,
        status=AgentDecommissionStatus.RETIRING_SESSIONS,
    )
    assert not await operations.finalize(job=job, lease_owner="retirement-owner")
    with pytest.raises(RuntimeError, match="lease was lost"):
        await operations.retire_root_tree(
            job=job, lease_owner="retirement-owner", root_session_id=subject.session_id
        )
    with pytest.raises(RuntimeError, match="lease was lost"):
        await operations.prepare_external_cleanup(
            job=job, lease_owner="retirement-owner"
        )
    now = datetime.datetime.now(datetime.UTC)
    assert not await operations.mark_retry(
        job=job,
        lease_owner="retirement-owner",
        next_attempt_at=now + datetime.timedelta(minutes=1),
        error_kind="StaleAttempt",
        error_summary="Stale claim",
        now=now,
    )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentSession, subject.session_id)
        assert row is not None and row.status is AgentSessionStatus.ACTIVE
        observed = await session.read_session.get(RDBAgentDecommissionJob, job.id)
        assert (
            observed is not None
            and observed.status is AgentDecommissionStatus.FINALIZING
        )
        assert (
            observed.attempt_count == job.attempt_count + 1
            and observed.lease_owner == "retirement-owner"
        )
