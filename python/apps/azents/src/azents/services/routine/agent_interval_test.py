"""Agent-owned checking cadence agrees at discovery and fenced admission."""

import datetime

import pytest
import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError

from azents.api.public.agent.v1.data import AgentCreateRequest, AgentUpdateRequest
from azents.core.routine_execution import RoutineCheckState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.judgment_inbox_test import repository, subject
from azents.repos.routine.source_dispatch import RoutineSourceRepository

NOW = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)
PATCH = TypeAdapter(AgentUpdateRequest)


@pytest.mark.parametrize("value", [None, 0, -1, 1441, 1.5, 1.0, True, "5"])
def test_invalid_interval_is_rejected_without_coercion(value: object) -> None:
    with pytest.raises(ValidationError):
        PATCH.validate_python({"routine_check_interval_minutes": value})


@pytest.mark.parametrize("value", [1, 30, 1440])
def test_interval_contract_and_omission(value: int) -> None:
    assert PATCH.validate_python({"routine_check_interval_minutes": value}) == {
        "routine_check_interval_minutes": value
    }
    assert PATCH.validate_python({}) == {}
    assert (
        AgentCreateRequest.model_fields["routine_check_interval_minutes"].default == 30
    )


@pytest.mark.parametrize("minutes", [1, 5, 60, 1440])
async def test_configured_interval_has_exact_boundary_in_both_paths(
    rdb_session_manager: SessionManager[WriteSession], minutes: int
) -> None:
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(routine_check_interval_minutes=minutes)
        )
        await repo.states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=NOW,
                last_action_at=None,
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    due = NOW + datetime.timedelta(minutes=minutes)
    early = due - datetime.timedelta(microseconds=1)
    assert await sources.next_check_at(now=NOW) == due
    assert await sources.list_due_scopes(now=early, limit=64) == []
    assert await repo.admit_tick(scope=scope, now=early) is None
    assert await sources.list_due_scopes(now=due, limit=64) == [scope]
    assert await repo.admit_tick(scope=scope, now=due) is not None


async def test_agents_are_independent_and_admission_rechecks_changed_setting(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repo = repository(rdb_session_manager)
    fast = await subject(rdb_session_manager)
    slow = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    async with rdb_session_manager() as session:
        for scope, minutes in [(fast, 5), (slow, 60)]:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == scope.agent_id)
                .values(routine_check_interval_minutes=minutes)
            )
            await repo.states.save_check(
                session,
                scope=scope,
                state=RoutineCheckState(
                    last_tick_at=NOW,
                    last_action_at=None,
                    source_inputs=(),
                    queued_judgment_id=None,
                ),
                expected_version=None,
            )
    at = NOW + datetime.timedelta(minutes=5)
    assert await sources.list_due_scopes(now=at, limit=64) == [fast]
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fast.agent_id)
            .values(routine_check_interval_minutes=120)
        )
    assert await repo.admit_tick(scope=fast, now=at) is None
    assert await sources.next_check_at(now=at) == NOW + datetime.timedelta(minutes=60)
    assert await sources.list_due_scopes(
        now=NOW + datetime.timedelta(minutes=60), limit=64
    ) == [slow]


async def test_shorter_check_interval_preserves_minimum_action_delay(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repo = repository(rdb_session_manager)
    scope = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(routine_check_interval_minutes=1)
        )
        await repo.states.save_check(
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
    assert await sources.next_check_at(now=NOW) == NOW + datetime.timedelta(minutes=30)
    # Direct source collection may coalesce evidence but must not start judgment.
    assert (
        await repo.admit_tick(scope=scope, now=NOW + datetime.timedelta(minutes=1))
        is None
    )
    assert (
        await repo.admit_tick(scope=scope, now=NOW + datetime.timedelta(minutes=30))
        is not None
    )
