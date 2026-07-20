"""Platform GitHub App System Settings domain contracts."""

import datetime
from typing import Self

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import BaseModel, ConfigDict, Field, field_validator

from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingEnvironmentBinding,
    SystemSettingFieldTarget,
    SystemSettingSection,
)


def validate_platform_github_app_id(value: str) -> str:
    """Validate the durable numeric GitHub App identity."""
    if not value or not value.isascii() or not value.isdigit():
        raise ValueError("Platform GitHub App ID must contain only ASCII digits.")
    return value


class PlatformGitHubAppConfig(BaseModel):
    """Raw non-secret Admin base fields for the Platform GitHub App."""

    model_config = ConfigDict(extra="forbid")

    app_id: str | None = None
    client_id: str | None = None


class PlatformGitHubAppSecrets(BaseModel):
    """Raw secret Admin base fields for the Platform GitHub App."""

    model_config = ConfigDict(extra="forbid")

    private_key: str | None = None
    client_secret: str | None = None


class PlatformGitHubAppEffective(BaseModel):
    """Complete and locally valid effective Platform GitHub App credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app_id: str = Field(min_length=1, pattern=r"^[0-9]+$")
    client_id: str = Field(min_length=1)
    private_key: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)

    @field_validator("private_key")
    @classmethod
    def validate_private_key(cls, value: str) -> str:
        """Validate an RSA private key without exposing its contents."""
        normalized = value.replace("\\n", "\n")
        try:
            key = serialization.load_pem_private_key(
                normalized.encode(),
                password=None,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Private key must be a valid unencrypted PEM key."
            ) from error
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("Private key must be an RSA private key.")
        return value

    @classmethod
    def from_parts(
        cls,
        config: PlatformGitHubAppConfig,
        secrets: PlatformGitHubAppSecrets,
    ) -> Self:
        """Require and locally validate all effective fields."""
        values = {
            "app_id": config.app_id,
            "client_id": config.client_id,
            "private_key": secrets.private_key,
            "client_secret": secrets.client_secret,
        }
        missing = tuple(name for name, value in values.items() if value is None)
        match (
            config.app_id,
            config.client_id,
            secrets.private_key,
            secrets.client_secret,
        ):
            case str(app_id), str(client_id), str(private_key), str(client_secret):
                return cls(
                    app_id=app_id,
                    client_id=client_id,
                    private_key=private_key,
                    client_secret=client_secret,
                )
            case _:
                raise PlatformGitHubAppIncomplete(missing_fields=missing)


def _validate_platform_github_app(
    config: BaseModel,
    secrets: BaseModel,
) -> None:
    """Ensure the registry supplied the expected raw typed models."""
    if not isinstance(config, PlatformGitHubAppConfig):
        raise TypeError("Unexpected Platform GitHub App config model.")
    if not isinstance(secrets, PlatformGitHubAppSecrets):
        raise TypeError("Unexpected Platform GitHub App secret model.")


def get_platform_github_app_definition() -> SystemSettingDefinition:
    """Return the compiled Platform GitHub App Section definition."""
    return SystemSettingDefinition(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=1,
        config_model=PlatformGitHubAppConfig,
        secret_model=PlatformGitHubAppSecrets,
        activation_mode=SystemSettingActivationMode.CONFIRMED,
        environment_bindings=(
            SystemSettingEnvironmentBinding(
                field_name="app_id",
                environment_variable="AZ_GITHUB_PLATFORM_APP_ID",
                target=SystemSettingFieldTarget.CONFIG,
            ),
            SystemSettingEnvironmentBinding(
                field_name="client_id",
                environment_variable="AZ_GITHUB_PLATFORM_CLIENT_ID",
                target=SystemSettingFieldTarget.CONFIG,
            ),
            SystemSettingEnvironmentBinding(
                field_name="private_key",
                environment_variable="AZ_GITHUB_PLATFORM_PRIVATE_KEY",
                target=SystemSettingFieldTarget.SECRET,
            ),
            SystemSettingEnvironmentBinding(
                field_name="client_secret",
                environment_variable="AZ_GITHUB_PLATFORM_CLIENT_SECRET",
                target=SystemSettingFieldTarget.SECRET,
            ),
        ),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_platform_github_app,
    )


class PlatformGitHubAppIncomplete(Exception):
    """Effective Platform GitHub App credentials are incomplete."""

    def __init__(self, *, missing_fields: tuple[str, ...]) -> None:
        self.missing_fields = missing_fields
        super().__init__("Platform GitHub App configuration is incomplete.")
