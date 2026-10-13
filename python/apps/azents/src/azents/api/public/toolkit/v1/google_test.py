"""Real HTTP routing with safe credential validation and exact ownership context."""

import datetime
from unittest.mock import create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.github_user_test import _member
from azents.api.public.toolkit.v1.google import router
from azents.core.auth.deps import get_workspace_member
from azents.core.google_oauth import GoogleOAuthError, GoogleSubject
from azents.services.google_oauth.data import GoogleConnectOutput
from azents.services.google_oauth.service import GoogleOAuthService


def _app(service: GoogleOAuthService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[GoogleOAuthService] = lambda: service
    return app


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
                "tasks": ["calendar_read"],
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
                "tasks": ["calendar_read"],
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
