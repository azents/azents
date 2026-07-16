"""Agent core contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.agent import (
    SelectableModelSettings,
    SelectableModelSettingsInput,
)


def test_selectable_model_settings_requires_complete_stored_shape() -> None:
    """Stored settings require explicit nullable caps and a concrete tool list."""
    with pytest.raises(ValidationError):
        SelectableModelSettings.model_validate({})


def test_selectable_model_settings_input_allows_omitted_defaults() -> None:
    """Input settings preserve omission as a request for capability defaults."""
    settings = SelectableModelSettingsInput.model_validate({})

    assert settings.context_window_tokens is None
    assert settings.max_output_tokens is None
    assert settings.builtin_tools is None


def test_selectable_model_settings_preserves_explicit_all_off() -> None:
    """A stored empty tool list represents an explicit all-off choice."""
    settings = SelectableModelSettings(
        context_window_tokens=None,
        max_output_tokens=None,
        builtin_tools=[],
    )

    assert settings.builtin_tools == []


@pytest.mark.parametrize("field", ["context_window_tokens", "max_output_tokens"])
def test_selectable_model_settings_rejects_non_positive_tokens(field: str) -> None:
    """Token caps must be positive when provided."""
    payload: dict[str, object] = {
        "context_window_tokens": None,
        "max_output_tokens": None,
        "builtin_tools": [],
    }
    payload[field] = 0

    with pytest.raises(ValidationError):
        SelectableModelSettings.model_validate(payload)
