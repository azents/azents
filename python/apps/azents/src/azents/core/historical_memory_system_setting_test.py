"""Typed Historical Memory execution cutoff contracts."""

import pytest
from pydantic import ValidationError

from azents.core.historical_memory_system_setting import (
    HistoricalMemoryExecutionConfig,
    HistoricalMemoryExecutionSecrets,
    get_historical_memory_execution_definition,
)
from azents.core.system_setting import SystemSettingActivationMode, SystemSettingSection
from azents.core.system_setting_registry import get_system_setting_registry


def test_defaults_and_explicit_unlimited_turns() -> None:
    """Unset and explicitly null turns preserve the unlimited default."""
    config = HistoricalMemoryExecutionConfig()
    assert config.model_dump() == {"max_turns": None, "timeout_seconds": 600}
    assert HistoricalMemoryExecutionConfig(max_turns=None) == config
    assert HistoricalMemoryExecutionConfig(
        max_turns=1, timeout_seconds=1
    ).model_dump() == {
        "max_turns": 1,
        "timeout_seconds": 1,
    }
    assert (
        HistoricalMemoryExecutionConfig.model_validate_json(config.model_dump_json())
        == config
    )


@pytest.mark.parametrize("field", ["max_turns", "timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "1"])
def test_cutoffs_require_strict_positive_integers(field: str, value: object) -> None:
    """Coercion and nonpositive cutoffs cannot enter an effective policy."""
    with pytest.raises(ValidationError):
        HistoricalMemoryExecutionConfig.model_validate({field: value})


def test_timeout_cannot_be_null_and_unknown_fields_are_rejected() -> None:
    """Only the explicit turn cutoff admits null; fields are closed."""
    for payload in ({"timeout_seconds": None}, {"max_turn": 2}):
        with pytest.raises(ValidationError):
            HistoricalMemoryExecutionConfig.model_validate(payload)
    with pytest.raises(ValidationError):
        HistoricalMemoryExecutionSecrets.model_validate({"token": "unexpected"})


def test_effective_config_is_immutable() -> None:
    """A resolved operation policy cannot be changed in place."""
    config = HistoricalMemoryExecutionConfig()
    with pytest.raises(ValidationError, match="frozen"):
        config.timeout_seconds = 1  # ty: ignore[invalid-assignment]  # Test frozen guard.


def test_registered_definition_is_direct_system_owned_and_secret_free() -> None:
    """The real registry exposes the typed no-environment execution policy."""
    definition = get_system_setting_registry().get(
        SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
    )
    assert definition == get_historical_memory_execution_definition()
    assert definition.schema_version == 1
    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert definition.environment_bindings == ()
    assert definition.config_model is HistoricalMemoryExecutionConfig
    assert definition.secret_model is HistoricalMemoryExecutionSecrets
    definition.local_validator(
        HistoricalMemoryExecutionConfig(), HistoricalMemoryExecutionSecrets()
    )
    with pytest.raises(TypeError, match="config model"):
        definition.local_validator(
            HistoricalMemoryExecutionSecrets(), HistoricalMemoryExecutionSecrets()
        )
    with pytest.raises(TypeError, match="secret model"):
        definition.local_validator(
            HistoricalMemoryExecutionConfig(), HistoricalMemoryExecutionConfig()
        )
