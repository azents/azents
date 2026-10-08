"""Process durable bounded Runtime configuration reconciliation tasks."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends

from azents.repos.runtime_profile.data import RuntimeConfigurationReconcileTask
from azents.repos.runtime_profile_reconciliation_operations import (
    RuntimeProfileReconciliationOperationRepository,
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

    operations: Annotated[
        RuntimeProfileReconciliationOperationRepository,
        Depends(RuntimeProfileReconciliationOperationRepository),
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
        tasks = await self.operations.claim(
            now=now, reclaim_before=now - _CLAIM_TIMEOUT, limit=task_limit
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
        snapshot = await self.operations.read_page(task, limit=page_size + 1)
        if snapshot.stale:
            return _result(stale_tasks=1 if snapshot.stale_completion_accepted else 0)
        agent_ids = snapshot.agent_ids

        page = agent_ids[:page_size]
        has_more = len(agent_ids) > page_size
        cursor = task.cursor
        reconciled = blocked = skipped = 0
        for agent_id in page:
            outcome = await self.operations.resolve_agent(agent_id)
            if outcome == "skipped":
                skipped += 1
            elif outcome == "database_unavailable":
                retried = await self.operations.retry(
                    task, cursor=cursor, available_at=tznow() + retry_delay
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
                if outcome == "blocked":
                    blocked += 1
            cursor = agent_id

        accepted = await self.operations.finalize(
            task, cursor=cursor, has_more=has_more, available_at=tznow()
        )
        continued_count = 1 if has_more and accepted else 0
        stale_count = 0 if accepted else 1
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
