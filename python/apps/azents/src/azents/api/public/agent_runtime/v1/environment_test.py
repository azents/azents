"""Agent Runtime environment HTTP redaction and exact scope tests."""

from unittest.mock import create_autospec

import pytest
from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.agent_runtime.v1.environment import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    RuntimeEnvironmentAccessError,
)
from azents.services.agent_runtime_environment import (
    AgentRuntimeEnvironmentService,
    RuntimeEnvironmentEntry,
    RuntimeEnvironmentSettings,
)


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="user",
        session_id="auth",
        workspace_id="workspace",
        workspace_user_id="member",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )


def test_redacted_get_and_exact_agent_replace() -> None:
    service = create_autospec(AgentRuntimeEnvironmentService, instance=True)
    settings = RuntimeEnvironmentSettings(
        entries=[RuntimeEnvironmentEntry(name="API_TOKEN", has_value=True)],
        can_manage=True,
    )
    service.get.return_value = Success(settings)
    service.replace.return_value = Success(settings)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[AgentRuntimeEnvironmentService] = lambda: service
    path = "/workspaces/ws/agents/exact-agent/runtime/environment"
    with TestClient(app) as client:
        response = client.put(
            path,
            json={
                "entries": [
                    {
                        "name": "API_TOKEN",
                        "value": {"type": "replace", "value": "secret-not-in-response"},
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert "secret-not-in-response" not in response.text
        response = client.get(path)
        assert response.json() == {
            "entries": [{"name": "API_TOKEN", "has_value": True}],
            "can_manage": True,
        }
    service.get.assert_awaited_once_with(
        "exact-agent",
        workspace_id="workspace",
        workspace_user_id="member",
        role=WorkspaceUserRole.OWNER,
    )
    assert service.replace.await_args.args == ("exact-agent",)
    assert (
        service.replace.await_args.kwargs["edits"][0].value.value.get_secret_value()
        == "secret-not-in-response"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "entries": [
                {
                    "name": "A",
                    "value": {"type": "replace", "value": {"secret": "hidden-input"}},
                }
            ]
        },
        {
            "entries": [
                {
                    "name": "A",
                    "value": {"type": "invalid-hidden-input", "value": "hidden-input"},
                }
            ]
        },
        {"entries": "hidden-input"},
    ],
)
def test_invalid_secret_input_is_not_echoed(payload: dict[str, object]) -> None:
    service = create_autospec(AgentRuntimeEnvironmentService, instance=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[AgentRuntimeEnvironmentService] = lambda: service
    with TestClient(app) as client:
        response = client.put(
            "/workspaces/ws/agents/a/runtime/environment", json=payload
        )
    assert response.status_code == 422
    assert "hidden-input" not in response.text
    service.replace.assert_not_awaited()


@pytest.mark.parametrize(
    "error, status",
    [
        (RuntimeEnvironmentAccessError.NOT_FOUND, 404),
        (RuntimeEnvironmentAccessError.DENIED, 403),
    ],
)
def test_management_errors_are_not_success(
    error: RuntimeEnvironmentAccessError, status: int
) -> None:
    service = create_autospec(AgentRuntimeEnvironmentService, instance=True)
    service.replace.return_value = Failure(error)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[AgentRuntimeEnvironmentService] = lambda: service
    with TestClient(app) as client:
        response = client.put(
            "/workspaces/ws/agents/a/runtime/environment", json={"entries": []}
        )
    assert response.status_code == status


def test_domain_validation_is_a_safe_422() -> None:
    service = create_autospec(AgentRuntimeEnvironmentService, instance=True)
    service.replace.side_effect = InvalidRuntimeEnvironment(
        "Variable values exceed the limit."
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[AgentRuntimeEnvironmentService] = lambda: service
    with TestClient(app) as client:
        response = client.put(
            "/workspaces/ws/agents/a/runtime/environment",
            json={
                "entries": [
                    {"name": "A", "value": {"type": "replace", "value": "hidden-input"}}
                ]
            },
        )
    assert response.status_code == 422
    assert "hidden-input" not in response.text
