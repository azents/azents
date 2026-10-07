"""Real Memory execution acceptance, common retention and purge boundaries."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa
from azcommon.uuid import uuid7

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    ArchivedSessionPurgeStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
    ConsolidationWorkKind,
    FreshMemoryAdmission,
    MemoryExecutionAuthorityError,
    MemoryExecutionBinding,
    MemoryExecutionPrincipal,
    TakeoverMemoryAdmission,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionPurgeJob,
    RDBSystemFileLifecycleSetting,
)
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_execution import (
    RDBMemoryExecution,
    RDBMemoryUnit,
    RDBMemoryWork,
)
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate, AgentRunPatch
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_purge_operations import (
    ArchivedSessionPurgeOperations,
)
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel_lifecycle_participant import (
    ExternalChannelLifecycleParticipantRepository,
)
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.historical_memory_consolidation.work import enroll_memory_work
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.lifecycle_target_test import lifecycle_pipeline
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_operation_completion import ModelOperationCompletionRepository
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.scheduled_task_lifecycle_participant import (
    ScheduledTaskLifecycleParticipantRepository,
)
from azents.repos.session_archive_operations import SessionArchiveOperations
from azents.repos.session_diagnostics import SessionDiagnosticRepository
from azents.repos.session_execution.repository_test import _create_execution_subject
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.repos.session_lifecycle_purge_operations import (
    SessionLifecyclePurgeOperations,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.archived_session_purge import ArchivedSessionPurgeService
from azents.services.archived_session_purge_test import _build_service
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)


@dataclasses.dataclass(frozen=True)
class _Corpus:
    key: ConsolidationUnitKey
    source_id: str
    work_id: str
    saved_id: str


def _repository(manager: SessionManager[WriteSession]) -> MemoryExecutionRepository:
    """Compose the real atomic model-success collaborator, including no-op state."""
    return MemoryExecutionRepository(
        manager,
        manager,
        ModelOperationCompletionRepository(
            AgentSessionRepository(),
            AgentRunRepository(),
            ModelCandidateHealthRepository(manager),
        ),
    )


async def _corpus(manager: SessionManager[WriteSession], *, handle: str) -> _Corpus:
    """Persist one actual prepared source and independently owned Saved Memory."""
    async with manager() as session:
        source, agent_id = await _create_execution_subject(session, handle=handle)
        agent = await session.read_session.get(RDBAgent, agent_id)
        assert agent is not None
        agent.memory_enabled = True
        await SessionExecutionRecordRepository().mark_idle(session, source.id)
        key = ConsolidationUnitKey(
            workspace_id=source.workspace_id,
            agent_id=agent_id,
            scope=ConsolidationScope.TEAM,
            associated_user_id=None,
        )
        now = datetime.datetime.now(datetime.UTC)
        prepared = RDBHistoricalMemorySource(
            source_session_id=source.id, admitted_at=now
        )
        prepared.prepared_at = now
        prepared.completed_source_activity_at = now
        prepared.completed_source_tail_event_id = uuid7().hex
        prepared.source_title_snapshot = "Prepared source"
        prepared.summary = "Prepared summary only."
        saved = RDBAgentMemory(
            agent_id=agent_id,
            scope="agent",
            type="note",
            name="independent-saved-memory",
            description="Saved Memory is not a temporary execution payload.",
            content="Keep this independently saved note.",
            user_id=None,
        )
        session.write_session.add_all([prepared, saved])
        work_id = await enroll_memory_work(
            session,
            key,
            source_session_id=source.id,
            kind=ConsolidationWorkKind.PREPARED,
        )
        await session.write_session.flush()
        return _Corpus(key, source.id, work_id, saved.id)


async def _principal(
    manager: SessionManager[WriteSession], binding: MemoryExecutionBinding
) -> MemoryExecutionPrincipal:
    """Use the real common ownership and Run repositories for the private host."""
    async with manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, binding.session_id
        )
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=binding.session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
        return MemoryExecutionPrincipal(
            binding, SessionExecutionOwner(binding.session_id, generation), run.id
        )


async def _start(
    manager: SessionManager[WriteSession], key: ConsolidationUnitKey
) -> MemoryExecutionPrincipal:
    repository = _repository(manager)
    binding = await repository.ensure_execution(
        key,
        admission=FreshMemoryAdmission(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
            HistoricalMemoryExecutionConfig(max_turns=10, timeout_seconds=600),
        ),
    )
    assert binding is not None
    principal = await _principal(manager, binding)
    await repository.provision_inputs(principal)
    return principal


def _archive(manager: SessionManager[WriteSession]) -> SessionArchiveOperations:
    return SessionArchiveOperations(
        manager, LifecycleTargetRepository(), AgentRunRepository(), lifecycle_pipeline()
    )


def _purger(manager: SessionManager[WriteSession]) -> ArchivedSessionPurgeService:
    """Use actual shared claim, checkpoint, participants and common finalization."""
    retention = ArchivedSessionRetentionRepository()
    checkpoints = SessionLifecyclePurgeOperations(
        session_manager=manager,
        read_only_session_manager=manager,
        retention_repository=retention,
        registry=get_session_lifecycle_registry(),
    )
    service, *_ = _build_service(events=[], active_checks=[])
    service.operations = ArchivedSessionPurgeOperations(
        session_manager=manager,
        read_only_session_manager=manager,
        retention_repository=retention,
        lifecycle_target_repository=LifecycleTargetRepository(),
        agent_run_repository=AgentRunRepository(),
        model_file_repository=ModelFileRepository(),
        artifact_repository=ArtifactRepository(),
        exchange_file_repository=ExchangeFileRepository(),
        lifecycle_finalizer_repository=SessionLifecycleFinalizerRepository(),
        lifecycle_operations=checkpoints,
        scheduled_participant=ScheduledTaskLifecycleParticipantRepository(
            ScheduledTaskLifecycleRepository()
        ),
        external_participant=ExternalChannelLifecycleParticipantRepository(
            ExternalChannelLifecycleRepository()
        ),
    )
    service.lifecycle_orchestrator = get_session_lifecycle_orchestrator(checkpoints)
    return service


@pytest.mark.parametrize("retention_days", [None, 7])
async def test_accepted_execution_retains_canonical_audit_under_common_policy(
    rdb_session_manager: SessionManager[WriteSession], retention_days: int | None
) -> None:
    """Accepted input, authored output and events survive finite/Unlimited archive."""
    corpus = await _corpus(rdb_session_manager, handle="memory-accepted-retention")
    repository = _repository(rdb_session_manager)
    principal = await _start(rdb_session_manager, corpus.key)
    await SessionExecutionFileRepository(rdb_session_manager).write(
        principal.owner,
        "result.md",
        "Integrated result.",
        None,
        True,
        overwrite=False,
    )
    async with rdb_session_manager() as session:
        await ArchivedSessionRetentionRepository().get_settings(session)
        await session.write_session.execute(
            sa.update(RDBSystemFileLifecycleSetting)
            .where(RDBSystemFileLifecycleSetting.id == 1)
            .values(archived_session_retention_days=retention_days)
        )
        event = RDBEvent(
            session_id=principal.binding.session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                sender_user_id=None, content="Explicitly submit the authored result."
            ).model_dump(mode="json"),
        )
        session.write_session.add(event)
        await session.write_session.flush()
        event_id = event.id
    outcome = await repository.submit(
        principal, tool_call_id="accepted-retention-call", authored_path="result.md"
    )
    assert outcome.settled_work_count == 1
    await _archive(rdb_session_manager).archive(
        root_session_id=principal.binding.session_id,
        expected_owner_generation=principal.owner.owner_generation,
    )
    diagnostics = SessionDiagnosticRepository(rdb_session_manager)
    metadata = await diagnostics.metadata(
        session_id=outcome.session_id, workspace_id=corpus.key.workspace_id
    )
    assert metadata is not None and metadata.status is AgentSessionStatus.ARCHIVED
    events = await diagnostics.events(
        session_id=outcome.session_id,
        workspace_id=corpus.key.workspace_id,
        after=None,
        limit=20,
    )
    assert events is not None and event_id in [item.event_id for item in events.items]
    for path, expected in [
        (f"inputs/{corpus.source_id}.md", "Prepared summary only."),
        ("result.md", "Integrated result."),
    ]:
        file = await diagnostics.file(
            session_id=outcome.session_id,
            workspace_id=corpus.key.workspace_id,
            path=path,
            offset=0,
            limit=1000,
        )
        assert file is not None and file.content == expected
    async with rdb_session_manager() as session:
        job = await session.read_session.scalar(
            sa.select(RDBArchivedSessionPurgeJob).where(
                RDBArchivedSessionPurgeJob.root_session_id == outcome.session_id
            )
        )
        assert (job is None) is (retention_days is None)
        if job is not None:
            assert metadata.archived_at is not None
            assert job.eligible_at == metadata.archived_at + datetime.timedelta(days=7)
        assert (
            await session.read_session.get(RDBConversation, outcome.session_id) is None
        )
    assert (
        await repository.inspect_accepted(
            outcome.session_id, tool_call_id=outcome.tool_call_id
        )
        == outcome
    )


async def test_shared_purge_preserves_original_acceptance_result_and_unadmitted_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Temporary Session cascade cannot remove domain truth or later source work."""
    corpus = await _corpus(rdb_session_manager, handle="memory-accepted-shared-purge")
    repository = _repository(rdb_session_manager)
    principal = await _start(rdb_session_manager, corpus.key)
    await SessionExecutionFileRepository(rdb_session_manager).write(
        principal.owner,
        "result.md",
        "Accepted original integrated result.",
        None,
        True,
        overwrite=False,
    )
    async with rdb_session_manager() as session:
        late_work = await enroll_memory_work(
            session,
            corpus.key,
            source_session_id=corpus.source_id,
            kind=ConsolidationWorkKind.PREPARED,
        )
        await ArchivedSessionRetentionRepository().get_settings(session)
        await session.write_session.execute(
            sa.update(RDBSystemFileLifecycleSetting)
            .where(RDBSystemFileLifecycleSetting.id == 1)
            .values(archived_session_retention_days=0)
        )
    outcome = await repository.submit(
        principal, tool_call_id="purge-original-call", authored_path="result.md"
    )
    assert outcome.settled_work_count == 1
    result = await repository.current_result(corpus.key)
    assert (
        result is not None and result.markdown == "Accepted original integrated result."
    )
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        common = await session.read_session.get(RDBAgentSession, outcome.session_id)
        assert run is not None and run.status is AgentRunStatus.COMPLETED
        assert common is not None and common.run_state is AgentSessionRunState.IDLE
    await _archive(rdb_session_manager).archive(
        root_session_id=outcome.session_id,
        expected_owner_generation=principal.owner.owner_generation,
    )
    summary = await _purger(rdb_session_manager).purge_once(
        lease_owner="memory-common-purger",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1),
    )
    assert summary.completed_count == 1 and summary.failed_count == 0
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.get(RDBAgentSession, outcome.session_id) is None
        )
        assert await session.read_session.get(RDBAgentRun, principal.run_id) is None
        assert (
            list(
                await session.read_session.scalars(
                    sa.select(RDBSessionExecutionFile.path).where(
                        RDBSessionExecutionFile.session_id == outcome.session_id
                    )
                )
            )
            == []
        )
        assert (
            await session.read_session.get(RDBMemoryExecution, outcome.session_id)
            is not None
        )
        assert (
            await session.read_session.get(RDBMemoryUnit, principal.binding.unit_id)
            is not None
        )
        assert await session.read_session.get(RDBMemoryWork, corpus.work_id) is None
        pending = await session.read_session.get(RDBMemoryWork, late_work)
        assert pending is not None and pending.admitted_session_id is None
        assert (
            await session.read_session.get(RDBHistoricalMemorySource, corpus.source_id)
            is not None
        )
        assert (
            await session.read_session.get(RDBAgentSession, corpus.source_id)
            is not None
        )
        assert (
            await session.read_session.get(RDBAgentMemory, corpus.saved_id) is not None
        )
        job = await session.read_session.scalar(
            sa.select(RDBArchivedSessionPurgeJob).where(
                RDBArchivedSessionPurgeJob.root_session_id == outcome.session_id
            )
        )
        assert job is not None and job.status is ArchivedSessionPurgeStatus.COMPLETED
    assert await repository.current_result(corpus.key) == result
    assert (
        await repository.inspect_accepted(
            outcome.session_id, tool_call_id=outcome.tool_call_id
        )
        == outcome
    )
    assert (
        await repository.inspect_accepted(
            outcome.session_id, tool_call_id="another-call"
        )
        is None
    )


