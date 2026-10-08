"""Explicit producer-address formats for exact hosting/API source identities."""

import dataclasses
from typing import assert_never

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import CatalogSourceModel, CatalogSourcePayload


class CatalogIdentityError(ValueError):
    """More than one adopted source record claims one execution identity."""


@dataclasses.dataclass(frozen=True)
class ScopedCatalogModel:
    """One source record and its exact provider-native execution identifier."""

    execution_model_identifier: str
    source_model: CatalogSourceModel


@dataclasses.dataclass(frozen=True)
class CatalogSourceIdentity:
    """Exact adopted source address, including an explicitly absent record."""

    provider: str
    source_model_key: str


def catalog_source_keys(
    *, provider: LLMProvider, model_identifier: str
) -> tuple[CatalogSourceIdentity, ...]:
    """Plan exact source reads using the existing literal namespace contract."""
    if not model_identifier or not _canonical_bare(provider, model_identifier):
        return ()
    namespaces = (
        "openai",
        "anthropic",
        "gemini",
        "bedrock_converse",
        "vertex_ai",
        "vertex_ai-language-models",
        "vertex_ai-anthropic_models",
        "chatgpt",
        "xai",
        "xai_oauth",
        "kimi_oauth",
        "openrouter",
    )
    return tuple(
        CatalogSourceIdentity(
            provider=namespace,
            source_model_key=f"{_address_prefix(provider)}{model_identifier}",
        )
        for namespace in namespaces
        if provider_namespace_matches(provider, namespace)
    )


def provider_namespace_matches(provider: LLMProvider, source_provider: str) -> bool:
    """Check host/API scope without equating native, OAuth, or cloud deployments."""
    match provider:
        case LLMProvider.OPENAI:
            return source_provider == "openai"
        case LLMProvider.ANTHROPIC:
            return source_provider == "anthropic"
        case LLMProvider.GOOGLE_GEMINI:
            return source_provider == "gemini"
        case LLMProvider.AWS_BEDROCK:
            return source_provider == "bedrock_converse"
        case LLMProvider.GOOGLE_VERTEX_AI:
            return source_provider in {
                "vertex_ai",
                "vertex_ai-language-models",
                "vertex_ai-anthropic_models",
            }
        case LLMProvider.CHATGPT_OAUTH:
            return source_provider == "chatgpt"
        case LLMProvider.XAI:
            return source_provider == "xai"
        case LLMProvider.XAI_OAUTH:
            return source_provider == "xai_oauth"
        case LLMProvider.KIMI_OAUTH:
            return source_provider == "kimi_oauth"
        case LLMProvider.OPENROUTER:
            return source_provider == "openrouter"
        case _ as unreachable:
            assert_never(unreachable)


def _address_prefix(provider: LLMProvider) -> str:
    match provider:
        case LLMProvider.OPENAI | LLMProvider.ANTHROPIC | LLMProvider.AWS_BEDROCK:
            return ""
        case LLMProvider.GOOGLE_GEMINI:
            return "gemini/"
        case LLMProvider.GOOGLE_VERTEX_AI:
            return "vertex_ai/"
        case LLMProvider.CHATGPT_OAUTH:
            return "chatgpt/"
        case LLMProvider.XAI:
            return "xai/"
        case LLMProvider.XAI_OAUTH:
            return "xai_oauth/"
        case LLMProvider.KIMI_OAUTH:
            return "kimi_oauth/"
        case LLMProvider.OPENROUTER:
            return "openrouter/"
        case _ as unreachable:
            assert_never(unreachable)


def _canonical_bare(provider: LLMProvider, identifier: str) -> bool:
    """Do not adopt an unverified qualified twin as a bare-source alias."""
    match provider:
        case LLMProvider.OPENAI:
            return not identifier.startswith("openai/")
        case LLMProvider.ANTHROPIC:
            return not identifier.startswith("anthropic/")
        case LLMProvider.AWS_BEDROCK:
            return not identifier.startswith(("bedrock/", "bedrock_converse/"))
        case _:
            return True


def source_model_matches(
    *, provider: LLMProvider, model_identifier: str, source_model: CatalogSourceModel
) -> bool:
    """Compare the adopted producer address without altering the literal model ID."""
    return (
        bool(model_identifier)
        and provider_namespace_matches(provider, source_model.provider)
        and _canonical_bare(provider, model_identifier)
        and source_model.source_key == f"{_address_prefix(provider)}{model_identifier}"
    )


def lookup_catalog_model(
    payload: CatalogSourcePayload, *, provider: LLMProvider, model_identifier: str
) -> CatalogSourceModel | None:
    """Return one unambiguous exact-scoped match; missing matches remain absent."""
    matches = [
        model
        for model in payload.models
        if source_model_matches(
            provider=provider, model_identifier=model_identifier, source_model=model
        )
    ]
    if len(matches) > 1:
        raise CatalogIdentityError("Conflicting canonical catalog identities.")
    return matches[0] if matches else None


def system_catalog_models(
    payload: CatalogSourcePayload, *, provider: LLMProvider
) -> tuple[ScopedCatalogModel, ...]:
    """Enumerate system inventory addresses without price or model-family inference."""
    if provider not in {
        LLMProvider.OPENAI,
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
    }:
        raise ValueError("Provider does not own a system conversation catalog.")
    prefix = _address_prefix(provider)
    selected: dict[str, ScopedCatalogModel] = {}
    for model in payload.models:
        if not provider_namespace_matches(provider, model.provider):
            continue
        if prefix and not model.source_key.startswith(prefix):
            # Noncanonical shorthand rows remain data, not alias authority.
            continue
        identifier = model.source_key[len(prefix) :]
        if not source_model_matches(
            provider=provider, model_identifier=identifier, source_model=model
        ):
            continue
        if identifier in selected:
            raise CatalogIdentityError("Conflicting system catalog identities.")
        selected[identifier] = ScopedCatalogModel(
            execution_model_identifier=identifier, source_model=model
        )
    return tuple(selected[identifier] for identifier in sorted(selected))
