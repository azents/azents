"""Scheduled Task repository tests."""

import datetime
from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ScheduledTaskScheduleType
from azents.rdb.models.scheduled_task import RDBScheduledTask
from azents.repos.scheduled_task.data import ScheduledTaskCreate
from azents.repos.scheduled_task.repository import ScheduledTaskRepository


def _dt(minutes: int) -> datetime.datetime:
    """Return one timezone-aware fixture instant."""
    return datetime.datetime(2026, 1, 1, 0, minutes, tzinfo=datetime.UTC)


def _rdb_task(task_id: str = "a" * 32) -> RDBScheduledTask:
    """Build one ORM row without requiring database defaults."""
    task = RDBScheduledTask(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        title="Daily report",
        objective="Prepare the report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        next_eligible_at=_dt(1),
        binding_id=None,
        scheduled_at=_dt(1),
        cron_expression=None,
        timezone=None,
    )
    task.id = task_id
    task.created_at = _dt(0)
    task.updated_at = _dt(0)
    return task


class _CreateSession:
    """Small async session double for repository create."""

    def __init__(self) -> None:
        self.row: RDBScheduledTask | None = None

    def add(self, row: RDBScheduledTask) -> None:
        self.row = row

    async def flush(self) -> None:
        assert self.row is not None
        self.row.created_at = _dt(0)
        self.row.updated_at = _dt(0)


class _ScalarSession:
    """Small async session double for exact lookup."""

    def __init__(self, row: RDBScheduledTask | None) -> None:
        self.row = row
        self.query: object | None = None

    async def scalar(self, query: object) -> RDBScheduledTask | None:
        self.query = query
        return self.row


class _ScalarResult:
    """Scalar result adapter for list tests."""

    def __init__(self, rows: list[RDBScheduledTask]) -> None:
        self.rows = rows

    def scalars(self) -> list[RDBScheduledTask]:
        return self.rows


class _ListSession:
    """Small async session double for Session-scoped listing."""

    def __init__(self, rows: list[RDBScheduledTask]) -> None:
        self.rows = rows
        self.query: object | None = None

    async def execute(self, query: object) -> _ScalarResult:
        self.query = query
        return _ScalarResult(self.rows)


class _DeleteResult:
    """Delete result with a row count."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _DeleteSession:
    """Small async session double for exact deletion."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.query: object | None = None
        self.flushed = False

    async def execute(self, query: object) -> _DeleteResult:
        self.query = query
        return _DeleteResult(self.rowcount)

    async def flush(self) -> None:
        self.flushed = True


