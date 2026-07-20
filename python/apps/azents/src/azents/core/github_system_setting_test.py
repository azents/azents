"""Platform GitHub App System Settings contract tests."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from azents.core.github_system_setting import (
    PlatformGitHubAppConfig,
    PlatformGitHubAppEffective,
    PlatformGitHubAppIncomplete,
    PlatformGitHubAppSecrets,
    get_platform_github_app_definition,
)


def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_definition_binds_all_legacy_environment_names() -> None:
    """The compiled Section keeps permanent field-level environment overlays."""
    definition = get_platform_github_app_definition()

    environment_variables = {
        binding.environment_variable for binding in definition.environment_bindings
    }
    assert environment_variables == {
        "AZ_GITHUB_PLATFORM_APP_ID",
        "AZ_GITHUB_PLATFORM_CLIENT_ID",
        "AZ_GITHUB_PLATFORM_PRIVATE_KEY",
        "AZ_GITHUB_PLATFORM_CLIENT_SECRET",
    }


def test_complete_effective_requires_all_four_fields() -> None:
    """Operational GitHub actions fail closed when any effective field is absent."""
    with pytest.raises(PlatformGitHubAppIncomplete) as exc_info:
        PlatformGitHubAppEffective.from_parts(
            PlatformGitHubAppConfig(app_id="123", client_id=None),
            PlatformGitHubAppSecrets(private_key=None, client_secret=None),
        )

    assert exc_info.value.missing_fields == (
        "client_id",
        "private_key",
        "client_secret",
    )


def test_private_key_validation_accepts_rsa_and_rejects_invalid_pem() -> None:
    """Operational validation rejects malformed material before GitHub calls."""
    valid = PlatformGitHubAppEffective.from_parts(
        PlatformGitHubAppConfig(app_id="123", client_id="Iv1.client"),
        PlatformGitHubAppSecrets(
            private_key=_private_key(),
            client_secret="secret",
        ),
    )
    assert valid.private_key

    with pytest.raises(ValidationError):
        PlatformGitHubAppEffective.from_parts(
            PlatformGitHubAppConfig(app_id="123", client_id="Iv1.client"),
            PlatformGitHubAppSecrets(
                private_key="not-a-private-key",
                client_secret="secret",
            ),
        )
