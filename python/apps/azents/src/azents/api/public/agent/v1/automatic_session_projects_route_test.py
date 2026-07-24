"""Automatic Session Project policy Public API route tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.repos.agent_automatic_project.data import AgentAutomaticProjectPolicy
from azents.services.agent.data import NotAdmin
from azents.services.agent_automatic_project import AgentAutomaticProjectService
from azents.services.agent_automatic_project.data import (
    AutomaticSessionProjectsRevisionConflict,
    AutomaticSessionProjectsRuntimeUnavailable,
)
from azents.services.session_workspace_project import InvalidProjectPath


def _policy() -> AgentAutomaticProjectPolicy:
    """Build one policy result for route tests."""
    now = datetime.now(UTC)
    return AgentAutomaticProjectPolicy(
        agent_id="agent-1",
        revision=3,
        project_paths=("/workspace/agent/payments", "/workspace/agent/orders"),
        updated_by_workspace_user_id="workspace-user-1",
        created_at=now,
        updated_at=now,
    )


def _app(service: AsyncMock) -> FastAPI:
    """Create a public API app with policy service and member overrides."""
    app = create_dummy_public_app()
    app.dependency_overrides[AgentAutomaticProjectService] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=set(),
        session_id="auth-session-1",
    )
    return app


def _client(service: AsyncMock) -> TestClient:
    """Create a public API client with policy service and member overrides."""
    return TestClient(_app(service))


def test_get_returns_ordered_policy_projection() -> None:
    """GET maps the service policy snapshot to the documented response shape."""
    service = AsyncMock(spec=AgentAutomaticProjectService)
    service.get_policy.return_value = Success(_policy())

    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/automatic-session-projects"
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 3
    assert response.json()["project_paths"] == [
        "/workspace/agent/payments",
        "/workspace/agent/orders",
    ]
    service.get_policy.assert_awaited_once_with(
        agent_id="agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
    )


def test_put_returns_structured_revision_conflict() -> None:
    """Revision conflicts expose a stable code rather than message parsing."""
    service = AsyncMock(spec=AgentAutomaticProjectService)
    service.replace_policy.return_value = Failure(
        AutomaticSessionProjectsRevisionConflict(expected_revision=2)
    )

    response = _client(service).put(
        "/agent/v1/workspaces/workspace/agents/agent-1/automatic-session-projects",
        json={
            "expected_revision": 2,
            "project_paths": ["/workspace/agent/payments"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "automatic_session_projects_revision_conflict"
    )


def test_put_returns_structured_runtime_unavailable_conflict() -> None:
    """Runtime availability conflicts expose the stable retry-required code."""
    service = AsyncMock(spec=AgentAutomaticProjectService)
    service.replace_policy.return_value = Failure(
        AutomaticSessionProjectsRuntimeUnavailable(
            message="Start the Agent runtime and retry."
        )
    )

    response = _client(service).put(
        "/agent/v1/workspaces/workspace/agents/agent-1/automatic-session-projects",
        json={
            "expected_revision": 2,
            "project_paths": ["/workspace/agent/payments"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "automatic_session_projects_runtime_unavailable",
        "message": "Start the Agent runtime and retry.",
    }


def test_put_maps_invalid_path_and_non_admin_errors() -> None:
    """Path validation stays 400 and explicit AgentAdmin denial stays 403."""
    invalid_service = AsyncMock(spec=AgentAutomaticProjectService)
    invalid_service.replace_policy.return_value = Failure(
        InvalidProjectPath(
            path="/tmp/project",
            reason="Project path must be under Agent Workspace root",
        )
    )
    invalid_response = _client(invalid_service).put(
        "/agent/v1/workspaces/workspace/agents/agent-1/automatic-session-projects",
        json={"expected_revision": 2, "project_paths": ["/tmp/project"]},
    )

    denied_service = AsyncMock(spec=AgentAutomaticProjectService)
    denied_service.replace_policy.return_value = Failure(NotAdmin(agent_id="agent-1"))
    denied_response = _client(denied_service).put(
        "/agent/v1/workspaces/workspace/agents/agent-1/automatic-session-projects",
        json={"expected_revision": 2, "project_paths": []},
    )

    assert invalid_response.status_code == 400
    assert invalid_response.json() == {
        "detail": {
            "message": "Project path must be under Agent Workspace root",
            "path": "/tmp/project",
        }
    }
    assert denied_response.status_code == 403
    assert denied_response.json() == {"detail": "Not allowed to manage this agent."}


def test_routes_publish_structured_error_response_contracts() -> None:
    """OpenAPI exposes path errors and both stable conflict discriminators."""
    service = AsyncMock(spec=AgentAutomaticProjectService)
    openapi = _app(service).openapi()
    route = openapi["paths"][
        "/agent/v1/workspaces/{handle}/agents/{agent_id}/automatic-session-projects"
    ]

    assert set(route["get"]["responses"]) == {"200", "403", "404", "422"}
    assert set(route["put"]["responses"]) == {
        "200",
        "400",
        "403",
        "404",
        "409",
        "422",
    }
    assert route["put"]["responses"]["400"]["content"]["application/json"]["schema"][
        "$ref"
    ] == ("#/components/schemas/AutomaticSessionProjectsInvalidPathErrorResponse")
    assert (
        route["put"]["responses"]["409"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/AutomaticSessionProjectsConflictErrorResponse"
    )

    conflict_schema = openapi["components"]["schemas"][
        "AutomaticSessionProjectsConflictErrorResponse"
    ]
    conflict_detail = conflict_schema["properties"]["detail"]
    assert conflict_detail["discriminator"]["propertyName"] == "code"
    assert set(conflict_detail["discriminator"]["mapping"]) == {
        "automatic_session_projects_revision_conflict",
        "automatic_session_projects_runtime_unavailable",
    }
