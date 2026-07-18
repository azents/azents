"""Built-in capability execution resolution tests."""

import pytest

from azents.core.enums import LLMProvider
from azents.engine.run.builtin_tools import (
    UnsupportedRequiredBuiltinToolError,
    resolve_builtin_tools,
)
from azents.engine.run.types import BuiltinToolSpec


@pytest.mark.parametrize(
    "provider",
    [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH],
)
def test_openai_image_generation_resolves_to_provider_hosted(
    provider: LLMProvider,
) -> None:
    """Keep OpenAI-family image generation provider-hosted."""
    tool = BuiltinToolSpec(name="image_generation", config={})

    resolved = resolve_builtin_tools(
        selected=[tool],
        provider=provider,
        supported=["image_generation"],
    )

    assert resolved.provider_hosted == [tool]
    assert resolved.client_executed == []


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
def test_xai_image_generation_resolves_to_client_execution(
    provider: LLMProvider,
) -> None:
    """Resolve both xAI credential modes to the Imagine client executor."""
    tool = BuiltinToolSpec(name="image_generation", config={})

    resolved = resolve_builtin_tools(
        selected=[tool],
        provider=provider,
        supported=["image_generation"],
    )

    assert resolved.provider_hosted == []
    assert resolved.client_executed == [tool]


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_web_search_remains_provider_hosted(provider: LLMProvider) -> None:
    """Preserve provider-hosted web search for every capable provider."""
    tool = BuiltinToolSpec(name="web_search", config={})

    resolved = resolve_builtin_tools(
        selected=[tool],
        provider=provider,
        supported=["web_search"],
    )

    assert resolved.provider_hosted == [tool]
    assert resolved.client_executed == []


def test_unsupported_selected_capability_fails() -> None:
    """Reject a selected capability missing from the model capability snapshot."""
    with pytest.raises(
        UnsupportedRequiredBuiltinToolError,
        match="Required builtin tool is not supported: image_generation",
    ):
        resolve_builtin_tools(
            selected=[BuiltinToolSpec(name="image_generation", config={})],
            provider=LLMProvider.XAI,
            supported=[],
        )


def test_unknown_selected_capability_fails() -> None:
    """Reject a capability without an implementation resolver branch."""
    with pytest.raises(
        UnsupportedRequiredBuiltinToolError,
        match="Required builtin tool is not implemented: future_tool",
    ):
        resolve_builtin_tools(
            selected=[BuiltinToolSpec(name="future_tool", config={})],
            provider=LLMProvider.OPENAI,
            supported=["future_tool"],
        )
