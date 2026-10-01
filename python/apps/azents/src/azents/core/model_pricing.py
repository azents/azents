"""Immutable snapshot-backed prices and content-free usage estimation."""

import dataclasses
import datetime
import math
from enum import StrEnum
from typing import Literal

from genai_prices import Usage

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceModelRecord,
    SourceProviderRecord,
)

GENAI_PRICES_ESTIMATOR_SCHEMA_VERSION = "3"


class ModelPricingUnavailableReason(StrEnum):
    """Safe reasons an estimate cannot be represented as a complete total."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    MODEL_UNMATCHED = "model_unmatched"
    PROVIDER_MISMATCH = "provider_pricing_mismatch"
    INVALID_PRICE = "invalid_price"
    MISSING_PRICE = "missing_price"
    INVALID_USAGE = "invalid_usage"
    UNSUPPORTED_TIER = "unsupported_service_tier"
    UNKNOWN_COMPONENT = "unknown_billable_component"
    UNSUPPORTED_RULE = "unsupported_billing_rule"


PricingComponentKind = Literal[
    "web_search",
    "file_search",
    "code_interpreter",
    "input_images",
    "output_images",
    "input_audio_seconds",
    "input_video_seconds",
    "output_audio_seconds",
    "output_video_seconds",
]
SearchContextSize = Literal["low", "medium", "high"]


@dataclasses.dataclass(frozen=True)
class GenAIModelPricing:
    """Immutable canonical genai-prices evidence for one model dispatch."""

    provider: LLMProvider
    model_identifier: str
    source_snapshot_id: str | None
    source_hash: str | None
    source_model_key: str | None
    estimator_version: str
    source_provider: SourceProviderRecord | None
    source_model: SourceModelRecord | None
    request_timestamp: datetime.datetime
    unavailable_reason: ModelPricingUnavailableReason | None


CapturedModelPricing = GenAIModelPricing


@dataclasses.dataclass(frozen=True)
class ModelPricingUsage:
    """Token accounting with explicit inclusion rules and native breakdowns."""

    prompt_tokens: int
    completion_tokens: int
    cached_input_tokens: int | None
    cache_write_input_tokens: int | None
    reasoning_tokens: int | None
    prompt_tokens_include_cache: bool
    completion_tokens_include_reasoning: bool
    cache_write_5m_tokens: int | None
    cache_write_1h_tokens: int | None
    input_audio_tokens: int | None
    input_image_tokens: int | None
    output_audio_tokens: int | None
    output_image_tokens: int | None


@dataclasses.dataclass(frozen=True)
class ModelPricingComponentUsage:
    """A separately billable quantity; content and provider bodies are excluded."""

    kind: PricingComponentKind
    quantity: int | float
    search_context_size: SearchContextSize | None


@dataclasses.dataclass(frozen=True)
class ModelPricingBilling:
    """Applicable provider billing metadata, not generation request content."""

    service_tier: str | None
    context_input_tokens: int | None
    components: tuple[ModelPricingComponentUsage, ...]
    unknown_billable_components: bool
    inference_geo: str | None
    speed: str | None
    data_residency: str | None


@dataclasses.dataclass(frozen=True)
class ModelCostEstimate:
    """A complete estimated amount or an explicitly unavailable result."""

    cost_usd: float | None
    unavailable_reason: ModelPricingUnavailableReason | None
    service_tier: str


def normalize_genai_model_pricing(
    *,
    provider: LLMProvider,
    model_identifier: str,
    source_snapshot_id: str | None,
    source_hash: str | None,
    source_provider: SourceProviderRecord | None,
    source_model: SourceModelRecord | None,
    request_timestamp: datetime.datetime,
) -> GenAIModelPricing:
    """Freeze one canonical source match for isolated later evaluation."""
    if source_snapshot_id is None or source_hash is None:
        reason = ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    elif source_provider is None or source_model is None:
        reason = ModelPricingUnavailableReason.MODEL_UNMATCHED
    else:
        reason = None
    return GenAIModelPricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id=source_snapshot_id,
        source_hash=source_hash,
        source_model_key=(
            f"{source_provider.id}/{source_model.id}"
            if source_provider is not None and source_model is not None
            else None
        ),
        estimator_version=GENAI_PRICES_ESTIMATOR_SCHEMA_VERSION,
        source_provider=source_provider,
        source_model=source_model,
        request_timestamp=request_timestamp,
        unavailable_reason=reason,
    )


def estimate_model_cost(
    *,
    pricing: GenAIModelPricing,
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> ModelCostEstimate:
    """Estimate a complete total from captured generic source evidence."""
    return _estimate_genai_model_cost(
        pricing=pricing,
        usage=usage,
        billing=billing,
    )


def _estimate_genai_model_cost(
    *,
    pricing: GenAIModelPricing,
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> ModelCostEstimate:
    tier = _normalize_tier(billing.service_tier)
    if pricing.unavailable_reason is not None:
        return _unavailable(tier, pricing.unavailable_reason)
    if tier != "standard":
        return _unavailable(tier, ModelPricingUnavailableReason.UNSUPPORTED_TIER)
    if billing.unknown_billable_components:
        return _unavailable(tier, ModelPricingUnavailableReason.UNKNOWN_COMPONENT)
    if not _valid_usage(usage):
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
    if (
        usage.cache_write_input_tokens is not None
        and (
            usage.cache_write_5m_tokens is not None
            or usage.cache_write_1h_tokens is not None
        )
        and (usage.cache_write_5m_tokens or 0) + (usage.cache_write_1h_tokens or 0)
        != usage.cache_write_input_tokens
    ):
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
    if pricing.source_provider is None or pricing.source_model is None:
        return _unavailable(tier, ModelPricingUnavailableReason.MODEL_UNMATCHED)

    prompt_tokens = usage.prompt_tokens
    if not usage.prompt_tokens_include_cache:
        prompt_tokens += (usage.cached_input_tokens or 0) + (
            usage.cache_write_input_tokens or 0
        )
    completion_tokens = usage.completion_tokens
    if not usage.completion_tokens_include_reasoning:
        completion_tokens += usage.reasoning_tokens or 0
    values: dict[str, int | float] = {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
    }
    for key, value in (
        ("cache_read_tokens", usage.cached_input_tokens),
        ("cache_write_tokens", usage.cache_write_input_tokens),
        ("cache_write_5m_tokens", usage.cache_write_5m_tokens),
        ("cache_write_1h_tokens", usage.cache_write_1h_tokens),
        ("input_audio_tokens", usage.input_audio_tokens),
        ("input_image_tokens", usage.input_image_tokens),
        ("output_audio_tokens", usage.output_audio_tokens),
        ("output_image_tokens", usage.output_image_tokens),
        ("output_reasoning_tokens", usage.reasoning_tokens),
    ):
        if value is not None:
            values[key] = value
    for component in billing.components:
        if (
            isinstance(component.quantity, bool)
            or not isinstance(component.quantity, int | float)
            or component.quantity < 0
        ):
            return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
        key = {
            "web_search": "web_searches",
            "file_search": "storage_searches",
            "code_interpreter": "code_executions",
        }.get(component.kind)
        if key is None:
            return _unavailable(tier, ModelPricingUnavailableReason.UNKNOWN_COMPONENT)
        values[key] = values.get(key, 0) + component.quantity

    try:
        [provider] = (
            ModelMetadataSourcePayload(providers=[pricing.source_provider])
            .to_data_snapshot()
            .providers
        )
        model = next(
            model for model in provider.models if model.id == pricing.source_model.id
        )
        calculation = model.calc_price(
            Usage(**values),
            provider,
            genai_request_timestamp=pricing.request_timestamp,
        )
        if not _has_required_prices(
            price_fields={
                key
                for key, value in calculation.model_price.__dict__.items()
                if not key.startswith("_") and value is not None
            },
            usage=usage,
            billing=billing,
        ):
            return _unavailable(tier, ModelPricingUnavailableReason.MISSING_PRICE)
        cost = float(calculation.total_price)
    except StopIteration, TypeError, ValueError:
        return _unavailable(tier, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
    if not math.isfinite(cost) or cost < 0:
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_PRICE)
    return ModelCostEstimate(cost_usd=cost, unavailable_reason=None, service_tier=tier)


def _has_required_prices(
    *,
    price_fields: set[str],
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> bool:
    """Require explicit rates for every separately identified billable quantity."""
    required: set[str] = set()
    if usage.prompt_tokens > 0:
        required.add("input_mtok")
    if usage.completion_tokens > 0:
        required.add("output_mtok")
    elif (
        not usage.completion_tokens_include_reasoning
        and (usage.reasoning_tokens or 0) > 0
        and not {"output_mtok", "output_reasoning_mtok"} & price_fields
    ):
        return False
    if (usage.cached_input_tokens or 0) > 0:
        required.add("cache_read_mtok")
    if (
        usage.cache_write_5m_tokens is not None
        or usage.cache_write_1h_tokens is not None
    ):
        if (usage.cache_write_5m_tokens or 0) > 0:
            required.add("cache_write_5m_mtok")
        if (usage.cache_write_1h_tokens or 0) > 0:
            required.add("cache_write_1h_mtok")
    elif (usage.cache_write_input_tokens or 0) > 0:
        required.add("cache_write_mtok")
    for count, price_field in (
        (usage.input_audio_tokens, "input_audio_mtok"),
        (usage.input_image_tokens, "input_image_mtok"),
        (usage.output_audio_tokens, "output_audio_mtok"),
        (usage.output_image_tokens, "output_image_mtok"),
    ):
        if (count or 0) > 0:
            required.add(price_field)
    component_price_fields = {
        "web_search": "web_searches_kcount",
        "file_search": "storage_searches_kcount",
        "code_interpreter": "code_executions_kcount",
    }
    for component in billing.components:
        if component.quantity > 0:
            required.add(component_price_fields[component.kind])
    return required <= price_fields


def _unavailable(tier: str, reason: ModelPricingUnavailableReason) -> ModelCostEstimate:
    return ModelCostEstimate(
        cost_usd=None, unavailable_reason=reason, service_tier=tier
    )


def _normalize_tier(value: str | None) -> str:
    if value is None or value.lower() in {"default", "standard", "auto", "on_demand"}:
        return "standard"
    if value.lower() in {"fast", "priority", "on_demand_priority"}:
        return "priority"
    return value.lower()


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_usage(usage: ModelPricingUsage) -> bool:
    return (
        _valid_count(usage.prompt_tokens)
        and _valid_count(usage.completion_tokens)
        and all(
            value is None or _valid_count(value)
            for value in (
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cached_input_tokens,
                usage.cache_write_input_tokens,
                usage.reasoning_tokens,
                usage.cache_write_5m_tokens,
                usage.cache_write_1h_tokens,
                usage.input_audio_tokens,
                usage.input_image_tokens,
                usage.output_audio_tokens,
                usage.output_image_tokens,
            )
        )
    )
