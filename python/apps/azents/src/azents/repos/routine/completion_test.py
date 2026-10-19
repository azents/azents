"""Real canonical completion keeps Routine items, host work and delivery separate."""

import dataclasses
import datetime
from dataclasses import dataclass

import pytest

from azents.core.enums import AgentRunStatus
from azents.core.routine import (
    RoutineDefinition,
    RoutineDeliveryStatus,
    RoutineObjectiveOutcome,
    RoutineScope,
    RoutineUnavailable,
    RoutineWorkResult,
)
from azents.core.routine_execution import (
    RoutineAdmittedContext,
    RoutineCheckState,
    RoutineExecutionState,
)
from azents.core.routine_judgment import RoutineJudgmentCandidate, RoutineSourceEvent
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.routine.authority import RoutineExecutionAuthorityRepository
from azents.repos.routine.completion import RoutineCompletionRepository
from azents.repos.routine.persistence_test import _content, _operations, _subject
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.state import RoutineStateRecord, RoutineStateRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.toolkit_state import ToolkitStateRepository

NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class Fixture:
    scope: RoutineScope
    authority: SessionResourceAuthority
    definitions: tuple[RoutineDefinition, ...]
    states: tuple[RoutineExecutionState, ...]
    repository: RoutineCompletionRepository


async def fixture(manager: SessionManager[WriteSession]) -> Fixture:
    async with manager() as session:
        scope = await _subject(session)
    definitions = tuple(
        [
            await _operations(manager).create(
                scope=scope,
                content=_content().model_copy(update={"title": f"Routine {index}"}),
                owner=None,
            )
            for index in range(2)
        ]
    )
    states = RoutineStateRepository(toolkit_states=ToolkitStateRepository())
    runs = AgentRunRepository()
    admitted: list[RoutineExecutionState] = []
    async with manager() as session:
        run = await runs.create(
            session,
            AgentRunCreate(
                session_id=scope.session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
        for index, definition in enumerate(definitions):
            state = RoutineExecutionState(
                context=RoutineAdmittedContext(
                    execution_id=f"occurrence-{index}",
                    judgment_id="joint-judgment",
                    scope=scope,
                    admitted_at=NOW,
                    candidate=RoutineJudgmentCandidate(
                        routine_id=definition.id,
                        slug=definition.slug,
                        content=definition.content,
                        events=(
                            RoutineSourceEvent(source_type="manual", observed_at=NOW),
                        ),
                        last_executed_at=None,
                        latest_work=None,
                    ),
                ),
                phase="started",
                current_run_id=run.id,
                started_at=NOW,
                completed_at=None,
                work=None,
                delivery_status=None,
                delivery_error=None,
            )
            await states.save_execution(
                session, scope=scope, state=state, expected_version=None
            )
            admitted.append(state)
        await states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=NOW,
                last_action_at=NOW,
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    authority = SessionResourceAuthority(
        workspace_id=scope.workspace_id,
        agent_id=scope.agent_id,
        session_id=scope.session_id,
        root_session_id=scope.session_id,
        run_id=run.id,
        run_index=run.run_index,
        owner_generation=0,
    )
    return Fixture(
        scope=scope,
        authority=authority,
        definitions=definitions,
        states=tuple(admitted),
        repository=RoutineCompletionRepository(
            session_manager=manager,
            read_session_manager=manager,
            states=states,
            records=RoutineWorkRecordRepository(),
            runs=runs,
            execution_authority=RoutineExecutionAuthorityRepository(states=states),
        ),
    )


def work(*, notify: bool, outcome: RoutineObjectiveOutcome) -> RoutineWorkResult:
    return RoutineWorkResult(
        objective_outcome=outcome,
        result="The official source was checked.",
        next_hint="Recheck at the next opportunity.",
        notify=notify,
        message="An important verified change was found." if notify else None,
    )


@pytest.mark.parametrize("notify", [False, True])
@pytest.mark.parametrize(
    "outcome", [RoutineObjectiveOutcome.FINISHED, RoutineObjectiveOutcome.FAILED]
)
async def test_completion_is_atomic_idempotent_and_only_closes_its_item(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    notify: bool,
    outcome: RoutineObjectiveOutcome,
) -> None:
    f = await fixture(rdb_session_manager)
    item = f.states[0]
    repo = f.repository
    await _operations(rdb_session_manager).update(
        scope=f.scope,
        slug=f.definitions[0].slug,
        expected=f.definitions[0].content,
        changes={"objective": "A changed objective for later executions only."},
        owner=f.authority.execution_owner,
    )
    original = await repo.context(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
    )
    assert original == item
    assert len(await repo.list_started(scope=f.scope, authority=f.authority)) == 2
    result = work(notify=notify, outcome=outcome)
    recording = await repo.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=result,
        now=NOW,
    )
    assert recording.created and recording.record is not None
    assert recording.state.phase == "completed" and not recording.state.incomplete
    assert recording.state.work == result
    assert recording.record.work == result
    assert recording.state.delivery_status is (
        RoutineDeliveryStatus.UNOBSERVED
        if notify
        else RoutineDeliveryStatus.NOT_REQUESTED
    )
    repeated = await repo.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=result,
        now=NOW,
    )
    assert not repeated.created
    assert repeated.record is not None and repeated.record.id == recording.record.id
    with pytest.raises(RoutineUnavailable, match="another result"):
        await repo.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=result.model_copy(update={"result": "Different result."}),
            now=NOW,
        )
    remaining = await repo.list_started(scope=f.scope, authority=f.authority)
    assert remaining == (f.states[1],)
    inspection = await _operations(rdb_session_manager).inspect(
        scope=f.scope, slug=f.definitions[0].slug, record_limit=1
    )
    assert inspection is not None
    assert (
        inspection.definition.content.objective
        != original.context.candidate.content.objective
    )
    assert (
        len(inspection.records) == 1 and inspection.records[0].id == recording.record.id
    )
    async with rdb_session_manager() as session:
        run = await repo.runs.get_by_id(session, f.authority.run_id)
        assert run is not None and run.status is AgentRunStatus.RUNNING
        check = await repo.states.get_check(session, scope=f.scope)
        assert check is not None and check.state.last_action_at == NOW
        saved = await repo.records.list_recent(
            session, scope=f.scope, routine_id=f.definitions[0].id, limit=100
        )
        assert len(saved) == 1


