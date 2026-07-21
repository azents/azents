"""Scheduled task registry."""

import dataclasses
import datetime
import logging

from azents.scheduler.types import (
    RetryPolicy,
    ScheduledTaskDefinition,
    TaskContext,
    TaskResult,
)
from azents.services.agent_decommission import AgentDecommissionService
from azents.services.archived_session_purge import ArchivedSessionPurgeService
from azents.services.archived_session_retention import (
    ArchivedSessionRetentionService,
)
from azents.services.file_lifecycle_cleanup import FileLifecycleCleanupService
from azents.services.llm_catalog import SystemCatalogProjectionService

logger = logging.getLogger(__name__)


async def heartbeat_handler(context: TaskContext) -> TaskResult:
    """Return heartbeat execution summary."""
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
        }
    )


async def system_catalog_projection_handler(context: TaskContext) -> TaskResult:
    """Refresh system model catalog projections."""
    service = await context.container.solve(SystemCatalogProjectionService)
    summaries = await service.sync_system_catalogs()
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            "catalogs": [
                {
                    "provider": summary.provider.value,
                    "catalog_id": summary.catalog_id,
                    "snapshot_id": summary.snapshot_id,
                    "visible_count": summary.visible_count,
                    "hidden_count": summary.hidden_count,
                }
                for summary in summaries
            ],
        }
    )


async def archived_session_retention_recalculation_handler(
    context: TaskContext,
) -> TaskResult:
    """Apply one bounded existing-archive retention recalculation batch."""
    service = await context.container.solve(ArchivedSessionRetentionService)
    summary = await service.recalculate_once(lease_owner=context.lease_owner)
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **dataclasses.asdict(summary),
        }
    )


async def archived_session_purge_handler(context: TaskContext) -> TaskResult:
    """Advance a bounded batch of durable archived-session purge jobs."""
    service = await context.container.solve(ArchivedSessionPurgeService)
    summary = await service.purge_once(
        lease_owner=context.lease_owner,
        deadline=context.deadline,
    )
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **dataclasses.asdict(summary),
        }
    )


async def agent_decommission_handler(context: TaskContext) -> TaskResult:
    """Advance durable Agent decommission jobs without owning session purge."""
    service = await context.container.solve(AgentDecommissionService)
    summary = await service.decommission_once(
        lease_owner=context.lease_owner,
        deadline=context.deadline,
    )
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **dataclasses.asdict(summary),
        }
    )


async def file_lifecycle_cleanup_handler(context: TaskContext) -> TaskResult:
    """Run bounded scheduler-owned file lifecycle cleanup."""
    service = await context.container.solve(FileLifecycleCleanupService)
    summary = await service.cleanup_once()
    logger.info(
        "File lifecycle cleanup completed",
        extra={
            "task_key": context.task_key,
            "manual_triggered": context.manual_triggered,
            **summary.to_dict(),
        },
    )
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **summary.to_dict(),
        }
    )


HEARTBEAT_TASK = ScheduledTaskDefinition(
    key="scheduler_heartbeat",
    description="No-op scheduler heartbeat used to verify periodic execution wiring.",
    interval=datetime.timedelta(minutes=1),
    timeout=datetime.timedelta(seconds=30),
    retry_policy=RetryPolicy(kind="next_interval"),
    handler=heartbeat_handler,
    enabled_by_default=True,
)

SYSTEM_CATALOG_PROJECTION_TASK = ScheduledTaskDefinition(
    key="model_catalog_system_projection",
    description="Refresh system model catalog projections from LiteLLM metadata.",
    interval=datetime.timedelta(hours=6),
    timeout=datetime.timedelta(minutes=5),
    retry_policy=RetryPolicy(
        kind="bounded_backoff",
        min_delay=datetime.timedelta(minutes=5),
        max_delay=datetime.timedelta(hours=1),
    ),
    handler=system_catalog_projection_handler,
    enabled_by_default=True,
)

ARCHIVED_SESSION_RETENTION_RECALCULATION_TASK = ScheduledTaskDefinition(
    key="archived_session_retention_recalculation",
    description="Apply retention revisions to existing archived sessions.",
    interval=datetime.timedelta(minutes=1),
    timeout=datetime.timedelta(minutes=2),
    retry_policy=RetryPolicy(
        kind="bounded_backoff",
        min_delay=datetime.timedelta(minutes=1),
        max_delay=datetime.timedelta(minutes=30),
    ),
    handler=archived_session_retention_recalculation_handler,
    enabled_by_default=True,
)

ARCHIVED_SESSION_PURGE_TASK = ScheduledTaskDefinition(
    key="archived_session_purge",
    description="Fence and purge due archived SessionAgent trees.",
    interval=datetime.timedelta(minutes=5),
    timeout=datetime.timedelta(minutes=10),
    retry_policy=RetryPolicy(
        kind="bounded_backoff",
        min_delay=datetime.timedelta(minutes=1),
        max_delay=datetime.timedelta(minutes=30),
    ),
    handler=archived_session_purge_handler,
    enabled_by_default=True,
)

AGENT_DECOMMISSION_TASK = ScheduledTaskDefinition(
    key="agent_decommission",
    description="Retire Agent roots and finalize decommissioned Agents.",
    interval=datetime.timedelta(minutes=1),
    timeout=datetime.timedelta(minutes=10),
    retry_policy=RetryPolicy(
        kind="bounded_backoff",
        min_delay=datetime.timedelta(minutes=1),
        max_delay=datetime.timedelta(minutes=30),
    ),
    handler=agent_decommission_handler,
    enabled_by_default=True,
)

FILE_LIFECYCLE_CLEANUP_TASK = ScheduledTaskDefinition(
    key="file_lifecycle_cleanup",
    description="Expire TTL-owned files and collect head-pruned ModelFiles.",
    interval=datetime.timedelta(minutes=5),
    timeout=datetime.timedelta(minutes=2),
    retry_policy=RetryPolicy(
        kind="bounded_backoff",
        min_delay=datetime.timedelta(minutes=5),
        max_delay=datetime.timedelta(hours=1),
    ),
    handler=file_lifecycle_cleanup_handler,
    enabled_by_default=True,
)

SCHEDULED_TASK_DEFINITIONS: tuple[ScheduledTaskDefinition, ...] = (
    HEARTBEAT_TASK,
    SYSTEM_CATALOG_PROJECTION_TASK,
    ARCHIVED_SESSION_RETENTION_RECALCULATION_TASK,
    ARCHIVED_SESSION_PURGE_TASK,
    AGENT_DECOMMISSION_TASK,
    FILE_LIFECYCLE_CLEANUP_TASK,
)


def get_task_definitions() -> tuple[ScheduledTaskDefinition, ...]:
    """Return code-registered scheduled task definitions."""
    return SCHEDULED_TASK_DEFINITIONS
