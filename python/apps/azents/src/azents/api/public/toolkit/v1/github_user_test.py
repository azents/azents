"""HTTP ownership symmetry and strict cleanup failure contracts."""

from unittest.mock import create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.github_user import (
    GitHubUserExchangeRequest,
    router,
)
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_oauth import (
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRequester,
)
from azents.services.github_user_oauth.data import (
    GitHubUserConnectOutput,
    GitHubUserStatusOutput,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="manager",
        session_id="auth-session",
        workspace_id="workspace",
        workspace_user_id="membership",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_route_binds_current_auth_session_and_exact_ownership(
    agent_id: str | None,
) -> None:
    service = create_autospec(GitHubUserOAuthService, instance=True)
    service.connect.return_value = GitHubUserConnectOutput(
        attempt_id="attempt",
        authorization_url="https://github.com/login/oauth/authorize?state=opaque",
        install_url="https://github.com/apps/selected/installations/new",
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserOAuthService] = lambda: service
    base = "/workspaces/ws"
    if agent_id is not None:
        base += f"/agents/{agent_id}"
    with TestClient(app) as client:
        response = client.post(base + "/toolkit-configs/toolkit/github-user/connect")
    assert response.status_code == 200
    service.connect.assert_awaited_once_with(
        GitHubUserRequester(
            user_id="manager",
            session_id="auth-session",
            workspace_id="workspace",
            agent_id=agent_id,
            toolkit_id="toolkit",
        )
    )
    assert response.json()["attempt_id"] == "attempt"


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_cleanup_failure_is_conflict_not_success(agent_id: str | None) -> None:
    service = create_autospec(GitHubUserOAuthService, instance=True)
    service.cleanup_retry.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.CLEANUP_REQUIRED,
        "GitHub token cleanup is incomplete. Retry cleanup.",
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserOAuthService] = lambda: service
    base = "/workspaces/ws"
    if agent_id is not None:
        base += f"/agents/{agent_id}"
    with TestClient(app) as client:
        response = client.post(
            base + "/toolkit-configs/toolkit/github-user/cleanup-retry"
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cleanup_required"
    assert "token" not in response.json()["detail"]


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_status_response_contains_no_private_connection_data(
    agent_id: str | None,
) -> None:
    service = create_autospec(GitHubUserOAuthService, instance=True)
    service.status.return_value = GitHubUserStatusOutput(
        connection=None, cleanup_pending=True
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserOAuthService] = lambda: service
    base = "/workspaces/ws"
    if agent_id is not None:
        base += f"/agents/{agent_id}"
    with TestClient(app) as client:
        response = client.get(base + "/toolkit-configs/toolkit/github-user/status")
    assert response.status_code == 200
    assert response.json() == {"connection": None, "cleanup_pending": True}


def test_callback_inputs_are_excluded_from_request_repr() -> None:
    request = GitHubUserExchangeRequest(code="private-code", state="private-state")
    assert "private-code" not in repr(request)
    assert "private-state" not in repr(request)


def test_routes_have_no_secret_bearing_response_fields() -> None:
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    outputs = (
        "GitHubUserConnectOutput",
        "GitHubUserCandidateSummary",
        "GitHubUserConnectionSummary",
        "GitHubUserStatusOutput",
        "GitHubSetupAvailability",
        "GitHubUserAccessPage",
    )
    for output in outputs:
        properties = schema["components"]["schemas"][output]["properties"]
        assert not {
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
            "code_verifier",
            "encrypted_token",
        }.intersection(properties)


@pytest.mark.parametrize(
    "body",
    [
        {"code": "private-code" * 400, "state": "private-state"},
        {"code": "private-code", "state": "private-state", "token": "private-token"},
        {"code": ["private-code"], "state": "private-state"},
    ],
)
def test_http_request_validation_does_not_echo_oauth_input(
    body: dict[str, object],
) -> None:
    service = create_autospec(GitHubUserOAuthService, instance=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GitHubUserOAuthService] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            "/workspaces/ws/toolkit-configs/toolkit/github-user/exchange", json=body
        )
    assert response.status_code == 422
    assert "private-code" not in response.text
    assert "private-state" not in response.text
    assert "private-token" not in response.text
    assert "input" not in response.text
    service.exchange.assert_not_awaited()
