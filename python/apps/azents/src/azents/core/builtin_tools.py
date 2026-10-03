"""Built-in tool validation rules.

Each built-in tool implements BuiltinToolRule to validate compatibility when
configuring an Agent.
"""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import ClassVar, Protocol

from azents.core.enums import LLMProvider
from azents.core.model_capability_contract import ModelCapabilityContract


class BuiltinToolConfigLike(Protocol):
    """Fields required for built-in tool settings."""

    @property
    def name(self) -> str:
        """Built-in tool name."""
        ...


class BuiltinToolCapabilities(Protocol):
    """Built-in tool capability fields."""

    @property
    def supported(self) -> list[str]:
        """List of supported built-in tool names."""
        ...


class BuiltinToolModelCapabilities(Protocol):
    """Capability fields required for built-in tool validation."""

    @property
    def semantic_contract(self) -> ModelCapabilityContract | None:
        """Versioned saved support, absent for historical snapshots."""
        ...

    @property
    def built_in_tools(self) -> BuiltinToolCapabilities:
        """Built-in tool capability."""
        ...


class BuiltinToolProviderModel(Protocol):
    """Provider model fields required for built-in tool validation."""

    @property
    def model_identifier(self) -> str:
        """Provider model identifier."""
        ...

    @property
    def capabilities(self) -> BuiltinToolModelCapabilities:
        """Model capability."""
        ...


@dataclasses.dataclass(frozen=True)
class BuiltinToolValidationContext:
    """Context required for validation."""

    provider_model: BuiltinToolProviderModel


class BuiltinToolRule(ABC):
    """Base for built-in tool validation rules.

    Each built-in tool inherits this class to validate compatibility when
    configuring an Agent.
    """

    name: ClassVar[str]

    @abstractmethod
    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Run validation. Return error messages; an empty list means pass."""
        ...


def builtin_tool_configurable(
    capabilities: BuiltinToolModelCapabilities, *, tool: str
) -> bool:
    """Check configuration potential without inventing a request context.

    Save and preparation have no effective effort or actual function declarations.
    A known conditional fact permits configuration, not dispatch authorization.
    Runtime lowerers evaluate its saved predicate before sending the request.
    Historical snapshots retain their unconditional-list compatibility.

    :param capabilities: the selected model's saved capability snapshot
    :param tool: the route-projected built-in capability name
    :returns: whether the saved facts allow this tool to be configured
    """
    contract = capabilities.semantic_contract
    if contract is None:
        return tool in capabilities.built_in_tools.supported
    return any(
        declaration.tool == tool
        and declaration.support.state in {"supported", "conditional"}
        for declaration in contract.built_in_tools
    )


class WebSearchRule(BuiltinToolRule):
    """Web Search: unified web search tool routed automatically by provider format.

    Runtime lowerers handle provider-specific native activation. At Agent save
    time, only model capability compatibility is checked.
    """

    name = "web_search"

    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Validate Web Search compatibility."""
        if builtin_tool_configurable(ctx.provider_model.capabilities, tool=self.name):
            return []
        return [
            f"Model '{ctx.provider_model.model_identifier}'"
            " does not support Web Search."
        ]


class ImageGenerationRule(BuiltinToolRule):
    """Image Generation: route-projected image creation capability."""

    name = "image_generation"

    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Validate Image Generation compatibility."""
        if builtin_tool_configurable(ctx.provider_model.capabilities, tool=self.name):
            return []
        return [
            f"Model '{ctx.provider_model.model_identifier}'"
            " does not support Image Generation."
        ]


BUILTIN_TOOL_RULES: dict[str, BuiltinToolRule] = {
    "web_search": WebSearchRule(),
    "image_generation": ImageGenerationRule(),
}
"""Registered built-in tool validation rule registry."""

_IMAGE_GENERATION_OPENAI_MODEL_PREFIXES = (
    "gpt-6",
    "gpt-5",
    "gpt-4.1",
    "gpt-4o",
    "o3",
)


def supported_builtin_capabilities(
    *,
    provider: LLMProvider,
    model_identifier: str,
    metadata: Mapping[str, object],
) -> list[str]:
    """Return built-in tools supported by trusted provider metadata and policy."""
    supported: list[str] = []
    if (
        metadata.get("supports_web_search") is True
        or provider == LLMProvider.CHATGPT_OAUTH
    ):
        supported.append("web_search")
    if _supports_image_generation(
        provider=provider,
        model_identifier=model_identifier,
        metadata=metadata,
    ):
        supported.append("image_generation")
    return supported


def _supports_image_generation(
    *,
    provider: LLMProvider,
    model_identifier: str,
    metadata: Mapping[str, object],
) -> bool:
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        if metadata.get("supports_function_calling") is False:
            return False
        if metadata.get("mode") not in {None, "chat", "responses"}:
            return False
        normalized = model_identifier.removeprefix("openai/").lower()
        return normalized.startswith(_IMAGE_GENERATION_OPENAI_MODEL_PREFIXES) or any(
            _string_sequence_contains(metadata.get(key), "image_generation")
            for key in ("supported_builtin_tools", "experimental_supported_tools")
        )

    if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
        return (
            metadata.get("mode") in {"chat", "responses"}
            and metadata.get("supports_function_calling") is True
        )

    explicit = metadata.get("supports_image_generation")
    if isinstance(explicit, bool):
        return explicit

    for key in ("supported_builtin_tools", "experimental_supported_tools"):
        value = metadata.get(key)
        if _string_sequence_contains(value, "image_generation"):
            return True

    return False


def _string_sequence_contains(value: object, expected: str) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    return any(item == expected for item in value)


def validate_builtin_tools(
    builtin_tools: Sequence[BuiltinToolConfigLike],
    context: BuiltinToolValidationContext,
) -> dict[str, list[str]]:
    """Run validation for every built-in tool.

    :param builtin_tools: Built-in tool settings to validate
    :param context: Validation context
    :return: Mapping of tool name to error messages; empty dict when there are no errors
    """
    errors: dict[str, list[str]] = {}
    for bt in builtin_tools:
        rule = BUILTIN_TOOL_RULES.get(bt.name)
        if rule is None:
            errors.setdefault(bt.name, []).append(f"Unknown built-in tool: '{bt.name}'")
            continue
        tool_errors = rule.validate(context)
        if tool_errors:
            errors[bt.name] = tool_errors
    return errors
