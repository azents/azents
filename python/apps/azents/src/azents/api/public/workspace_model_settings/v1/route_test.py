"""HTTP boundary preserves Workspace default patch presence and clear errors."""

import pytest
from azcommon.result import Failure, Result, Success
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from azents.api.public.workspace_model_settings.v1 import mount
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.services.workspace_model_settings import WorkspaceModelSettingsService
from azents.services.workspace_model_settings.data import (
    DefaultModelCannotBeCleared,
    InvalidSelectableModelOptions,
    ModelSelectionNotFound,
    WorkspaceModelSettingsOutput,
    WorkspaceModelSettingsUpdateInput,
)
from azents.utils.fastapi.route import as_route_mounter


class _SettingsService(WorkspaceModelSettingsService):
    """Observe typed route payloads and return an explicit bounded outcome."""

    def __init__(self, reject_clear: bool) -> None:
        self.reject_clear = reject_clear
        self.calls: list[WorkspaceModelSettingsUpdateInput] = []

    async def update(
        self, workspace_id: str, update: WorkspaceModelSettingsUpdateInput
    ) -> Result[
        WorkspaceModelSettingsOutput,
        ModelSelectionNotFound
        | InvalidSelectableModelOptions
        | DefaultModelCannotBeCleared,
    ]:
        assert workspace_id == "workspace-1"
        self.calls.append(update)
        if self.reject_clear:
            return Failure(DefaultModelCannotBeCleared(workspace_id))
        return Success(WorkspaceModelSettingsOutput())


def _client(service: _SettingsService, allowed: bool) -> TestClient:
    app = FastAPI()
    mount(as_route_mounter(app))

    def member() -> WorkspaceMember:
        if not allowed:
            raise HTTPException(
                status_code=403, detail="Not a member of this workspace."
            )
        return WorkspaceMember(
            user_id="user-1",
            workspace_id="workspace-1",
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MEMBER,
            permissions=set(),
            session_id="session-1",
        )

    app.dependency_overrides[get_workspace_member] = member
    app.dependency_overrides[WorkspaceModelSettingsService] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize("lightweight", [False, True])
def test_explicit_label_clear_maps_to_existing_400(lightweight: bool) -> None:
    """Null remains present when the service rejects a configured default clear."""
    service = _SettingsService(reject_clear=True)
    field = (
        "default_lightweight_model_label" if lightweight else "default_main_model_label"
    )
    with _client(service, allowed=True) as client:
        response = client.put(
            "/workspace-model-settings/v1/workspaces/workspace", json={field: None}
        )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Workspace default model cannot be cleared once set."
    }
    if lightweight:
        assert service.calls == [{"default_lightweight_model_label": None}]
    else:
        assert service.calls == [{"default_main_model_label": None}]


def test_empty_partial_payload_does_not_add_null_keys() -> None:
    """The HTTP decoder preserves omission instead of filling nullable defaults."""
    service = _SettingsService(reject_clear=False)
    with _client(service, allowed=True) as client:
        response = client.put(
            "/workspace-model-settings/v1/workspaces/workspace", json={}
        )
    assert response.status_code == 200
    assert service.calls == [{}]


def test_workspace_permission_failure_precedes_mutation() -> None:
    """The existing membership dependency retains its 403/no-update contract."""
    service = _SettingsService(reject_clear=True)
    with _client(service, allowed=False) as client:
        response = client.put(
            "/workspace-model-settings/v1/workspaces/workspace",
            json={"default_main_model_label": None},
        )
    assert response.status_code == 403
    assert service.calls == []


def test_unknown_fields_retain_422_without_mutation() -> None:
    """Existing closed wire validation is unchanged by label-clear semantics."""
    service = _SettingsService(reject_clear=False)
    with _client(service, allowed=True) as client:
        response = client.put(
            "/workspace-model-settings/v1/workspaces/workspace", json={"unknown": None}
        )
    assert response.status_code == 422
    assert service.calls == []
