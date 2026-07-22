"""Platform Runtime System Settings domain contracts."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingSection,
)


class PlatformRuntimeConfig(BaseModel):
    """Raw non-secret Platform Runtime policy fields."""

    model_config = ConfigDict(extra="forbid")

    default_provider_id: str | None = Field(default=None, min_length=1, max_length=120)


class PlatformRuntimeSecrets(BaseModel):
    """Platform Runtime has no secret fields."""

    model_config = ConfigDict(extra="forbid")


def _validate_platform_runtime(config: BaseModel, secrets: BaseModel) -> None:
    """Ensure the registry supplied the expected typed models."""
    if not isinstance(config, PlatformRuntimeConfig):
        raise TypeError("Unexpected Platform Runtime config model.")
    if not isinstance(secrets, PlatformRuntimeSecrets):
        raise TypeError("Unexpected Platform Runtime secret model.")


def get_platform_runtime_definition() -> SystemSettingDefinition:
    """Return the compiled Platform Runtime Section definition."""
    return SystemSettingDefinition(
        section=SystemSettingSection.PLATFORM_RUNTIME,
        schema_version=1,
        config_model=PlatformRuntimeConfig,
        secret_model=PlatformRuntimeSecrets,
        activation_mode=SystemSettingActivationMode.CONFIRMED,
        environment_bindings=(),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_platform_runtime,
    )
