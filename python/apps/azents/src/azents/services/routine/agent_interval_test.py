"""Agent-owned checking cadence agrees at discovery and fenced admission."""

import datetime

import pytest
import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError

from azents.api.public.agent.v1.data import AgentCreateRequest, AgentUpdateRequest
from azents.core.routine_execution import RoutineCheckState
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.judgment_inbox_test import (
    outcome,
    promote,
    repository,
    subject,
)
from azents.repos.routine.source_dispatch import RoutineSourceRepository

NOW = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)
PATCH = TypeAdapter(AgentUpdateRequest)


@pytest.mark.parametrize("value", [None, 0, -1, 1, 29, 1441, 30.5, 30.0, True, "30"])
@pytest.mark.parametrize(
    "field",
    [
        "routine_check_interval_minutes",
        "routine_min_action_delay_minutes",
    ],
)
def test_invalid_interval_is_rejected_without_coercion(
    value: object, field: str
) -> None:
    with pytest.raises(ValidationError):
        PATCH.validate_python({field: value})


def test_creation_defaults_and_cross_field_constraint() -> None:
    defaults = AgentCreateRequest(name="Cadence")
    assert defaults.routine_check_interval_minutes == 180
    assert defaults.routine_min_action_delay_minutes == 30
    with pytest.raises(ValidationError):
        AgentCreateRequest(
            name="Cadence",
            routine_check_interval_minutes=60,
            routine_min_action_delay_minutes=90,
        )


@pytest.mark.parametrize("value", [30, 180, 1440])
def test_interval_contract_and_omission(value: int) -> None:
    assert PATCH.validate_python({"routine_check_interval_minutes": value}) == {
        "routine_check_interval_minutes": value
    }
    assert PATCH.validate_python({}) == {}
    assert (
        AgentCreateRequest.model_fields["routine_check_interval_minutes"].default == 180
    )


@pytest.mark.parametrize("minutes", [30, 60, 180, 1440])
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
        for scope, minutes in [(fast, 30), (slow, 60)]:
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
    at = NOW + datetime.timedelta(minutes=30)
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


@pytest.mark.parametrize("elapsed,admitted", [(59, False), (60, True)])
async def test_configured_minimum_delay_has_its_own_reference(
    rdb_session_manager: SessionManager[WriteSession],
    elapsed: int,
    admitted: bool,
) -> None:
    repo = repository(rdb_session_manager)
    scope = await subject(rdb_session_manager)
    sources = RoutineSourceRepository(session_manager=rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(
                routine_check_interval_minutes=180,
                routine_min_action_delay_minutes=60,
            )
        )
        await repo.states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=NOW - datetime.timedelta(hours=4),
                last_action_at=NOW,
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    assert await sources.next_check_at(now=NOW) == NOW + datetime.timedelta(minutes=60)
    # Discovery and direct admission both respect the independent action clock.
    assert (
        await repo.admit_tick(
            scope=scope, now=NOW + datetime.timedelta(minutes=elapsed)
        )
        is not None
    ) is admitted


@pytest.mark.parametrize("phase", ["capture", "settle"])
async def test_minimum_increase_is_rechecked_at_existing_final_gates(
    rdb_session_manager: SessionManager[WriteSession],
    phase: str,
) -> None:
    """An already queued judgment retains identity but uses the current minimum."""
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(
                routine_check_interval_minutes=180,
                routine_min_action_delay_minutes=30,
            )
        )
        await repo.states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=None,
                last_action_at=NOW - datetime.timedelta(minutes=40),
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    admitted = await repo.admit_tick(scope=scope, now=NOW)
    assert admitted is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        rdb_session_manager,
        scope=scope,
        action=action,
        buffer_id=admitted.mailbox_item.id,
    )
    owner = SessionExecutionOwner(scope.session_id, 0)

    async def increase_minimum() -> None:
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == scope.agent_id)
                .values(
                    routine_min_action_delay_minutes=60,
                )
            )

    if phase == "capture":
        await increase_minimum()
    captured = await repo.capture(
        scope=scope,
        action=action,
        execution=execution,
        owner=owner,
        now=NOW,
    )
    if phase == "capture":
        assert captured.candidates == ()
        return
    assert captured.candidates
    await increase_minimum()
    settled = await repo.settle(
        scope=scope,
        captured=captured,
        execution=execution,
        owner=owner,
        outcome=outcome(captured, act=True, failed=False),
        provider="openai",
        model="fixture",
        now=NOW,
    )
    assert settled.admission is None
