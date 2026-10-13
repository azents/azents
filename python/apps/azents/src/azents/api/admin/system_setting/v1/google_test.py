"""Presence-aware Google operator mutation and safe route error boundaries."""

from unittest.mock import create_autospec

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from azents.api.admin.system_setting.v1.google import (
    GoogleApplicationPatchRequest,
    patch_google_oauth_setting,
    router,
)
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.system_setting import (
    SystemSettingSection,
    SystemSettingVersionConflict,
)
from azents.services.google_application.service import GoogleApplicationService

_PATCH = TypeAdapter(GoogleApplicationPatchRequest)


def test_patch_has_no_implicit_secret_or_client_mutation() -> None:
    assert _PATCH.validate_python({"expected_version": 2}) == {"expected_version": 2}
    assert _PATCH.validate_python({"expected_version": 2, "client_id": None}) == {
        "expected_version": 2,
        "client_id": None,
    }
    with pytest.raises(ValidationError):
        _PATCH.validate_python({"expected_version": 2, "client_secret": "plaintext"})
    with pytest.raises(ValidationError):
        _PATCH.validate_python({"expected_version": 2, "other_client": "not-admitted"})


@pytest.mark.asyncio
async def test_empty_mutation_does_not_call_service() -> None:
    service = create_autospec(GoogleApplicationService, instance=True)
    with pytest.raises(HTTPException) as caught:
        await patch_google_oauth_setting(
            service,
            SystemAdmin(user_id="admin", session_id="login"),
            {"expected_version": 2},
        )
    assert caught.value.status_code == 422
    service.patch.assert_not_called()


@pytest.mark.asyncio
async def test_stale_operator_version_is_not_provider_failure() -> None:
    service = create_autospec(GoogleApplicationService, instance=True)
    service.patch.side_effect = SystemSettingVersionConflict(
        section=SystemSettingSection.GOOGLE_OAUTH,
        expected_version=2,
        current_version=3,
    )
    with pytest.raises(HTTPException) as caught:
        await patch_google_oauth_setting(
            service,
            SystemAdmin(user_id="admin", session_id="login"),
            {"expected_version": 2, "client_id": "new-client"},
        )
    assert caught.value.status_code == 409
    detail: object = caught.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "stale_system_setting_version"


@pytest.mark.parametrize(
    "body",
    [
        {
            "expected_version": 0,
            "client_secret": {"action": "clear", "value": "SECRET-MARKER"},
        },
        {
            "expected_version": 0,
            "client_secret": {"action": "unknown", "value": "SECRET-MARKER"},
        },
        {
            "expected_version": "SECRET-MARKER",
            "client_secret": {"action": "replace", "value": "SECRET-MARKER"},
        },
        {"expected_version": 0, "client_secret": "SECRET-MARKER"},
        ["SECRET-MARKER"],
    ],
)
def test_http_secret_validation_is_redacted_before_endpoint(body: object) -> None:
    application = create_autospec(GoogleApplicationService, instance=True)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_system_admin] = lambda: SystemAdmin("admin", "login")
    app.dependency_overrides[GoogleApplicationService] = lambda: application
    with TestClient(app) as client:
        response = client.patch("/sections/google-oauth", json=body)
    assert response.status_code == 422
    assert "SECRET-MARKER" not in response.text
    assert '"input"' not in response.text
    application.patch.assert_not_awaited()
