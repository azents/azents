"""Exact-scope setup contracts, strict final inputs and secret-free validation."""

from unittest.mock import create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.data import ToolkitConfigCreateRequest
from azents.api.public.toolkit.v1.github_setup import router as setup_router
from azents.api.public.toolkit.v1.github_user_creation import router as creation_router
from azents.api.public.toolkit.v1.github_user_test import _member
from azents.core.auth.deps import get_workspace_member
from azents.core.github_setup import (
    GitHubPATSetupVerification,
    GitHubSetupAppOutput,
    GitHubSetupConnectivity,
    GitHubSetupUserIdentity,
    GitHubSetupVerificationOutput,
)
from azents.core.github_user_creation import (
    GitHubUserCreationFinalSettings,
    GitHubUserCreationSubject,
)
from azents.repos.toolkit.data import ToolkitCreate
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.data import GitHubUserCreatedOutput
from azents.services.github_user_oauth.setup import GitHubSetupService
from azents.services.toolkit.data import ToolkitCreateInput


def _settings() -> dict[str, object]:
    return {
        "name": None,
        "slug": None,
        "description": None,
        "prompt": None,
        "enabled": True,
        "always_expose_tools": False,
        "toolsets": ["repos", "future_group"],
        "timeout": 30.0,
        "inject_runtime_environment": False,
        "runtime_risk_acknowledged": False,
    }


def _base(agent_id: str | None) -> str:
    return "/workspaces/ws" + (f"/agents/{agent_id}" if agent_id else "")


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_setup_verification_binds_exact_management_scope(agent_id: str | None) -> None:
    service = create_autospec(GitHubSetupService, instance=True)
    service.verify.return_value = GitHubSetupVerificationOutput(
        identity=GitHubSetupUserIdentity(
            type="user", id=42, login="actual", avatar_url=None
        ),
        installations=[],
        connectivity=GitHubSetupConnectivity(status="ready", message=None),
    )
    app = FastAPI()
    app.include_router(setup_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubSetupService] = lambda: service
    body = {
        "github_auth_type": "pat",
        "token": "private-token-sentinel",
        "transport": {"toolsets": ["repos"], "timeout": 30.0},
    }
    with TestClient(app) as client:
        response = client.post(
            _base(agent_id) + "/github/setup-verification", json=body
        )
    assert response.status_code == 200
    assert response.json()["identity"]["login"] == "actual"
    assert "private-token-sentinel" not in response.text
    service.verify.assert_awaited_once_with(
        GitHubUserCreationSubject("manager", "auth-session", "workspace", agent_id),
        GitHubPATSetupVerification.model_validate(body),
    )


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
@pytest.mark.parametrize(
    "body",
    [
        {"github_auth_type": "pat", "token": ["private-token-sentinel"]},
        {
            "github_auth_type": "github_app_platform",
            "installation_ids": ["1"],
            "private_key": "private-key-sentinel",
            "transport": {"toolsets": [], "timeout": 30.0},
        },
        {
            "github_auth_type": "github_app",
            "app_id": True,
            "private_key": "private-key-sentinel",
            "installation_ids": ["1"],
            "transport": {"toolsets": [], "timeout": 30.0},
        },
        {
            "github_auth_type": "pat",
            "token": "private-token-sentinel",
            "transport": {
                "toolsets": [],
                "timeout": 30.0,
                "server_url": "private-url-sentinel",
            },
        },
    ],
)
def test_verification_validation_never_echoes_secrets(
    agent_id: str | None, body: dict[str, object]
) -> None:
    service = create_autospec(GitHubSetupService, instance=True)
    app = FastAPI()
    app.include_router(setup_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubSetupService] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            _base(agent_id) + "/github/setup-verification", json=body
        )
    assert response.status_code == 422
    assert "sentinel" not in response.text
    assert "input" not in response.text
    service.verify.assert_not_awaited()


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_confirm_requires_complete_final_settings(agent_id: str | None) -> None:
    service = create_autospec(GitHubUserCreationService, instance=True)
    service.confirm.return_value = GitHubUserCreatedOutput(toolkit_id="created")
    app = FastAPI()
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserCreationService] = lambda: service
    path = _base(agent_id) + "/github-user-creations/confirm"
    with TestClient(app) as client:
        for body in [
            {"attempt_id": "attempt"},
            {"attempt_id": "attempt", "settings": {}},
        ]:
            assert client.post(path, json=body).status_code == 422
        service.confirm.assert_not_awaited()
        response = client.post(
            path, json={"attempt_id": "attempt", "settings": _settings()}
        )
    assert response.status_code == 200
    service.confirm.assert_awaited_once_with(
        GitHubUserCreationSubject("manager", "auth-session", "workspace", agent_id),
        "attempt",
        GitHubUserCreationFinalSettings.model_validate(_settings()),
    )


