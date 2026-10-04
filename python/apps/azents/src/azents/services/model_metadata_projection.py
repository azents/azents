"""Pure current conversation projections from exact source and provider evidence."""

import datetime
import importlib.metadata
from collections.abc import Mapping
from typing import assert_never

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import model_freshness_rank
from azents.core.llm_catalog_sync import CatalogProjectionVersion
from azents.core.model_capability_projection import (
    CAPABILITY_PROJECTION_REVISION,
    project_capabilities,
)
from azents.core.model_catalog_identity import (
    catalog_source_keys,
    lookup_catalog_model,
    system_catalog_models,
)
from azents.core.model_catalog_source import CatalogSourceModel
from azents.core.model_pricing import (
    ModelPricingDefinition,
    ModelPricingUnavailableReason,
)
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    protocol_for_provider,
)
from azents.repos.llm_catalog.data import LLMCatalogEntryCreate
from azents.repos.model_metadata_source_data import (
    ModelMetadataSource,
    SourceModelExpectation,
)
from azents.services.model_listing.data import NormalizedModelCandidate
from azents.services.model_listing.providers import _openai_supported_execution_options

MODEL_METADATA_PROJECTION_SCHEMA_VERSION = "2"


def current_catalog_projection_version() -> CatalogProjectionVersion:
    """Report procedural interpretation versions, never a model-data revision."""
    return CatalogProjectionVersion(
        schema_version=MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
        resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    )


_SYSTEM_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
)


class ModelMetadataProjectionError(RuntimeError):
    """Source evidence cannot produce a complete system projection."""


def _pricing(
    source: ModelMetadataSource | None,
    model: CatalogSourceModel | None,
    prices: Mapping[tuple[str, str], ModelPricingDefinition],
) -> ModelPricingDefinition:
    """Copy normalized exact evidence without interpreting prices again."""
    if source is not None and model is not None:
        price = prices.get((model.provider, model.source_key))
        if price is None:
            raise ModelMetadataProjectionError(
                "The source model is missing its normalized pricing definition."
            )
        return price
    return ModelPricingDefinition(
        rules=None,
        unavailable_reason=(
            ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
            if source is None
            else ModelPricingUnavailableReason.MODEL_UNMATCHED
        ),
        source_key=source.source_key if source is not None else None,
        source_model_key=None,
        collected_at=source.collected_at if source is not None else None,
    )


def projection_source_expectations(
    *,
    provider: LLMProvider,
    candidates: list[NormalizedModelCandidate],
    source: ModelMetadataSource | None,
) -> tuple[SourceModelExpectation, ...]:
    """Capture all exact adopted addresses, including currently absent keys."""
    rows = (
        {(item.model.provider, item.model.source_key): item for item in source.models}
        if source is not None
        else {}
    )
    keys = {
        key
        for candidate in candidates
        for key in catalog_source_keys(
            provider=provider, model_identifier=candidate.model_identifier
        )
    }
    return tuple(
        SourceModelExpectation(
            provider=key.provider,
            source_model_key=key.source_model_key,
            current=rows.get((key.provider, key.source_model_key)),
        )
        for key in sorted(keys, key=lambda item: (item.provider, item.source_model_key))
    )


def project_system_entries(
    *,
    provider: LLMProvider,
    source: ModelMetadataSource,
    effective_date: datetime.date,
) -> list[LLMCatalogEntryCreate]:
    """Project exact system inventory without price or name capability gates."""
    if provider not in _SYSTEM_PROVIDERS:
        raise ValueError("Provider does not have a system metadata source.")
    models = system_catalog_models(source.payload, provider=provider)
    prices = {
        (item.model.provider, item.model.source_key): item.pricing
        for item in source.models
    }
    if not models:
        raise ModelMetadataProjectionError(
            f"The model metadata source is missing provider {provider.value}."
        )
    return [
        _project_system_model(
            provider=provider,
            identifier=item.execution_model_identifier,
            model=item.source_model,
            source=source,
            pricing=_pricing(source, item.source_model, prices),
            effective_date=effective_date,
        )
        for item in models
    ]


def project_integration_replacement_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    candidates: list[NormalizedModelCandidate],
    source: ModelMetadataSource | None,
    provider_listing_source: str,
) -> list[LLMCatalogEntryCreate]:
    """Publish provider-visible identifiers with exact presence-aware source facts."""
    entries: list[LLMCatalogEntryCreate] = []
    prices = (
        {
            (item.model.provider, item.model.source_key): item.pricing
            for item in source.models
        }
        if source is not None
        else {}
    )
    for candidate in candidates:
        source_model = (
            lookup_catalog_model(
                source.payload,
                provider=provider,
                model_identifier=candidate.model_identifier,
            )
            if source is not None
            else None
        )
        capabilities = project_capabilities(
            provider=provider,
            exact_model=candidate.model_identifier,
            source_model=source_model,
            evidence=candidate.capability_evidence,
            model_developer=candidate.model_developer,
        )
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=candidate.model_identifier,
                display_name=candidate.model_display_name,
                normalized_capabilities=capabilities.model_dump(mode="json"),
                supported_execution_options=[
                    option.value for option in candidate.supported_execution_options
                ],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                pricing=_pricing(source, source_model, prices),
                source_metadata={
                    "source_kind": source.source_kind if source else None,
                    "source_key": source.source_key if source else None,
                    "source_provider_id": source_model.provider
                    if source_model
                    else None,
                    "source_model_id": source_model.source_key
                    if source_model
                    else None,
                    "provider_listing_source": provider_listing_source,
                    "provider_metadata": candidate.source_metadata,
                    "capability_evidence": (
                        candidate.capability_evidence.model_dump(mode="json")
                        if candidate.capability_evidence is not None
                        else None
                    ),
                },
                projection_metadata={
                    "capability_compiler_revision": CAPABILITY_PROJECTION_REVISION,
                    "matched": source_model is not None,
                    "runtime_dependency_versions": projection_runtime_versions(
                        provider
                    ),
                    "native_protocol": protocol_for_provider(
                        provider=provider, model=candidate.model_identifier
                    ),
                    "source_diagnostics": list(source_model.reasoning.diagnostics)
                    if source_model is not None
                    else [],
                },
                hidden_reason=None,
            )
        )
    return entries


