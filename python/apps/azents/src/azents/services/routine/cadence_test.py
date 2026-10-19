"""Judge-relative checks use the common Scheduler rather than another timer."""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon import di

from azents.broker.types import SessionBroker
from azents.core.routine import ROUTINE_TICK_INTERVAL
from azents.core.routine_execution import RoutineCheckState
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.job_runtime.types import JobOutcome
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.judgment_inbox_test import (
    outcome,
    promote,
    repository,
    subject,
)
from azents.repos.routine.source_dispatch import RoutineSourceRepository
from azents.scheduler.routine_source_dispatch import routine_source_dispatch_handler
from azents.scheduler.service import SchedulerService
from azents.scheduler.service_test import (
    CompletedOperations,
    RecordingRuntime,
    _definition,
    _state,
)
from azents.scheduler.types import TaskContext
from azents.services.routine.source_dispatch import RoutineSourceDispatcher

NOW = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)


@pytest.mark.parametrize("act,failed", [(True, False), (False, False), (False, True)])
async def test_judge_completion_retimes_the_next_shared_check(
    rdb_session_manager: SessionManager[WriteSession], *, act: bool, failed: bool
) -> None:
    repo = repository(rdb_session_manager)
    scope = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    admitted = await repo.admit_tick(scope=scope, now=NOW)
    assert admitted is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        rdb_session_manager,
        scope=scope,
        action=action,
        buffer_id=admitted.mailbox_item.id,
    )
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=0)
    captured = await repo.capture(
        scope=scope, action=action, execution=execution, owner=owner, now=NOW
    )
    finished = NOW + datetime.timedelta(seconds=7)
    await repo.settle(
        scope=scope,
        captured=captured,
        execution=execution,
        owner=owner,
        outcome=outcome(captured, act=act, failed=failed),
        provider="openai",
        model="synthetic",
        now=finished,
    )
    assert (
        await sources.list_due_scopes(now=NOW + ROUTINE_TICK_INTERVAL, limit=64) == []
    )
    assert (
        await sources.next_check_at(now=NOW + ROUTINE_TICK_INTERVAL)
        == finished + ROUTINE_TICK_INTERVAL
    )
    assert await sources.list_due_scopes(
        now=finished + ROUTINE_TICK_INTERVAL, limit=64
    ) == [scope]
    async with rdb_session_manager() as session:
        state = await repo.states.get_check(session, scope=scope)
        assert state is not None
        assert state.state.last_tick_at == finished
        assert state.state.last_action_at == (finished if act else None)
    # Ordinary selected work is still incomplete; completing it is not the clock.
    if act:
        async with rdb_session_manager() as session:
            work = await repo.states.list_executions(session, scope=scope)
            assert len(work) == 1 and work[0].state.incomplete
    else:
        second = await repo.admit_tick(
            scope=scope, now=finished + ROUTINE_TICK_INTERVAL
        )
        assert second is not None


