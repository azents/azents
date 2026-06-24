"""Built-in tool validation rules.

Each built-in tool implements BuiltinToolRule to validate compatibility when
configuring an Agent.
"""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Protocol

from azents.core.enums import AgentRole, LLMModelDeveloper


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

    agent_role: AgentRole
    shell_enabled: bool
    has_toolkits: bool
    provider_model: BuiltinToolProviderModel
    model_developer: LLMModelDeveloper | None = None
    all_builtin_tools: list[str] = dataclasses.field(default_factory=list)
    reasoning_enabled: bool = False


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


class WebSearchRule(BuiltinToolRule):
    """Web Search: unified web search tool routed automatically by provider format.

    Runtime lowerers handle provider-specific native activation. At Agent save
    time, only model capability compatibility is checked.
    """

    name = "web_search"

    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Validate Web Search compatibility."""
        errors: list[str] = []

        # Provider compatibility
        supported = ctx.provider_model.capabilities.built_in_tools.supported
        if self.name not in supported:
            errors.append(
                f"Model '{ctx.provider_model.model_identifier}'"
                " does not support Web Search."
            )

        return errors


class ImageGenerationRule(BuiltinToolRule):
    """Image Generation: provider compatibility validation and Gemini exclusivity.

    Gemini cannot be used with other builtin tools, requires shell disabled, and
    requires reasoning disabled.
    """

    name = "image_generation"

    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Validate Image Generation compatibility."""
        errors: list[str] = []

        # Provider compatibility
        supported = ctx.provider_model.capabilities.built_in_tools.supported
        if self.name not in supported:
            errors.append(
                f"Model '{ctx.provider_model.model_identifier}'"
                " does not support image generation."
            )

        # Gemini: exclusivity constraints
        if ctx.model_developer == LLMModelDeveloper.GOOGLE:
            other_tools = [t for t in ctx.all_builtin_tools if t != self.name]
            if other_tools:
                errors.append(
                    "No other built-in tools allowed"
                    " when image generation on Gemini is enabled."
                )
            if ctx.shell_enabled:
                errors.append(
                    "Shell must be disabled when image generation on Gemini is enabled."
                )
            if ctx.reasoning_enabled:
                errors.append(
                    "Reasoning must be disabled"
                    " when image generation on Gemini is enabled."
                )

        return errors


class WebFetchRule(BuiltinToolRule):
    """Web Fetch: Anthropic provider-side URL fetch tool."""

    name = "web_fetch"

    def validate(self, ctx: BuiltinToolValidationContext) -> list[str]:
        """Validate Web Fetch compatibility."""
        supported = ctx.provider_model.capabilities.built_in_tools.supported
        if self.name not in supported:
            return [
                f"Model '{ctx.provider_model.model_identifier}'"
                " does not support Web Fetch."
            ]
        return []


BUILTIN_TOOL_RULES: dict[str, BuiltinToolRule] = {
    "web_search": WebSearchRule(),
    "web_fetch": WebFetchRule(),
    "image_generation": ImageGenerationRule(),
}
"""Registered built-in tool validation rule registry."""


def validate_builtin_tools(
    builtin_tools: Sequence[BuiltinToolConfigLike],
    context: BuiltinToolValidationContext,
) -> dict[str, list[str]]:
    """Run validation for every built-in tool.

    :param builtin_tools: Built-in tool settings to validate
    :param context: Validation context
    :return: Mapping of tool name to error messages; empty dict when there are no errors
    """
    ctx = dataclasses.replace(
        context, all_builtin_tools=[bt.name for bt in builtin_tools]
    )
    errors: dict[str, list[str]] = {}
    for bt in builtin_tools:
        rule = BUILTIN_TOOL_RULES.get(bt.name)
        if rule is None:
            errors.setdefault(bt.name, []).append(f"Unknown built-in tool: '{bt.name}'")
            continue
        tool_errors = rule.validate(ctx)
        if tool_errors:
            errors[bt.name] = tool_errors
    return errors
