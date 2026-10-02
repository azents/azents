"""Completed Scheduler current-state operations over the existing query predicates."""

import dataclasses
import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository
from azents.repos.scheduled_task_state.data import ScheduledTaskState


@dataclasses.dataclass(frozen=True)
class SchedulerStateOperationRepository:
    """Own the seven original Scheduler database groups without job callbacks."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    state_repository: Annotated[
        ScheduledTaskStateRepository, Depends(ScheduledTaskStateRepository)
    ]

    async def ensure_registered_states(
        self, *, task_keys: tuple[str, ...], now: datetime.datetime
    ) -> None:
        """Ensure ordered code keys atomically, including disabled definitions."""
        async with self.session_manager() as session:
            for task_key in task_keys:
                await self.state_repository.ensure_state(
                    session, task_key=task_key, next_run_at=now
                )

    async def list_states(self) -> list[ScheduledTaskState]:
        """Complete the existing ordered read after the separate ensure pass."""
        async with self.session_manager() as session:
            return await self.state_repository.list_states(session)

    async def get_state(self, task_key: str) -> ScheduledTaskState | None:
        """Complete one existing unlocked task-key read."""
        async with self.session_manager() as session:
            return await self.state_repository.get(session, task_key)

    async def trigger(
        self, *, task_key: str, now: datetime.datetime
    ) -> ScheduledTaskState | None:
        """Commit the existing manual due marker without enabling a task."""
        async with self.session_manager() as session:
            return await self.state_repository.trigger(
                session, task_key=task_key, now=now
            )

    async def claim_due(
        self,
        *,
        task_key: str,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ScheduledTaskState | None:
        """Complete the original conditional claim and return detached authority."""
        async with self.session_manager() as session:
            return await self.state_repository.claim_due(
                session,
                task_key=task_key,
                now=now,
                lease_owner=lease_owner,
                lease_until=lease_until,
            )

    async def mark_success(
        self,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        result_summary: dict[str, Any] | None,
    ) -> ScheduledTaskState | None:
        """Keep the existing opaque validated summary and owner-only settlement."""
        async with self.session_manager() as session:
            return await self.state_repository.mark_success(
                session,
                task_key=task_key,
                lease_owner=lease_owner,
                finished_at=finished_at,
                next_run_at=next_run_at,
                result_summary=result_summary,
            )

    async def mark_failure(
        self,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        error_code: str,
        error_message: str,
    ) -> ScheduledTaskState | None:
        """Commit the original failure/streak/clear group or normal stale no-op."""
        async with self.session_manager() as session:
            return await self.state_repository.mark_failure(
                session,
                task_key=task_key,
                lease_owner=lease_owner,
                finished_at=finished_at,
                next_run_at=next_run_at,
                error_code=error_code,
                error_message=error_message,
            )
