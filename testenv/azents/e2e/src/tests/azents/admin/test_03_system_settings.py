"""Admin-managed System Settings API E2E coverage."""

import subprocess
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentsadminclient.api.system_settings_v1_api import SystemSettingsV1Api
from azentsadminclient.models.platform_git_hub_app_confirm_request import (
    PlatformGitHubAppConfirmRequest,
)
from azentsadminclient.models.platform_git_hub_app_patch_request import (
    PlatformGitHubAppPatchRequest,
)
from azentsadminclient.models.system_setting_health_status import (
    SystemSettingHealthStatus,
)
from azentsadminclient.models.system_setting_secret_action_request import (
    SystemSettingSecretActionRequest,
)
from azentsadminclient.models.system_setting_secret_action_type import (
    SystemSettingSecretActionType,
)
from azentsadminclient.models.system_setting_validation_status import (
    SystemSettingValidationStatus,
)
from testcontainers.core.container import DockerContainer

from support.utils import authenticate_user, unique

_APP_ID = "123"
_CLIENT_ID = "Iv1.azents-test"
_CLIENT_SECRET_SENTINEL = "e2e-client-secret-sentinel"
_ROTATED_SECRET_SENTINEL = "e2e-rotated-secret-sentinel"
_PROVIDER_PRIVATE_DIAGNOSTIC = "provider credential details are private"


def _client_for_token(
    *,
    server_url: str,
    access_token: str,
) -> azentsadminclient.ApiClient:
    """Create an Admin API client for one access token."""
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=server_url,
            access_token=access_token,
        )
    )


def _assert_api_status(error: azentsadminclient.ApiException, expected: int) -> None:
    assert cast(Any, error).status == expected


def _api_error_body(error: azentsadminclient.ApiException) -> str:
    """Return a generated-client error body as a typed string."""
    body: object = cast(Any, error).body
    return body if isinstance(body, str) else ""


def _generate_private_key() -> str:
    """Generate a disposable RSA private key without printing it."""
    result = subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _set_provider_scenario(base_url: str, scenario: str) -> None:
    """Select one deterministic provider response classification."""
    response = requests.post(
        f"{base_url}/__testenv/scenario",
        json={"scenario": scenario},
        timeout=5,
    )
    assert response.status_code == 200
    assert response.json() == {"scenario": scenario}


def _replace_secret(value: str) -> SystemSettingSecretActionRequest:
    """Create an explicit secret replacement action."""
    return SystemSettingSecretActionRequest(
        action=SystemSettingSecretActionType.REPLACE,
        value=value,
    )


