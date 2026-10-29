"""Saved known defaults constrain genuine omission, never an explicit clear."""

import pytest
from azents_llm_contract.settings import FeatureCondition

from azents_llm_proxy.request import decode_request
from azents_llm_proxy.request_test import request
from azents_llm_proxy.settings import UnsupportedRequest, normalize_request
from azents_llm_proxy.settings_test import configured


@pytest.mark.parametrize(
    "declaration", [None, {}, {"effort": None}, {"effort": None, "summary": "auto"}]
)
def test_known_default_is_not_borrowed_for_explicit_reasoning_clear(
    declaration: object,
) -> None:
    value = configured()
    value = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "parameters": None,
                    "known_default_reasoning": "low",
                    "feature_conditions": (
                        FeatureCondition(
                            feature="temperature",
                            reasoning_efforts=("low",),
                            function_tools=None,
                        ),
                    ),
                }
            )
        }
    )
    with pytest.raises(UnsupportedRequest):
        normalize_request(
            decode_request({**request(), "temperature": 0.2, "reasoning": declaration}),
            value,
        )


@pytest.mark.parametrize("summary_only", [False, True])
def test_known_default_applies_to_support_context_without_becoming_a_preference(
    summary_only: bool,
) -> None:
    value = configured()
    value = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "parameters": None,
                    "known_default_reasoning": "low",
                    "feature_conditions": (
                        FeatureCondition(
                            feature="temperature",
                            reasoning_efforts=("low",),
                            function_tools=None,
                        ),
                    ),
                }
            )
        }
    )
    body = {**request(), "temperature": 0.2}
    if summary_only:
        body["reasoning"] = {"summary": "auto"}
    result = normalize_request(decode_request(body), value)
    if summary_only:
        assert result["reasoning"] == {"summary": "auto"}
    else:
        assert "reasoning" not in result