async def test_fresh_execution_has_only_current_inputs_and_exact_unit_predecessors(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A moved active pointer cannot hide predecessors or transfer their payload."""
    corpus = await _corpus(rdb_session_manager, handle="memory-fresh-isolation")
    unrelated = await _corpus(rdb_session_manager, handle="memory-unrelated-unit")
    repository = _repository(rdb_session_manager)
    first = await _start(rdb_session_manager, corpus.key)
    foreign = await _start(rdb_session_manager, unrelated.key)
    async with rdb_session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="memory-unit-isolation@example.test")
        )
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=corpus.key.workspace_id,
                user_id=user.id,
                name="Memory unit isolation",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        personal_key = ConsolidationUnitKey(
            workspace_id=corpus.key.workspace_id,
            agent_id=corpus.key.agent_id,
            scope=ConsolidationScope.USER,
            associated_user_id=user.id,
        )
    personal = await _start(rdb_session_manager, personal_key)
    files = SessionExecutionFileRepository(rdb_session_manager)
    await files.write(
        first.owner,
        "old-draft.md",
        "Old integrated result.",
        None,
        True,
        overwrite=False,
    )
    async with rdb_session_manager() as session:
        session.write_session.add(
            RDBEvent(
                session_id=first.binding.session_id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(
                    sender_user_id=None, content="Old private execution history."
                ).model_dump(mode="json"),
            )
        )
    accepted = await repository.submit(
        first, tool_call_id="first-original-call", authored_path="old-draft.md"
    )
    async with rdb_session_manager() as session:
        source = await session.read_session.get(
            RDBHistoricalMemorySource, corpus.source_id
        )
        assert source is not None
        source.summary = "New current prepared summary."
    second = await _start(rdb_session_manager, corpus.key)
    assert second.binding.session_id != first.binding.session_id
    current_files = await files.list_files(second.owner)
    assert {file.path for file in current_files} == {
        "README.md",
        f"inputs/{corpus.source_id}.md",
    }
    assert all("Old integrated result." not in file.content for file in current_files)
    fresh_input = await files.read(second.owner, f"inputs/{corpus.source_id}.md")
    assert fresh_input is not None
    assert fresh_input.content == "New current prepared summary."
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBEvent.id).where(
                    RDBEvent.session_id == second.binding.session_id
                )
            )
            is None
        )
    predecessors = await repository.list_predecessors(first.binding.unit_id)
    assert set(predecessors) == {
        first.binding.session_id,
        second.binding.session_id,
    }
    assert foreign.binding.session_id not in predecessors
    assert personal.binding.session_id not in predecessors
    await _archive(rdb_session_manager).archive(
        root_session_id=first.binding.session_id,
        expected_owner_generation=first.owner.owner_generation,
    )
    assert await repository.list_predecessors(first.binding.unit_id) == (
        second.binding.session_id,
    )
    async with rdb_session_manager() as session:
        foreign_common = await session.read_session.get(
            RDBAgentSession, foreign.binding.session_id
        )
        assert foreign_common is not None
        assert foreign_common.status is AgentSessionStatus.ACTIVE
        assert foreign_common.run_state is AgentSessionRunState.RUNNING
        personal_common = await session.read_session.get(
            RDBAgentSession, personal.binding.session_id
        )
        assert personal_common is not None
        assert personal_common.status is AgentSessionStatus.ACTIVE
        assert personal_common.run_state is AgentSessionRunState.RUNNING
    await files.write(
        second.owner, "new.md", "New accepted result.", None, True, overwrite=False
    )
    await repository.submit(second, tool_call_id="new-call", authored_path="new.md")
    result = await repository.current_result(corpus.key)
    assert result is not None and result.markdown == "New accepted result."
    assert (
        await repository.inspect_accepted(
            first.binding.session_id, tool_call_id=accepted.tool_call_id
        )
        == accepted
    )


async def test_terminal_takeover_fences_old_files_and_submission_without_reset(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Only settled predecessor state admits takeover; its owner cannot write."""
    corpus = await _corpus(rdb_session_manager, handle="memory-terminal-takeover")
    repository = _repository(rdb_session_manager)
    old = await _start(rdb_session_manager, corpus.key)
    files = SessionExecutionFileRepository(rdb_session_manager)
    await files.write(
        old.owner, "unfinished.md", "Unfinished draft.", None, True, overwrite=False
    )
    await repository.start_turn(old)
    started = await repository.start_turn(old)
    admission = TakeoverMemoryAdmission(
        predecessor_session_id=old.binding.session_id,
        expected_owner_generation=old.owner.owner_generation,
    )
    with pytest.raises(MemoryExecutionAuthorityError, match="active execution"):
        await repository.ensure_execution(corpus.key, admission=admission)
    with pytest.raises(ValueError, match="still active"):
        await _archive(rdb_session_manager).archive(
            root_session_id=old.binding.session_id,
            expected_owner_generation=old.owner.owner_generation,
        )
    async with rdb_session_manager() as session:
        await AgentRunRepository().update(
            session,
            old.run_id,
            AgentRunPatch(
                status=AgentRunStatus.CANCELLED,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
        )
        await SessionExecutionRecordRepository().mark_idle(
            session, old.binding.session_id
        )
    replacement = await repository.ensure_execution(corpus.key, admission=admission)
    assert replacement is not None
    assert replacement.session_id != old.binding.session_id
    assert replacement.deadline_at == started.deadline_at
    assert replacement.execution_policy == started.execution_policy
    assert replacement.started_turns == started.started_turns == 2
    with pytest.raises(PermissionError):
        await files.write(
            old.owner, "unfinished.md", "Stale overwrite.", None, False, overwrite=False
        )
    with pytest.raises(MemoryExecutionAuthorityError):
        await repository.submit(
            old, tool_call_id="stale-submit", authored_path="unfinished.md"
        )
    fresh = await _principal(rdb_session_manager, replacement)
    await repository.provision_inputs(fresh)
    assert await files.read(fresh.owner, "unfinished.md") is None
    await _archive(rdb_session_manager).archive(
        root_session_id=old.binding.session_id,
        expected_owner_generation=old.owner.owner_generation + 1,
    )
    assert await repository.list_predecessors(old.binding.unit_id) == (
        fresh.binding.session_id,
    )


async def test_worker_owned_recovery_atomically_settles_predecessor_before_archive(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A current common Worker owner can recover; old heartbeat alone cannot."""
    corpus = await _corpus(rdb_session_manager, handle="memory-worker-recovery")
    repository = _repository(rdb_session_manager)
    old = await _start(rdb_session_manager, corpus.key)
    files = SessionExecutionFileRepository(rdb_session_manager)
    await files.write(
        old.owner,
        "unfinished.md",
        "Private abandoned draft.",
        None,
        True,
        overwrite=False,
    )
    await repository.start_turn(old)
    started = await repository.start_turn(old)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == old.binding.session_id)
            .values(
                run_heartbeat_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(hours=1)
            )
        )
    fresh_notification = await repository.ensure_execution(
        corpus.key,
        admission=FreshMemoryAdmission(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=20),
            HistoricalMemoryExecutionConfig(max_turns=20, timeout_seconds=1200),
        ),
    )
    assert fresh_notification is not None
    assert fresh_notification.session_id == old.binding.session_id
    assert fresh_notification.deadline_at == old.binding.deadline_at
    async with rdb_session_manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, old.binding.session_id
        )
    worker_owner = SessionExecutionOwner(old.binding.session_id, generation)
    with pytest.raises(MemoryExecutionAuthorityError):
        await repository.recover_worker_execution(old.binding, old.owner)
    replacement = await repository.recover_worker_execution(old.binding, worker_owner)
    assert replacement is not None
    assert replacement.session_id != old.binding.session_id
    assert replacement.deadline_at == started.deadline_at
    assert replacement.execution_policy == started.execution_policy
    assert replacement.started_turns == started.started_turns == 2
    async with rdb_session_manager() as session:
        common = await SessionExecutionRecordRepository().get_by_id(
            session, old.binding.session_id
        )
        run = await session.read_session.get(RDBAgentRun, old.run_id)
        work = await session.read_session.get(RDBMemoryWork, corpus.work_id)
        unit = await session.read_session.get(RDBMemoryUnit, old.binding.unit_id)
        assert common is not None and common.run_state is AgentSessionRunState.IDLE
        assert common.owner_generation > worker_owner.owner_generation
        assert run is not None and run.status is AgentRunStatus.CANCELLED
        assert run.ended_at is not None
        assert work is not None and work.admitted_session_id is None
        assert unit is not None and unit.active_session_id == replacement.session_id
        archive_generation = common.owner_generation
    assert set(await repository.list_predecessors(old.binding.unit_id)) == {
        old.binding.session_id,
        replacement.session_id,
    }
    await _archive(rdb_session_manager).archive(
        root_session_id=old.binding.session_id,
        expected_owner_generation=archive_generation,
    )
    async with rdb_session_manager() as session:
        owner_generation = (
            await SessionExecutionRecordRepository().claim_owner_generation(
                session, replacement.session_id
            )
        )
    principal = await repository.open_run(
        replacement, SessionExecutionOwner(replacement.session_id, owner_generation)
    )
    await repository.provision_inputs(principal)
    assert await files.read(principal.owner, "unfinished.md") is None
    assert await repository.list_predecessors(old.binding.unit_id) == (
        replacement.session_id,
    )
