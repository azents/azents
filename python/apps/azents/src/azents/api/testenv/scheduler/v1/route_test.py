"""Tests for credential-free Scheduler devtools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.testenv.scheduler.v1 import mount
from azents.scheduler.deps import get_scheduler_service
from azents.utils.fastapi.route import as_route_mounter


def _app(scheduler: object) -> FastAPI:
    """Mount routes with an isolated Scheduler dependency."""
    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[get_scheduler_service] = lambda: scheduler
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
