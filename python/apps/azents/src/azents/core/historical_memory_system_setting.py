"""System-owned execution policy for the Historical Memory Agent."""

import datetime

from pydantic import BaseModel, ConfigDict, Field

from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingSection,
)


class HistoricalMemoryExecutionConfig(BaseModel):
    """The additional execution cutoffs authorized for consolidation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_turns: int | None = Field(default=None, ge=1, strict=True)
    timeout_seconds: int = Field(default=600, ge=1, strict=True)


class HistoricalMemoryExecutionSecrets(BaseModel):
    """Execution policy has no secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_execution_policy(config: BaseModel, secrets: BaseModel) -> None:
    if not isinstance(config, HistoricalMemoryExecutionConfig):
        raise TypeError("Unexpected Historical Memory execution config model.")
    if not isinstance(secrets, HistoricalMemoryExecutionSecrets):
        raise TypeError("Unexpected Historical Memory execution secret model.")


def get_historical_memory_execution_definition() -> SystemSettingDefinition:
    return SystemSettingDefinition(
        section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
        schema_version=1,
        config_model=HistoricalMemoryExecutionConfig,
        secret_model=HistoricalMemoryExecutionSecrets,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=(),
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate_execution_policy,
    )
