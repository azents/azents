"""Closed request-local configuration projections and cap/unset semantics."""

import pytest
from pydantic import ValidationError

from azents_llm_contract.settings import ModelConfiguration


def configuration() -> ModelConfiguration:
    return ModelConfiguration(
        parameters=None,
        context_window_tokens=None,
        max_output_tokens=3000,
        default_input_tokens=10000,
        maximum_input_tokens=20000,
        maximum_output_tokens=2000,
        builtin_tools=(),
        supported_features=("max_output_tokens",),
        reasoning_efforts=(),
        known_default_reasoning=None,
        feature_conditions=(),
        supported_execution_options=(),
    )


def test_transport_preserves_configured_cap_and_unset_values() -> None:
    value = configuration()
    assert value.max_output_tokens == 3000  # Request normalizer owns clamping.
    assert value.context_window_tokens is None
    assert ModelConfiguration.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", "sentinel"),
        ("sdk_kwargs", {"api_base": "https://attacker.invalid"}),
        ("supported_features", ["arbitrary"]),
        ("max_output_tokens", 0),
        ("parameters", {"temperature": 0.1, "api_key": "sentinel"}),
    ],
)
def test_unknown_controls_do_not_become_transport_settings(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        ModelConfiguration.model_validate(
            {**configuration().model_dump(), field: value}
        )
