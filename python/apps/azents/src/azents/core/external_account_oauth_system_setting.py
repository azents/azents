"""Admin-managed provider OAuth System Settings contracts."""

import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingSection,
)


class ExternalAccountOAuthConfig(BaseModel):
    """Common non-secret provider OAuth client configuration."""

    model_config = ConfigDict(extra="forbid")

    client_id: str | None = None

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str | None) -> str | None:
        """Reject configured blank OAuth client identifiers."""
        if value is not None and not value.strip():
            raise ValueError("OAuth client ID must not be blank.")
        return value


class ExternalAccountOAuthSecrets(BaseModel):
    """Common secret provider OAuth client configuration."""

    model_config = ConfigDict(extra="forbid")

    client_secret: str | None = None

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: str | None) -> str | None:
        """Reject configured blank OAuth client secrets."""
        if value is not None and not value.strip():
            raise ValueError("OAuth client secret must not be blank.")
        return value


class DiscordIdentityOAuthConfig(BaseModel):
    """Discord OAuth application identity configuration."""

    model_config = ConfigDict(extra="forbid")

    application_id: str | None = None

    @field_validator("application_id")
    @classmethod
    def validate_application_id(cls, value: str | None) -> str | None:
        """Require a Discord snowflake-shaped application identifier."""
        if value is not None and (
            not value.isascii() or not value.isdigit() or not value.strip()
        ):
            raise ValueError("Discord application ID must contain ASCII digits.")
        return value


class DiscordIdentityOAuthSecrets(BaseModel):
    """Discord OAuth application secret configuration."""

    model_config = ConfigDict(extra="forbid")

    client_secret: str | None = None

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: str | None) -> str | None:
        """Reject configured blank Discord OAuth client secrets."""
        if value is not None and not value.strip():
            raise ValueError("OAuth client secret must not be blank.")
        return value


def _validate_slack_definition(config: BaseModel, secrets: BaseModel) -> None:
    """Validate the compiled Slack Section model pair."""
    if not isinstance(config, ExternalAccountOAuthConfig):
        raise TypeError("Unexpected Slack OAuth config model.")
    if not isinstance(secrets, ExternalAccountOAuthSecrets):
        raise TypeError("Unexpected Slack OAuth secrets model.")


def _validate_discord_definition(config: BaseModel, secrets: BaseModel) -> None:
    """Validate the compiled Discord Section model pair."""
    if not isinstance(config, DiscordIdentityOAuthConfig):
        raise TypeError("Unexpected Discord OAuth config model.")
    if not isinstance(secrets, DiscordIdentityOAuthSecrets):
        raise TypeError("Unexpected Discord OAuth secrets model.")


def get_slack_identity_oauth_definition() -> SystemSettingDefinition:
    """Return the Slack identity OAuth Section definition."""
    return SystemSettingDefinition(
        section=SystemSettingSection.SLACK_IDENTITY_OAUTH,
        schema_version=1,
        config_model=ExternalAccountOAuthConfig,
        secret_model=ExternalAccountOAuthSecrets,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=(),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_slack_definition,
    )


def get_discord_identity_oauth_definition() -> SystemSettingDefinition:
    """Return the Discord identity OAuth Section definition."""
    return SystemSettingDefinition(
        section=SystemSettingSection.DISCORD_IDENTITY_OAUTH,
        schema_version=1,
        config_model=DiscordIdentityOAuthConfig,
        secret_model=DiscordIdentityOAuthSecrets,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=(),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_discord_definition,
    )
