"""Built-in tool validation rules.

Each built-in tool implements BuiltinToolRule to validate compatibility when
configuring an Agent.
"""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Protocol


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


BUILTIN_TOOL_RULES: dict[str, BuiltinToolRule] = {
    "web_search": WebSearchRule(),
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
