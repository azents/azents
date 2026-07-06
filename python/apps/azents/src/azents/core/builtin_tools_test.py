"""Built-in tool validation rule tests."""

import dataclasses

from azents.core.agent import BuiltinToolConfig
from azents.core.builtin_tools import (
    BuiltinToolValidationContext,
    ImageGenerationRule,
    WebFetchRule,
    WebSearchRule,
    validate_builtin_tools,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
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
    provider: LLMProvider = LLMProvider.GOOGLE_GEMINI,
    model_identifier: str = "gemini-2.5-flash",
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
    shell_enabled: bool = False,
    has_toolkits: bool = False,
    supported_builtin_tools: list[str] | None = None,
    provider: LLMProvider = LLMProvider.GOOGLE_GEMINI,
    all_builtin_tools: list[str] | None = None,
    model_developer: LLMModelDeveloper | None = None,
) -> BuiltinToolValidationContext:
    """Create BuiltinToolValidationContext for tests."""
    if supported_builtin_tools is None:
        supported_builtin_tools = ["web_search"]
    return BuiltinToolValidationContext(
        shell_enabled=shell_enabled,
        has_toolkits=has_toolkits,
        provider_model=_make_provider_model(
            supported_builtin_tools=supported_builtin_tools,
            provider=provider,
        ),
        model_developer=model_developer,
        all_builtin_tools=all_builtin_tools or [],
    )


# -------------------------------------------------------------------
# validate_builtin_tools
# -------------------------------------------------------------------


class TestValidateBuiltinTools:
    """validate_builtin_tools() tests."""

    def test_valid_tools(self) -> None:
        """Return empty dict for valid settings."""
        # Given: valid web_search setting
        tools = [BuiltinToolConfig(name="web_search")]
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
        )

        # When: validation
        errors = validate_builtin_tools(tools, ctx)

        # Then: no errors
        assert errors == {}

    def test_unknown_tool(self) -> None:
        """Error when tool name is unknown."""
        # Given: nonexistent tool
        tools = [BuiltinToolConfig(name="nonexistent")]
        ctx = _make_context()

        # When: validation
        errors = validate_builtin_tools(tools, ctx)

        # Then: unknown tool error
        assert "nonexistent" in errors
        assert any("Unknown" in e for e in errors["nonexistent"])

    def test_empty_tools(self) -> None:
        """Return empty dict for empty list."""
        # Given: empty list
        tools: list[BuiltinToolConfig] = []
        ctx = _make_context()

        # When: validation
        errors = validate_builtin_tools(tools, ctx)

        # Then: no errors
        assert errors == {}

    def test_web_search_valid(self) -> None:
        """Return empty dict when web_search setting is valid."""
        # Given: valid web_search setting (OpenAI)
        tools = [BuiltinToolConfig(name="web_search")]
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.OPENAI,
        )

        # When: validation
        errors = validate_builtin_tools(tools, ctx)

        # Then: no errors
        assert errors == {}


# -------------------------------------------------------------------
# WebSearchRule
# -------------------------------------------------------------------


