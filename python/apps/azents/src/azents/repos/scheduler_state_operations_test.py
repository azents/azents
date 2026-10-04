"""Genuine PostgreSQL Scheduler completed-state atomicity and contention proofs."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import ScheduledTaskStatus
from azents.rdb.models.scheduled_task_state import RDBScheduledTaskState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository
from azents.repos.scheduled_task_state.data import ScheduledTaskState
from azents.repos.scheduler_state_operations import SchedulerStateOperationRepository

_START = datetime(2026, 10, 2, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return _START + timedelta(minutes=minutes)


class SchedulerManager:
    """Observe genuine Session completion, not a fake application SQL adapter."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.sessions: list[WriteSession] = []
        self.active: list[WriteSession] = []
        self.commits = 0
        self.failures = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        assert not self.active, "Completed Scheduler operations cannot nest"
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                self.active.append(session)
                try:
                    yield session
                finally:
                    self.active.remove(session)
        except BaseException:
            self.failures += 1
            raise
        else:
            self.commits += 1

    def assert_closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


class SchedulerFault:
    """A test-only post-primitive fault or barrier follows actual SQL/flush."""

    def __init__(self, manager: SchedulerManager) -> None:
        self.manager = manager
        self.stage: str | None = None
        self.key: str | None = None
        self.error: BaseException | None = None
        self.pause = False
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.trace: list[tuple[str, str | None, ReadSession]] = []

    async def point(self, stage: str, key: str | None, session: ReadSession) -> None:
        assert self.manager.active == [session]
        assert session.read_session.in_transaction()
        self.trace.append((stage, key, session))
        if stage == self.stage and (self.key is None or self.key == key):
            self.reached.set()
            if self.pause:
                await self.release.wait()
            if self.error is not None:
                raise self.error


class FaultStates(ScheduledTaskStateRepository):
    """Narrow real SQL primitives with typed post-write/read observation."""

    def __init__(self, fault: SchedulerFault) -> None:
        self.fault = fault

    async def ensure_state(
        self, session: WriteSession, *, task_key: str, next_run_at: datetime
    ) -> ScheduledTaskState:
        result = await super().ensure_state(
            session, task_key=task_key, next_run_at=next_run_at
        )
        await self.fault.point("ensure_state", task_key, session)
        return result

    async def list_states(self, session: ReadSession) -> list[ScheduledTaskState]:
        result = await super().list_states(session)
        await self.fault.point("list_states", None, session)
        return result

    async def get(
        self, session: ReadSession, task_key: str
    ) -> ScheduledTaskState | None:
        result = await super().get(session, task_key)
        await self.fault.point("get", task_key, session)
        return result

    async def trigger(
        self, session: WriteSession, *, task_key: str, now: datetime
    ) -> ScheduledTaskState | None:
        result = await super().trigger(session, task_key=task_key, now=now)
        await self.fault.point("trigger", task_key, session)
        return result

    async def claim_due(
        self,
        session: WriteSession,
        *,
        task_key: str,
        now: datetime,
        lease_owner: str,
        lease_until: datetime,
    ) -> ScheduledTaskState | None:
        result = await super().claim_due(
            session,
            task_key=task_key,
            now=now,
            lease_owner=lease_owner,
            lease_until=lease_until,
        )
        await self.fault.point("claim_due", task_key, session)
        return result

    async def mark_success(
        self,
        session: WriteSession,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime,
        next_run_at: datetime,
        result_summary: dict[str, Any] | None,
    ) -> ScheduledTaskState | None:
        result = await super().mark_success(
            session,
            task_key=task_key,
            lease_owner=lease_owner,
            finished_at=finished_at,
            next_run_at=next_run_at,
            result_summary=result_summary,
        )
        await self.fault.point("mark_success", task_key, session)
        return result

    async def mark_failure(
        self,
        session: WriteSession,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime,
        next_run_at: datetime,
        error_code: str,
        error_message: str,
    ) -> ScheduledTaskState | None:
        result = await super().mark_failure(
            session,
            task_key=task_key,
            lease_owner=lease_owner,
            finished_at=finished_at,
            next_run_at=next_run_at,
            error_code=error_code,
            error_message=error_message,
        )
        await self.fault.point("mark_failure", task_key, session)
        return result


