"""Real Routine archive, owner recovery, restore and purge participant boundaries."""

import dataclasses
import datetime
from dataclasses import asdict

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success

from azents.core.chat_data import RunningSessionArchiveBlocked
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import (
    MailboxItemCreate,
    MailboxPresentationItem,
    RoutineTriggerMailboxPayload,
)
from azents.core.routine import RoutineObjectiveOutcome, RoutineUnavailable
from azents.core.routine_presentation import (
    render_routine_execution_input,
    routine_execution_ref,
)
from azents.core.session_lifecycle import (
    SessionLifecyclePurgeContext,
    SessionLifecycleTransitionContext,
)
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.engine.events.types import RoutineInputPayload, UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_run_input_event import RDBAgentRunInputEvent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.routine import RDBRoutine
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.historical_memory_consolidation.execution_lifecycle_test import (
    _purger,
)
from azents.repos.idle_continuation import (
    IdleContinuationInput,
    IdleContinuationRepository,
)
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.lifecycle_target_test import lifecycle_pipeline
from azents.repos.mailbox import MailboxRepository
from azents.repos.routine.completion_test import NOW, Fixture, fixture, work
from azents.repos.routine.judgment_inbox_test import (
    repository as judgment_repository,
)
from azents.repos.routine.judgment_inbox_test import (
    subject,
)
from azents.repos.routine.lifecycle_participant import (
    RoutineLifecycleParticipantRepository,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    SessionExecutionRepository,
)
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.worker_session_recovery import WorkerSessionRecoveryQueryRepository
from azents.services.chat.team_session_test import _service
from azents.testing.routine import make_test_routine_lifecycle


async def _attach_routine_input(
    manager: SessionManager[WriteSession], f: Fixture
) -> None:
    """Use canonical Event append and Run association, not synthetic Run labels."""
    async with manager() as session:
        event = await EventTranscriptRepository().append(
            session,
            EventCreate(
                session_id=f.scope.session_id,
                kind=EventKind.ROUTINE_TRIGGER,
                payload=RoutineInputPayload(
                    executions=tuple(
                        routine_execution_ref(state) for state in f.states
                    ),
                    content=render_routine_execution_input(
                        f.states, continuation=False
                    ),
                ).model_dump(mode="json"),
                external_id="routine-lifecycle-trigger",
            ),
        )
        await f.repository.runs.associate_input_events(
            session, run_id=f.authority.run_id, event_ids=[event.id]
        )
        await SessionExecutionRecordRepository().mark_running(
            session, f.scope.session_id
        )
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(
                RDBAgent.id == f.scope.agent_id,
            )
            .values(auto_archive_ttl_days=1)
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == f.scope.session_id)
            .values(last_activity_at=sa.func.now() - datetime.timedelta(days=2))
        )
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(
                RDBConversation.session_id == f.scope.session_id,
            )
            .values(primary_kind=None)
        )


async def _archive(manager: SessionManager[WriteSession], f: Fixture) -> None:
    result = await _service(manager).operations.archive_agent_session(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=None,
    )
    assert isinstance(result, Success), result


async def test_archived_started_work_finishes_without_recreating_definition(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    lifecycle = make_test_routine_lifecycle()
    async with rdb_session_manager() as session:
        owner = await session.read_session.get(RDBAgentSession, f.scope.session_id)
        assert owner is not None and owner.status is AgentSessionStatus.ARCHIVED
        assert owner.run_state is AgentSessionRunState.RUNNING
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBRoutine)
                .where(RDBRoutine.session_id == f.scope.session_id)
            )
            == 0
        )
        assert await f.repository.states.get_check(session, scope=f.scope) is None
        verification = await lifecycle.verify_session_tree(
            session, session_ids=(f.scope.session_id,)
        )
        assert verification.started_count == 2
        assert verification.definition_count == verification.work_record_count == 0
        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            session,
            session_id=f.scope.session_id,
            owner_generation=f.authority.owner_generation,
        )
        assert snapshot.session_id == f.scope.session_id
    item = f.states[0]
    completed = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    assert completed.record is None and completed.state.phase == "completed"
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 1
    )
    with pytest.raises(RoutineUnavailable):
        async with rdb_session_manager() as session:
            authorizer = lifecycle_pipeline().routine_repository.authority
            await authorizer.require_execution_scope(
                session,
                scope=dataclasses.replace(f.scope, session_id="other"),
                run_id=f.authority.run_id,
            )