def test_system_settings_authorization_lifecycle_redaction_and_audit(
    admin_api_client: azentsadminclient.ApiClient,
    public_api_client: azentspublicclient.ApiClient,
    azents_admin_server_url: str,
    azents_admin_server_container: DockerContainer,
    github_validation_proxy_url: str,
) -> None:
    """Exercise the redacted lifecycle through deployed API and provider boundaries."""
    settings_api = SystemSettingsV1Api(admin_api_client)

    initial_inventory = settings_api.system_settings_v1_list_system_setting_sections()
    assert len(initial_inventory.items) == 1
    assert initial_inventory.items[0].section == "platform_github_app"
    assert initial_inventory.items[0].admin_version == 0
    assert initial_inventory.items[0].effective_status == "not_configured"

    initial = settings_api.system_settings_v1_get_platform_github_app_setting()
    assert initial.admin_version == 0
    assert initial.candidate is None
    assert initial.health is None
    assert initial.app_slug is None
    assert {field.name for field in initial.fields} == {
        "app_id",
        "client_id",
        "private_key",
        "client_secret",
    }
    for field in initial.fields:
        assert field.configured is False
        assert field.source == "unset"
        if field.secret:
            assert field.value is None

    ordinary_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"settings-ordinary-{unique()}@example.com",
    )
    with _client_for_token(
        server_url=azents_admin_server_url,
        access_token=ordinary_token,
    ) as ordinary_client:
        ordinary_api = SystemSettingsV1Api(ordinary_client)
        for operation in (
            ordinary_api.system_settings_v1_list_system_setting_sections,
            ordinary_api.system_settings_v1_get_platform_github_app_setting,
            ordinary_api.system_settings_v1_list_system_setting_audit_events,
        ):
            with pytest.raises(azentsadminclient.ApiException) as denied:
                operation()
            _assert_api_status(denied.value, 403)
            assert "platform_github_app" not in _api_error_body(denied.value)

    incomplete_health = (
        settings_api.system_settings_v1_check_platform_github_app_health()
    )
    assert incomplete_health.health is not None
    assert incomplete_health.health.status is SystemSettingHealthStatus.INVALID
    assert incomplete_health.health.code == "platform_github_app_incomplete"

    private_key = _generate_private_key()
    _set_provider_scenario(github_validation_proxy_url, "valid")
    activated = settings_api.system_settings_v1_patch_platform_github_app_setting(
        PlatformGitHubAppPatchRequest(
            expected_version=0,
            app_id=_APP_ID,
            client_id=_CLIENT_ID,
            private_key=_replace_secret(private_key),
            client_secret=_replace_secret(_CLIENT_SECRET_SENTINEL),
        )
    )
    assert activated.admin_version == 1
    assert activated.effective_status == "ready"
    assert activated.candidate is None
    assert activated.activation_validation_status is SystemSettingValidationStatus.VALID
    assert activated.app_slug == "azents-test"
    fields = {field.name: field for field in activated.fields}
    assert fields["app_id"].value == _APP_ID
    assert fields["client_id"].value == _CLIENT_ID
    assert fields["private_key"].configured is True
    assert fields["private_key"].value is None
    assert fields["client_secret"].configured is True
    assert fields["client_secret"].value is None

    activated_json = activated.to_json()
    assert private_key not in activated_json
    assert _CLIENT_SECRET_SENTINEL not in activated_json
    assert "effective_generation" not in activated_json

    with pytest.raises(azentsadminclient.ApiException) as stale_patch:
        settings_api.system_settings_v1_patch_platform_github_app_setting(
            PlatformGitHubAppPatchRequest(expected_version=0, app_id=_APP_ID)
        )
    _assert_api_status(stale_patch.value, 409)
    assert "stale_system_setting_version" in _api_error_body(stale_patch.value)

    _set_provider_scenario(github_validation_proxy_url, "unavailable")
    unavailable = settings_api.system_settings_v1_patch_platform_github_app_setting(
        PlatformGitHubAppPatchRequest(
            expected_version=1,
            client_secret=_replace_secret(_ROTATED_SECRET_SENTINEL),
        )
    )
    assert unavailable.admin_version == 1
    assert unavailable.candidate is not None
    assert (
        unavailable.candidate.validation_status
        is SystemSettingValidationStatus.UNAVAILABLE
    )
    assert unavailable.candidate.validation_code == "github_unavailable"
    candidate_id = unavailable.candidate.id

    _set_provider_scenario(github_validation_proxy_url, "invalid_oauth")
    invalid = settings_api.system_settings_v1_validate_platform_github_app_candidate()
    assert invalid.candidate is not None
    assert invalid.candidate.id == candidate_id
    assert invalid.candidate.validation_status is SystemSettingValidationStatus.INVALID
    assert invalid.candidate.validation_code == "github_oauth_credentials_invalid"
    assert _PROVIDER_PRIVATE_DIAGNOSTIC not in invalid.to_json()

    with pytest.raises(azentsadminclient.ApiException) as unvalidated_confirmation:
        settings_api.system_settings_v1_confirm_platform_github_app_candidate(
            PlatformGitHubAppConfirmRequest(
                candidate_id=candidate_id,
                expected_version=1,
                confirmation_action="activate",
            )
        )
    _assert_api_status(unvalidated_confirmation.value, 409)
    assert "system_setting_candidate_not_validated" in _api_error_body(
        unvalidated_confirmation.value
    )

    settings_api.system_settings_v1_cancel_platform_github_app_candidate(candidate_id)
    after_cancel = settings_api.system_settings_v1_get_platform_github_app_setting()
    assert after_cancel.admin_version == 1
    assert after_cancel.candidate is None

    _set_provider_scenario(github_validation_proxy_url, "valid")
    healthy = settings_api.system_settings_v1_check_platform_github_app_health()
    assert healthy.health is not None
    assert healthy.health.status is SystemSettingHealthStatus.HEALTHY
    assert healthy.health.metadata == {"app_slug": "azents-test"}

    provider_state = requests.get(
        f"{github_validation_proxy_url}/__testenv/state",
        timeout=5,
    )
    assert provider_state.status_code == 200
    assert provider_state.json()["app_request_count"] == 1
    assert provider_state.json()["oauth_request_count"] == 1

    audit = settings_api.system_settings_v1_list_system_setting_audit_events(limit=100)
    audit_json = audit.to_json()
    assert audit.total >= 7
    assert {
        "candidate_replaced",
        "candidate_validated",
        "candidate_cancelled",
        "activated",
        "health_checked",
    }.issubset({event.event_type.value for event in audit.items})
    assert any(
        event.secret_actions == {"client_secret": "replace", "private_key": "replace"}
        for event in audit.items
    )
    for sentinel in (
        private_key,
        _CLIENT_SECRET_SENTINEL,
        _ROTATED_SECRET_SENTINEL,
        _PROVIDER_PRIVATE_DIAGNOSTIC,
        "effective_generation",
    ):
        assert sentinel not in audit_json

    stdout, stderr = azents_admin_server_container.get_logs()
    server_logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
    assert _CLIENT_SECRET_SENTINEL not in server_logs
    assert _ROTATED_SECRET_SENTINEL not in server_logs
    assert _PROVIDER_PRIVATE_DIAGNOSTIC not in server_logs