class TestWebSearchRule:
    """WebSearchRule validation tests."""

    def test_valid_openai(self) -> None:
        """No errors when web_search is valid on OpenAI model."""
        # Given: OpenAI provider with web_search support
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.OPENAI,
        )
        rule = WebSearchRule()

        # When: validation
        errors = rule.validate(ctx)

        # Then: no errors
        assert errors == []

    def test_valid_anthropic(self) -> None:
        """No errors when web_search is valid on Anthropic model."""
        # Given: Anthropic provider with web_search support
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.ANTHROPIC,
        )
        rule = WebSearchRule()

        # When: validation
        errors = rule.validate(ctx)

        # Then: no errors
        assert errors == []

    def test_valid_gemini(self) -> None:
        """No errors when Gemini model has web_search capability."""
        # Given: Gemini provider with valid setting
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.GOOGLE_GEMINI,
            shell_enabled=False,
            has_toolkits=False,
            model_developer=LLMModelDeveloper.GOOGLE,
        )
        rule = WebSearchRule()

        # When: validation
        errors = rule.validate(ctx)

        # Then: no errors
        assert errors == []

    def test_unsupported_model(self) -> None:
        """Error when model does not support web_search."""
        # Given: model without web_search support
        ctx = _make_context(
            supported_builtin_tools=[],
            provider=LLMProvider.OPENAI,
        )

        # When: validation
        errors = WebSearchRule().validate(ctx)

        # Then: model incompatibility error
        assert len(errors) == 1
        assert "does not support" in errors[0]

    def test_openai_no_exclusive_constraints(self) -> None:
        """OpenAI has no shell/toolkit/agent role constraints."""
        # Given: OpenAI, agent role + shell + toolkits, which would error on Gemini
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.OPENAI,
            shell_enabled=True,
            has_toolkits=True,
        )

        # When: validation
        errors = WebSearchRule().validate(ctx)

        # Then: no errors (OpenAI has no exclusivity constraints)
        assert errors == []

    def test_anthropic_no_exclusive_constraints(self) -> None:
        """Anthropic has no shell/toolkit/agent role constraints."""
        # Given: Anthropic, agent role + shell + toolkits
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.ANTHROPIC,
            shell_enabled=True,
            has_toolkits=True,
        )

        # When: validation
        errors = WebSearchRule().validate(ctx)

        # Then: no errors
        assert errors == []

    def test_gemini_no_exclusive_constraints(self) -> None:
        """Gemini web_search has no shell/toolkit/agent role constraints."""
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.GOOGLE_GEMINI,
            shell_enabled=True,
            has_toolkits=True,
            model_developer=LLMModelDeveloper.GOOGLE,
        )

        errors = WebSearchRule().validate(ctx)

        assert errors == []

    def test_gemini_other_builtin_tools_allowed_by_web_search_rule(self) -> None:
        """web_search rule does not forbid combinations with other builtin tools."""
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.GOOGLE_GEMINI,
            all_builtin_tools=["web_search", "image_generation"],
            model_developer=LLMModelDeveloper.GOOGLE,
        )

        errors = WebSearchRule().validate(ctx)

        assert errors == []

    def test_gemini_multiple_errors(self) -> None:
        """Even on Gemini, only unsupported capability returns web_search error."""
        ctx = _make_context(
            supported_builtin_tools=[],
            provider=LLMProvider.GOOGLE_GEMINI,
            shell_enabled=True,
            has_toolkits=True,
            model_developer=LLMModelDeveloper.GOOGLE,
        )

        # When: validation
        errors = WebSearchRule().validate(ctx)

        assert len(errors) == 1
        assert "does not support" in errors[0]

    def test_vertex_ai_google_vendor_uses_gemini_constraints(self) -> None:
        """Vertex AI Google models also have no exclusivity constraints."""
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.GOOGLE_VERTEX_AI,
            model_developer=LLMModelDeveloper.GOOGLE,
        )

        errors = WebSearchRule().validate(ctx)

        assert errors == []

    def test_vertex_ai_anthropic_vendor_skips_gemini_constraints(self) -> None:
        """Gemini exclusivity constraints do not apply to Vertex AI Anthropic models."""
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.GOOGLE_VERTEX_AI,
            model_developer=LLMModelDeveloper.ANTHROPIC,
        )

        errors = WebSearchRule().validate(ctx)

        assert errors == []

    def test_openai_other_builtin_tools_allowed(self) -> None:
        """OpenAI can be used with other builtin tools."""
        # Given: OpenAI, web_search + another builtin tool
        ctx = _make_context(
            supported_builtin_tools=["web_search"],
            provider=LLMProvider.OPENAI,
            all_builtin_tools=["web_search", "image_generation"],
        )

        # When: validation
        errors = WebSearchRule().validate(ctx)

        # Then: no errors
        assert errors == []


# -------------------------------------------------------------------
# ImageGenerationRule
# -------------------------------------------------------------------


