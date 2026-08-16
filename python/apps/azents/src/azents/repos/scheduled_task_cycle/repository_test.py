"""Scheduled Task cycle repository tests."""

import datetime
from typing import Literal, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ScheduledTaskScheduleType
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleSnapshot,
    ScheduledTaskCycleState,
)
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert


def _now() -> datetime.datetime:
    """Return one stable timezone-aware fixture instant."""
    return datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)


def _snapshot() -> ScheduledTaskCycleSnapshot:
    """Build one immutable admitted occurrence snapshot."""
    return ScheduledTaskCycleSnapshot(
        cycle_id="c" * 32,
        task_id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=None,
        title="Daily report",
        objective="Prepare the current report.",
        schedule_type=ScheduledTaskScheduleType.CRON,
        scheduled_at=None,
        cron_expression="0 9 * * *",
        timezone="America/New_York",
        scheduled_for=_now(),
    )


class _ToolkitStateRepository(ToolkitStateRepository):
    """In-memory Toolkit State collaborator recording whole-state saves."""

    def __init__(self) -> None:
        self.record: ToolkitStateRecord | None = None
        self.saves: list[ToolkitStateUpsert] = []

    async def get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        toolkit_namespace: str,
        state_name: str,
    ) -> ToolkitStateRecord | None:
        """Return the configured record when its identity matches."""
        del session
        record = self.record
        if record is None:
            return None
        if (
            record.agent_id,
            record.session_id,
            record.toolkit_namespace,
            record.state_name,
        ) != (agent_id, session_id, toolkit_namespace, state_name):
            return None
        return record

    async def save(
        self,
        session: AsyncSession,
        state: ToolkitStateUpsert,
    ) -> ToolkitStateRecord:
        """Record one create-or-CAS save and return its next version."""
        del session
        self.saves.append(state)
        version = 1 if state.expected_version is None else state.expected_version + 1
        now = _now()
        self.record = ToolkitStateRecord(
            id="k" * 32,
            agent_id=state.agent_id,
            session_id=state.session_id,
            toolkit_namespace=state.toolkit_namespace,
            state_name=state.state_name,
            state_json=state.state_json,
            schema_version=state.schema_version,
            version=version,
            created_at=now,
            updated_at=now,
        )
        return self.record


def _repository() -> tuple[ScheduledTaskCycleRepository, _ToolkitStateRepository]:
    """Create the cycle repository with its recording state collaborator."""
    state_repository = _ToolkitStateRepository()
    return (
        ScheduledTaskCycleRepository(toolkit_state_repository=state_repository),
        state_repository,
    )


def _cycle_state(
    *,
    cycle_id: str,
    phase: Literal["admitted", "started"],
    scheduled_for: datetime.datetime,
) -> ScheduledTaskCycleState:
    """Build one cycle state for direct SQL repository tests."""
    return ScheduledTaskCycleState(
        cycle_id=cycle_id,
        task_id="t" * 32,
        phase=phase,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=None,
        title="Daily report",
        objective="Prepare the current report.",
        schedule_type=ScheduledTaskScheduleType.CRON,
        scheduled_at=None,
        cron_expression="0 9 * * *",
        timezone="America/New_York",
        scheduled_for=scheduled_for,
        current_run_id="r" * 32 if phase == "started" else None,
        started_at=_now() if phase == "started" else None,
        progress_title=None,
    )


def _rdb_state(
    *,
    state: ScheduledTaskCycleState,
    state_name: str | None = None,
    toolkit_state_id: str = "k" * 32,
    version: int = 2,
) -> RDBToolkitState:
    """Build one ORM state row without database defaults."""
    row = RDBToolkitState(
        agent_id=state.agent_id,
        session_id=state.session_id,
        toolkit_namespace="scheduled",
        state_name=state_name or f"cycle:{state.cycle_id}",
        state_json=state.model_dump(mode="json"),
        schema_version=1,
        version=version,
    )
    row.id = toolkit_state_id
    row.created_at = _now()
    row.updated_at = _now()
    return row


