"""Built-in tool validation rules.

Each built-in tool implements BuiltinToolRule to validate compatibility when
configuring an Agent.
"""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import ClassVar, Protocol

from azents.core.enums import LLMProvider


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
    """Read configuration potential from the final supported-tool list.

    Saved request constraints are evaluated only at actual dispatch. Configuration
    does not invent an effort or function-tool context to filter supported choices.

    :param capabilities: the selected model's saved capability snapshot
    :param tool: the route-projected built-in capability name
    :returns: whether the saved facts allow this tool to be configured
    """
    return tool in capabilities.built_in_tools.supported


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


def supported_builtin_capabilities(
    *,
    provider: LLMProvider,
    model_identifier: str,
    metadata: Mapping[str, object],
) -> list[str]:
    """Return built-in tools supported by trusted provider metadata and policy."""
    supported: list[str] = []
    if metadata.get("supports_web_search") is True or (
        provider == LLMProvider.CHATGPT_OAUTH
        and metadata.get("supports_web_search") is not False
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
    if provider in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
    }:
        # This is a registered client executor, not a hosted model output form.
        # Its request owner needs a supported function route and conversation
        # mode; similarly named models do not establish either prerequisite.
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
