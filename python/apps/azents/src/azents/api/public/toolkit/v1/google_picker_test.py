"""Picker bearer responses remain non-cacheable and exact-manager scoped."""

import datetime
from unittest.mock import Mock, create_autospec

import pytest
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.google_test import _app
from azents.core.google_oauth import (
    GoogleOAuthError,
    GooglePersonalSubject,
    GoogleSubject,
)
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.services.google_oauth.data import (
    GooglePickerTokenInput,
    GooglePickerTokenOutput,
)
from azents.services.google_oauth.picker import GooglePickerService
from azents.services.google_oauth.service import GoogleOAuthService


def _client(picker: Mock) -> TestClient:
    service = create_autospec(GoogleOAuthService, instance=True)
    app = _app(service)
    app.dependency_overrides[GooglePickerService] = lambda: picker
    return TestClient(app)


@pytest.mark.parametrize("owner", ["shared", "agent", "personal"])
def test_minimal_picker_response_is_manager_scoped_and_not_cached(owner: str) -> None:
    picker = create_autospec(GooglePickerService, instance=True)
    picker.issue.return_value = GooglePickerTokenOutput(
        access_token="MINIMAL-PICKER-CANARY",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        api_key="BROWSER-KEY",
        app_id="123456789",
    )
    subject: GoogleSubject | GooglePersonalSubject
    if owner == "personal":
        path = "/workspaces/ws/personal-toolkit-configs/toolkit/google/picker-token"
        subject = GooglePersonalSubject(
            "manager",
            "auth-session",
            UserToolkitOwner(
                kind=ToolkitOwnerKind.USER,
                user_id="manager",
                workspace_id="workspace",
            ),
        )
    elif owner == "agent":
        path = (
            "/workspaces/ws/agents/exact-agent/"
            "toolkit-configs/toolkit/google/picker-token"
        )
        subject = GoogleSubject("manager", "auth-session", "workspace", "exact-agent")
    else:
        path = "/workspaces/ws/toolkit-configs/toolkit/google/picker-token"
        subject = GoogleSubject("manager", "auth-session", "workspace", None)
    with _client(picker) as client:
        response = client.post(
            path, json={"expected_revision": 3, "connection_id": "connection"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert set(response.json()) == {"access_token", "expires_at", "api_key", "app_id"}
    assert response.json()["access_token"] == "MINIMAL-PICKER-CANARY"
    picker.issue.assert_awaited_once_with(
        subject,
        "toolkit",
        GooglePickerTokenInput(expected_revision=3, connection_id="connection"),
    )


@pytest.mark.parametrize("extra", ["access_token", "scope", "user_id", "refresh_token"])
def test_picker_request_cannot_supply_credentials_scope_or_account(extra: str) -> None:
    picker = create_autospec(GooglePickerService, instance=True)
    with _client(picker) as client:
        response = client.post(
            "/workspaces/ws/toolkit-configs/toolkit/google/picker-token",
            json={
                "expected_revision": 3,
                "connection_id": "connection",
                extra: "PRIVATE-INPUT-CANARY",
            },
        )
    assert response.status_code == 422
    assert "PRIVATE-INPUT-CANARY" not in response.text
    picker.issue.assert_not_awaited()


@pytest.mark.parametrize(
    "code,status",
    [("stale", 409), ("picker_scope_unverified", 422), ("forbidden", 403)],
)
def test_failed_issuance_contains_no_browser_credential(code: str, status: int) -> None:
    picker = create_autospec(GooglePickerService, instance=True)
    picker.issue.side_effect = GoogleOAuthError(
        code, "Current Picker issuance is unavailable."
    )
    with _client(picker) as client:
        response = client.post(
            "/workspaces/ws/toolkit-configs/toolkit/google/picker-token",
            json={"expected_revision": 3, "connection_id": "connection"},
        )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert set(response.json()) == {"detail"}