class _Result:
    """SQLAlchemy result double for list and returning-delete operations."""

    def __init__(
        self,
        *,
        rows: list[RDBToolkitState] | None = None,
        scalar: str | None = None,
    ) -> None:
        self.rows = rows or []
        self.scalar = scalar

    def scalars(self) -> list[RDBToolkitState]:
        """Return configured ORM rows."""
        return self.rows

    def scalar_one_or_none(self) -> str | None:
        """Return configured deletion identity."""
        return self.scalar


class _QuerySession:
    """Capture one direct SQL statement."""

    def __init__(self, result: _Result) -> None:
        self.result = result
        self.query: object | None = None

    async def execute(self, query: object) -> _Result:
        """Capture and return the configured SQL result."""
        self.query = query
        return self.result


def _sql(statement: object) -> str:
    """Compile one captured SQL statement with literal fixture values."""
    return str(
        cast(sa.ClauseElement, statement).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


async def test_create_admitted_persists_complete_snapshot() -> None:
    """Create stores the immutable occurrence and admitted runtime defaults."""
    repository, state_repository = _repository()

    record = await repository.create_admitted(
        cast(AsyncSession, object()),
        _snapshot(),
    )

    assert record.state.phase == "admitted"
    assert record.state.cycle_id == "c" * 32
    assert record.state.task_id == "t" * 32
    assert record.state.title == "Daily report"
    assert record.state.scheduled_for == _now()
    assert record.state.current_run_id is None
    assert record.state.started_at is None
    assert record.state.ordered_tasks == []
    assert record.version == 1
    saved = state_repository.saves[0]
    assert saved.toolkit_namespace == "scheduled"
    assert saved.state_name == f"cycle:{'c' * 32}"
    assert saved.schema_version == 1
    assert saved.expected_version is None


async def test_start_uses_exact_version_and_records_first_run() -> None:
    """Start performs one CAS transition from admitted to started."""
    repository, state_repository = _repository()
    admitted = await repository.create_admitted(
        cast(AsyncSession, object()),
        _snapshot(),
    )
    started_at = _now() + datetime.timedelta(minutes=1)

    started = await repository.start(
        cast(AsyncSession, object()),
        record=admitted,
        run_id="r" * 32,
        started_at=started_at,
    )

    assert started.state.phase == "started"
    assert started.state.current_run_id == "r" * 32
    assert started.state.started_at == started_at
    assert started.state.scheduled_for == admitted.state.scheduled_for
    assert started.version == 2
    saved = state_repository.saves[-1]
    assert saved.expected_version == admitted.version


async def test_bind_run_preserves_started_snapshot() -> None:
    """Continuation binding changes only the current Run identity."""
    repository, _ = _repository()
    admitted = await repository.create_admitted(
        cast(AsyncSession, object()),
        _snapshot(),
    )
    started = await repository.start(
        cast(AsyncSession, object()),
        record=admitted,
        run_id="r" * 32,
        started_at=_now(),
    )

    rebound = await repository.bind_run(
        cast(AsyncSession, object()),
        record=started,
        run_id="n" * 32,
    )

    assert rebound.state.phase == "started"
    assert rebound.state.current_run_id == "n" * 32
    assert rebound.state.started_at == started.state.started_at
    assert rebound.state.objective == started.state.objective
    assert rebound.version == 3


async def test_invalid_phase_transitions_are_rejected() -> None:
    """Start and continuation binding reject the opposite lifecycle phase."""
    repository, _ = _repository()
    admitted = await repository.create_admitted(
        cast(AsyncSession, object()),
        _snapshot(),
    )
    with pytest.raises(ValueError, match="not started"):
        await repository.bind_run(
            cast(AsyncSession, object()),
            record=admitted,
            run_id="n" * 32,
        )

    started = await repository.start(
        cast(AsyncSession, object()),
        record=admitted,
        run_id="r" * 32,
        started_at=_now(),
    )
    with pytest.raises(ValueError, match="not admitted"):
        await repository.start(
            cast(AsyncSession, object()),
            record=started,
            run_id="n" * 32,
            started_at=_now(),
        )


async def test_get_started_filters_admitted_state() -> None:
    """Started lookup hides admitted or missing cycle state."""
    repository, _ = _repository()
    admitted = await repository.create_admitted(
        cast(AsyncSession, object()),
        _snapshot(),
    )

    assert (
        await repository.get_started(
            cast(AsyncSession, object()),
            agent_id=admitted.state.agent_id,
            session_id=admitted.state.session_id,
            cycle_id=admitted.state.cycle_id,
        )
        is None
    )

    await repository.start(
        cast(AsyncSession, object()),
        record=admitted,
        run_id="r" * 32,
        started_at=_now(),
    )
    started = await repository.get_started(
        cast(AsyncSession, object()),
        agent_id=admitted.state.agent_id,
        session_id=admitted.state.session_id,
        cycle_id=admitted.state.cycle_id,
    )

    assert started is not None
    assert started.state.current_run_id == "r" * 32


async def test_list_started_filters_and_orders_current_cycle_rows() -> None:
    """Compaction and idle reads omit admitted/non-cycle state deterministically."""
    started_later = _rdb_state(
        state=_cycle_state(
            cycle_id="b" * 32,
            phase="started",
            scheduled_for=_now() + datetime.timedelta(minutes=1),
        ),
        toolkit_state_id="1" * 32,
    )
    started_first_b = _rdb_state(
        state=_cycle_state(
            cycle_id="d" * 32,
            phase="started",
            scheduled_for=_now(),
        ),
        toolkit_state_id="2" * 32,
    )
    started_first_a = _rdb_state(
        state=_cycle_state(
            cycle_id="c" * 32,
            phase="started",
            scheduled_for=_now(),
        ),
        toolkit_state_id="3" * 32,
    )
    admitted = _rdb_state(
        state=_cycle_state(
            cycle_id="a" * 32,
            phase="admitted",
            scheduled_for=_now() - datetime.timedelta(minutes=1),
        ),
        toolkit_state_id="4" * 32,
    )
    unrelated = _rdb_state(
        state=_cycle_state(
            cycle_id="e" * 32,
            phase="started",
            scheduled_for=_now() - datetime.timedelta(minutes=2),
        ),
        state_name="projection",
        toolkit_state_id="5" * 32,
    )
    session = _QuerySession(
        _Result(
            rows=[
                started_later,
                started_first_b,
                admitted,
                unrelated,
                started_first_a,
            ]
        )
    )
    repository = ScheduledTaskCycleRepository(
        toolkit_state_repository=ToolkitStateRepository()
    )

    records = await repository.list_started(
        cast(AsyncSession, session),
        agent_id="a" * 32,
        session_id="s" * 32,
    )

    assert [record.state.cycle_id for record in records] == [
        "c" * 32,
        "d" * 32,
        "b" * 32,
    ]
    statement = _sql(session.query)
    assert "toolkit_states.agent_id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'" in statement
    assert "toolkit_states.session_id = 'ssssssssssssssssssssssssssssssss'" in statement
    assert "toolkit_states.toolkit_namespace = 'scheduled'" in statement


async def test_delete_started_uses_exact_row_version_fence() -> None:
    """Terminal deletion cannot remove a concurrently changed cycle row."""
    record = ScheduledTaskCycleRecord(
        state=_cycle_state(
            cycle_id="c" * 32,
            phase="started",
            scheduled_for=_now(),
        ),
        version=7,
        toolkit_state_id="k" * 32,
    )
    session = _QuerySession(_Result(scalar=record.toolkit_state_id))
    repository = ScheduledTaskCycleRepository(
        toolkit_state_repository=ToolkitStateRepository()
    )

    assert await repository.delete_started(
        cast(AsyncSession, session),
        record=record,
    )

    statement = _sql(session.query)
    assert "toolkit_states.id = 'kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk'" in statement
    assert "toolkit_states.version = 7" in statement


async def test_delete_started_rejects_admitted_cycle() -> None:
    """Terminalization never deletes work that has not crossed the start boundary."""
    record = ScheduledTaskCycleRecord(
        state=_cycle_state(
            cycle_id="c" * 32,
            phase="admitted",
            scheduled_for=_now(),
        ),
        version=1,
        toolkit_state_id="k" * 32,
    )
    repository = ScheduledTaskCycleRepository(
        toolkit_state_repository=ToolkitStateRepository()
    )

    with pytest.raises(ValueError, match="not started"):
        await repository.delete_started(
            cast(AsyncSession, object()),
            record=record,
        )
