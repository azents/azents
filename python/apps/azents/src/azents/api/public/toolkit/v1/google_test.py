"""Real HTTP routing with safe credential validation and exact ownership context."""

import datetime
from unittest.mock import create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.github_user_test import _member
from azents.api.public.toolkit.v1.google import router
from azents.api.public.toolkit.v1.personal_google import router as personal_router
from azents.core.auth.deps import CurrentUser, get_current_user, get_workspace_member
from azents.core.google_oauth import (
    GoogleOAuthError,
    GooglePersonalSubject,
    GoogleSubject,
)
from azents.core.google_workspace_policy import drive_access
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.services.google_oauth.data import (
    GoogleConnectionOutput,
    GoogleConnectOutput,
    GoogleServicesUpdateInput,
)
from azents.services.google_oauth.service import GoogleOAuthService
from azents.services.google_oauth.workspace_projection import service_accesses


def _app(service: GoogleOAuthService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(personal_router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="manager", session_id="auth-session"
    )
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GoogleOAuthService] = lambda: service
    return app


def test_personal_google_connect_has_workspace_scoped_user_owner() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.connect.return_value = GoogleConnectOutput(
        attempt_id="attempt",
        authorization_url="https://accounts.google.com/authorize",
        expires_at=datetime.datetime.now(datetime.UTC),
    )
    with TestClient(_app(service)) as client:
        response = client.post(
            "/workspaces/ws/personal/google/connect",
            json={
                "services": ["calendar"],
                "oauth_request_scopes": [
                    "https://www.googleapis.com/auth/calendar.events.readonly"
                ],
                "timeout": 30.0,
            },
        )
    assert response.status_code == 200
    service.connect.assert_awaited_once()
    subject = service.connect.call_args.args[0]
    assert subject == GooglePersonalSubject(
        "manager",
        "auth-session",
        UserToolkitOwner(
            kind=ToolkitOwnerKind.USER, user_id="manager", workspace_id="workspace"
        ),
    )
    assert subject.workspace_id == "workspace" and subject.agent_id is None
    assert service.connect.call_args.kwargs == {"target_toolkit_id": None}
    service.confirm.assert_not_awaited()


def test_personal_google_callback_validation_remains_credential_safe() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    with TestClient(_app(service)) as client:
        response = client.post(
            "/workspaces/ws/personal/google/exchange",
            json={"code": "PERSONAL-CODE-SECRET", "state": ["PERSONAL-STATE-SECRET"]},
        )
    assert response.status_code == 422
    assert "PERSONAL-CODE-SECRET" not in response.text
    assert "PERSONAL-STATE-SECRET" not in response.text
    service.exchange.assert_not_awaited()


@pytest.mark.parametrize("agent_id", [None, "exact-agent"])
def test_routes_capture_current_login_and_do_not_create_toolkit(
    agent_id: str | None,
) -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.connect.return_value = GoogleConnectOutput(
        attempt_id="attempt",
        authorization_url="https://accounts.google.com/authorize",
        expires_at=datetime.datetime.now(datetime.UTC),
    )
    base = "/workspaces/ws" + ("" if agent_id is None else f"/agents/{agent_id}")
    with TestClient(_app(service)) as client:
        response = client.post(
            base + "/google/connect",
            json={
                "services": ["calendar"],
                "oauth_request_scopes": [
                    "https://www.googleapis.com/auth/calendar.events.readonly"
                ],
                "timeout": 30.0,
            },
        )
    assert response.status_code == 200
    assert service.connect.call_args.args[0] == GoogleSubject(
        "manager",
        "auth-session",
        "workspace",
        agent_id,
    )
    assert service.connect.call_args.kwargs["target_toolkit_id"] is None
    service.confirm.assert_not_awaited()


