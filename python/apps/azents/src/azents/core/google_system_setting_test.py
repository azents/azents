"""Operator field ownership and safe configuration models."""

import pytest
from pydantic import ValidationError

from azents.core.google_system_setting import (
    GoogleApplicationConfig,
    GoogleApplicationRegistration,
    GoogleApplicationSecrets,
    get_google_oauth_definition,
)
from azents.core.system_setting import SystemSettingActivationMode


def test_google_operator_definition_has_one_direct_current_authority() -> None:
    definition = get_google_oauth_definition()
    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert {
        field.environment_variable for field in definition.environment_bindings
    } == {
        "AZ_GOOGLE_OAUTH_CLIENT_ID",
        "AZ_GOOGLE_OAUTH_CLIENT_SECRET",
        "AZ_GOOGLE_PICKER_API_KEY",
        "AZ_GOOGLE_PICKER_APP_ID",
    }


def test_secret_and_generation_are_not_in_registration_repr() -> None:
    registration = GoogleApplicationRegistration(
        "client",
        "test-secret-value",
        "internal-generation",
        "https://example.invalid/callback",
    )
    assert "test-secret-value" not in repr(registration)
    assert "internal-generation" not in repr(registration)


@pytest.mark.parametrize("value", ["", " ", " padded "])
def test_blank_or_padded_client_is_not_a_ready_registration(value: str) -> None:
    with pytest.raises(ValidationError):
        GoogleApplicationConfig(client_id=value)


def test_secret_validation_does_not_echo_the_input() -> None:
    with pytest.raises(ValidationError) as caught:
        GoogleApplicationSecrets(client_secret="   ")
    assert "input_value" not in str(caught.value)


def test_operator_secret_model_does_not_include_secret_in_repr() -> None:
    assert "PRIVATE-SECRET" not in repr(
        GoogleApplicationSecrets(client_secret="PRIVATE-SECRET")
    )


@pytest.mark.parametrize("value", ["", "  ", " padded "])
def test_picker_api_key_validation_is_redacted(value: str) -> None:
    with pytest.raises(ValidationError) as error:
        GoogleApplicationConfig(picker_api_key=value)
    assert "input_value" not in str(error.value)


@pytest.mark.parametrize("value", ["", "project-name", "-1", " 123 "])
def test_picker_app_id_is_a_project_number(value: str) -> None:
    with pytest.raises(ValidationError):
        GoogleApplicationConfig(picker_app_id=value)
