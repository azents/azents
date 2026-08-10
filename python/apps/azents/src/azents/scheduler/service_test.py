"""Scheduler service tests."""

import asyncio
import datetime
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.enums import ScheduledTaskStatus
from azents.job_runtime.types import JobOutcome, JobRequest
from azents.repos.scheduled_task_state.data import ScheduledTaskState
from azents.scheduler.service import SchedulerService, compute_failure_next_run_at
from azents.scheduler.types import (
    RetryPolicy,
    ScheduledTaskDefinition,
)


def test_compute_failure_next_run_at_uses_next_interval() -> None:
    """next_interval retry waits for regular interval."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    result = compute_failure_next_run_at(
        RetryPolicy(kind="next_interval"),
        datetime.timedelta(hours=1),
        3,
        now,
    )

    assert result == now + datetime.timedelta(hours=1)


def test_compute_failure_next_run_at_bounds_backoff() -> None:
    """bounded_backoff is capped by max_delay."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    result = compute_failure_next_run_at(
        RetryPolicy(
            kind="bounded_backoff",
            min_delay=datetime.timedelta(minutes=5),
            max_delay=datetime.timedelta(minutes=30),
        ),
        datetime.timedelta(hours=1),
        5,
        now,
    )

    assert result == now + datetime.timedelta(minutes=30)


@pytest.mark.asyncio
async def test_run_once_continues_when_task_lifecycle_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One task lifecycle failure does not stop later scheduled tasks."""
    failing = ScheduledTaskDefinition(
        key="failing",
        description="Fails while recording task failure.",
        interval=datetime.timedelta(minutes=1),
        timeout=datetime.timedelta(minutes=1),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=AsyncMock(),
        enabled_by_default=True,
    )
    succeeding = ScheduledTaskDefinition(
        key="succeeding",
        description="Runs after the failed task.",
        interval=datetime.timedelta(minutes=1),
        timeout=datetime.timedelta(minutes=1),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=AsyncMock(),
        enabled_by_default=True,
    )
    scheduler = SchedulerService(
        session_manager=MagicMock(),
        state_repository=MagicMock(),
        job_runtime=MagicMock(),
        scheduler_id="scheduler",
    )
    attempted: list[str] = []

    async def claim(
        self: SchedulerService,
        definition: ScheduledTaskDefinition,
        now: datetime.datetime,
    ) -> MagicMock:
        return MagicMock()

    async def execute_claimed(
        self: SchedulerService,
        definition: ScheduledTaskDefinition,
        state: MagicMock,
    ) -> None:
        attempted.append(definition.key)
        if definition.key == "failing":
            raise RuntimeError("task-state recording failed")

    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (failing, succeeding),
    )
    monkeypatch.setattr(SchedulerService, "_claim_definition", claim)
    monkeypatch.setattr(SchedulerService, "_execute_claimed", execute_claimed)

    await scheduler.run_once()

    assert attempted == ["failing", "succeeding"]


@pytest.mark.asyncio
async def test_run_once_propagates_task_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task cancellation stops the scheduler run instead of being isolated."""
    definition = ScheduledTaskDefinition(
        key="cancelling",
        description="Raises cancellation.",
        interval=datetime.timedelta(minutes=1),
        timeout=datetime.timedelta(minutes=1),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=AsyncMock(),
        enabled_by_default=True,
    )
    scheduler = SchedulerService(
        session_manager=MagicMock(),
        state_repository=MagicMock(),
        job_runtime=MagicMock(),
        scheduler_id="scheduler",
    )

    async def claim(
        self: SchedulerService,
        definition: ScheduledTaskDefinition,
        now: datetime.datetime,
    ) -> MagicMock:
        return MagicMock()

    async def execute_claimed(
        self: SchedulerService,
        definition: ScheduledTaskDefinition,
        state: MagicMock,
    ) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (definition,),
    )
    monkeypatch.setattr(SchedulerService, "_claim_definition", claim)
    monkeypatch.setattr(SchedulerService, "_execute_claimed", execute_claimed)

    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_once()


@pytest.mark.asyncio
async def test_execute_claimed_submits_json_safe_per_claim_request() -> None:
    """Scheduler delegates one claimed task through the common Job Runtime."""
    attempt_started_at = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    definition = ScheduledTaskDefinition(
        key="cleanup",
        description="Clean expired resources.",
        interval=datetime.timedelta(hours=1),
        timeout=datetime.timedelta(minutes=2),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=AsyncMock(),
        enabled_by_default=True,
    )
    state = _state(
        task_key=definition.key,
        last_started_at=attempt_started_at,
        manual_requested_at=attempt_started_at,
    )
    handle = MagicMock()
    handle.wait = AsyncMock(return_value=JobOutcome.succeeded({"deleted": 3}))
    job_runtime = MagicMock()
    job_runtime.submit = AsyncMock(return_value=handle)
    state_repository = MagicMock()
    state_repository.mark_success = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    scheduler = SchedulerService(
        session_manager=cast(Any, session_manager),
        state_repository=state_repository,
        job_runtime=job_runtime,
        scheduler_id="scheduler-1",
    )

    await scheduler._execute_claimed(definition, state)

    submit_call = job_runtime.submit.await_args
    assert submit_call is not None
    submitted = submit_call.args[0]
    assert isinstance(submitted, JobRequest)
    assert submitted.handler_key == "scheduler.task"
    assert submitted.execution_key == (
        "scheduler:cleanup:scheduler-1:2026-08-10T00:00:00+00:00"
    )
    assert submitted.deadline == attempt_started_at + definition.timeout
    assert submitted.payload == {
        "task_key": "cleanup",
        "attempt_started_at": "2026-08-10T00:00:00Z",
        "lease_owner": "scheduler-1",
        "manual_triggered": True,
    }
    handle.wait.assert_awaited_once_with()
    state_repository.mark_success.assert_awaited_once()
    mark_success_call = state_repository.mark_success.await_args
    assert mark_success_call is not None
    assert mark_success_call.kwargs["result_summary"] == {"deleted": 3}


def _state(
    *,
    task_key: str,
    last_started_at: datetime.datetime | None,
    manual_requested_at: datetime.datetime | None = None,
) -> ScheduledTaskState:
    """Build a focused Scheduler state fixture."""
    now = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    return ScheduledTaskState(
        task_key=task_key,
        latest_status=ScheduledTaskStatus.RUNNING,
        next_run_at=now,
        last_started_at=last_started_at,
        last_finished_at=None,
        last_succeeded_at=None,
        last_failed_at=None,
        failure_streak=0,
        latest_error_code=None,
        latest_error_message=None,
        latest_result_summary=None,
        lease_owner="scheduler-1",
        leased_at=now,
        lease_until=now + datetime.timedelta(minutes=3),
        manual_requested_at=manual_requested_at,
        created_at=now,
        updated_at=now,
    )