class TestImageGenerationRule:
    """ImageGenerationRule validation tests."""

    def test_valid_openai(self) -> None:
        """No errors when image_generation is valid on OpenAI model."""
        # Given: OpenAI provider with image_generation support
        ctx = _make_context(
            supported_builtin_tools=["image_generation"],
            provider=LLMProvider.OPENAI,
        )
        rule = ImageGenerationRule()

        # When: validation
        errors = rule.validate(ctx)

        # Then: no errors
        assert errors == []

    def test_unsupported_model(self) -> None:
        """Error when model does not support image_generation."""
        # Given: model without image_generation support
        ctx = _make_context(
            supported_builtin_tools=[],
            provider=LLMProvider.OPENAI,
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: model incompatibility error
        assert len(errors) == 1
        assert "does not support" in errors[0]

    def test_valid_gemini(self) -> None:
        """No errors for valid setting on Gemini."""
        # Given: Gemini, only image_generation enabled, shell/reasoning disabled
        ctx = BuiltinToolValidationContext(
            shell_enabled=False,
            has_toolkits=False,
            provider_model=_make_provider_model(
                supported_builtin_tools=["image_generation"],
                provider=LLMProvider.GOOGLE_GEMINI,
            ),
            model_developer=LLMModelDeveloper.GOOGLE,
            reasoning_enabled=False,
            all_builtin_tools=["image_generation"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: no errors
        assert errors == []

    def test_gemini_other_builtin_tools(self) -> None:
        """Error when Gemini has another builtin tool."""
        # Given: Gemini, image_generation + web_search
        ctx = BuiltinToolValidationContext(
            shell_enabled=False,
            has_toolkits=False,
            provider_model=_make_provider_model(
                supported_builtin_tools=["image_generation", "web_search"],
                provider=LLMProvider.GOOGLE_GEMINI,
            ),
            model_developer=LLMModelDeveloper.GOOGLE,
            reasoning_enabled=False,
            all_builtin_tools=["image_generation", "web_search"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: another builtin tool error
        assert any("No other built-in tools" in e for e in errors)

    def test_gemini_shell_enabled(self) -> None:
        """Error when shell is enabled on Gemini."""
        # Given: Gemini, shell enabled
        ctx = BuiltinToolValidationContext(
            shell_enabled=True,
            has_toolkits=False,
            provider_model=_make_provider_model(
                supported_builtin_tools=["image_generation"],
                provider=LLMProvider.GOOGLE_GEMINI,
            ),
            model_developer=LLMModelDeveloper.GOOGLE,
            reasoning_enabled=False,
            all_builtin_tools=["image_generation"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: shell disabled error
        assert any("Shell must be disabled" in e for e in errors)

    def test_gemini_reasoning_enabled(self) -> None:
        """Error when reasoning is enabled on Gemini."""
        # Given: Gemini, reasoning enabled
        ctx = BuiltinToolValidationContext(
            shell_enabled=False,
            has_toolkits=False,
            provider_model=_make_provider_model(
                supported_builtin_tools=["image_generation"],
                provider=LLMProvider.GOOGLE_GEMINI,
            ),
            model_developer=LLMModelDeveloper.GOOGLE,
            reasoning_enabled=True,
            all_builtin_tools=["image_generation"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: reasoning disabled error
        assert any("Reasoning must be disabled" in e for e in errors)

    def test_gemini_multiple_errors(self) -> None:
        """Return all errors when multiple Gemini constraints are violated at once."""
        # Given: all Gemini constraints violated
        ctx = BuiltinToolValidationContext(
            shell_enabled=True,
            has_toolkits=False,
            provider_model=_make_provider_model(
                supported_builtin_tools=[],
                provider=LLMProvider.GOOGLE_GEMINI,
            ),
            model_developer=LLMModelDeveloper.GOOGLE,
            reasoning_enabled=True,
            all_builtin_tools=["image_generation", "web_search"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: 4 errors: unsupported + other builtin + shell + reasoning
        assert len(errors) == 4

    def test_openai_no_exclusive_constraints(self) -> None:
        """Gemini exclusivity constraints do not apply on OpenAI."""
        # Given: OpenAI, shell + reasoning, which would error on Gemini
        ctx = BuiltinToolValidationContext(
            shell_enabled=True,
            has_toolkits=True,
            provider_model=_make_provider_model(
                supported_builtin_tools=["image_generation"],
                provider=LLMProvider.OPENAI,
            ),
            reasoning_enabled=True,
            all_builtin_tools=["image_generation", "web_search"],
        )

        # When: validation
        errors = ImageGenerationRule().validate(ctx)

        # Then: no errors
        assert errors == []


class TestWebFetchRule:
    """WebFetchRule validation tests."""

    def test_valid_anthropic(self) -> None:
        """No errors when web_fetch is valid on Anthropic model."""
        ctx = _make_context(
            supported_builtin_tools=["web_fetch"],
            provider=LLMProvider.ANTHROPIC,
        )

        errors = WebFetchRule().validate(ctx)

        assert errors == []

    def test_unsupported_model(self) -> None:
        """Error when model does not support web_fetch."""
        ctx = _make_context(
            supported_builtin_tools=[],
            provider=LLMProvider.ANTHROPIC,
        )

        errors = WebFetchRule().validate(ctx)

        assert len(errors) == 1
        assert "does not support" in errors[0]
