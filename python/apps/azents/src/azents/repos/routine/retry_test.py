"""Explicit failed-run retry carries incomplete Routine state atomically."""

import dataclasses
import datetime
from dataclasses import dataclass

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentRunStatus, EventKind
from azents.core.routine import (
    RoutineObjectiveOutcome,
    RoutineScope,
    RoutineUnavailable,
)
from azents.core.routine_execution import RoutineExecutionState
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.routine.completion_test import NOW, Fixture, fixture, work
from azents.repos.routine.execution import RoutineExecutionRepository
from azents.repos.routine.lifecycle_test import _attach_routine_input
from azents.repos.routine.state import RoutineStateRecord, RoutineStateRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.chat_write_test import (
    _create_user,
    _failed_run_system_error_payload,
    _service,
)


@dataclass(frozen=True)
class RetryFixture:
    routine: Fixture
    user_id: str
    failed_event_id: str
    input_event_id: str


async def _seed(manager: SessionManager[WriteSession]) -> RetryFixture:
    f = await fixture(manager)
    await _attach_routine_input(manager, f)
    first = f.states[0]
    await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=first.context.candidate.slug,
        execution_id=first.context.execution_id,
        work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    async with manager() as session:
        user_id = await _create_user(
            session, f"routine-retry-{f.scope.session_id}@example.com"
        )
        input_event = await EventTranscriptRepository().get_by_external_id(
            session,
            f.scope.session_id,
            "routine-lifecycle-trigger",
        )
        assert input_event is not None
        error = await EventTranscriptRepository().append(
            session,
            EventCreate(
                session_id=f.scope.session_id,
                kind=EventKind.SYSTEM_ERROR,
                payload=_failed_run_system_error_payload(),
            ),
        )
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == f.authority.run_id)
            .values(requested_model_target_label="default")
        )
        await f.repository.runs.mark_terminal(
            session,
            f.authority.run_id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
            terminal_result_event_id=error.id,
            terminal_result_message="temporary failure",
        )
        await SessionExecutionRecordRepository().mark_idle(session, f.scope.session_id)
    return RetryFixture(f, user_id, error.id, input_event.id)


async def test_explicit_retry_rebinds_only_incomplete_occurrences_and_keeps_profile(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    seeded = await _seed(rdb_session_manager)
    f = seeded.routine
    service = _service(rdb_session_manager)
    result = await service.create_idempotent_failed_run_retry(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=seeded.user_id,
        client_request_id="routine-retry",
        failed_event_id=seeded.failed_event_id,
        payload={"failed_event_id": seeded.failed_event_id},
    )
    assert result.request.created
    async with rdb_session_manager() as session:
        runs = await f.repository.runs.list_by_input_event_id(
            session, event_id=seeded.input_event_id
        )
        assert len(runs) == 2
        original, retry = runs
        assert original.id == f.authority.run_id
        assert retry.id != original.id and retry.status is AgentRunStatus.PENDING
        assert (
            retry.requested_model_target_label
            == original.requested_model_target_label
            == "default"
        )
        assert retry.requested_reasoning_effort == original.requested_reasoning_effort
        assert (
            retry.requested_enabled_execution_options
            == original.requested_enabled_execution_options
        )
        first, second = [
            await f.repository.states.get_occurrence(
                session,
                scope=f.scope,
                slug=state.context.candidate.slug,
                execution_id=state.context.execution_id,
            )
            for state in f.states
        ]
        assert first is not None and first.state.phase == "completed"
        assert first.state.current_run_id == original.id
        assert second is not None and second.state.phase == "started"
        assert second.state.current_run_id == retry.id
        assert second.state.context == f.states[1].context
        assert second.state.started_at == f.states[1].started_at
        await f.repository.runs.activate_pending(
            session,
            run_id=retry.id,
            activated_at=datetime.datetime.now(datetime.UTC),
            requested_model_target_label="default",
            requested_reasoning_effort=None,
            requested_enabled_execution_options=[],
        )
    repeated = await service.create_idempotent_failed_run_retry(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=seeded.user_id,
        client_request_id="routine-retry",
        failed_event_id=seeded.failed_event_id,
        payload={"failed_event_id": seeded.failed_event_id},
    )
    assert not repeated.request.created
    authority = dataclasses.replace(
        f.authority, run_id=retry.id, run_index=retry.run_index
    )
    with pytest.raises(RoutineUnavailable):
        await f.repository.complete(
            scope=f.scope,
            authority=authority,
            slug=f.states[0].context.candidate.slug,
            execution_id=f.states[0].context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    completed = await f.repository.complete(
        scope=f.scope,
        authority=authority,
        slug=f.states[1].context.candidate.slug,
        execution_id=f.states[1].context.execution_id,
        work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    assert completed.state.context == f.states[1].context
    assert completed.created


class _FailingRebind(RoutineStateRepository):
    async def save_execution(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        state: RoutineExecutionState,
        expected_version: int | None,
    ) -> RoutineStateRecord[RoutineExecutionState]:
        raise RuntimeError("Injected Routine retry rollback")


async def test_retry_run_profile_input_record_and_routine_binding_rollback_together(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    seeded = await _seed(rdb_session_manager)
    f = seeded.routine
    service = _service(rdb_session_manager)
    service.operations = dataclasses.replace(
        service.operations,
        routine_execution_repository=RoutineExecutionRepository(
            states=_FailingRebind(toolkit_states=f.repository.states.toolkit_states),
        ),
    )
    with pytest.raises(RuntimeError, match="retry rollback"):
        await service.create_idempotent_failed_run_retry(
            agent_id=f.scope.agent_id,
            session_id=f.scope.session_id,
            user_id=seeded.user_id,
            client_request_id="rollback-retry",
            failed_event_id=seeded.failed_event_id,
            payload={"failed_event_id": seeded.failed_event_id},
        )
    async with rdb_session_manager() as session:
        runs = await f.repository.runs.list_by_input_event_id(
            session, event_id=seeded.input_event_id
        )
        assert len(runs) == 1 and runs[0].status is AgentRunStatus.FAILED
        failure = await session.read_session.get(RDBEvent, seeded.failed_event_id)
        assert failure is not None and not failure.reverted
        state = await f.repository.states.get_occurrence(
            session,
            scope=f.scope,
            slug=f.states[1].context.candidate.slug,
            execution_id=f.states[1].context.execution_id,
        )
        assert state is not None and state.state == f.states[1]
    accepted = await _service(rdb_session_manager).create_idempotent_failed_run_retry(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=seeded.user_id,
        client_request_id="rollback-retry",
        failed_event_id=seeded.failed_event_id,
        payload={"failed_event_id": seeded.failed_event_id},
    )
    assert accepted.request.created
