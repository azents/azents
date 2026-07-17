"""Built-in tool validation rule tests."""

import dataclasses

from azents.core.agent import BuiltinToolConfig
from azents.core.builtin_tools import (
    BuiltinToolValidationContext,
    ImageGenerationRule,
    WebSearchRule,
    validate_builtin_tools,
)
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities


@dataclasses.dataclass(frozen=True)
class _ProviderModel:
    """Provider model protocol implementation for tests."""

    provider: LLMProvider
    model_identifier: str
    capabilities: ModelCapabilities


def _make_provider_model(
    *,
    supported_builtin_tools: list[str] | None = None,
    provider: LLMProvider = LLMProvider.OPENAI,
    model_identifier: str = "gpt-5",
) -> _ProviderModel:
    """Create a provider model for tests."""
    capabilities = ModelCapabilities()
    if supported_builtin_tools is not None:
        capabilities.built_in_tools.supported = supported_builtin_tools
    return _ProviderModel(
        provider=provider,
        model_identifier=model_identifier,
        capabilities=capabilities,
    )


def _make_context(
    *,
    supported_builtin_tools: list[str] | None = None,
    provider: LLMProvider = LLMProvider.OPENAI,
) -> BuiltinToolValidationContext:
    """Create a validation context for tests."""
    return BuiltinToolValidationContext(
        provider_model=_make_provider_model(
            supported_builtin_tools=(
                ["web_search"]
                if supported_builtin_tools is None
                else supported_builtin_tools
            ),
            provider=provider,
        )
    )


class TestValidateBuiltinTools:
    """validate_builtin_tools() tests."""

    def test_valid_web_search(self) -> None:
        """Return no errors for supported web search."""
        errors = validate_builtin_tools(
            [BuiltinToolConfig(name="web_search")],
            _make_context(supported_builtin_tools=["web_search"]),
        )

        assert errors == {}

    def test_valid_image_generation(self) -> None:
        """Return no errors for supported image generation."""
        errors = validate_builtin_tools(
            [BuiltinToolConfig(name="image_generation")],
            _make_context(supported_builtin_tools=["image_generation"]),
        )

        assert errors == {}

    def test_unknown_tool(self) -> None:
        """Reject unimplemented built-in tools."""
        errors = validate_builtin_tools(
            [BuiltinToolConfig(name="web_fetch")],
            _make_context(),
        )

        assert errors == {"web_fetch": ["Unknown built-in tool: 'web_fetch'"]}

    def test_empty_tools(self) -> None:
        """Return no errors for an explicit all-off configuration."""
        assert validate_builtin_tools([], _make_context()) == {}


class TestImageGenerationRule:
    """ImageGenerationRule validation tests."""

    def test_supported_provider_models(self) -> None:
        """Accept image generation whenever the capability advertises it."""
        for provider in (
            LLMProvider.OPENAI,
            LLMProvider.CHATGPT_OAUTH,
        ):
            errors = ImageGenerationRule().validate(
                _make_context(
                    supported_builtin_tools=["image_generation"],
                    provider=provider,
                )
            )
            assert errors == []

    def test_unsupported_model(self) -> None:
        """Reject a model without the image generation capability."""
        errors = ImageGenerationRule().validate(
            _make_context(supported_builtin_tools=[]),
        )

        assert errors == ["Model 'gpt-5' does not support Image Generation."]


class TestWebSearchRule:
    """WebSearchRule validation tests."""

    def test_supported_provider_models(self) -> None:
        """Accept web search whenever the normalized capability advertises it."""
        for provider in (
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC,
            LLMProvider.GOOGLE_GEMINI,
            LLMProvider.GOOGLE_VERTEX_AI,
        ):
            errors = WebSearchRule().validate(
                _make_context(
                    supported_builtin_tools=["web_search"],
                    provider=provider,
                )
            )
            assert errors == []

    def test_unsupported_model(self) -> None:
        """Reject a model without the web search capability."""
        errors = WebSearchRule().validate(
            _make_context(supported_builtin_tools=[]),
        )

        assert errors == ["Model 'gpt-5' does not support Web Search."]
