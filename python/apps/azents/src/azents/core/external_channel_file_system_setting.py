"""External Channel file-transfer System Settings domain contracts."""

import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.external_channel_file import (
    DEFAULT_EXTERNAL_CHANNEL_INBOUND_MAX_FILE_BYTES,
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES,
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES,
    MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES,
    MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
)
from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingSection,
)


class ExternalChannelFilesConfig(BaseModel):
    """Provider-neutral byte limits for External Channel file transfer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inbound_max_file_bytes: int = Field(
        default=DEFAULT_EXTERNAL_CHANNEL_INBOUND_MAX_FILE_BYTES,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
        strict=True,
    )
    outbound_max_file_bytes: int = Field(
        default=DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
        strict=True,
    )
    outbound_max_action_bytes: int = Field(
        default=DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES,
        strict=True,
    )

    @model_validator(mode="after")
    def validate_outbound_aggregate(self) -> "ExternalChannelFilesConfig":
        """Require one action to permit at least one maximum-size outbound file."""
        if self.outbound_max_action_bytes < self.outbound_max_file_bytes:
            raise ValueError(
                "External Channel outbound action limit must be at least the "
                "outbound per-file limit."
            )
        return self


class ExternalChannelFilesSecrets(BaseModel):
    """External Channel file-transfer policy has no secret fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_external_channel_files(config: BaseModel, secrets: BaseModel) -> None:
    """Ensure the registry supplied the expected typed models."""
    if not isinstance(config, ExternalChannelFilesConfig):
        raise TypeError("Unexpected External Channel files config model.")
    if not isinstance(secrets, ExternalChannelFilesSecrets):
        raise TypeError("Unexpected External Channel files secret model.")


def get_external_channel_files_definition() -> SystemSettingDefinition:
    """Return the compiled External Channel file-transfer Section definition."""
    return SystemSettingDefinition(
        section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
        schema_version=1,
        config_model=ExternalChannelFilesConfig,
        secret_model=ExternalChannelFilesSecrets,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=(),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_external_channel_files,
    )
