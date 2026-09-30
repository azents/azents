"""Exact semantic-model lookup in the retained validated metadata source."""

import dataclasses
from collections.abc import Mapping
from typing import Any, assert_never

from azents.core.enums import LLMProvider


@dataclasses.dataclass(frozen=True)
class SourceModelMetadata:
    """One exact retained-source match without execution identifier rewriting."""

    source_model_key: str
    metadata: Mapping[str, Any]


def lookup_model_source_metadata(
    *,
    provider: LLMProvider,
    model_identifier: str,
    payload: Mapping[str, Any],
) -> SourceModelMetadata | None:
    """Match a saved semantic provider/model against source-owned keys.

    :param provider: saved semantic provider identity
    :param model_identifier: exact saved provider model identifier
    :param payload: validated source snapshot payload, including expanded aliases
    :returns: the exact matching source key and metadata, or no match
    """
    keys = _source_keys(provider, model_identifier)
    for key in keys:
        metadata = payload.get(key)
        if isinstance(metadata, dict) and source_provider_matches(
            provider, key, metadata
        ):
            return SourceModelMetadata(source_model_key=key, metadata=metadata)
    return None


def source_provider_matches(
    provider: LLMProvider,
    source_model_key: str,
    metadata: Mapping[str, object],
) -> bool:
    """Keep bare model matches from borrowing another provider's metadata.

    :param provider: authoritative selected provider identity
    :param source_model_key: exact source candidate, not a rewritten execution ID
    :param metadata: candidate fields from the validated retained source
    :returns: whether provider identity is consistent with the candidate
    """
    source_provider = metadata.get("litellm_provider")
    if source_provider is None:
        return True
    families: Mapping[LLMProvider, frozenset[str]] = {
        LLMProvider.OPENAI: frozenset({"openai"}),
        LLMProvider.CHATGPT_OAUTH: frozenset({"openai"}),
        LLMProvider.ANTHROPIC: frozenset({"anthropic"}),
        LLMProvider.GOOGLE_GEMINI: frozenset({"gemini"}),
        LLMProvider.XAI: frozenset({"xai"}),
        LLMProvider.XAI_OAUTH: frozenset({"xai"}),
        LLMProvider.KIMI_OAUTH: frozenset({"moonshot"}),
        LLMProvider.AWS_BEDROCK: frozenset({"bedrock", "bedrock_converse"}),
        LLMProvider.GOOGLE_VERTEX_AI: frozenset(
            {"vertex_ai", "vertex_ai-anthropic", "vertex_ai-google"}
        ),
        LLMProvider.OPENROUTER: frozenset({"openrouter"}),
    }
    if any(
        source_model_key.startswith(f"{namespace}/") for namespace in families[provider]
    ):
        return True
    return isinstance(source_provider, str) and source_provider in families[provider]


def source_max_input_tokens(metadata: SourceModelMetadata | None) -> int | None:
    """Read a positive source maximum without coercing booleans or strings.

    :param metadata: optional exact retained-source model match
    :returns: positive input-token maximum or unknown metadata
    """
    if metadata is None:
        return None
    value = metadata.metadata.get("max_input_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _source_keys(provider: LLMProvider, model_identifier: str) -> tuple[str, ...]:
    """Apply only explicit source namespaces; never strip model-ID segments."""
    match provider:
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            return model_identifier, f"openai/{model_identifier}"
        case LLMProvider.ANTHROPIC:
            return f"anthropic/{model_identifier}", model_identifier
        case LLMProvider.GOOGLE_GEMINI:
            return f"gemini/{model_identifier}", model_identifier
        case LLMProvider.AWS_BEDROCK:
            return (f"bedrock/{model_identifier}",)
        case LLMProvider.GOOGLE_VERTEX_AI:
            return (f"vertex_ai/{model_identifier}",)
        case LLMProvider.XAI | LLMProvider.XAI_OAUTH:
            return (f"xai/{model_identifier}",)
        case LLMProvider.KIMI_OAUTH:
            return (f"moonshot/{model_identifier}",)
        case LLMProvider.OPENROUTER:
            return (f"openrouter/{model_identifier}",)
        case _ as unreachable:
            assert_never(unreachable)