@pytest.mark.parametrize("ordinary_input", [False, True])
async def test_archive_requires_actual_routine_only_input_provenance(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    ordinary_input: bool,
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    if ordinary_input:
        async with rdb_session_manager() as session:
            event = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=f.scope.session_id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(
                        content="Unrelated ordinary work.",
                        sender_user_id=None,
                    ).model_dump(mode="json"),
                ),
            )
            await f.repository.runs.associate_input_events(
                session, run_id=f.authority.run_id, event_ids=[event.id]
            )
    else:
        # A started snapshot without input provenance cannot create the exception.
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentRunInputEvent).where(
                    RDBAgentRunInputEvent.agent_run_id == f.authority.run_id
                )
            )
    result = await _service(rdb_session_manager).operations.archive_agent_session(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=None,
    )
    assert isinstance(result, Failure) and isinstance(
        result.error, RunningSessionArchiveBlocked
    )
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 2
    )


async def test_archived_owner_recovery_reuses_ordinary_generation_and_fences_old_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == f.scope.session_id,
            )
            .values(run_heartbeat_at=sa.func.now() - datetime.timedelta(hours=1))
        )
    async with rdb_session_manager() as session:
        recovered = await WorkerSessionRecoveryQueryRepository().find_stuck_running(
            session,
            stale_threshold=datetime.timedelta(minutes=30),
            limit=100,
        )
        assert f.scope.session_id in {item.id for item in recovered}
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, f.scope.session_id
        )
        await SessionExecutionRecordRepository().mark_running(
            session, f.scope.session_id
        )
    assert generation == f.authority.owner_generation + 1
    item = f.states[0]
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FAILED),
            now=NOW,
        )
    current = dataclasses.replace(f.authority, owner_generation=generation)
    result = await f.repository.complete(
        scope=f.scope,
        authority=current,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=False, outcome=RoutineObjectiveOutcome.FAILED),
        now=NOW,
    )
    assert result.state.context == item.context


async def test_purge_waits_for_started_work_and_rechecks_namespace_absence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    participant = RoutineLifecycleParticipantRepository(make_test_routine_lifecycle())
    definition = get_session_lifecycle_registry().get("session.routine")
    context = SessionLifecyclePurgeContext(
        purge_job_id="routine-purge",
        lease_owner="fixture",
        root_session_id=f.scope.session_id,
        subtree_session_ids=(f.scope.session_id,),
    )
    with pytest.raises(RuntimeError, match="has not finished"):
        async with rdb_session_manager() as session:
            await participant.prepare_purge_participant(session, definition, context)
    for item in f.states:
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    async with rdb_session_manager() as session:
        assert (
            await participant.prepare_purge_participant(session, definition, context)
            is not None
        )
        await participant.cleanup_purge_participant(session, definition, context)
        result = await participant.verify_purge_participant(
            session, definition, context
        )
        assert result is not None and not any(asdict(result).values())
        assert (
            await participant.finalize_purge_participant(session, definition, context)
            == result
        )


async def test_restore_does_not_recreate_routine_definitions_or_source_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    async with rdb_session_manager() as session:
        await lifecycle_pipeline().restore(
            session,
            SessionLifecycleTransitionContext(
                transition_id="routine-restore",
                root_session_id=f.scope.session_id,
                subtree_session_ids=(f.scope.session_id,),
            ),
        )
        owner = await session.read_session.get(RDBAgentSession, f.scope.session_id)
        assert owner is not None and owner.status is AgentSessionStatus.ACTIVE
        assert await f.repository.states.get_check(session, scope=f.scope) is None
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBRoutine)
                .where(RDBRoutine.session_id == f.scope.session_id)
            )
            == 0
        )


