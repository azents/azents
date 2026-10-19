"""Routine cancellation composes with the real owner-fenced User Stop stage."""

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentRunStatus
from azents.core.routine import RoutineObjectiveOutcome
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.completion_test import NOW, fixture, work
from azents.repos.routine.persistence_test import _operations
from azents.repos.user_stop_data import UserStopOwnerInput
from azents.repos.user_stop_test import stop_fixture


@pytest.mark.parametrize("first_completed", [False, True])
async def test_explicit_stop_closes_attempts_and_preserves_definitions_and_results(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    first_completed: bool,
) -> None:
    f = await fixture(rdb_session_manager)
    dependencies = await stop_fixture(rdb_session_manager, "routine-stop", child=False)
    if first_completed:
        item = f.states[0]
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
            work=work(notify=False, outcome=RoutineObjectiveOutcome.FAILED),
            now=NOW,
        )
    # Include a pre-start obligation as well as the already started occurrence.
    async with rdb_session_manager() as session:
        second = f.states[1]
        record = await f.repository.states.get_occurrence(
            session,
            scope=f.scope,
            slug=second.context.candidate.slug,
            execution_id=second.context.execution_id,
        )
        assert record is not None
        await f.repository.states.save_execution(
            session,
            scope=f.scope,
            state=second.model_copy(
                update={"phase": "admitted", "current_run_id": None, "started_at": None}
            ),
            expected_version=record.version,
        )
        await dependencies.sessions.request_stop(
            session,
            session_id=f.scope.session_id,
            stop_request_id="routine-stop-request",
            stop_requester_user_id=None,
        )
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(
                RDBAgentRun.id == f.authority.run_id,
            )
            .values(status=AgentRunStatus.STOPPED)
        )
    await dependencies.stop.clear_stop_request(
        UserStopOwnerInput(
            session_id=f.scope.session_id,
            owner_generation=f.authority.owner_generation,
        )
    )
    assert len(await _operations(rdb_session_manager).list_routines(scope=f.scope)) == 2
    async with rdb_session_manager() as session:
        states = await f.repository.states.list_executions(session, scope=f.scope)
        assert {item.state.phase for item in states} == (
            {"completed", "cancelled"} if first_completed else {"cancelled"}
        )
        assert not any(item.state.incomplete for item in states)
        check = await f.repository.states.get_check(session, scope=f.scope)
        assert check is not None and check.state.last_action_at == NOW
        owner = await dependencies.sessions.get_by_id(session, f.scope.session_id)
        assert owner is not None and owner.stop_requested_at is None