def test_exchange_validation_contains_no_input_codes_or_state() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    with TestClient(_app(service)) as client:
        response = client.post(
            "/workspaces/ws/google/exchange",
            json={
                "code": "CODE-SECRET",
                "state": ["STATE-SECRET"],
            },
        )
    assert response.status_code == 422
    assert "CODE-SECRET" not in response.text
    assert "STATE-SECRET" not in response.text
    service.exchange.assert_not_awaited()


def test_context_error_is_not_an_internal_server_error() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.connect.side_effect = GoogleOAuthError(
        "not_found", "Google setup context not found."
    )
    with TestClient(_app(service)) as client:
        response = client.post(
            "/workspaces/ws/agents/other/google/connect",
            json={
                "services": ["calendar"],
                "oauth_request_scopes": [
                    "https://www.googleapis.com/auth/calendar.events.readonly"
                ],
                "timeout": 30.0,
            },
        )
    assert response.status_code == 404


def test_shared_query_cannot_substitute_agent_path_authority() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.disconnect.return_value = None
    with TestClient(_app(service)) as client:
        response = client.delete(
            "/workspaces/ws/toolkit-configs/toolkit/google/connection?agent_id=other"
        )
    assert response.status_code == 204
    service.disconnect.assert_awaited_once_with(
        GoogleSubject("manager", "auth-session", "workspace", None),
        "toolkit",
    )


@pytest.mark.parametrize("owner", ["shared", "agent", "personal"])
def test_service_save_routes_preserve_exact_manager_context(owner: str) -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.update_services.return_value = GoogleConnectionOutput(
        toolkit_id="toolkit",
        revision=4,
        connection_id=None,
        status="not_connected",
        identity=None,
        services=(),
        oauth_request_scopes=("email", "openid"),
        granted_scopes=None,
        timeout=30.0,
        accesses=service_accesses((), None),
        drive_access=drive_access((), None),
        renewable=False,
        service_access_verified=False,
    )
    if owner == "personal":
        path = "/workspaces/ws/personal-toolkit-configs/toolkit/google/services"
        expected = GooglePersonalSubject(
            "manager",
            "auth-session",
            UserToolkitOwner(
                kind=ToolkitOwnerKind.USER, user_id="manager", workspace_id="workspace"
            ),
        )
    elif owner == "agent":
        path = (
            "/workspaces/ws/agents/exact-agent/toolkit-configs/toolkit/google/services"
        )
        expected = GoogleSubject("manager", "auth-session", "workspace", "exact-agent")
    else:
        path = "/workspaces/ws/toolkit-configs/toolkit/google/services"
        expected = GoogleSubject("manager", "auth-session", "workspace", None)
    with TestClient(_app(service)) as client:
        response = client.patch(path, json={"services": [], "expected_revision": 3})
    assert response.status_code == 200 and response.json()["revision"] == 4
    service.update_services.assert_awaited_once_with(
        expected, "toolkit", GoogleServicesUpdateInput(services=(), expected_revision=3)
    )


@pytest.mark.parametrize(
    "body",
    [
        {"services": [], "expected_revision": True},
        {"services": ["PRIVATE-UNKNOWN-SERVICE"], "expected_revision": 3},
        {"services": [], "expected_revision": 3, "grant": True},
    ],
)
def test_service_save_validation_is_strict_and_redacted(
    body: dict[str, object],
) -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    with TestClient(_app(service)) as client:
        response = client.patch(
            "/workspaces/ws/toolkit-configs/toolkit/google/services", json=body
        )
    assert response.status_code == 422
    assert "PRIVATE-UNKNOWN-SERVICE" not in response.text
    service.update_services.assert_not_awaited()


def test_stale_service_save_is_an_explicit_conflict() -> None:
    service = create_autospec(GoogleOAuthService, instance=True)
    service.update_services.side_effect = GoogleOAuthError(
        "stale", "Reload current settings."
    )
    with TestClient(_app(service)) as client:
        response = client.patch(
            "/workspaces/ws/toolkit-configs/toolkit/google/services",
            json={"services": [], "expected_revision": 3},
        )
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale"