async def test_deleted_definition_context_can_finish_without_recreating_records(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    item = f.states[0]
    await _operations(rdb_session_manager).delete(
        scope=f.scope, slug=f.definitions[0].slug, owner=f.authority.execution_owner
    )
    replacement = await _operations(rdb_session_manager).create(
        scope=f.scope,
        content=f.definitions[0].content,
        owner=f.authority.execution_owner,
    )
    assert replacement.id != f.definitions[0].id
    assert (
        await f.repository.context(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
        )
        == item
    )
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    assert recording.created and recording.record is None
    assert recording.state.phase == "completed"
    assert recording.state.delivery_status is RoutineDeliveryStatus.UNOBSERVED
    assert replacement.slug == f.definitions[0].slug
    inspection = await _operations(rdb_session_manager).inspect(
        scope=f.scope, slug=replacement.slug, record_limit=100
    )
    assert inspection is not None
    assert inspection.definition == replacement
    assert inspection.records == ()
    async with rdb_session_manager() as session:
        assert (
            await f.repository.records.list_recent(
                session, scope=f.scope, routine_id=replacement.id, limit=100
            )
            == []
        )
        assert (
            await f.repository.records.list_recent(
                session, scope=f.scope, routine_id=f.definitions[0].id, limit=100
            )
            == []
        )


@pytest.mark.parametrize(
    "reason",
    [
        "stale_owner",
        "other_run",
        "wrong_index",
        "non_root",
        "stopped",
        "terminal",
        "different_occurrence",
    ],
)
async def test_completion_rejects_stale_or_stopped_execution_authority(
    rdb_session_manager: SessionManager[WriteSession], *, reason: str
) -> None:
    f = await fixture(rdb_session_manager)
    authority = f.authority
    execution_id = f.states[0].context.execution_id
    if reason == "stale_owner":
        authority = dataclasses.replace(authority, owner_generation=99)
    elif reason == "other_run":
        authority = dataclasses.replace(authority, run_id="another-run")
    elif reason == "wrong_index":
        authority = dataclasses.replace(authority, run_index=authority.run_index + 1)
    elif reason == "non_root":
        authority = dataclasses.replace(authority, root_session_id="another-root")
    elif reason == "different_occurrence":
        execution_id = "another-occurrence"
    else:
        async with rdb_session_manager() as session:
            if reason == "stopped":
                target = await session.write_session.get(
                    RDBAgentSession, f.scope.session_id
                )
                assert target is not None
                target.stop_requested_at = NOW
            else:
                run = await session.write_session.get(RDBAgentRun, authority.run_id)
                assert run is not None
                run.status = AgentRunStatus.COMPLETED
    error = (
        CanonicalExecutionOwnerGenerationStaleError
        if reason == "stale_owner"
        else RoutineUnavailable
    )
    with pytest.raises(error):
        await f.repository.complete(
            scope=f.scope,
            authority=authority,
            slug=f.definitions[0].slug,
            execution_id=execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    async with rdb_session_manager() as session:
        state = await f.repository.states.get_execution(
            session, scope=f.scope, routine_id=f.definitions[0].id
        )
        assert state is not None and state.state.phase == "started"
        assert (
            await f.repository.records.list_recent(
                session, scope=f.scope, routine_id=f.definitions[0].id, limit=100
            )
            == []
        )


class FailingCompletionState(RoutineStateRepository):
    async def save_execution(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        state: RoutineExecutionState,
        expected_version: int | None,
    ) -> RoutineStateRecord[RoutineExecutionState]:
        raise RuntimeError("Synthetic state save failure")


async def test_pre_start_admission_is_not_completion_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    current = f.states[0]
    admitted = RoutineExecutionState(
        context=current.context,
        phase="admitted",
        current_run_id=None,
        started_at=None,
        completed_at=None,
        work=None,
        delivery_status=None,
        delivery_error=None,
    )
    async with rdb_session_manager() as session:
        record = await f.repository.states.get_execution(
            session, scope=f.scope, routine_id=f.definitions[0].id
        )
        assert record is not None
        await f.repository.states.save_execution(
            session, scope=f.scope, state=admitted, expected_version=record.version
        )
    with pytest.raises(RoutineUnavailable):
        await f.repository.context(
            scope=f.scope,
            authority=f.authority,
            slug=f.definitions[0].slug,
            execution_id=current.context.execution_id,
        )
    with pytest.raises(RoutineUnavailable):
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=f.definitions[0].slug,
            execution_id=current.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 1
    )


async def test_record_and_incomplete_closure_roll_back_together(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    repo = dataclasses.replace(
        f.repository,
        states=FailingCompletionState(toolkit_states=ToolkitStateRepository()),
    )
    with pytest.raises(RuntimeError, match="Synthetic state save failure"):
        await repo.complete(
            scope=f.scope,
            authority=f.authority,
            slug=f.definitions[0].slug,
            execution_id=f.states[0].context.execution_id,
            work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
            now=NOW,
        )
    async with rdb_session_manager() as session:
        state = await f.repository.states.get_execution(
            session, scope=f.scope, routine_id=f.definitions[0].id
        )
        assert state is not None and state.state.phase == "started"
        assert (
            await f.repository.records.list_recent(
                session, scope=f.scope, routine_id=f.definitions[0].id, limit=100
            )
            == []
        )
