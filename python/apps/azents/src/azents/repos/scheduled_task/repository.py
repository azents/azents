"""Scheduled Task repository."""

from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.scheduled_task import RDBScheduledTask

from .data import ScheduledTask, ScheduledTaskCreate


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