@dataclasses.dataclass(frozen=True)
class SchedulerFixture:
    manager: SchedulerManager
    fault: SchedulerFault
    repository: SchedulerStateOperationRepository


def scheduler_fixture(manager: SessionManager[WriteSession]) -> SchedulerFixture:
    observed = SchedulerManager(manager)
    fault = SchedulerFault(observed)
    return SchedulerFixture(
        observed, fault, SchedulerStateOperationRepository(observed, FaultStates(fault))
    )


async def row(fixture: SchedulerFixture, key: str) -> ScheduledTaskState | None:
    """Inspect committed facts outside the observed operation boundary."""
    async with fixture.manager.manager() as session:
        return await ScheduledTaskStateRepository().get(session, key)


async def claim(
    fixture: SchedulerFixture,
    *,
    key: str,
    now: datetime,
    owner: str,
    until: datetime | None,
) -> ScheduledTaskState | None:
    return await fixture.repository.claim_due(
        task_key=key,
        now=now,
        lease_owner=owner,
        lease_until=now + timedelta(minutes=10) if until is None else until,
    )


async def settle(
    fixture: SchedulerFixture,
    *,
    success: bool,
    key: str,
    owner: str,
    finished: datetime,
    next_run: datetime | None,
) -> ScheduledTaskState | None:
    next_run = finished + timedelta(minutes=30) if next_run is None else next_run
    if success:
        return await fixture.repository.mark_success(
            task_key=key,
            lease_owner=owner,
            finished_at=finished,
            next_run_at=next_run,
            result_summary={"nested": [1, None, {"ok": True}]},
        )
    return await fixture.repository.mark_failure(
        task_key=key,
        lease_owner=owner,
        finished_at=finished,
        next_run_at=next_run,
        error_code="task-error",
        error_message="existing opaque error\nsecond line",
    )


