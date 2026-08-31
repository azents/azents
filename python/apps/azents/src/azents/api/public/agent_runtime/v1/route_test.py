"""Agent Runtime v1 public route tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from azents_runtime_control.system_metrics import (
    RunnerSystemMetricAvailability,
    RunnerSystemMetricsScope,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.agent_runtime.v1 import mount
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import AgentRuntimeCapability, WorkspaceUserRole
from azents.services.agent_runtime.lifecycle_data import (
    AgentNotFound,
    AgentRuntimePublicActions,
    AgentRuntimeReadOutput,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.agent_runtime_system_metrics.data import (
    AgentRuntimeSystemMetricsOutput,
    RuntimeSystemMetricCurrent,
    RuntimeSystemMetricObservation,
    RuntimeSystemMetricsSample,
    RuntimeSystemMetricsSummary,
    RuntimeSystemMetricState,
)
from azents.services.agent_runtime_system_metrics.service import (
    AgentRuntimeSystemMetricsService,
    get_agent_runtime_system_metrics_service,
)
from azents.utils.fastapi.route import as_route_mounter


def _make_app() -> FastAPI:
    """Create a test app with Agent Runtime public endpoints mounted."""
    app = FastAPI()
    mount(as_route_mounter(app))
    return app


class TestRouteMount:
    """Test Agent Runtime v1 mount paths."""

    def test_mounts_agent_scoped_runtime_routes(self) -> None:
        """Mount lifecycle routes based on Agent ID."""
        app = _make_app()

        paths = set(app.openapi()["paths"])

        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime" in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/start"
            in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/reset"
            in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/add"
            in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/remove"
            in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/"
            "system-metrics" in paths
        )


def test_metrics_route_returns_privacy_safe_agent_authorized_projection() -> None:
    """The dedicated route exposes only normalized presentation fields."""
    metrics_service = AsyncMock(spec=AgentRuntimeSystemMetricsService)
    metrics_service.get.return_value = Success(_metrics_output())
    client = _client(metrics_service=metrics_service)

    response = client.get(
        "/agent-runtime/v1/workspaces/workspace/agents/agent-1/runtime/system-metrics"
    )

    assert response.status_code == 200
    assert response.json() == {
        "summary": "partial",
        "scope": "container",
        "cpu": {
            "state": "fresh",
            "measured_at": "2026-08-24T12:00:00Z",
            "used": 250,
            "total": 1000,
            "percentage": 25.0,
        },
        "memory": {
            "state": "unavailable",
            "measured_at": "2026-08-24T12:00:00Z",
            "used": None,
            "total": None,
            "percentage": None,
        },
        "disk": {
            "state": "unsupported",
            "measured_at": "2026-08-24T12:00:00Z",
            "used": None,
            "total": None,
            "percentage": None,
        },
        "samples": [
            {
                "measured_at": "2026-08-24T12:00:00Z",
                "scope": "container",
                "cpu": {
                    "availability": "available",
                    "used": 250,
                    "total": 1000,
                },
                "memory": {
                    "availability": "unavailable",
                    "used": None,
                    "total": None,
                },
                "disk": {
                    "availability": "unsupported",
                    "used": None,
                    "total": None,
                },
            }
        ],
    }
    metrics_service.get.assert_awaited_once_with(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
    )
    serialized = response.text
    for forbidden in (
        "runtime-1",
        "runner-1",
        "provider-1",
        "connection-1",
        "/workspace",
        "generation",
        "hostname",
        "device",
        "process",
    ):
        assert forbidden not in serialized


def test_metrics_route_preserves_existing_agent_not_found_boundary() -> None:
    """Unauthorized or cross-Workspace reads retain the stable 404 response."""
    metrics_service = AsyncMock(spec=AgentRuntimeSystemMetricsService)
    metrics_service.get.return_value = Failure(AgentNotFound(agent_id="agent-1"))

    response = _client(metrics_service=metrics_service).get(
        "/agent-runtime/v1/workspaces/workspace/agents/agent-1/runtime/system-metrics"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Agent was not found."}


def test_metrics_failure_does_not_change_lifecycle_route() -> None:
    """A metrics-only failure leaves the existing Runtime GET successful."""
    metrics_service = AsyncMock(spec=AgentRuntimeSystemMetricsService)
    metrics_service.get.side_effect = RuntimeError("metrics store unavailable")
    runtime_service = AsyncMock(spec=AgentRuntimeService)
    runtime_service.get.return_value = Success(_runtime_free_output())
    client = _client(
        metrics_service=metrics_service,
        runtime_service=runtime_service,
        raise_server_exceptions=False,
    )

    metrics_response = client.get(
        "/agent-runtime/v1/workspaces/workspace/agents/agent-1/runtime/system-metrics"
    )
    lifecycle_response = client.get(
        "/agent-runtime/v1/workspaces/workspace/agents/agent-1/runtime"
    )

    assert metrics_response.status_code == 500
    assert lifecycle_response.status_code == 200
    assert lifecycle_response.json()["capability"] == "none"
    assert lifecycle_response.json()["runtime"] is None


def _client(
    *,
    metrics_service: AsyncMock,
    runtime_service: AsyncMock | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = _make_app()
    app.dependency_overrides[get_agent_runtime_system_metrics_service] = lambda: (
        metrics_service
    )
    if runtime_service is not None:
        app.dependency_overrides[AgentRuntimeService] = lambda: runtime_service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
        session_id="auth-session-1",
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _metrics_output() -> AgentRuntimeSystemMetricsOutput:
    measured_at = datetime(2026, 8, 24, 12, tzinfo=UTC)
    available = RuntimeSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.AVAILABLE,
        used=250,
        total=1000,
    )
    unavailable = RuntimeSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNAVAILABLE,
        used=None,
        total=None,
    )
    unsupported = RuntimeSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNSUPPORTED,
        used=None,
        total=None,
    )
    return AgentRuntimeSystemMetricsOutput(
        summary=RuntimeSystemMetricsSummary.PARTIAL,
        scope=RunnerSystemMetricsScope.CONTAINER,
        cpu=RuntimeSystemMetricCurrent(
            state=RuntimeSystemMetricState.FRESH,
            measured_at=measured_at,
            used=250,
            total=1000,
            percentage=25.0,
        ),
        memory=RuntimeSystemMetricCurrent(
            state=RuntimeSystemMetricState.UNAVAILABLE,
            measured_at=measured_at,
            used=None,
            total=None,
            percentage=None,
        ),
        disk=RuntimeSystemMetricCurrent(
            state=RuntimeSystemMetricState.UNSUPPORTED,
            measured_at=measured_at,
            used=None,
            total=None,
            percentage=None,
        ),
        samples=[
            RuntimeSystemMetricsSample(
                measured_at=measured_at,
                scope=RunnerSystemMetricsScope.CONTAINER,
                cpu=available,
                memory=unavailable,
                disk=unsupported,
            )
        ],
    )


def _runtime_free_output() -> AgentRuntimeReadOutput:
    return AgentRuntimeReadOutput(
        capability=AgentRuntimeCapability.NONE,
        capability_version=1,
        runtime_profile_id=None,
        runtime_profile_selection_version=1,
        runtime_profile_status="not_applicable",
        runtime_profile_available=False,
        runtime_profile_availability_reason_code=None,
        removal_impact=None,
        removal=None,
        runtime=None,
        lifecycle=None,
        configuration=None,
        actions=AgentRuntimePublicActions(
            add=False,
            remove=False,
            start=False,
            stop=False,
            restart=False,
            reset=False,
            observe=False,
            use_runner=False,
        ),
    )