def projection_runtime_versions(provider: LLMProvider) -> dict[str, str]:
    """Describe installed codec dependencies without adopting their model facts."""
    match provider:
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            packages = ("openai",)
        case LLMProvider.ANTHROPIC:
            packages = ("pydantic-ai-slim", "anthropic")
        case LLMProvider.GOOGLE_GEMINI:
            packages = ("pydantic-ai-slim", "google-genai")
        case LLMProvider.GOOGLE_VERTEX_AI:
            packages = ("pydantic-ai-slim", "google-genai", "anthropic")
        case LLMProvider.AWS_BEDROCK:
            packages = ("pydantic-ai-slim", "boto3", "botocore")
        case (
            LLMProvider.XAI
            | LLMProvider.XAI_OAUTH
            | LLMProvider.OPENROUTER
            | LLMProvider.KIMI_OAUTH
        ):
            packages = ("pydantic-ai-slim", "openai")
        case _ as unreachable:
            assert_never(unreachable)
    return {package: importlib.metadata.version(package) for package in packages}


def _project_system_model(
    *,
    provider: LLMProvider,
    identifier: str,
    model: CatalogSourceModel,
    source: ModelMetadataSource,
    pricing: ModelPricingDefinition,
    effective_date: datetime.date,
) -> LLMCatalogEntryCreate:
    deprecated = False
    if model.facts.deprecation_date.value is not None:
        try:
            deprecated = (
                datetime.date.fromisoformat(model.facts.deprecation_date.value)
                <= effective_date
            )
        except ValueError as error:
            raise ModelMetadataProjectionError(
                "The source deprecation date is invalid."
            ) from error
    hidden_reason = _hidden_reason(
        provider=provider, model=model, deprecated=deprecated
    )
    capabilities = project_capabilities(
        provider=provider,
        exact_model=identifier,
        source_model=model,
        evidence=None,
        model_developer=_developer(provider),
    )
    return LLMCatalogEntryCreate(
        provider=provider,
        provider_model_identifier=identifier,
        display_name=model.facts.display_name.value or identifier,
        normalized_capabilities=capabilities.model_dump(mode="json"),
        supported_execution_options=(
            [option.value for option in _openai_supported_execution_options(identifier)]
            if provider == LLMProvider.OPENAI
            else []
        ),
        lifecycle_status=LLMModelLifecycleStatus.DEPRECATED
        if deprecated
        else LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.HIDDEN
        if hidden_reason
        else LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=None,
        publisher=_developer(provider).value,
        family=None,
        pricing=pricing,
        source_metadata={
            "source_kind": source.source_kind,
            "source_key": source.source_key,
            "source_provider_id": model.provider,
            "source_model_id": model.source_key,
            "deprecation_date": model.facts.deprecation_date.value,
            "facts": model.facts.model_dump(mode="json"),
        },
        projection_metadata={
            "capability_compiler_revision": CAPABILITY_PROJECTION_REVISION,
            "projection_mode": "replacement",
            "runtime_dependency_versions": projection_runtime_versions(provider),
            "freshness_rank": model_freshness_rank(identifier),
            "native_protocol": protocol_for_provider(
                provider=provider, model=identifier
            ),
            "effective_date": effective_date.isoformat(),
            "diagnostics": list(model.reasoning.diagnostics),
        },
        hidden_reason=hidden_reason,
    )


def _hidden_reason(
    *, provider: LLMProvider, model: CatalogSourceModel, deprecated: bool
) -> str | None:
    if deprecated:
        return "deprecated"
    facts = model.facts
    if facts.mode.value not in {"chat", "responses"}:
        return (
            "unsupported_model_kind"
            if facts.mode.state == "value"
            else "conversation_support_unknown"
        )
    if facts.output_modalities.state == "value" and "text" not in (
        facts.output_modalities.value or ()
    ):
        return "unsupported_output_modality"
    if (
        provider == LLMProvider.OPENAI
        and facts.supported_endpoints.state == "value"
        and "/v1/responses" not in (facts.supported_endpoints.value or ())
    ):
        return "unsupported_endpoint"
    return None


def _developer(provider: LLMProvider) -> LLMModelDeveloper:
    match provider:
        case LLMProvider.OPENAI:
            return LLMModelDeveloper.OPENAI
        case LLMProvider.ANTHROPIC:
            return LLMModelDeveloper.ANTHROPIC
        case LLMProvider.GOOGLE_GEMINI:
            return LLMModelDeveloper.GOOGLE
        case _:
            raise ValueError("Provider does not own a system catalog.")
