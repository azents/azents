"""Process durable bounded Runtime configuration reconciliation tasks."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.data import RuntimeConfigurationReconcileTask
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionUnavailable,
)
from azents.services.runtime_profile_resolution.service import (
    RuntimeProfileResolutionService,
)

_CLAIM_TIMEOUT = datetime.timedelta(minutes=5)


@dataclasses.dataclass(frozen=True)
class RuntimeProfileReconciliationResult:
    """Summary of one bounded durable reconciliation pass."""

    claimed_tasks: int
    reconciled_agents: int
    blocked_agents: int
    skipped_agents: int
    stale_tasks: int
    continued_tasks: int
    retried_tasks: int


@dataclasses.dataclass
class RuntimeProfileReconciliationService:
    """Fan out source changes to exact Agent Runtime desired revisions."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    resolution_service: Annotated[
        RuntimeProfileResolutionService,
        Depends(RuntimeProfileResolutionService),
    ]

    async def reconcile_once(
        self,
        *,
        task_limit: int = 10,
        page_size: int = 100,
        retry_delay: datetime.timedelta = datetime.timedelta(seconds=5),
    ) -> RuntimeProfileReconciliationResult:
        """Claim tasks and process at most one bounded Agent page per task."""
        if task_limit < 1:
            raise ValueError("Reconcile task limit must be positive.")
        if page_size < 1:
            raise ValueError("Reconcile page size must be positive.")
        now = tznow()
        async with self.session_manager() as session:
            tasks = await self.profile_repository.claim_reconcile_tasks(
                session,
                available_before=now,
                reclaim_running_before=now - _CLAIM_TIMEOUT,
                limit=task_limit,
            )

        reconciled = blocked = skipped = stale = continued = retried = 0
        for task in tasks:
            outcome = await self._reconcile_task(
                task,
                page_size=page_size,
                retry_delay=retry_delay,
            )
            reconciled += outcome.reconciled_agents
            blocked += outcome.blocked_agents
            skipped += outcome.skipped_agents
            stale += outcome.stale_tasks
            continued += outcome.continued_tasks
            retried += outcome.retried_tasks
        return RuntimeProfileReconciliationResult(
            claimed_tasks=len(tasks),
            reconciled_agents=reconciled,
            blocked_agents=blocked,
            skipped_agents=skipped,
            stale_tasks=stale,
            continued_tasks=continued,
            retried_tasks=retried,
        )

    async def _reconcile_task(
        self,
        task: RuntimeConfigurationReconcileTask,
        *,
        page_size: int,
        retry_delay: datetime.timedelta,
    ) -> RuntimeProfileReconciliationResult:
        async with self.session_manager() as session:
            current_version = (
                await self.profile_repository.get_reconcile_source_version(
                    session,
                    source_type=task.source_type,
                    source_id=task.source_id,
                )
            )
            if current_version != task.source_version:
                completed = await self.profile_repository.complete_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=task.cursor,
                )
                return _result(stale_tasks=1 if completed else 0)
            agent_ids = await self.profile_repository.list_affected_agent_ids(
                session,
                source_type=task.source_type,
                source_id=task.source_id,
                after_agent_id=task.cursor,
                limit=page_size + 1,
            )

        page = agent_ids[:page_size]
        has_more = len(agent_ids) > page_size
        cursor = task.cursor
        reconciled = blocked = skipped = 0
        for agent_id in page:
            try:
                resolution = await self.resolution_service.ensure_for_agent(agent_id)
            except RuntimeProfileResolutionUnavailable:
                skipped += 1
            except SQLAlchemyError:
                async with self.session_manager() as session:
                    retried = await self.profile_repository.retry_reconcile_task(
                        session,
                        task_id=task.id,
                        expected_attempt=task.attempt,
                        cursor=cursor,
                        available_at=tznow() + retry_delay,
                        failure_code="database_unavailable",
                    )
                return _result(
                    reconciled_agents=reconciled,
                    blocked_agents=blocked,
                    skipped_agents=skipped,
                    stale_tasks=0 if retried else 1,
                    retried_tasks=1 if retried else 0,
                )
            else:
                reconciled += 1
                if (
                    resolution.desired_revision.resolution_status
                    is RuntimeConfigurationResolutionStatus.BLOCKED
                ):
                    blocked += 1
            cursor = agent_id

        async with self.session_manager() as session:
            if has_more:
                if cursor is None:
                    raise AssertionError("A non-empty reconcile page lost its cursor.")
                continued = await self.profile_repository.continue_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=cursor,
                    available_at=tznow(),
                )
                continued_count = 1 if continued else 0
                stale_count = 0 if continued else 1
            else:
                completed = await self.profile_repository.complete_reconcile_task(
                    session,
                    task_id=task.id,
                    expected_attempt=task.attempt,
                    cursor=cursor,
                )
                continued_count = 0
                stale_count = 0 if completed else 1
        return _result(
            reconciled_agents=reconciled,
            blocked_agents=blocked,
            skipped_agents=skipped,
            stale_tasks=stale_count,
            continued_tasks=continued_count,
        )


def _result(
    *,
    reconciled_agents: int = 0,
    blocked_agents: int = 0,
    skipped_agents: int = 0,
    stale_tasks: int = 0,
    continued_tasks: int = 0,
    retried_tasks: int = 0,
) -> RuntimeProfileReconciliationResult:
    return RuntimeProfileReconciliationResult(
        claimed_tasks=0,
        reconciled_agents=reconciled_agents,
        blocked_agents=blocked_agents,
        skipped_agents=skipped_agents,
        stale_tasks=stale_tasks,
        continued_tasks=continued_tasks,
        retried_tasks=retried_tasks,
    )