async def test_bulk_ensure_is_ordered_one_scope_idempotent_and_detached(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    keys = ("z-disabled", "a-enabled", "m-unregistered", "a-enabled")
    await fixture.repository.ensure_registered_states(task_keys=keys, now=_START)
    calls = [
        (stage, key) for stage, key, _ in fixture.fault.trace if stage == "ensure_state"
    ]
    assert calls == [("ensure_state", key) for key in keys]
    assert len({id(session) for _, _, session in fixture.fault.trace}) == 1
    states = await fixture.repository.list_states()
    assert [state.task_key for state in states] == [
        "a-enabled",
        "m-unregistered",
        "z-disabled",
    ]
    assert all(state.next_run_at == _START for state in states)
    assert all(state.latest_status is ScheduledTaskStatus.IDLE for state in states)
    assert all(state.lease_owner is None for state in states)
    await fixture.repository.trigger(task_key="a-enabled", now=at(1))
    changed = await fixture.repository.get_state("a-enabled")
    assert changed is not None
    assert changed.next_run_at == changed.manual_requested_at == at(1)
    assert changed.latest_status is ScheduledTaskStatus.IDLE
    await fixture.repository.ensure_registered_states(task_keys=keys, now=at(40))
    assert await fixture.repository.get_state("a-enabled") == changed
    assert await fixture.repository.get_state("unknown") is None
    assert await fixture.repository.trigger(task_key="unknown", now=at(50)) is None
    assert states[0].next_run_at == _START, "Returned snapshots remain detached"
    assert len(fixture.manager.sessions) == 8
    fixture.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_bulk_ensure_later_write_error_or_actual_task_cancel_rolls_back_batch(
    rdb_session_manager: SessionManager[WriteSession],
    cancel: bool,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(
        task_keys=("existing",), now=at(0)
    )
    await fixture.repository.trigger(task_key="existing", now=at(1))
    before = await row(fixture, "existing")
    fixture.fault.stage = "ensure_state"
    fixture.fault.key = "second"
    if cancel:
        fixture.fault.pause = True
        task = asyncio.create_task(
            fixture.repository.ensure_registered_states(
                task_keys=("first", "existing", "second"), now=at(9)
            )
        )
        try:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=5)
            task.cancel("after actual registration writes")
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            fixture.fault.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    else:
        fixture.fault.error = RuntimeError("after real registration writes")
        with pytest.raises(RuntimeError, match="after real registration writes"):
            await fixture.repository.ensure_registered_states(
                task_keys=("first", "existing", "second"), now=at(9)
            )
    assert await row(fixture, "first") is None
    assert await row(fixture, "second") is None
    assert await row(fixture, "existing") == before
    assert fixture.manager.failures == 1
    fixture.manager.assert_closed()


@pytest.mark.parametrize("operation", ["list_states", "get", "trigger"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_separate_completed_ensure_survives_later_read_trigger_failure(
    rdb_session_manager: SessionManager[WriteSession],
    operation: str,
    cancel: bool,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    before = await row(fixture, "task")
    fixture.fault.stage = operation
    fixture.fault.error = (
        asyncio.CancelledError("later operation")
        if cancel
        else RuntimeError("later operation")
    )
    with pytest.raises(type(fixture.fault.error), match="later operation"):
        if operation == "list_states":
            await fixture.repository.list_states()
        elif operation == "get":
            await fixture.repository.get_state("task")
        else:
            await fixture.repository.trigger(task_key="task", now=at(5))
    assert await row(fixture, "task") == before
    assert fixture.manager.commits == 1 and fixture.manager.failures == 1
    fixture.manager.assert_closed()


@pytest.mark.parametrize("due_delta", [-1, 0, 1])
async def test_claim_due_comparison_is_inclusive_application_time(
    rdb_session_manager: SessionManager[WriteSession],
    due_delta: int,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    due = _START + timedelta(microseconds=due_delta)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=due)
    result = await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
    if due_delta > 0:
        assert result is None
        assert (await row(fixture, "task")) is not None
    else:
        assert result is not None
        assert result.last_started_at == result.leased_at == _START
        assert result.lease_until == at(10)
        assert result.latest_status is ScheduledTaskStatus.RUNNING
    fixture.manager.assert_closed()


@pytest.mark.parametrize("lease_delta", [-1, 0, 1])
async def test_reclaim_lease_comparison_is_strict_not_equal(
    rdb_session_manager: SessionManager[WriteSession],
    lease_delta: int,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    first = await claim(fixture, key="task", now=_START, owner="owner-a", until=at(10))
    assert first is not None
    now = at(10) + timedelta(microseconds=lease_delta)
    second = await claim(fixture, key="task", now=now, owner="owner-b", until=None)
    if lease_delta <= 0:
        assert second is None
        assert await row(fixture, "task") == first
    else:
        assert second is not None
        assert second.lease_owner == "owner-b" and second.last_started_at == now
    fixture.manager.assert_closed()


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize(
    "lease_state", ["current", "expired", "not_running", "same_owner_reclaim"]
)
async def test_settlement_has_only_existing_task_key_and_owner_fences(
    rdb_session_manager: SessionManager[WriteSession],
    success: bool,
    lease_state: str,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    old = await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
    assert old is not None
    if lease_state == "not_running":
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBScheduledTaskState)
                .where(RDBScheduledTaskState.task_key == "task")
                .values(latest_status=ScheduledTaskStatus.IDLE)
            )
    elif lease_state == "same_owner_reclaim":
        newer = await claim(
            fixture, key="task", now=at(11), owner="owner-a", until=None
        )
        assert newer is not None and newer.last_started_at == at(11)
    finished = at(20) if lease_state == "expired" else at(2)
    result = await settle(
        fixture,
        success=success,
        key="task",
        owner="owner-a",
        finished=finished,
        next_run=None,
    )
    assert result is not None
    assert result.last_finished_at == finished
    assert result.next_run_at == finished + timedelta(minutes=30)
    assert result.lease_owner is result.leased_at is result.lease_until is None
    if lease_state == "same_owner_reclaim":
        assert result.last_started_at == at(11), (
            "Old attempt can settle same owner's new claim"
        )
        assert result.last_finished_at is not None
        assert result.last_started_at is not None
        assert result.last_finished_at < result.last_started_at
    assert result.latest_status is (
        ScheduledTaskStatus.SUCCEEDED if success else ScheduledTaskStatus.FAILED
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize("success", [False, True])
async def test_other_owner_and_unknown_settlement_are_normal_unchanged_none(
    rdb_session_manager: SessionManager[WriteSession],
    success: bool,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    current = await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
    assert current is not None
    before_commits = fixture.manager.commits
    assert (
        await settle(
            fixture,
            success=success,
            key="task",
            owner="other",
            finished=_START,
            next_run=None,
        )
        is None
    )
    assert (
        await settle(
            fixture,
            success=success,
            key="unknown",
            owner="owner-a",
            finished=_START,
            next_run=None,
        )
        is None
    )
    assert fixture.manager.commits == before_commits + 2
    assert await row(fixture, "task") == current
    fixture.manager.assert_closed()


async def test_failure_streak_and_success_clear_exact_fields_and_opaque_summary(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    await fixture.repository.trigger(task_key="task", now=at(0))
    claimed = await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
    assert claimed is not None
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBScheduledTaskState)
            .where(RDBScheduledTaskState.task_key == "task")
            .values(
                failure_streak=7,
                latest_result_summary={"old": True},
                last_succeeded_at=at(-5),
            )
        )
    failed = await fixture.repository.mark_failure(
        task_key="task",
        lease_owner="owner-a",
        finished_at=at(1),
        next_run_at=at(123),
        error_code="preserved-error-code",
        error_message="untrusted opaque text\nline",
    )
    assert failed is not None
    assert failed.failure_streak == 8, (
        "Increment persisted SQL value, not claimed snapshot"
    )
    assert failed.last_finished_at == failed.last_failed_at == at(1)
    assert failed.last_succeeded_at == at(-5)
    assert failed.latest_error_code == "preserved-error-code"
    assert failed.latest_error_message == "untrusted opaque text\nline"
    assert failed.latest_result_summary is failed.manual_requested_at is None
    assert failed.next_run_at == at(123)
    await fixture.repository.trigger(task_key="task", now=at(2))
    reclaimed = await claim(fixture, key="task", now=at(2), owner="owner-a", until=None)
    assert reclaimed is not None and reclaimed.failure_streak == 8
    summary = {"objects": [1, None, True, {"nested": "value"}], "count": 2}
    succeeded = await fixture.repository.mark_success(
        task_key="task",
        lease_owner="owner-a",
        finished_at=at(3),
        next_run_at=at(321),
        result_summary=summary,
    )
    assert succeeded is not None
    assert succeeded.failure_streak == 0
    assert succeeded.latest_error_code is succeeded.latest_error_message is None
    assert succeeded.latest_result_summary == summary
    assert succeeded.last_failed_at == at(1)
    assert succeeded.last_finished_at == succeeded.last_succeeded_at == at(3)
    assert succeeded.next_run_at == at(321)
    assert (
        succeeded.lease_owner
        is succeeded.leased_at
        is succeeded.lease_until
        is succeeded.manual_requested_at
        is None
    )
    assert claimed.lease_owner == "owner-a", (
        "Prior result is a detached immutable snapshot"
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "operation", ["trigger", "claim_due", "mark_success", "mark_failure"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_postwrite_error_or_actual_task_cancel_restores_only_current_operation(
    rdb_session_manager: SessionManager[WriteSession],
    operation: str,
    cancel: bool,
) -> None:
    fixture = scheduler_fixture(rdb_session_manager)
    await fixture.repository.ensure_registered_states(task_keys=("task",), now=_START)
    await fixture.repository.trigger(task_key="task", now=_START)
    if operation in {"mark_success", "mark_failure"}:
        assert (
            await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
            is not None
        )
    before = await row(fixture, "task")
    fixture.fault.stage = operation

    async def action() -> None:
        if operation == "trigger":
            await fixture.repository.trigger(task_key="task", now=at(9))
        elif operation == "claim_due":
            await claim(fixture, key="task", now=_START, owner="owner-a", until=None)
        else:
            await settle(
                fixture,
                success=operation == "mark_success",
                key="task",
                owner="owner-a",
                finished=at(9),
                next_run=None,
            )

    if cancel:
        fixture.fault.pause = True
        task = asyncio.create_task(action())
        try:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=5)
            task.cancel("after actual Scheduler write")
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            fixture.fault.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    else:
        fixture.fault.error = RuntimeError("after actual Scheduler write")
        with pytest.raises(RuntimeError, match="after actual Scheduler write"):
            await action()
    assert await row(fixture, "task") == before
    if operation in {"mark_success", "mark_failure"}:
        assert before is not None and before.lease_owner == "owner-a"
    fixture.manager.assert_closed()


class IndependentSchedulerManager:
    """Commit real transactions on independently pooled PostgreSQL connections."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.pids: list[int] = []
        self.entered = asyncio.Event()

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        async with AsyncSession(self.engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                pid = await session.read_session.scalar(
                    sa.text("SELECT pg_backend_pid()")
                )
                assert isinstance(pid, int)
                self.pids.append(pid)
                self.entered.set()
                yield session
            except BaseException:
                await session.write_session.rollback()
                raise
            else:
                await session.write_session.commit()


async def wait_scheduler_blocked(
    manager: SessionManager[WriteSession], *, holder: int, contender: int
) -> None:
    """Prove actual row contention using PostgreSQL, not a timing assumption."""
    assert holder != contender
    async with asyncio.timeout(10):
        async with manager() as observer:
            while True:
                blockers = await observer.write_session.scalar(
                    sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": contender}
                )
                if isinstance(blockers, list) and holder in blockers:
                    return


async def finish_scheduler_holder(
    task: asyncio.Task[ScheduledTaskState | None],
    fixture: SchedulerFixture,
    outcome: str,
) -> ScheduledTaskState | None:
    """Release or cancel the post-SQL barrier without hiding unexpected errors."""
    if outcome == "cancel":
        task.cancel("cancel actual independent Scheduler operation")
        with pytest.raises(asyncio.CancelledError):
            await task
        return None
    fixture.fault.release.set()
    if outcome == "error":
        with pytest.raises(RuntimeError, match="independent postwrite failure"):
            await task
        return None
    return await task


async def cleanup_scheduler_race(
    manager: SessionManager[WriteSession],
    *,
    key: str,
    tasks: list[asyncio.Task[ScheduledTaskState | None]],
    release: asyncio.Event,
) -> None:
    """Drain all subjects and remove only this UUID-scoped committed state."""
    release.set()
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBScheduledTaskState).where(
                RDBScheduledTaskState.task_key == key
            )
        )


@pytest.mark.parametrize("reclaim", [False, True])
@pytest.mark.parametrize("outcome", ["commit", "error", "cancel"])
async def test_independent_claim_reclaim_rechecks_predicate_after_blocked_writer(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    reclaim: bool,
    outcome: str,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    observer = IndependentSchedulerManager(rdb_engine)
    holder_manager = IndependentSchedulerManager(rdb_engine)
    contender_manager = IndependentSchedulerManager(rdb_engine)
    holder = scheduler_fixture(holder_manager)
    contender = scheduler_fixture(contender_manager)
    key = f"scheduler-claim-race-{uuid4()}"
    tasks: list[asyncio.Task[ScheduledTaskState | None]] = []
    try:
        await holder.repository.ensure_registered_states(task_keys=(key,), now=_START)
        if reclaim:
            assert (
                await claim(holder, key=key, now=_START, owner="expired", until=None)
                is not None
            )
        now = at(11) if reclaim else _START
        holder.fault.stage = "claim_due"
        holder.fault.pause = True
        if outcome == "error":
            holder.fault.error = RuntimeError("independent postwrite failure")
        first = asyncio.create_task(
            claim(holder, key=key, now=now, owner="first", until=None)
        )
        tasks.append(first)
        await asyncio.wait_for(holder.fault.reached.wait(), timeout=10)
        holder_pid = holder_manager.pids[-1]
        second = asyncio.create_task(
            claim(contender, key=key, now=now, owner="second", until=None)
        )
        tasks.append(second)
        await asyncio.wait_for(contender_manager.entered.wait(), timeout=10)
        contender_pid = contender_manager.pids[-1]
        await wait_scheduler_blocked(
            observer, holder=holder_pid, contender=contender_pid
        )
        assert not second.done()
        record_property("holder_backend_pid", holder_pid)
        record_property("contender_backend_pid", contender_pid)
        record_property("lock_witness", "pg_blocking_pids")
        first_result = await finish_scheduler_holder(first, holder, outcome)
        second_result = await asyncio.wait_for(second, timeout=10)
        if outcome == "commit":
            assert first_result is not None and first_result.lease_owner == "first"
            assert second_result is None
            persisted = await row(contender, key)
            assert persisted == first_result
        else:
            assert second_result is not None and second_result.lease_owner == "second"
            assert await row(contender, key) == second_result
            assert holder.manager.failures == 1
        holder.manager.assert_closed()
        contender.manager.assert_closed()
    finally:
        await cleanup_scheduler_race(
            observer, key=key, tasks=tasks, release=holder.fault.release
        )


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("first_operation", ["reclaim", "settlement"])
@pytest.mark.parametrize("outcome", ["commit", "error", "cancel"])
async def test_independent_reclaim_and_old_owner_settlement_preserve_existing_cas(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    success: bool,
    first_operation: str,
    outcome: str,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    observer = IndependentSchedulerManager(rdb_engine)
    holder_manager = IndependentSchedulerManager(rdb_engine)
    contender_manager = IndependentSchedulerManager(rdb_engine)
    holder = scheduler_fixture(holder_manager)
    contender = scheduler_fixture(contender_manager)
    key = f"scheduler-settlement-race-{uuid4()}"
    tasks: list[asyncio.Task[ScheduledTaskState | None]] = []
    try:
        await holder.repository.ensure_registered_states(task_keys=(key,), now=_START)
        assert (
            await claim(holder, key=key, now=_START, owner="old", until=None)
            is not None
        )
        holder.fault.stage = (
            "claim_due"
            if first_operation == "reclaim"
            else "mark_success"
            if success
            else "mark_failure"
        )
        holder.fault.pause = True
        if outcome == "error":
            holder.fault.error = RuntimeError("independent postwrite failure")

        async def action(
            fixture: SchedulerFixture, *, reclaim: bool
        ) -> ScheduledTaskState | None:
            if reclaim:
                return await claim(
                    fixture, key=key, now=at(11), owner="new", until=None
                )
            return await settle(
                fixture,
                key=key,
                success=success,
                owner="old",
                finished=at(12),
                next_run=None,
            )

        first = asyncio.create_task(
            action(holder, reclaim=first_operation == "reclaim")
        )
        tasks.append(first)
        await asyncio.wait_for(holder.fault.reached.wait(), timeout=10)
        holder_pid = holder_manager.pids[-1]
        second = asyncio.create_task(
            action(contender, reclaim=first_operation == "settlement")
        )
        tasks.append(second)
        await asyncio.wait_for(contender_manager.entered.wait(), timeout=10)
        contender_pid = contender_manager.pids[-1]
        await wait_scheduler_blocked(
            observer, holder=holder_pid, contender=contender_pid
        )
        assert not second.done()
        record_property("holder_backend_pid", holder_pid)
        record_property("contender_backend_pid", contender_pid)
        record_property("lock_witness", "pg_blocking_pids")
        first_result = await finish_scheduler_holder(first, holder, outcome)
        second_result = await asyncio.wait_for(second, timeout=10)
        expected = first_result if outcome == "commit" else second_result
        assert expected is not None
        assert await row(contender, key) == expected
        if outcome == "commit":
            assert second_result is None, (
                "Recheck owner after reclaim or due time after settlement"
            )
        else:
            assert holder.manager.failures == 1
        settled = (
            first_operation == "settlement"
            if outcome == "commit"
            else first_operation == "reclaim"
        )
        if settled:
            assert expected.lease_owner is None
            assert expected.last_finished_at == at(12)
            assert expected.next_run_at == at(42)
            assert expected.latest_status is (
                ScheduledTaskStatus.SUCCEEDED if success else ScheduledTaskStatus.FAILED
            )
            assert expected.failure_streak == (0 if success else 1)
        else:
            assert expected.lease_owner == "new"
            assert expected.latest_status is ScheduledTaskStatus.RUNNING
            assert expected.failure_streak == 0
        holder.manager.assert_closed()
        contender.manager.assert_closed()
    finally:
        await cleanup_scheduler_race(
            observer, key=key, tasks=tasks, release=holder.fault.release
        )
