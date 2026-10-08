"""Distinct registration branches preserve existing GitHub credential contracts."""

import pytest
from pydantic import ConfigDict, TypeAdapter, ValidationError

from azents.core.github_credentials import (
    GitHubSecrets,
    GitHubSecretsAppPlatformUser,
    GitHubSecretsAppUser,
)
from azents.core.tools import GitHubToolkitConfig


def test_user_registration_contains_no_execution_token() -> None:
    credentials = GitHubSecretsAppUser(
        app_id="123",
        private_key="private-registration-key",
        client_id="Iv1.test",
        client_secret="registration-secret",
    )
    assert credentials.type == "github_app_user"
    assert "private-registration-key" not in repr(credentials)
    assert "registration-secret" not in repr(credentials)
    assert "token" not in type(credentials).model_fields
    assert "refresh_token" not in type(credentials).model_fields


@pytest.mark.parametrize("unexpected", ["token", "refresh_token", "expires_in"])
def test_user_registration_rejects_client_supplied_token_material(
    unexpected: str,
) -> None:
    adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(
        GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
    )
    with pytest.raises(ValidationError) as caught:
        adapter.validate_python(
            {
                "type": "github_app_user",
                "app_id": "123",
                "private_key": "private-registration-key",
                "client_id": "Iv1.test",
                "client_secret": "registration-secret",
                unexpected: "user-token-must-not-be-submitted",
            }
        )
    assert "user-token-must-not-be-submitted" not in str(caught.value)
    assert "registration-secret" not in str(caught.value)


def test_platform_user_registration_has_only_server_app_binding() -> None:
    credential = GitHubSecretsAppPlatformUser(app_id="123")
    assert set(credential.model_dump()) == {"type", "app_id"}


@pytest.mark.parametrize(
    "auth_type",
    [
        "pat",
        "github_app",
        "github_app_platform",
        "github_app_user",
        "github_app_platform_user",
    ],
)
def test_all_five_config_modes_keep_runtime_handoff_opt_in(auth_type: str) -> None:
    config = GitHubToolkitConfig.model_validate({"github_auth_type": auth_type})
    assert config.inject_runtime_environment is False
    assert config.github_auth_type == auth_type


def test_existing_byoa_installation_needs_no_oauth_registration() -> None:
    adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(
        GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
    )
    credential = adapter.validate_python(
        {
            "type": "github_app",
            "app_id": "123",
            "private_key": "installation-private-key",
            "installations": [
                {
                    "installation_id": "456",
                    "account_login": "owner",
                    "account_type": "Organization",
                    "account_avatar_url": None,
                }
            ],
        }
    )
    assert credential.type == "github_app"
    assert "client_id" not in type(credential).model_fields
