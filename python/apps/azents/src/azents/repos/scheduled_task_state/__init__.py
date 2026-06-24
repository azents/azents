"""Scheduled task state repository."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ScheduledTaskStatus
from azents.rdb.models.scheduled_task_state import RDBScheduledTaskState

from .data import ScheduledTaskState


class ScheduledTaskStateRepository:
    """Repository for scheduled task current state."""

    async def ensure_state(
        self,
        session: AsyncSession,
        *,
        task_key: str,
        next_run_at: datetime.datetime,
    ) -> ScheduledTaskState:
        """Ensure a state row exists.

        :param session: Database session
        :param task_key: Task key
        :param next_run_at: Initial next run time
        :return: Current state
        """
        stmt = (
            insert(RDBScheduledTaskState)
            .values(task_key=task_key, next_run_at=next_run_at)
            .on_conflict_do_nothing(index_elements=["task_key"])
        )
        await session.execute(stmt)
        await session.flush()
        state = await self.get(session, task_key)
        if state is None:
            raise RuntimeError("Scheduled task state ensure failed")
        return state

    async def list_states(
        self,
        session: AsyncSession,
    ) -> list[ScheduledTaskState]:
        """List task states ordered by task key."""
        result = await session.execute(
            sa.select(RDBScheduledTaskState).order_by(RDBScheduledTaskState.task_key)
        )
        return [self._build(row) for row in result.scalars()]

    async def get(
        self,
        session: AsyncSession,
        task_key: str,
    ) -> ScheduledTaskState | None:
        """Fetch one task state."""
        rdb = await session.get(RDBScheduledTaskState, task_key)
        if rdb is None:
            return None
        return self._build(rdb)

    async def trigger(
        self,
        session: AsyncSession,
        *,
        task_key: str,
        now: datetime.datetime,
    ) -> ScheduledTaskState | None:
        """Request a manual run by marking the task due."""
        result = await session.execute(
            sa.update(RDBScheduledTaskState)
            .where(RDBScheduledTaskState.task_key == task_key)
            .values(next_run_at=now, manual_requested_at=now)
            .returning(RDBScheduledTaskState)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        task_key: str,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ScheduledTaskState | None:
        """Atomically claim a due task with an expired or empty lease."""
        result = await session.execute(
            sa.update(RDBScheduledTaskState)
            .where(
                RDBScheduledTaskState.task_key == task_key,
                RDBScheduledTaskState.next_run_at <= now,
                sa.or_(
                    RDBScheduledTaskState.lease_until.is_(None),
                    RDBScheduledTaskState.lease_until < now,
                ),
            )
            .values(
                latest_status=ScheduledTaskStatus.RUNNING,
                last_started_at=now,
                lease_owner=lease_owner,
                leased_at=now,
                lease_until=lease_until,
            )
            .returning(RDBScheduledTaskState)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def mark_success(
        self,
        session: AsyncSession,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        result_summary: dict[str, Any] | None,
    ) -> ScheduledTaskState | None:
        """Record successful task execution and release lease."""
        result = await session.execute(
            sa.update(RDBScheduledTaskState)
            .where(
                RDBScheduledTaskState.task_key == task_key,
                RDBScheduledTaskState.lease_owner == lease_owner,
            )
            .values(
                latest_status=ScheduledTaskStatus.SUCCEEDED,
                last_finished_at=finished_at,
                last_succeeded_at=finished_at,
                failure_streak=0,
                latest_error_code=None,
                latest_error_message=None,
                latest_result_summary=result_summary,
                lease_owner=None,
                leased_at=None,
                lease_until=None,
                manual_requested_at=None,
                next_run_at=next_run_at,
            )
            .returning(RDBScheduledTaskState)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def mark_failure(
        self,
        session: AsyncSession,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        error_code: str,
        error_message: str,
    ) -> ScheduledTaskState | None:
        """Record failed task execution and release lease."""
        result = await session.execute(
            sa.update(RDBScheduledTaskState)
            .where(
                RDBScheduledTaskState.task_key == task_key,
                RDBScheduledTaskState.lease_owner == lease_owner,
            )
            .values(
                latest_status=ScheduledTaskStatus.FAILED,
                last_finished_at=finished_at,
                last_failed_at=finished_at,
                failure_streak=RDBScheduledTaskState.failure_streak + 1,
                latest_error_code=error_code,
                latest_error_message=error_message,
                latest_result_summary=None,
                lease_owner=None,
                leased_at=None,
                lease_until=None,
                manual_requested_at=None,
                next_run_at=next_run_at,
            )
            .returning(RDBScheduledTaskState)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    def _build(self, rdb: RDBScheduledTaskState) -> ScheduledTaskState:
        return ScheduledTaskState(
            task_key=rdb.task_key,
            latest_status=rdb.latest_status,
            next_run_at=rdb.next_run_at,
            last_started_at=rdb.last_started_at,
            last_finished_at=rdb.last_finished_at,
            last_succeeded_at=rdb.last_succeeded_at,
            last_failed_at=rdb.last_failed_at,
            failure_streak=rdb.failure_streak,
            latest_error_code=rdb.latest_error_code,
            latest_error_message=rdb.latest_error_message,
            latest_result_summary=rdb.latest_result_summary,
            lease_owner=rdb.lease_owner,
            leased_at=rdb.leased_at,
            lease_until=rdb.lease_until,
            manual_requested_at=rdb.manual_requested_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
