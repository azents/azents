"""Scheduled Task v1 Public API route tests."""

import datetime
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import (
    ScheduledTaskScheduleType,
    WorkspaceUserRole,
)
from azents.services.scheduled_task.management import (
    ScheduledTaskManagementProjection,
    ScheduledTaskManagementService,
    ScheduledTaskManagementUnavailable,
    ScheduledTaskSessionProjection,
)

from . import get_scheduled_task_management_service

_NOW = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
_BASE = "/scheduled-task/v1/workspaces/ws/agents/agent-1/scheduled-tasks"


def _projection() -> ScheduledTaskManagementProjection:
    return ScheduledTaskManagementProjection(
        id="t" * 32,
        title="Daily report",
        objective="Prepare the daily report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        scheduled_at=_NOW,
        cron_expression=None,
        timezone=None,
        next_eligible_at=_NOW,
        execution_state="idle",
        session=ScheduledTaskSessionProjection(
            id="s" * 32,
            handle="scheduled-session",
            title="Scheduled work",
        ),
        target=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _client(service: AsyncMock) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[get_scheduled_task_management_service] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
        session_id="auth-session-1",
    )
    return TestClient(app)


def _create_payload(*, channel_id: str | None = None) -> dict[str, str | None]:
    return {
        "session_id": "s" * 32,
        "title": "Daily report",
        "objective": "Prepare the daily report.",
        "at": "2099-08-17T00:00:00Z",
        "cron": None,
        "timezone": None,
        "channel_id": channel_id,
    }


def _replace_payload() -> dict[str, str | None]:
    payload = _create_payload()
    payload.pop("session_id")
    return payload


def test_openapi_has_exact_route_set_and_sanitized_schemas() -> None:
    """Generated clients see CRUD/cycle projections without internal authority."""
    spec = create_dummy_public_app().openapi()
    base = "/scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks"
    item = f"{base}/{{task_id}}"
    cycle = f"{item}/cycle"

    assert set(spec["paths"][base]) == {"get", "post"}
    assert set(spec["paths"][item]) == {"get", "put", "delete"}
    assert set(spec["paths"][cycle]) == {"get"}
    response_properties = set(
        spec["components"]["schemas"]["ScheduledTaskResponse"]["properties"]
    )
    assert response_properties == {
        "id",
        "title",
        "objective",
        "schedule_type",
        "scheduled_at",
        "cron_expression",
        "timezone",
        "next_eligible_at",
        "execution_state",
        "session",
        "target",
        "created_at",
        "updated_at",
    }
    cycle_properties = set(
        spec["components"]["schemas"]["ScheduledTaskCurrentCycleResponse"]["properties"]
    )
    assert cycle_properties == {
        "phase",
        "scheduled_for",
        "started_at",
        "progress_title",
        "ordered_tasks",
    }
    scheduled_schema = json.dumps(
        {
            name: schema
            for name, schema in spec["components"]["schemas"].items()
            if name.startswith("ScheduledTask")
        }
    )
    for forbidden in (
        "active_cycle_id",
        "cycle_id",
        "lease_owner",
        "lease_until",
        "provider_message",
        "revision",
        "toolkit_state",
    ):
        assert forbidden not in scheduled_schema


@pytest.mark.parametrize("reason", ["wrong_session", "wrong_binding"])
def test_create_hides_wrong_session_and_binding(reason: str) -> None:
    """Unavailable Session and Binding authority share one opaque response."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.create.side_effect = ScheduledTaskManagementUnavailable("not_found")

    response = _client(service).post(
        _BASE,
        json=_create_payload(
            channel_id=None if reason == "wrong_session" else "b" * 32
        ),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "not_found"}}


def test_get_hides_wrong_task() -> None:
    """Missing and unauthorized Task IDs remain indistinguishable."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.get.side_effect = ScheduledTaskManagementUnavailable("not_found")

    response = _client(service).get(f"{_BASE}/{'x' * 32}")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "not_found"}}


def test_create_returns_422_for_invalid_schedule() -> None:
    """Canonical schedule validation remains distinct from authority absence."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.create.side_effect = ScheduledTaskManagementUnavailable("invalid_schedule")

    response = _client(service).post(_BASE, json=_create_payload())

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_schedule"}}


def test_started_one_time_edit_returns_conflict() -> None:
    """A started one-time Task edit is exposed as a stable conflict."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.replace.side_effect = ScheduledTaskManagementUnavailable("conflict")

    response = _client(service).put(
        f"{_BASE}/{'t' * 32}",
        json=_replace_payload(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "conflict"}}


def test_current_cycle_is_nullable_without_internal_identity() -> None:
    """An idle Task returns an explicit nullable current-cycle envelope."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.get_current_cycle.return_value = None

    response = _client(service).get(f"{_BASE}/{'t' * 32}/cycle")

    assert response.status_code == 200
    assert response.json() == {"current_cycle": None}
    service.get_current_cycle.assert_awaited_once_with(
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        task_id="t" * 32,
    )


def test_get_returns_sanitized_task_projection() -> None:
    """Task reads expose canonical Session navigation and no internal state."""
    service = AsyncMock(spec=ScheduledTaskManagementService)
    service.get.return_value = _projection()

    response = _client(service).get(f"{_BASE}/{'t' * 32}")

    assert response.status_code == 200
    assert response.json()["session"] == {
        "id": "s" * 32,
        "handle": "scheduled-session",
        "title": "Scheduled work",
    }
    assert response.json()["target"] is None
