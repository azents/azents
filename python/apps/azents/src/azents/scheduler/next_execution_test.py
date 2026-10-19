"""Explicit next times preserve common Scheduler ownership and default cadence."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from azents.job_runtime.types import JobOutcome
from azents.scheduler.executor import execute_scheduled_task_job
from azents.scheduler.executor_test import _context
from azents.scheduler.service import SchedulerService
from azents.scheduler.service_test import (
    CompletedOperations,
    RecordingRuntime,
    _definition,
    _state,
)
from azents.scheduler.types import RetryPolicy, ScheduledTaskDefinition, TaskResult

NOW = datetime.datetime(2026, 10, 19, tzinfo=datetime.UTC)


@pytest.mark.parametrize("offset", [None, -1, 7])
async def test_success_schedule_uses_explicit_time_or_unchanged_default(
    monkeypatch: pytest.MonkeyPatch, offset: int | None
) -> None:
    next_at = None if offset is None else NOW + datetime.timedelta(seconds=offset)
    monkeypatch.setattr("azents.scheduler.service._utcnow", lambda: NOW)
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    runtime = RecordingRuntime(
        trace,
        {
            "cleanup": JobOutcome.succeeded(
                TaskResult(summary={"checked": 1}, next_run_at=next_at).model_dump(
                    mode="json"
                )
            )
        },
        {},
    )
    scheduler = SchedulerService(repository, runtime, scheduler_id="scheduler")
    definition = _definition("cleanup", enabled=True)
    await scheduler._execute_claimed(
        definition,
        _state(task_key="cleanup", last_started_at=NOW, manual_requested_at=None),
    )
    assert repository.success_times == [
        NOW + definition.interval if next_at is None else max(NOW, next_at)
    ]
    assert repository.success_summaries == [{"checked": 1}]


async def test_malformed_schedule_result_records_failure_not_success() -> None:
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    runtime = RecordingRuntime(
        trace,
        {
            "cleanup": JobOutcome.succeeded(
                {"summary": None, "next_run_at": "2026-10-19T00:00:00"}
            )
        },
        {},
    )
    scheduler = SchedulerService(repository, runtime, scheduler_id="scheduler")
    await scheduler._execute_claimed(
        _definition("cleanup", enabled=True),
        _state(task_key="cleanup", last_started_at=NOW, manual_requested_at=None),
    )
    assert repository.success_times == []
    assert repository.failure_codes == ["ValidationError"]


async def test_explicit_next_time_survives_the_job_runtime_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AsyncMock(return_value=TaskResult(summary=None, next_run_at=NOW))
    definition = ScheduledTaskDefinition(
        key="cleanup",
        description="Check due resources.",
        interval=datetime.timedelta(minutes=30),
        timeout=datetime.timedelta(minutes=2),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=handler,
        enabled_by_default=True,
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions", lambda: (definition,)
    )
    result = await execute_scheduled_task_job(_context(MagicMock()))
    assert result == {"summary": None, "next_run_at": "2026-10-19T00:00:00Z"}


def test_task_result_rejects_naive_unknown_and_missing_scheduling_fields() -> None:
    for payload in [
        {"summary": None},
        {"summary": None, "next_run_at": "2026-10-19T00:00:00"},
        {"summary": None, "next_run_at": None, "interval": 1},
    ]:
        with pytest.raises(ValidationError):
            TaskResult.model_validate(payload)