async def test_archived_completed_work_consumes_idle_without_unrelated_continuation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """An empty obligation set settles idle; it does not keep a Run owner alive."""
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    for item in f.states:
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(status=AgentRunStatus.COMPLETED)
        )
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(RDBConversation.session_id == f.scope.session_id)
            .values(pending_idle_continuation_run_id=f.authority.run_id)
        )
        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            session,
            session_id=f.scope.session_id,
            owner_generation=f.authority.owner_generation,
        )
        assert snapshot.session_id == f.scope.session_id
    repository = IdleContinuationRepository(
        session_manager=rdb_session_manager,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=f.repository.runs,
        mailbox_repository=MailboxRepository(),
        scheduled_task_cycle_repository=ScheduledTaskCycleRepository(
            ToolkitStateRepository()
        ),
        routine_authority=f.repository.execution_authority,
    )
    finalization = await repository.finalize(
        session_id=f.scope.session_id,
        run_id=f.authority.run_id,
        owner_generation=f.authority.owner_generation,
        inputs=[
            IdleContinuationInput(
                session_id=f.scope.session_id,
                kind=MailboxItemKind.GOAL_CONTINUATION,
                content="Unrelated work must not acquire an archive exemption.",
                idempotency_key="unrelated-goal",
                metadata={},
                payload=None,
                scheduled_cycle_id=None,
            )
        ],
    )
    assert finalization.consumed and finalization.continuation_count == 0
    assert not finalization.admissions
    async with rdb_session_manager() as session:
        owner = await SessionExecutionRecordRepository().get_by_id(
            session, f.scope.session_id
        )
        assert owner is not None and owner.run_state is AgentSessionRunState.IDLE
        conversation = await session.read_session.get(
            RDBConversation, f.scope.session_id
        )
        assert (
            conversation is not None
            and conversation.pending_idle_continuation_run_id is None
        )
    with pytest.raises(ValueError, match="not active"):
        async with rdb_session_manager() as session:
            await SessionExecutionRecordRepository().claim_owner_generation(
                session, f.scope.session_id
            )


async def test_real_purge_waits_without_fencing_owner_then_deletes_the_root(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """The actual service dispatches Routine cleanup before final root deletion."""
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        await LifecycleTargetRepository().accelerate_account_purge(
            session,
            root_session_id=f.scope.session_id,
            session_ids=(f.scope.session_id,),
            archived_at=now,
            now=now,
            retention_repository=ArchivedSessionRetentionRepository(),
        )
    service = _purger(rdb_session_manager)
    claim = await service.operations.claim(now=now, lease_owner="routine-purge")
    assert claim.job is not None and claim.materialization_error is None
    waiting = await service.operations.prepare_root(
        job=claim.job, lease_owner="routine-purge", now=now
    )
    assert waiting.active and waiting.preserve_started_work
    async with rdb_session_manager() as session:
        owner = await SessionExecutionRecordRepository().get_by_id(
            session, f.scope.session_id
        )
        assert owner is not None
        assert owner.owner_generation == f.authority.owner_generation
        assert owner.stop_requested_at is None
    for item in f.states:
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(status=AgentRunStatus.COMPLETED)
        )
        await SessionExecutionRecordRepository().mark_idle(session, f.scope.session_id)
    summary = await service._purge_claimed(job=claim.job, lease_owner="routine-purge")
    assert summary.completed and not summary.retry_scheduled
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.get(RDBAgentSession, f.scope.session_id) is None
        )
        counts = await make_test_routine_lifecycle().verify_session_tree(
            session, session_ids=(f.scope.session_id,)
        )
        assert not any(asdict(counts).values())


