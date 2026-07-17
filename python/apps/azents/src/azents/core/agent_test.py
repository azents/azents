"""Agent core contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.agent import (
    MAX_SUBAGENT_GUIDANCE_LENGTH,
    SelectableModelSettings,
    SelectableModelSettingsInput,
)


def test_selectable_model_settings_requires_complete_stored_shape() -> None:
    """Stored settings require explicit execution and subagent policy fields."""
    with pytest.raises(ValidationError):
        SelectableModelSettings.model_validate(
            {
                "context_window_tokens": None,
                "max_output_tokens": None,
                "builtin_tools": [],
            }
        )


def test_selectable_model_settings_input_allows_omitted_defaults() -> None:
    """Input settings preserve omission as a request for capability defaults."""
    settings = SelectableModelSettingsInput.model_validate({})

    assert settings.context_window_tokens is None
    assert settings.max_output_tokens is None
    assert settings.builtin_tools is None
    assert settings.subagent_enabled is True
    assert settings.subagent_guidance is None


def test_selectable_model_settings_preserves_explicit_all_off() -> None:
    """A stored empty tool list represents an explicit all-off choice."""
    settings = SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[],
        subagent_enabled=False,
        subagent_guidance="Use only for targeted review.",
    )

    assert settings.builtin_tools == []
    assert settings.subagent_enabled is False
    assert settings.subagent_guidance == "Use only for targeted review."


@pytest.mark.parametrize("field", ["context_window_tokens", "max_output_tokens"])
def test_selectable_model_settings_rejects_non_positive_tokens(field: str) -> None:
    """Token caps must be positive when provided."""
    payload: dict[str, object] = {
        "context_window_tokens": None,
        "max_output_tokens": None,
        "builtin_tools": [],
        "subagent_enabled": True,
        "subagent_guidance": None,
    }
    payload[field] = 0

    with pytest.raises(ValidationError):
        SelectableModelSettings.model_validate(payload)


def test_selectable_model_settings_rejects_long_subagent_guidance() -> None:
    """Subagent guidance is bounded to control dynamic tool prompt growth."""
    with pytest.raises(ValidationError):
        SelectableModelSettingsInput(
            subagent_guidance="x" * (MAX_SUBAGENT_GUIDANCE_LENGTH + 1)
        )
