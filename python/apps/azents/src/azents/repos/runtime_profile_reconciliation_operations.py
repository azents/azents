"""Completed claim, resolution and fenced finalization operations for Profile tasks."""

import dataclasses
import datetime
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError

from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_profile.data import RuntimeConfigurationReconcileTask
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_profile_resolution_operations import (
    RuntimeProfileResolutionOperationRepository,
    RuntimeProfileResolutionRejected,
)


@dataclasses.dataclass(frozen=True)
class RuntimeProfileReconcilePage:
    """Detached exact-source page or a completed stale-source fence outcome."""

    agent_ids: tuple[str, ...]
    stale: bool
    stale_completion_accepted: bool


@dataclasses.dataclass
class RuntimeProfileReconciliationOperationRepository:
    """Own all task DB scopes while keeping per-Agent resolution independent."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    resolution_operations: Annotated[
        RuntimeProfileResolutionOperationRepository,
        Depends(RuntimeProfileResolutionOperationRepository),
    ]

    async def claim(
        self, *, now: datetime.datetime, reclaim_before: datetime.datetime, limit: int
    ) -> tuple[RuntimeConfigurationReconcileTask, ...]:
        """Commit exact bounded claims before any Agent work begins."""
        async with self.session_manager() as session:
            tasks = await self.profile_repository.claim_reconcile_tasks(
                session,
                available_before=now,
                reclaim_running_before=reclaim_before,
                limit=limit,
            )
        return tuple(tasks)

    async def read_page(
        self, task: RuntimeConfigurationReconcileTask, *, limit: int
    ) -> RuntimeProfileReconcilePage:
        """Check source version and complete obsolete claims in the same scope."""
        async with self.session_manager() as session:
            version = await self.profile_repository.get_reconcile_source_version(
                session, source_type=task.source_type, source_id=task.source_id
            )
            if version != task.source_version:
                completed = await self.profile_repository.complete_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=task.cursor,
                )
                page = RuntimeProfileReconcilePage(
                    agent_ids=(), stale=True, stale_completion_accepted=completed
                )
            else:
                agent_ids = await self.profile_repository.list_affected_agent_ids(
                    session,
                    source_type=task.source_type,
                    source_id=task.source_id,
                    after_agent_id=task.cursor,
                    limit=limit,
                )
                page = RuntimeProfileReconcilePage(
                    agent_ids=tuple(agent_ids),
                    stale=False,
                    stale_completion_accepted=False,
                )
        return page

    async def resolve_agent(
        self, agent_id: str
    ) -> Literal["ready", "blocked", "skipped", "database_unavailable"]:
        """Classify only the previously handled DB and source-resolution failures."""
        try:
            record = await self.resolution_operations.ensure_for_agent(agent_id)
        except RuntimeProfileResolutionRejected:
            return "skipped"
        except SQLAlchemyError:
            return "database_unavailable"
        return (
            "blocked"
            if record.desired.status is RuntimeConfigurationStateStatus.BLOCKED
            else "ready"
        )

    async def retry(
        self,
        task: RuntimeConfigurationReconcileTask,
        *,
        cursor: str | None,
        available_at: datetime.datetime,
    ) -> bool:
        """Commit the previous completed Agent cursor through its attempt fence."""
        async with self.session_manager() as session:
            accepted = await self.profile_repository.retry_reconcile_task(
                session,
                task_id=task.id,
                expected_attempt=task.attempt,
                cursor=cursor,
                available_at=available_at,
                failure_code="database_unavailable",
            )
        return accepted

    async def finalize(
        self,
        task: RuntimeConfigurationReconcileTask,
        *,
        cursor: str | None,
        has_more: bool,
        available_at: datetime.datetime,
    ) -> bool:
        """Complete or continue one exact claim after per-Agent commits finish."""
        async with self.session_manager() as session:
            if has_more:
                if cursor is None:
                    raise AssertionError("A non-empty reconcile page lost its cursor.")
                accepted = await self.profile_repository.continue_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=cursor,
                    available_at=available_at,
                )
            else:
                accepted = await self.profile_repository.complete_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=cursor,
                )
        return accepted
