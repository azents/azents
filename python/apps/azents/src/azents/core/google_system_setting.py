"""One operator-owned Google registration; configuration is not live evidence."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypedDict

from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingEnvironmentBinding,
    SystemSettingFieldSource,
    SystemSettingFieldTarget,
    SystemSettingSection,
)


class GoogleApplicationConfig(BaseModel):
    """Partially configured operator client; no account credential is stored here."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    client_id: str | None = None
    picker_api_key: str | None = Field(
        default=None, min_length=1, max_length=255, repr=False
    )
    picker_app_id: str | None = Field(
        default=None, min_length=1, max_length=32, pattern=r"^[0-9]+$"
    )

    @field_validator("picker_api_key")
    @classmethod
    def trimmed_picker_key(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("Google Picker API key must be nonblank and trimmed.")
        return value

    @field_validator("client_id")
    @classmethod
    def nonblank_client(cls, value: str | None) -> str | None:
        """Reject explicit blank application identifiers."""
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("Google client ID must be nonblank and trimmed.")
        return value


class GoogleApplicationSecrets(BaseModel):
    """Write-only current operator secret; never copied into Toolkit credentials."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    client_secret: str | None = Field(default=None, repr=False)

    @field_validator("client_secret")
    @classmethod
    def nonblank_secret(cls, value: str | None) -> str | None:
        """Reject blank secret replacements without echoing the value."""
        if value is not None and not value.strip():
            raise ValueError("Google client secret must be nonblank.")
        return value


class GoogleApplicationUnavailable(ValueError):
    """Safe preparation error, distinct from Google account rejection."""


@dataclasses.dataclass(frozen=True)
class GoogleApplicationRegistration:
    """Detached current registration used only between completed DB operations."""

    client_id: str
    client_secret: str = dataclasses.field(repr=False)
    effective_generation: str = dataclasses.field(repr=False)
    redirect_uri: str


@dataclasses.dataclass(frozen=True)
class GooglePickerApplication:
    """One detached operator snapshot; browser preparation is not live verification."""

    registration: GoogleApplicationRegistration = dataclasses.field(repr=False)
    api_key: str = dataclasses.field(repr=False)
    app_id: str


class GooglePreparation(BaseModel):
    """Separate local OAuth and optional Picker preparation, without live claims."""

    status: Literal["not_configured", "incomplete", "configured_unverified"]
    client_id: str | None
    callback_url: str | None
    picker_status: Literal["not_configured", "incomplete", "configured_unverified"]
    service_access_verified: bool = Field(
        strict=True,
        description="Local preparation does not verify live service access.",
    )


class GoogleApplicationDetail(GooglePreparation):
    """Admin redacted effective fields and optimistic version, never secret values."""

    section: Literal["google_oauth"]
    schema_version: int
    admin_version: int
    client_id_source: SystemSettingFieldSource
    client_secret_source: SystemSettingFieldSource
    client_secret_configured: bool
    picker_api_key: str | None = Field(repr=False)
    picker_app_id: str | None
    picker_api_key_source: SystemSettingFieldSource
    picker_app_id_source: SystemSettingFieldSource


class GoogleApplicationConfigPatch(TypedDict, total=False, closed=True):
    """Presence-aware operator nonsecret patch; explicit null clears a field."""

    client_id: str | None
    picker_api_key: str | None
    picker_app_id: str | None


def resolve_google_registration(
    resolved: ResolvedSystemSetting, redirect_uri: str
) -> GoogleApplicationRegistration:
    """Require a complete exact effective registration without external I/O."""
    config = resolved.config
    secrets = resolved.secrets
    if not isinstance(config, GoogleApplicationConfig) or not isinstance(
        secrets, GoogleApplicationSecrets
    ):
        raise TypeError("Unexpected Google application setting models.")
    if config.client_id is None or secrets.client_secret is None:
        raise GoogleApplicationUnavailable("Google operator application is incomplete.")
    return GoogleApplicationRegistration(
        config.client_id,
        secrets.client_secret,
        resolved.effective_generation,
        redirect_uri,
    )


def google_preparation(
    resolved: ResolvedSystemSetting, redirect_uri: str | None
) -> GooglePreparation:
    """Project only preparation facts, never secret material or live health."""
    config = resolved.config
    secrets = resolved.secrets
    if not isinstance(config, GoogleApplicationConfig) or not isinstance(
        secrets, GoogleApplicationSecrets
    ):
        raise TypeError("Unexpected Google application setting models.")
    status: Literal["not_configured", "incomplete", "configured_unverified"]
    if config.client_id is None and secrets.client_secret is None:
        status = "not_configured"
    elif (
        config.client_id is None
        or secrets.client_secret is None
        or redirect_uri is None
    ):
        status = "incomplete"
    else:
        status = "configured_unverified"
    picker_status: Literal["not_configured", "incomplete", "configured_unverified"]
    if config.picker_api_key is None and config.picker_app_id is None:
        picker_status = "not_configured"
    elif config.picker_api_key is None or config.picker_app_id is None:
        picker_status = "incomplete"
    else:
        picker_status = "configured_unverified"
    return GooglePreparation(
        status=status,
        client_id=config.client_id,
        callback_url=redirect_uri,
        picker_status=picker_status,
        service_access_verified=False,
    )


def _validate_google_models(config: BaseModel, secrets: BaseModel) -> None:
    if not isinstance(config, GoogleApplicationConfig):
        raise TypeError("Unexpected Google application config.")
    if not isinstance(secrets, GoogleApplicationSecrets):
        raise TypeError("Unexpected Google application secrets.")


def get_google_oauth_definition() -> SystemSettingDefinition:
    """Reuse direct encrypted operator Section activation and field ownership."""
    return SystemSettingDefinition(
        section=SystemSettingSection.GOOGLE_OAUTH,
        schema_version=1,
        config_model=GoogleApplicationConfig,
        secret_model=GoogleApplicationSecrets,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=(
            SystemSettingEnvironmentBinding(
                field_name="client_id",
                environment_variable="AZ_GOOGLE_OAUTH_CLIENT_ID",
                target=SystemSettingFieldTarget.CONFIG,
            ),
            SystemSettingEnvironmentBinding(
                field_name="client_secret",
                environment_variable="AZ_GOOGLE_OAUTH_CLIENT_SECRET",
                target=SystemSettingFieldTarget.SECRET,
            ),
            SystemSettingEnvironmentBinding(
                field_name="picker_api_key",
                environment_variable="AZ_GOOGLE_PICKER_API_KEY",
                target=SystemSettingFieldTarget.CONFIG,
            ),
            SystemSettingEnvironmentBinding(
                field_name="picker_app_id",
                environment_variable="AZ_GOOGLE_PICKER_APP_ID",
                target=SystemSettingFieldTarget.CONFIG,
            ),
        ),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_google_models,
    )
