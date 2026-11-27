"""Agent Vault HTTP redaction and authenticated scope tests."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from azents.api.public.agent.v1.vault import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.services.agent_vault import (
    AgentVaultEntryMetadata,
    AgentVaultService,
    AgentVaultSettings,
    VaultSettingsDenial,
    VaultSettingsError,
)

_PATH = "/workspaces/workspace/agents/agent/vault/entries"
_MARKER = "synthetic-secret-do-not-return"


@pytest.fixture
def service() -> AsyncMock:
    return AsyncMock(spec=AgentVaultService)


@pytest.fixture
def client(service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        "user", "workspace-id", "membership", WorkspaceUserRole.OWNER, set(), "login"
    )
    app.dependency_overrides[AgentVaultService] = lambda: service
    return TestClient(app)


def test_settings_only_expose_metadata(client: TestClient, service: AsyncMock) -> None:
    service.list_entries.return_value = AgentVaultSettings(
        entries=[AgentVaultEntryMetadata(name="TOKEN", contributor_label="Owner")]
    )
    response = client.get(_PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "entries": [{"name": "TOKEN", "contributor_label": "Owner"}]
    }
    service.list_entries.assert_awaited_once_with(
        "agent", workspace_id="workspace-id", user_id="user"
    )


def test_secret_write_is_empty_and_malformed_body_is_redacted(
    client: TestClient, service: AsyncMock
) -> None:
    bad = client.post(_PATH, json={"name": "TOKEN", "value": {"secret": _MARKER}})
    assert bad.status_code == 422
    assert _MARKER not in bad.text
    assert bad.json() == {"detail": "Invalid Vault request."}
    service.create_entry.assert_not_awaited()
    success = client.post(_PATH, json={"name": "TOKEN", "value": _MARKER})
    assert success.status_code == 204
    assert success.content == b""
    assert success.headers["cache-control"] == "no-store"
    service.create_entry.assert_awaited_once_with(
        "agent",
        "TOKEN",
        SecretStr(_MARKER),
        workspace_id="workspace-id",
        user_id="user",
    )


def test_conflict_and_denial_never_echo_input(
    client: TestClient, service: AsyncMock
) -> None:
    service.replace_entry.side_effect = VaultSettingsError(
        VaultSettingsDenial.NOT_FOUND
    )
    result = client.put(_PATH, json={"name": "TOKEN", "value": _MARKER})
    assert result.status_code == 404
    assert _MARKER not in result.text
    service.create_entry.side_effect = VaultSettingsError(VaultSettingsDenial.CONFLICT)
    result = client.post(_PATH, json={"name": "TOKEN", "value": _MARKER})
    assert result.status_code == 409
    assert _MARKER not in result.text
    result = client.delete(_PATH, params={"name": "TOKEN"})
    assert result.status_code == 204
    service.delete_entry.assert_awaited_once_with(
        "agent", "TOKEN", workspace_id="workspace-id", user_id="user"
    )
