"""Resolve selected built-in capabilities to runtime execution ownership."""

import dataclasses
from collections.abc import Sequence

from azents.core.enums import LLMProvider
from azents.engine.run.types import BuiltinToolSpec


class UnsupportedRequiredBuiltinToolError(ValueError):
    """Raised when a required built-in capability has no supported implementation."""


class ClientBuiltinToolImplementationUnavailableError(ValueError):
    """Raised when a selected client built-in has not been bound to this run."""


@dataclasses.dataclass(frozen=True)
class ResolvedBuiltinTools:
    """Built-in tools partitioned by runtime execution ownership."""

    provider_hosted: list[BuiltinToolSpec]
    client_executed: list[BuiltinToolSpec]


def resolve_builtin_tools(
    *,
    selected: Sequence[BuiltinToolSpec],
    provider: LLMProvider,
    supported: Sequence[str],
) -> ResolvedBuiltinTools:
    """Resolve semantic built-in selections for the selected model provider."""
    supported_names = set(supported)
    provider_hosted: list[BuiltinToolSpec] = []
    client_executed: list[BuiltinToolSpec] = []

    for tool in selected:
        if tool.name not in supported_names:
            msg = f"Required builtin tool is not supported: {tool.name}"
            raise UnsupportedRequiredBuiltinToolError(msg)

        match tool.name:
            case "web_search":
                provider_hosted.append(tool)
            case "image_generation":
                if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
                    client_executed.append(tool)
                else:
                    provider_hosted.append(tool)
            case _:
                msg = f"Required builtin tool is not implemented: {tool.name}"
                raise UnsupportedRequiredBuiltinToolError(msg)

    return ResolvedBuiltinTools(
        provider_hosted=provider_hosted,
        client_executed=client_executed,
    )
