"""Scheduler Job Runtime handler adapter tests."""

import asyncio
import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.job_runtime.types import JobExecutionContext, JobRequest
from azents.scheduler.executor import execute_scheduled_task_job
from azents.scheduler.types import RetryPolicy, ScheduledTaskDefinition, TaskResult


def _context(container: object) -> JobExecutionContext:
    started_at = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    return JobExecutionContext(
        request=JobRequest(
            handler_key="scheduler.task",
            execution_key="scheduler:cleanup:scheduler-1:claim-1",
            deadline=started_at + datetime.timedelta(minutes=2),
            payload={
                "task_key": "cleanup",
                "attempt_started_at": "2026-08-10T00:00:00Z",
                "lease_owner": "scheduler-1",
                "manual_triggered": True,
            },
        ),
        container=cast(Any, container),
    )


@pytest.mark.asyncio
async def test_execute_scheduled_task_job_reconstructs_task_local_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter keeps the DI container outside the JSON-safe request."""
    handler = AsyncMock(return_value=TaskResult(summary={"deleted": 3}))
    definition = ScheduledTaskDefinition(
        key="cleanup",
        description="Clean expired resources.",
        interval=datetime.timedelta(hours=1),
        timeout=datetime.timedelta(minutes=2),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=handler,
        enabled_by_default=True,
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions",
        lambda: (definition,),
    )
    container = MagicMock()
    context = _context(container)

    result = await execute_scheduled_task_job(context)

    assert result == {"deleted": 3}
    handler.assert_awaited_once()
    handler_call = handler.await_args
    assert handler_call is not None
    task_context = handler_call.args[0]
    assert task_context.task_key == "cleanup"
    assert task_context.attempt_started_at == datetime.datetime(
        2026,
        8,
        10,
        tzinfo=datetime.UTC,
    )
    assert task_context.lease_owner == "scheduler-1"
    assert task_context.deadline == context.request.deadline
    assert task_context.manual_triggered is True
    assert task_context.container is container


@pytest.mark.asyncio
async def test_execute_scheduled_task_job_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered adapter never converts cancellation into task failure."""
    handler = AsyncMock(side_effect=asyncio.CancelledError())
    definition = ScheduledTaskDefinition(
        key="cleanup",
        description="Clean expired resources.",
        interval=datetime.timedelta(hours=1),
        timeout=datetime.timedelta(minutes=2),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=handler,
        enabled_by_default=True,
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions",
        lambda: (definition,),
    )

    with pytest.raises(asyncio.CancelledError):
        await execute_scheduled_task_job(_context(MagicMock()))
