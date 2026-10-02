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
from azents.services.historical_memory.discovery import (
    HistoricalMemoryAdmissionSample,
    HistoricalMemoryDiscoveryService,
)
from azents.services.historical_memory.preparation import (
    HistoricalMemoryPreparationService,
    HistoricalMemoryPreparationSummary,
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


def test_historical_sample_shares_aware_instant_and_preserves_real_deadline() -> None:
    """One isolated sample uses ordinary services and a wallclock deadline."""
    discovery = SimpleNamespace(
        admit_and_list_due_agents=AsyncMock(
            return_value=HistoricalMemoryAdmissionSample(
                admitted=1,
                due_agent_ids=("a" * 32,),
            )
        ),
    )
    preparation = SimpleNamespace(
        prepare_agent=AsyncMock(
            return_value=HistoricalMemoryPreparationSummary(
                attempted=1,
                prepared=1,
                empty=0,
                failed=0,
                quota_advanced=0,
            ),
        ),
    )
    app = _app(SimpleNamespace())
    app.dependency_overrides[HistoricalMemoryDiscoveryService] = lambda: discovery
    app.dependency_overrides[HistoricalMemoryPreparationService] = lambda: preparation
    real_before = datetime.datetime.now(datetime.UTC)
    response = TestClient(app).post(
        "/scheduler/v1/historical-memory/sample",
        json={"agent_id": "a" * 32, "now": "2099-01-01T09:00:00+09:00"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "now": "2099-01-01T00:00:00Z",
        "admitted": 1,
        "due_agents": 1,
        "attempted": 1,
        "prepared": 1,
        "empty": 0,
        "failed": 0,
        "quota_advanced": 0,
    }
    sampled_at = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    discovery.admit_and_list_due_agents.assert_awaited_once_with(
        now=sampled_at,
        agent_id="a" * 32,
    )
    kwargs = preparation.prepare_agent.await_args.kwargs
    assert kwargs["now"] == sampled_at
    assert kwargs["agent_id"] == "a" * 32
    assert real_before < kwargs["deadline"]
    assert kwargs["deadline"] < real_before + datetime.timedelta(seconds=120)


def test_historical_sample_rejects_naive_time_and_never_prepares_non_due_agent() -> (
    None
):
    """Invalid timestamps and unrelated work cannot reach model preparation."""
    discovery = SimpleNamespace(
        admit_and_list_due_agents=AsyncMock(
            return_value=HistoricalMemoryAdmissionSample(admitted=0, due_agent_ids=()),
        ),
    )
    preparation = SimpleNamespace(prepare_agent=AsyncMock())
    app = _app(SimpleNamespace())
    app.dependency_overrides[HistoricalMemoryDiscoveryService] = lambda: discovery
    app.dependency_overrides[HistoricalMemoryPreparationService] = lambda: preparation
    client = TestClient(app)
    invalid = client.post(
        "/scheduler/v1/historical-memory/sample",
        json={"agent_id": "a" * 32, "now": "2099-01-01T00:00:00"},
    )
    assert invalid.status_code == 422
    discovery.admit_and_list_due_agents.assert_not_awaited()
    response = client.post(
        "/scheduler/v1/historical-memory/sample",
        json={"agent_id": "a" * 32, "now": "2099-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["attempted"] == 0
    preparation.prepare_agent.assert_not_awaited()