async def test_purge_waits_between_runs_without_stopping_preserved_idle_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A physical Run boundary is not completion of the remaining obligation."""
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(status=AgentRunStatus.COMPLETED)
        )
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(RDBConversation.session_id == f.scope.session_id)
            .values(pending_idle_continuation_run_id=f.authority.run_id)
        )
        await LifecycleTargetRepository().accelerate_account_purge(
            session,
            root_session_id=f.scope.session_id,
            session_ids=(f.scope.session_id,),
            archived_at=now,
            now=now,
            retention_repository=ArchivedSessionRetentionRepository(),
        )
    service = _purger(rdb_session_manager)
    claim = await service.operations.claim(now=now, lease_owner="routine-idle-purge")
    assert claim.job is not None
    waiting = await service.operations.prepare_root(
        job=claim.job, lease_owner="routine-idle-purge", now=now
    )
    assert waiting.active and waiting.preserve_started_work
    remaining = await f.repository.list_for_idle(
        scope=f.scope, owner=f.authority.execution_owner, run_id=f.authority.run_id
    )
    assert len(remaining) == 2
    async with rdb_session_manager() as session:
        owner = await SessionExecutionRecordRepository().get_by_id(
            session, f.scope.session_id
        )
        assert owner is not None
        assert owner.owner_generation == f.authority.owner_generation
        assert owner.stop_requested_at is None


async def test_terminal_failed_host_cannot_hold_permanent_purge_open(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Explicit purge removes residual attempts without inventing a work result."""
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    await _archive(rdb_session_manager, f)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(status=AgentRunStatus.FAILED)
        )
        await SessionExecutionRecordRepository().mark_idle(session, f.scope.session_id)
        await LifecycleTargetRepository().accelerate_account_purge(
            session,
            root_session_id=f.scope.session_id,
            session_ids=(f.scope.session_id,),
            archived_at=now,
            now=now,
            retention_repository=ArchivedSessionRetentionRepository(),
        )
    service = _purger(rdb_session_manager)
    claim = await service.operations.claim(now=now, lease_owner="routine-terminal")
    assert claim.job is not None
    summary = await service._purge_claimed(
        job=claim.job, lease_owner="routine-terminal"
    )
    assert summary.completed
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.get(RDBAgentSession, f.scope.session_id) is None
        )
        counts = await make_test_routine_lifecycle().verify_session_tree(
            session, session_ids=(f.scope.session_id,)
        )
        assert not any(asdict(counts).values())


async def test_archive_removes_source_only_judgment_before_any_run_starts(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    admission = await judgment_repository(rdb_session_manager).admit_tick(
        scope=scope, now=NOW
    )
    assert admission is not None
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(auto_archive_ttl_days=1)
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == scope.session_id)
            .values(last_activity_at=sa.func.now() - datetime.timedelta(days=2))
        )
    result = await _service(rdb_session_manager).operations.archive_agent_session(
        agent_id=scope.agent_id, session_id=scope.session_id, user_id=None
    )
    assert isinstance(result, Success), result
    async with rdb_session_manager() as session:
        counts = await make_test_routine_lifecycle().verify_session_tree(
            session, session_ids=(scope.session_id,)
        )
        assert not any(asdict(counts).values())
        assert (
            await MailboxRepository().list_by_session_id(session, scope.session_id)
            == []
        )


async def test_archive_removes_admitted_trigger_and_retained_completed_records(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    first, second = f.states
    recorded = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=first.context.candidate.slug,
        execution_id=first.context.execution_id,
        work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    assert recorded.record is not None
    admitted = second.model_copy(
        update={
            "phase": "admitted",
            "current_run_id": None,
            "started_at": None,
        }
    )
    content = render_routine_execution_input((admitted,), continuation=False)
    async with rdb_session_manager() as session:
        current = await f.repository.states.get_occurrence(
            session,
            scope=f.scope,
            slug=second.context.candidate.slug,
            execution_id=second.context.execution_id,
        )
        assert current is not None
        await f.repository.states.save_execution(
            session,
            scope=f.scope,
            state=admitted,
            expected_version=current.version,
        )
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(status=AgentRunStatus.COMPLETED)
        )
        await MailboxRepository().create_idempotent(
            session,
            MailboxItemCreate(
                session_id=f.scope.session_id,
                kind=MailboxItemKind.ROUTINE_TRIGGER,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content=content,
                idempotency_key="routine-pre-start-archive",
                metadata={},
                action=None,
                attachments=[],
                file_parts=[],
                payload=RoutineTriggerMailboxPayload(
                    type="routine_trigger",
                    executions=(routine_execution_ref(admitted),),
                    items=[
                        MailboxPresentationItem(
                            item_key="routine_trigger:0",
                            presentation_kind="routine_trigger",
                            content=content,
                        )
                    ],
                ),
            ),
            idempotency_key="routine-pre-start-archive",
        )
    await _archive(rdb_session_manager, f)
    async with rdb_session_manager() as session:
        counts = await make_test_routine_lifecycle().verify_session_tree(
            session, session_ids=(f.scope.session_id,)
        )
        assert not any(asdict(counts).values())
