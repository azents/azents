"""Scheduled Task repository."""

import datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ScheduledTaskScheduleType
from azents.rdb.models.scheduled_task import RDBScheduledTask

from .data import ScheduledTask, ScheduledTaskCreate, ScheduledTaskReplace


class ScheduledTaskRepository:
    """Repository for durable user Scheduled Tasks."""

    async def create(
        self,
        session: AsyncSession,
        create: ScheduledTaskCreate,
    ) -> ScheduledTask:
        """Create one Scheduled Task row."""
        rdb = RDBScheduledTask(
            workspace_id=create.workspace_id,
            agent_id=create.agent_id,
            session_id=create.session_id,
            title=create.title,
            objective=create.objective,
            schedule_type=create.schedule_type,
            next_eligible_at=create.next_eligible_at,
            binding_id=create.binding_id,
            scheduled_at=create.scheduled_at,
            cron_expression=create.cron_expression,
            timezone=create.timezone,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        """Fetch one Scheduled Task by exact ID."""
        rdb = await session.scalar(
            sa.select(RDBScheduledTask).where(RDBScheduledTask.id == task_id)
        )
        return self._build(rdb) if rdb is not None else None

    async def get_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
        lock: bool = False,
    ) -> ScheduledTask | None:
        """Fetch one exact Task owned by one exact Session."""
        query = sa.select(RDBScheduledTask).where(
            RDBScheduledTask.session_id == session_id,
            RDBScheduledTask.id == task_id,
        )
        if lock:
            query = query.with_for_update()
        rdb = await session.scalar(query)
        return self._build(rdb) if rdb is not None else None

    async def lock_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        """Lock and fetch one Scheduled Task by exact ID."""
        rdb = await session.scalar(
            sa.select(RDBScheduledTask)
            .where(RDBScheduledTask.id == task_id)
            .with_for_update()
        )
        return self._build(rdb) if rdb is not None else None

    async def lock_claimed_by_id(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        lease_owner: str,
        lease_token: datetime.datetime,
        now: datetime.datetime,
    ) -> ScheduledTask | None:
        """Lock one Task only while its unexpired lease belongs to the caller."""
        rdb = await session.scalar(
            sa.select(RDBScheduledTask)
            .where(
                RDBScheduledTask.id == task_id,
                RDBScheduledTask.lease_owner == lease_owner,
                RDBScheduledTask.lease_until == lease_token,
                RDBScheduledTask.lease_until > now,
            )
            .with_for_update()
        )
        return self._build(rdb) if rdb is not None else None

    async def list_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> list[ScheduledTask]:
        """List Tasks owned by one exact Session."""
        result = await session.execute(
            sa.select(RDBScheduledTask)
            .where(RDBScheduledTask.session_id == session_id)
            .order_by(
                RDBScheduledTask.created_at.asc(),
                RDBScheduledTask.id.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def replace(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
        replace: ScheduledTaskReplace,
        preserve_active_cycle: bool = False,
    ) -> ScheduledTask | None:
        """Replace editable definition fields for one Session-owned Task."""
        values: dict[str, object] = {
            "title": replace.title,
            "objective": replace.objective,
            "schedule_type": replace.schedule_type,
            "next_eligible_at": replace.next_eligible_at,
            "binding_id": replace.binding_id,
            "scheduled_at": replace.scheduled_at,
            "cron_expression": replace.cron_expression,
            "timezone": replace.timezone,
            "pending_scheduled_for": None,
            "lease_owner": None,
            "lease_until": None,
            "updated_at": sa.func.now(),
        }
        if not preserve_active_cycle:
            values["active_cycle_id"] = None
            values["active_scheduled_for"] = None
        result = await session.execute(
            sa.update(RDBScheduledTask)
            .where(
                RDBScheduledTask.session_id == session_id,
                RDBScheduledTask.id == task_id,
            )
            .values(**values)
            .returning(RDBScheduledTask)
        )
        await session.flush()
        rdb = result.scalar_one_or_none()
        return self._build(rdb) if rdb is not None else None

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[ScheduledTask]:
        """Claim a bounded batch of due Tasks using PostgreSQL SKIP LOCKED."""
        result = await session.execute(
            sa.select(RDBScheduledTask)
            .where(
                RDBScheduledTask.next_eligible_at <= now,
                sa.or_(
                    RDBScheduledTask.active_cycle_id.is_(None),
                    RDBScheduledTask.schedule_type == ScheduledTaskScheduleType.CRON,
                ),
                sa.or_(
                    RDBScheduledTask.lease_until.is_(None),
                    RDBScheduledTask.lease_until <= now,
                ),
            )
            .order_by(
                RDBScheduledTask.next_eligible_at.asc(),
                RDBScheduledTask.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars())
        for row in rows:
            row.lease_owner = lease_owner
            row.lease_until = lease_until
        await session.flush()
        for row in rows:
            await session.refresh(row, attribute_names=["updated_at"])
        return [self._build(row) for row in rows]

    async def complete_claim(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        lease_owner: str,
        lease_token: datetime.datetime,
        lease_now: datetime.datetime,
        next_eligible_at: datetime.datetime,
        active_cycle_id: str | None,
        active_scheduled_for: datetime.datetime | None,
        pending_scheduled_for: datetime.datetime | None,
    ) -> bool:
        """Persist one dispatch cursor transition and release its lease."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBScheduledTask)
                .where(
                    RDBScheduledTask.id == task_id,
                    RDBScheduledTask.lease_owner == lease_owner,
                    RDBScheduledTask.lease_until == lease_token,
                    RDBScheduledTask.lease_until > lease_now,
                )
                .values(
                    next_eligible_at=next_eligible_at,
                    active_cycle_id=active_cycle_id,
                    active_scheduled_for=active_scheduled_for,
                    pending_scheduled_for=pending_scheduled_for,
                    lease_owner=None,
                    lease_until=None,
                    updated_at=sa.func.now(),
                )
            ),
        )
        await session.flush()
        return bool(result.rowcount)

    async def delete_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> bool:
        """Delete one Scheduled Task by exact ID."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBScheduledTask).where(RDBScheduledTask.id == task_id)
            ),
        )
        await session.flush()
        return bool(result.rowcount)

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
    ) -> bool:
        """Delete one Task only when its Session ownership matches exactly."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBScheduledTask).where(
                    RDBScheduledTask.session_id == session_id,
                    RDBScheduledTask.id == task_id,
                )
            ),
        )
        await session.flush()
        return bool(result.rowcount)

    async def delete_completed_once(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        cycle_id: str,
    ) -> bool:
        """Delete a one-time Task only while it owns the completed cycle."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBScheduledTask).where(
                    RDBScheduledTask.id == task_id,
                    RDBScheduledTask.schedule_type == ScheduledTaskScheduleType.ONCE,
                    RDBScheduledTask.active_cycle_id == cycle_id,
                )
            ),
        )
        await session.flush()
        return bool(result.rowcount)

    async def release_completed_recurring(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        cycle_id: str,
    ) -> bool:
        """Release a recurring Task fence and expose pending or future work."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBScheduledTask)
                .where(
                    RDBScheduledTask.id == task_id,
                    RDBScheduledTask.schedule_type == ScheduledTaskScheduleType.CRON,
                    RDBScheduledTask.active_cycle_id == cycle_id,
                )
                .values(
                    next_eligible_at=sa.func.coalesce(
                        RDBScheduledTask.pending_scheduled_for,
                        RDBScheduledTask.next_eligible_at,
                    ),
                    active_cycle_id=None,
                    active_scheduled_for=None,
                    pending_scheduled_for=None,
                    lease_owner=None,
                    lease_until=None,
                    updated_at=sa.func.now(),
                )
            ),
        )
        await session.flush()
        return bool(result.rowcount)

    def _build(self, rdb: RDBScheduledTask) -> ScheduledTask:
        """Convert one ORM row to its persistence data contract."""
        return ScheduledTask(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_id=rdb.agent_id,
            session_id=rdb.session_id,
            binding_id=rdb.binding_id,
            title=rdb.title,
            objective=rdb.objective,
            schedule_type=rdb.schedule_type,
            scheduled_at=rdb.scheduled_at,
            cron_expression=rdb.cron_expression,
            timezone=rdb.timezone,
            next_eligible_at=rdb.next_eligible_at,
            active_cycle_id=rdb.active_cycle_id,
            active_scheduled_for=rdb.active_scheduled_for,
            pending_scheduled_for=rdb.pending_scheduled_for,
            lease_owner=rdb.lease_owner,
            lease_until=rdb.lease_until,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
