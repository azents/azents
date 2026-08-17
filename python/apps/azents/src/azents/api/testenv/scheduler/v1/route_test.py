"""Tests for credential-free Scheduler devtools."""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.testenv.scheduler.v1 import mount
from azents.scheduler.deps import get_scheduler_service
from azents.scheduler.user_scheduled_task_dispatch import (
    get_user_scheduled_task_dispatcher,
)
from azents.services.scheduled_task.service import ScheduledTaskDispatchSummary
from azents.utils.fastapi.route import as_route_mounter


def _app(scheduler: object, *, dispatcher: object | None = None) -> FastAPI:
    """Mount routes with an isolated Scheduler dependency."""
    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[get_scheduler_service] = lambda: scheduler
    if dispatcher is not None:
        app.dependency_overrides[get_user_scheduled_task_dispatcher] = lambda: (
            dispatcher
        )
    return app


def test_run_triggers_task_and_executes_scheduler_pass() -> None:
    """Run delegates to the real Scheduler service boundary."""
    scheduler = SimpleNamespace(
        trigger=AsyncMock(return_value=SimpleNamespace()),
        run_once=AsyncMock(),
    )

    response = TestClient(_app(scheduler)).post(
        "/scheduler/v1/run",
        json={"task_key": "archived_session_purge"},
    )

    assert response.status_code == 200
    assert response.json() == {"task_key": "archived_session_purge"}
    scheduler.trigger.assert_awaited_once_with("archived_session_purge")
    scheduler.run_once.assert_awaited_once_with()


def test_run_rejects_unknown_task() -> None:
    """Unknown task keys cannot execute an unrelated scheduler pass."""
    scheduler = SimpleNamespace(
        trigger=AsyncMock(return_value=None),
        run_once=AsyncMock(),
    )

    response = TestClient(_app(scheduler)).post(
        "/scheduler/v1/run",
        json={"task_key": "unknown"},
    )

    assert response.status_code == 404
    scheduler.run_once.assert_not_awaited()


def test_dispatch_scheduled_tasks_uses_exact_aware_instant() -> None:
    """Scheduled dispatch delegates one deterministic instant to the real service."""
    dispatcher = SimpleNamespace(
        dispatch_once=AsyncMock(
            return_value=ScheduledTaskDispatchSummary(
                claimed=3,
                admitted=1,
                coalesced=1,
                skipped=1,
                wake_failed=0,
            )
        )
    )
    now = "2026-08-16T19:30:00+09:00"

    response = TestClient(_app(SimpleNamespace(), dispatcher=dispatcher)).post(
        "/scheduler/v1/scheduled-tasks/dispatch",
        json={"now": now},
    )

    assert response.status_code == 200
    assert response.json() == {
        "now": "2026-08-16T10:30:00Z",
        "claimed": 3,
        "admitted": 1,
        "coalesced": 1,
        "skipped": 1,
        "wake_failed": 0,
    }
    dispatcher.dispatch_once.assert_awaited_once_with(
        lease_owner="testenv-scheduled-task-dispatch",
        now=datetime.datetime(2026, 8, 16, 10, 30, tzinfo=datetime.UTC),
    )


def test_dispatch_scheduled_tasks_rejects_naive_instant() -> None:
    """Naive timestamps cannot become dispatcher claim authority."""
    dispatcher = SimpleNamespace(dispatch_once=AsyncMock())

    response = TestClient(_app(SimpleNamespace(), dispatcher=dispatcher)).post(
        "/scheduler/v1/scheduled-tasks/dispatch",
        json={"now": "2026-08-16T10:30:00"},
    )

    assert response.status_code == 422
    dispatcher.dispatch_once.assert_not_awaited()
