"""Retained native Responses setting contracts; transport lives in model tests."""

import pytest

from azents.core.enums import LLMProvider
from azents.engine.responses import (
    DEFAULT_RESPONSES_TEXT_CONFIG,
    responses_max_output_tokens,
)


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_text_operation_output_limit_preserves_native_openai_behavior(
    provider: LLMProvider,
) -> None:
    expected = (
        None if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH} else 80
    )
    assert responses_max_output_tokens(provider, 80) == expected
    assert responses_max_output_tokens(provider, None) is None
    assert responses_max_output_tokens(provider, 0) is None
    assert responses_max_output_tokens(provider, -1) is None


def test_default_native_responses_text_mode_is_unchanged() -> None:
    assert DEFAULT_RESPONSES_TEXT_CONFIG == {
        "format": {"type": "text"},
        "verbosity": "low",
    }