@pytest.mark.parametrize(
    "field",
    [
        "github_auth_type",
        "auth_type",
        "toolkit_type",
        "workspace_id",
        "owner_agent_id",
        "app_id",
        "source",
        "credentials",
        "client_id",
        "callback_url",
        "server_url",
    ],
)
def test_final_settings_reject_authentication_and_ownership_injection(
    field: str,
) -> None:
    service = create_autospec(GitHubUserCreationService, instance=True)
    app = FastAPI()
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserCreationService] = lambda: service
    body = {
        "attempt_id": "attempt",
        "settings": {**_settings(), field: "private-sentinel"},
    }
    with TestClient(app) as client:
        response = client.post(
            "/workspaces/ws/github-user-creations/confirm", json=body
        )
    assert response.status_code == 422
    assert "private-sentinel" not in response.text
    service.confirm.assert_not_awaited()


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_runtime_on_requires_explicit_acknowledgment(agent_id: str | None) -> None:
    service = create_autospec(GitHubUserCreationService, instance=True)
    app = FastAPI()
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserCreationService] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            _base(agent_id) + "/github-user-creations/confirm",
            json={
                "attempt_id": "attempt",
                "settings": {**_settings(), "inject_runtime_environment": True},
            },
        )
    assert response.status_code == 422
    service.confirm.assert_not_awaited()


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_metadata_routes_bind_scope_and_exact_candidate(agent_id: str | None) -> None:
    setup = create_autospec(GitHubSetupService, instance=True)
    creation = create_autospec(GitHubUserCreationService, instance=True)
    setup.app.return_value = GitHubSetupAppOutput(app=None)
    creation.app.return_value = GitHubSetupAppOutput(app=None)
    app = FastAPI()
    app.include_router(setup_router)
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubSetupService] = lambda: setup
    app.dependency_overrides[GitHubUserCreationService] = lambda: creation
    with TestClient(app) as client:
        assert client.get(_base(agent_id) + "/github/setup-app").status_code == 200
        assert (
            client.get(
                _base(agent_id) + "/github-user-creations/exact-attempt/app"
            ).status_code
            == 200
        )
    subject = GitHubUserCreationSubject(
        "manager", "auth-session", "workspace", agent_id
    )
    setup.app.assert_awaited_once_with(subject)
    creation.app.assert_awaited_once_with(subject, "exact-attempt")


@pytest.mark.parametrize("missing", list(_settings()))
def test_every_final_setting_is_required_even_when_nullable(missing: str) -> None:
    service = create_autospec(GitHubUserCreationService, instance=True)
    app = FastAPI()
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserCreationService] = lambda: service
    settings = _settings()
    del settings[missing]
    with TestClient(app) as client:
        response = client.post(
            "/workspaces/ws/github-user-creations/confirm",
            json={"attempt_id": "attempt", "settings": settings},
        )
    assert response.status_code == 422
    service.confirm.assert_not_awaited()


def test_creation_credential_models_exclude_secrets_from_representations() -> None:
    request = ToolkitConfigCreateRequest(
        toolkit_type="github",
        config={"github_auth_type": "github_app_user"},
        credentials={"client_secret": "private-secret-sentinel"},
    )
    service_input = ToolkitCreateInput(workspace_id="workspace", **request.model_dump())
    desired = ToolkitCreate(
        workspace_id="workspace",
        owner_agent_id=None,
        toolkit_type="github",
        name="GitHub",
        slug="github",
        config={"github_auth_type": "github_app_user"},
        credentials="private-secret-sentinel",
        always_expose_tools=False,
    )
    for model in [request, service_input, desired]:
        assert "private-secret-sentinel" not in repr(model)
