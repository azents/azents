"""Scheduler service tests."""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

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
        executor=MagicMock(),
        container=MagicMock(),
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
        executor=MagicMock(),
        container=MagicMock(),
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