def _sql(statement: object) -> str:
    """Compile one captured SQL statement with literal fixture values."""
    return str(
        cast(sa.ClauseElement, statement).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestScheduledTaskRepository:
    """Scheduled Task persistence repository tests."""

    async def test_create_builds_complete_once_row(self) -> None:
        """Create persists the complete M1 definition shape."""
        session = _CreateSession()
        task = await ScheduledTaskRepository().create(
            cast(AsyncSession, session),
            ScheduledTaskCreate(
                workspace_id="w" * 32,
                agent_id="a" * 32,
                session_id="s" * 32,
                title="Daily report",
                objective="Prepare the report.",
                schedule_type=ScheduledTaskScheduleType.ONCE,
                next_eligible_at=_dt(1),
                binding_id=None,
                scheduled_at=_dt(1),
                cron_expression=None,
                timezone=None,
            ),
        )

        assert session.row is not None
        assert len(task.id) == 32
        assert task.schedule_type is ScheduledTaskScheduleType.ONCE
        assert task.scheduled_at == _dt(1)
        assert task.cron_expression is None
        assert task.timezone is None
        assert task.active_cycle_id is None
        assert task.pending_scheduled_for is None
        assert task.lease_owner is None

    async def test_get_by_id_is_exact(self) -> None:
        """Exact lookup returns the matching persistence contract."""
        task = _rdb_task()
        session = _ScalarSession(task)
        result = await ScheduledTaskRepository().get_by_id(
            cast(AsyncSession, session),
            task.id,
        )

        assert result is not None
        assert result.id == task.id
        assert result.session_id == task.session_id
        assert f"WHERE scheduled_tasks.id = '{task.id}'" in _sql(session.query)

    async def test_lock_by_id_is_exact(self) -> None:
        """Locking lookup returns the matching persistence contract."""
        task = _rdb_task()
        session = _ScalarSession(task)
        result = await ScheduledTaskRepository().lock_by_id(
            cast(AsyncSession, session),
            task.id,
        )

        assert result is not None
        assert result.id == task.id
        statement = _sql(session.query)
        assert f"WHERE scheduled_tasks.id = '{task.id}'" in statement
        assert statement.endswith("FOR UPDATE")

    async def test_lock_claimed_by_id_fences_owner_token_and_expiry(self) -> None:
        """Claim locking includes owner, lease token, and unexpired predicates."""
        task = _rdb_task()
        task.lease_owner = "scheduler-1"
        task.lease_until = _dt(5)
        session = _ScalarSession(task)
        result = await ScheduledTaskRepository().lock_claimed_by_id(
            cast(AsyncSession, session),
            task_id=task.id,
            lease_owner="scheduler-1",
            lease_token=_dt(5),
            now=_dt(1),
        )

        assert result is not None
        statement = _sql(session.query)
        assert "scheduled_tasks.lease_owner = 'scheduler-1'" in statement
        assert "scheduled_tasks.lease_until = " in statement
        assert "scheduled_tasks.lease_until > " in statement
        assert statement.endswith("FOR UPDATE")

    async def test_list_by_session_id_preserves_repository_order(self) -> None:
        """Session-scoped list converts every ORM row."""
        rows = [_rdb_task("a" * 32), _rdb_task("b" * 32)]
        session = _ListSession(rows)
        result = await ScheduledTaskRepository().list_by_session_id(
            cast(AsyncSession, session),
            "s" * 32,
        )

        assert [task.id for task in result] == ["a" * 32, "b" * 32]
        statement = _sql(session.query)
        assert (
            "WHERE scheduled_tasks.session_id = 'ssssssssssssssssssssssssssssssss'"
        ) in statement
        assert (
            "ORDER BY scheduled_tasks.created_at ASC, scheduled_tasks.id ASC"
            in statement
        )

    async def test_delete_by_id_reports_exact_row_count(self) -> None:
        """Exact deletion reports whether one row was removed."""
        session = _DeleteSession(rowcount=1)
        assert await ScheduledTaskRepository().delete_by_id(
            cast(AsyncSession, session),
            "a" * 32,
        )
        assert "WHERE scheduled_tasks.id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'" in _sql(
            session.query
        )
        assert session.flushed is True

    async def test_delete_by_id_returns_false_when_no_row_was_removed(self) -> None:
        """Exact deletion reports a missing row without treating it as success."""
        session = _DeleteSession(rowcount=0)
        assert not await ScheduledTaskRepository().delete_by_id(
            cast(AsyncSession, session),
            "a" * 32,
        )
        assert session.flushed is True

    async def test_delete_completed_once_fences_task_cycle_and_schedule_type(
        self,
    ) -> None:
        """One-time completion deletes only its exact active cycle owner."""
        session = _DeleteSession(rowcount=1)

        assert await ScheduledTaskRepository().delete_completed_once(
            cast(AsyncSession, session),
            task_id="t" * 32,
            cycle_id="c" * 32,
        )

        statement = _sql(session.query)
        assert "scheduled_tasks.id = 'tttttttttttttttttttttttttttttttt'" in statement
        assert "scheduled_tasks.schedule_type = 'once'" in statement
        assert (
            "scheduled_tasks.active_cycle_id = 'cccccccccccccccccccccccccccccccc'"
        ) in statement
        assert session.flushed is True

    async def test_release_completed_recurring_exposes_pending_or_future_cursor(
        self,
    ) -> None:
        """Recurring completion atomically clears every active ownership field."""
        session = _DeleteSession(rowcount=1)

        assert await ScheduledTaskRepository().release_completed_recurring(
            cast(AsyncSession, session),
            task_id="t" * 32,
            cycle_id="c" * 32,
        )

        statement = _sql(session.query)
        assert "scheduled_tasks.schedule_type = 'cron'" in statement
        assert (
            "next_eligible_at=coalesce(scheduled_tasks.pending_scheduled_for, "
            "scheduled_tasks.next_eligible_at)"
        ) in statement
        assert "active_cycle_id=NULL" in statement
        assert "active_scheduled_for=NULL" in statement
        assert "pending_scheduled_for=NULL" in statement
        assert "lease_owner=NULL" in statement
        assert "lease_until=NULL" in statement
        assert session.flushed is True
