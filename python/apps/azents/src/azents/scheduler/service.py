"""Scheduler service."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated
from uuid import uuid4

from azcommon import di
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository
from azents.repos.scheduled_task_state.data import ScheduledTaskState
from azents.scheduler.executor import LocalTaskExecutor, TaskExecutor
from azents.scheduler.registry import get_task_definitions
from azents.scheduler.types import RetryPolicy, ScheduledTaskDefinition, TaskContext

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = datetime.timedelta(seconds=10)


def get_task_executor() -> TaskExecutor:
    """Scheduler TaskExecutor dependency."""
    return LocalTaskExecutor()


@dataclasses.dataclass(frozen=True)
class SchedulerService:
    """Periodic scheduled task service."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    state_repository: Annotated[
        ScheduledTaskStateRepository, Depends(ScheduledTaskStateRepository)
    ]
    executor: Annotated[TaskExecutor, Depends(get_task_executor)]
    container: Annotated[di.Container, Depends(di.get_container)]
    scheduler_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    poll_interval: datetime.timedelta = _DEFAULT_POLL_INTERVAL

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Run scheduler loop until shutdown."""
        logger.info("Scheduler starting", extra={"scheduler_id": self.scheduler_id})
        await self.ensure_registered_states()
        try:
            while not shutdown_event.is_set():
                await self.run_once()
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.poll_interval.total_seconds(),
                    )
                    return
                except asyncio.TimeoutError:
                    continue
        finally:
            logger.info("Scheduler stopped", extra={"scheduler_id": self.scheduler_id})

    async def ensure_registered_states(self) -> None:
        """Ensure DB state rows exist for all registered task definitions."""
        now = _utcnow()
        async with self.session_manager() as session:
            for definition in get_task_definitions():
                await self.state_repository.ensure_state(
                    session,
                    task_key=definition.key,
                    next_run_at=now,
                )

    async def list_states(self) -> list[ScheduledTaskState]:
        """Return all scheduler states."""
        await self.ensure_registered_states()
        async with self.session_manager() as session:
            return await self.state_repository.list_states(session)

    async def get_state(self, task_key: str) -> ScheduledTaskState | None:
        """Return one scheduler state."""
        await self.ensure_registered_states()
        async with self.session_manager() as session:
            return await self.state_repository.get(session, task_key)

    async def trigger(self, task_key: str) -> ScheduledTaskState | None:
        """Request manual execution for one task key."""
        await self.ensure_registered_states()
        if _get_definition(task_key) is None:
            return None
        now = _utcnow()
        async with self.session_manager() as session:
            state = await self.state_repository.trigger(
                session,
                task_key=task_key,
                now=now,
            )
        logger.info(
            "Scheduled task trigger requested",
            extra={"task_key": task_key, "scheduler_id": self.scheduler_id},
        )
        return state

    async def run_once(self) -> None:
        """Execute every due registered task at most once."""
        now = _utcnow()
        for definition in get_task_definitions():
            if not definition.enabled_by_default:
                continue
            state = await self._claim_definition(definition, now)
            if state is None:
                continue
            await self._execute_claimed(definition, state)

    async def _claim_definition(
        self,
        definition: ScheduledTaskDefinition,
        now: datetime.datetime,
    ) -> ScheduledTaskState | None:
        lease_until = now + definition.timeout + datetime.timedelta(seconds=30)
        async with self.session_manager() as session:
            state = await self.state_repository.claim_due(
                session,
                task_key=definition.key,
                now=now,
                lease_owner=self.scheduler_id,
                lease_until=lease_until,
            )
        if state is None:
            logger.debug(
                "Scheduled task not claimed",
                extra={"task_key": definition.key, "scheduler_id": self.scheduler_id},
            )
            return None
        logger.info(
            "Scheduled task claimed",
            extra={"task_key": definition.key, "scheduler_id": self.scheduler_id},
        )
        return state

    async def _execute_claimed(
        self,
        definition: ScheduledTaskDefinition,
        state: ScheduledTaskState,
    ) -> None:
        now = _utcnow()
        context = TaskContext(
            task_key=definition.key,
            attempt_started_at=now,
            lease_owner=self.scheduler_id,
            deadline=now + definition.timeout,
            manual_triggered=state.manual_requested_at is not None,
            container=self.container,
        )
        try:
            result = await self.executor.execute(definition, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._record_failure(definition, state, exc)
            return
        finished_at = _utcnow()
        next_run_at = finished_at + definition.interval
        async with self.session_manager() as session:
            await self.state_repository.mark_success(
                session,
                task_key=definition.key,
                lease_owner=self.scheduler_id,
                finished_at=finished_at,
                next_run_at=next_run_at,
                result_summary=result.summary,
            )
        logger.info(
            "Scheduled task succeeded",
            extra={"task_key": definition.key, "scheduler_id": self.scheduler_id},
        )

    async def _record_failure(
        self,
        definition: ScheduledTaskDefinition,
        state: ScheduledTaskState,
        exc: Exception,
    ) -> None:
        finished_at = _utcnow()
        next_run_at = compute_failure_next_run_at(
            definition.retry_policy,
            definition.interval,
            state.failure_streak + 1,
            finished_at,
        )
        async with self.session_manager() as session:
            await self.state_repository.mark_failure(
                session,
                task_key=definition.key,
                lease_owner=self.scheduler_id,
                finished_at=finished_at,
                next_run_at=next_run_at,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
        logger.exception(
            "Scheduled task failed",
            extra={"task_key": definition.key, "scheduler_id": self.scheduler_id},
        )


def _get_definition(task_key: str) -> ScheduledTaskDefinition | None:
    for definition in get_task_definitions():
        if definition.key == task_key:
            return definition
    return None


def compute_failure_next_run_at(
    retry_policy: RetryPolicy,
    interval: datetime.timedelta,
    failure_streak: int,
    now: datetime.datetime,
) -> datetime.datetime:
    if retry_policy.kind == "next_interval":
        return now + interval
    if retry_policy.min_delay is None or retry_policy.max_delay is None:
        return now + interval
    multiplier = 2 ** max(failure_streak - 1, 0)
    delay = retry_policy.min_delay * multiplier
    if delay > retry_policy.max_delay:
        delay = retry_policy.max_delay
    return now + delay


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