async def test_earliest_session_and_legacy_action_boundary_use_the_same_due_time(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repo = repository(rdb_session_manager)
    early = await subject(rdb_session_manager)
    later = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    async with rdb_session_manager() as session:
        for scope, offset in [(early, 7), (later, 20)]:
            await repo.states.save_check(
                session,
                scope=scope,
                state=RoutineCheckState(
                    last_tick_at=NOW,
                    last_action_at=NOW + datetime.timedelta(seconds=offset),
                    source_inputs=(),
                    queued_judgment_id=None,
                ),
                expected_version=None,
            )
    at = NOW + ROUTINE_TICK_INTERVAL
    assert await sources.list_due_scopes(now=at, limit=64) == []
    assert await sources.next_check_at(now=at) == at + datetime.timedelta(seconds=7)
    assert await sources.list_due_scopes(
        now=at + datetime.timedelta(seconds=7), limit=64
    ) == [early]
    assert await sources.list_due_scopes(
        now=at + datetime.timedelta(seconds=20), limit=64
    ) == [early, later]


async def test_next_check_preserves_discovery_and_requests_remaining_due_work(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    broker = Mock(spec=SessionBroker)
    broker.send_message = AsyncMock()
    dispatcher = RoutineSourceDispatcher(
        sources=sources,
        inbox=repository(rdb_session_manager),
        broker=broker,
        clock=lambda: NOW,
        batch_size=1,
    )
    assert await dispatcher.next_check_at() == NOW + ROUTINE_TICK_INTERVAL
    scope = await subject(rdb_session_manager)
    assert await dispatcher.next_check_at() == NOW
    await dispatcher.dispatch_once(
        now=NOW, deadline=NOW + datetime.timedelta(minutes=2)
    )
    assert await dispatcher.next_check_at() == NOW + ROUTINE_TICK_INTERVAL
    # A queued judgment keeps one identity while later source checks remain bounded.
    async with rdb_session_manager() as session:
        state = await dispatcher.inbox.states.get_check(session, scope=scope)
        assert state is not None and state.state.queued_judgment_id is not None


async def test_consecutive_no_action_judgments_schedule_from_each_completion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repo = repository(rdb_session_manager)
    scope = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=0)
    due = NOW
    for latency in [7, 90, 3]:
        admitted = await repo.admit_tick(scope=scope, now=due)
        assert admitted is not None
        action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
        execution = await promote(
            rdb_session_manager,
            scope=scope,
            action=action,
            buffer_id=admitted.mailbox_item.id,
        )
        captured = await repo.capture(
            scope=scope, action=action, execution=execution, owner=owner, now=due
        )
        completed = due + datetime.timedelta(seconds=latency)
        await repo.settle(
            scope=scope,
            captured=captured,
            execution=execution,
            owner=owner,
            outcome=outcome(captured, act=False, failed=False),
            provider="openai",
            model="synthetic",
            now=completed,
        )
        due = completed + ROUTINE_TICK_INTERVAL
        assert await sources.next_check_at(now=completed) == due
        assert (
            await sources.list_due_scopes(
                now=due - datetime.timedelta(microseconds=1), limit=64
            )
            == []
        )
        assert await sources.list_due_scopes(now=due, limit=64) == [scope]


async def test_early_scan_schedules_only_the_remaining_delay_through_common_scheduler(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(rdb_session_manager)
    scope = await subject(rdb_session_manager)
    async with rdb_session_manager() as session:
        await repo.states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=NOW + datetime.timedelta(seconds=7),
                last_action_at=NOW + datetime.timedelta(seconds=7),
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    early = NOW + ROUTINE_TICK_INTERVAL
    broker = Mock(spec=SessionBroker)
    broker.send_message = AsyncMock()
    dispatcher = RoutineSourceDispatcher(
        sources=RoutineSourceRepository(session_manager=rdb_session_manager),
        inbox=repo,
        broker=broker,
        clock=lambda: early,
        batch_size=64,
    )
    container = Mock(spec=di.Container)
    container.solve = AsyncMock(return_value=dispatcher)
    context = TaskContext(
        task_key="routine_source_dispatch",
        attempt_started_at=early,
        lease_owner="scheduler",
        deadline=early + datetime.timedelta(minutes=2),
        manual_triggered=False,
        container=container,
    )
    result = await routine_source_dispatch_handler(context)
    broker.send_message.assert_not_awaited()
    trace: list[str] = []
    operations = CompletedOperations(trace, {})
    runtime = RecordingRuntime(
        trace,
        {
            "routine_source_dispatch": JobOutcome.succeeded(
                result.model_dump(mode="json")
            )
        },
        {},
    )
    scheduler = SchedulerService(operations, runtime, scheduler_id="scheduler")
    monkeypatch.setattr("azents.scheduler.service._utcnow", lambda: early)
    await scheduler._execute_claimed(
        _definition("routine_source_dispatch", enabled=True),
        _state(
            task_key="routine_source_dispatch",
            last_started_at=early,
            manual_requested_at=None,
        ),
    )
    assert operations.success_times == [early + datetime.timedelta(seconds=7)]
    # The remaining seven seconds, not another full interval, makes it eligible.
    assert await dispatcher.sources.list_due_scopes(
        now=operations.success_times[0], limit=64
    ) == [scope]
