"""Built-in tool validation rule tests."""

import dataclasses
from typing import Literal

import pytest

from azents.core.agent import BuiltinToolConfig
from azents.core.builtin_tools import (
    BuiltinToolValidationContext,
    ImageGenerationRule,
    WebSearchRule,
    builtin_tool_configurable,
    supported_builtin_capabilities,
    validate_builtin_tools,
)
from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_contract import (
    BuiltinToolSupport,
    CapabilitySupport,
    SupportPredicate,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize("function_calling", [True, False])
def test_xai_client_image_support_is_independent_of_hosted_image_metadata(
    provider: LLMProvider, function_calling: bool
) -> None:
    """The Imagine client tool requires function calling, not hosted images."""
    supported = supported_builtin_capabilities(
        provider=provider,
        model_identifier="grok-4",
        metadata={
            "mode": "chat",
            "supports_function_calling": function_calling,
            "supports_image_generation": False,
        },
    )

    assert ("image_generation" in supported) is function_calling


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


@pytest.mark.parametrize("tool", ["web_search", "image_generation"])
@pytest.mark.parametrize(
    ("support", "configurable"),
    [
        (CapabilitySupport(state="supported", origin="explicit", predicate=None), True),
        (
            CapabilitySupport(
                state="conditional",
                origin="explicit",
                predicate=SupportPredicate(
                    reasoning_efforts=("none",), function_tools=True
                ),
            ),
            True,
        ),
        (
            CapabilitySupport(state="unsupported", origin="explicit", predicate=None),
            False,
        ),
        (CapabilitySupport(state="unknown", origin=None, predicate=None), False),
    ],
)
def test_v2_configuration_potential_is_separate_from_dispatch_authorization(
    tool: Literal["web_search", "image_generation"],
    support: CapabilitySupport,
    configurable: bool,
) -> None:
    capabilities = project_capabilities(
        provider=LLMProvider.OPENAI,
        exact_model="exact-selected-model",
        source_model=None,
        evidence=None,
        model_developer=None,
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={"built_in_tools": (BuiltinToolSupport(tool=tool, support=support),)}
    )
    # Configuration potential comes from the versioned fact, independent of its
    # conservative effective view; dispatch still evaluates the actual predicate.
    capabilities.built_in_tools.supported = [] if configurable else [tool]
    context = BuiltinToolValidationContext(
        provider_model=_ProviderModel(
            provider=LLMProvider.OPENAI,
            model_identifier="exact-selected-model",
            capabilities=capabilities,
        )
    )
    assert builtin_tool_configurable(capabilities, tool=tool) is configurable
    errors = validate_builtin_tools([BuiltinToolConfig(name=tool)], context)
    assert (not errors) is configurable


def test_missing_v2_hosted_declaration_does_not_use_legacy_list_as_authority() -> None:
    capabilities = project_capabilities(
        provider=LLMProvider.OPENAI,
        exact_model="exact-selected-model",
        source_model=None,
        evidence=None,
        model_developer=None,
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={"built_in_tools": ()}
    )
    capabilities.built_in_tools.supported = ["web_search"]
    assert not builtin_tool_configurable(capabilities, tool="web_search")


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
    ],
)
def test_route_projected_client_image_is_configurable_despite_hosted_denial(
    provider: LLMProvider,
) -> None:
    capabilities = project_capabilities(
        provider=provider,
        exact_model="exact-client-image-model",
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            client_image_generation=CatalogFact(state="value", value=True),
            hosted_image_generation=CatalogFact(state="value", value=False),
        ),
        model_developer=None,
    )
    assert capabilities.semantic_contract is not None
    image = next(
        fact
        for fact in capabilities.semantic_contract.built_in_tools
        if fact.tool == "image_generation"
    )
    assert image.support.state == "supported"
    assert builtin_tool_configurable(capabilities, tool="image_generation")
    context = BuiltinToolValidationContext(
        provider_model=_ProviderModel(
            provider=provider,
            model_identifier="exact-client-image-model",
            capabilities=capabilities,
        )
    )
    assert ImageGenerationRule().validate(context) == []
