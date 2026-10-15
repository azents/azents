"""Workspace metadata, exact Agent scope and secret-safe HTTP contracts."""

from unittest.mock import create_autospec

from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.agent_runtime.v1.environment_test import _member
from azents.api.public.workspace.v1.environment import router
from azents.core.auth.deps import get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import RuntimeEnvironmentAccessError
from azents.core.workspace_environment import (
    AgentWorkspaceEnvironmentSettings,
    WorkspaceEnvironmentEntry,
    WorkspaceEnvironmentSettings,
)
from azents.services.workspace_environment import WorkspaceEnvironmentService


def test_redacted_workspace_values_and_exact_opt_in_scope() -> None:
    service = create_autospec(WorkspaceEnvironmentService, instance=True)
    service.get.return_value = WorkspaceEnvironmentSettings(
        entries=[
            WorkspaceEnvironmentEntry(id="variable", name="TOKEN", has_value=True)
        ],
        can_manage=True,
    )
    service.agent_settings.return_value = Success(
        AgentWorkspaceEnvironmentSettings(
            entries=[], selected_ids=[], overridden_names=[], can_manage=True
        )
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[WorkspaceEnvironmentService] = lambda: service
    with TestClient(app) as client:
        response = client.get("/workspaces/ws/environment")
        assert response.status_code == 200
        assert response.json()["entries"] == [
            {"id": "variable", "name": "TOKEN", "has_value": True}
        ]
        response = client.put(
            "/workspaces/ws/agents/exact/environment-selection",
            json={"selected_ids": ["variable"]},
        )
        assert response.status_code == 200
    service.get.assert_awaited_once_with("workspace", role=WorkspaceUserRole.OWNER)
    service.agent_settings.assert_awaited_once_with(
        "exact",
        workspace_id="workspace",
        workspace_user_id="member",
        role=WorkspaceUserRole.OWNER,
        selected_ids=["variable"],
    )


def test_secret_inputs_are_not_echoed_and_write_denial_is_not_success() -> None:
    service = create_autospec(WorkspaceEnvironmentService, instance=True)
    service.replace.return_value = Failure(RuntimeEnvironmentAccessError.DENIED)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[WorkspaceEnvironmentService] = lambda: service
    with TestClient(app) as client:
        response = client.put(
            "/workspaces/ws/environment",
            json={
                "entries": [
                    {
                        "id": None,
                        "name": "TOKEN",
                        "value": {
                            "type": "replace",
                            "value": {"sensitive": "not-to-echo"},
                        },
                    }
                ]
            },
        )
        assert response.status_code == 422 and "not-to-echo" not in response.text
        service.replace.assert_not_awaited()
        response = client.put("/workspaces/ws/environment", json={"entries": []})
        assert response.status_code == 403
