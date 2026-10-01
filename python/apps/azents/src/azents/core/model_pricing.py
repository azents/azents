"""Immutable snapshot-backed prices and content-free usage estimation."""

import dataclasses
import datetime
import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Literal

from genai_prices import Usage

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.core.model_source_metadata import source_provider_matches

ESTIMATOR_SCHEMA_VERSION = "1"
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


PricingMetric = Literal[
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
    "reasoning_tokens",
    "input_audio_tokens",
    "input_image_tokens",
    "output_audio_tokens",
    "output_image_tokens",
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
class ModelPriceRate:
    """One decoded source rate, including invalid evidence without a fake zero."""

    metric: PricingMetric
    service_tier: str
    above_input_tokens: int | None
    search_context_size: SearchContextSize | None
    usd_per_unit: Decimal | None


@dataclasses.dataclass(frozen=True)
class ModelPriceMultiplier:
    """A provider-specific multiplier decoded at the source ingress."""

    kind: Literal["inference_geo", "speed", "data_residency"]
    value: str
    multiplier: Decimal | None


@dataclasses.dataclass(frozen=True)
class ModelPricing:
    """Immutable prices tied to exact semantic selection and source evidence."""

    provider: LLMProvider
    model_identifier: str
    source_snapshot_id: str | None
    source_hash: str | None
    source_model_key: str | None
    estimator_version: str
    rates: tuple[ModelPriceRate, ...]
    multipliers: tuple[ModelPriceMultiplier, ...]
    unavailable_reason: ModelPricingUnavailableReason | None


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


CapturedModelPricing = ModelPricing | GenAIModelPricing


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


# Source field vocabulary is not a process-local price authority.
_TOKEN_SOURCE_FIELDS: Mapping[str, PricingMetric] = {
    "input_cost_per_token": "input_tokens",
    "output_cost_per_token": "output_tokens",
    "cache_read_input_token_cost": "cache_read_tokens",
    "cache_creation_input_token_cost": "cache_write_5m_tokens",
    "cache_creation_input_token_cost_above_1hr": "cache_write_1h_tokens",
    "output_cost_per_reasoning_token": "reasoning_tokens",
    "input_cost_per_audio_token": "input_audio_tokens",
    "input_cost_per_image_token": "input_image_tokens",
    "output_cost_per_audio_token": "output_audio_tokens",
    "output_cost_per_image_token": "output_image_tokens",
    "input_cost_per_image": "input_images",
    "output_cost_per_image": "output_images",
    "input_cost_per_audio_per_second": "input_audio_seconds",
    "input_cost_per_video_per_second": "input_video_seconds",
    "output_cost_per_audio_per_second": "output_audio_seconds",
    "output_cost_per_video_per_second": "output_video_seconds",
    "file_search_cost_per_1k_calls": "file_search",
    "code_interpreter_cost_per_session": "code_interpreter",
}
_THRESHOLD_SUFFIX = re.compile(
    r"^(?:_(priority|flex))?(?:_above_([0-9]+(?:k)?)_tokens)?"
    r"(?:_(priority|flex))?$"
)


def normalize_model_pricing(
    *,
    provider: LLMProvider,
    model_identifier: str,
    source_snapshot_id: str | None,
    source_hash: str | None,
    source_model_key: str | None,
    metadata: Mapping[str, object] | None,
) -> ModelPricing:
    """Decode only pricing inputs from an explicitly selected validated snapshot.

    :param provider: semantic provider, independent of SDK routing prefixes
    :param model_identifier: exact selected provider model identifier
    :param source_snapshot_id: captured validated source snapshot identity
    :param source_hash: captured source content hash
    :param source_model_key: exact matched source key or alias
    :param metadata: matched source entry, never a package or remote lookup
    :returns: frozen pricing evidence, including unavailable-source state
    """
    reason: ModelPricingUnavailableReason | None = None
    rates: list[ModelPriceRate] = []
    multipliers: list[ModelPriceMultiplier] = []
    if source_snapshot_id is None or source_hash is None:
        reason = ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    elif metadata is None or source_model_key is None:
        reason = ModelPricingUnavailableReason.MODEL_UNMATCHED
    elif not source_provider_matches(provider, source_model_key, metadata):
        reason = ModelPricingUnavailableReason.PROVIDER_MISMATCH
    elif metadata.get("currency", "USD") != "USD":
        reason = ModelPricingUnavailableReason.UNSUPPORTED_RULE
    elif _has_character_billing(metadata):
        reason = ModelPricingUnavailableReason.UNSUPPORTED_RULE
    else:
        for source_field, metric in _TOKEN_SOURCE_FIELDS.items():
            for key, value in metadata.items():
                if key == source_field or key.startswith(source_field + "_"):
                    suffix = _THRESHOLD_SUFFIX.fullmatch(key[len(source_field) :])
                    if suffix is None:
                        continue
                    tier_before, threshold_text, tier_after = suffix.groups()
                    if tier_before and tier_after and tier_before != tier_after:
                        reason = ModelPricingUnavailableReason.INVALID_PRICE
                        continue
                    try:
                        threshold = _threshold_value(threshold_text)
                    except ValueError:
                        reason = ModelPricingUnavailableReason.INVALID_PRICE
                        continue
                    rate = _decimal_nonnegative(value)
                    if metric == "file_search" and rate is not None:
                        with localcontext() as decimal_context:
                            decimal_context.prec = 50
                            rate /= Decimal(1000)
                    rates.append(
                        ModelPriceRate(
                            metric=metric,
                            service_tier=(
                                tier_before
                                or tier_after
                                or ("all" if _unit_fee(metric) else "standard")
                            ),
                            above_input_tokens=threshold,
                            search_context_size=None,
                            usd_per_unit=rate,
                        )
                    )
        _decode_search_rates(metadata, rates)
        _decode_generic_second_rates(metadata, rates)
        _decode_multipliers(metadata, multipliers)
        if not rates:
            reason = ModelPricingUnavailableReason.MISSING_PRICE
    return ModelPricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id=source_snapshot_id,
        source_hash=source_hash,
        source_model_key=source_model_key,
        estimator_version=ESTIMATOR_SCHEMA_VERSION,
        rates=tuple(rates),
        multipliers=tuple(multipliers),
        unavailable_reason=reason,
    )


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
    pricing: CapturedModelPricing,
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> ModelCostEstimate:
    """Estimate a complete total from normalized quantities without output content.

    :param pricing: captured immutable source prices and provenance
    :param usage: native token accounting with explicit inclusion semantics
    :param billing: applicable tier and separately billed activity quantities
    :returns: finite nonnegative estimated USD or an unavailable reason
    """
    if isinstance(pricing, GenAIModelPricing):
        return _estimate_genai_model_cost(
            pricing=pricing,
            usage=usage,
            billing=billing,
        )
    tier = _normalize_tier(billing.service_tier)
    if pricing.unavailable_reason is not None:
        return _unavailable(tier, pricing.unavailable_reason)
    if tier not in {"standard", "priority", "flex"}:
        return _unavailable(tier, ModelPricingUnavailableReason.UNSUPPORTED_TIER)
    if billing.unknown_billable_components:
        return _unavailable(tier, ModelPricingUnavailableReason.UNKNOWN_COMPONENT)
    if not _valid_usage(usage) or (
        billing.context_input_tokens is not None
        and not _valid_count(billing.context_input_tokens)
    ):
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)

    cache_read = usage.cached_input_tokens or 0
    cache_write = usage.cache_write_input_tokens or 0
    write_5m = usage.cache_write_5m_tokens
    write_1h = usage.cache_write_1h_tokens
    if write_5m is not None or write_1h is not None:
        ttl_total = (write_5m or 0) + (write_1h or 0)
        if usage.cache_write_input_tokens is not None and cache_write != ttl_total:
            return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
        cache_write = ttl_total
    else:
        write_5m = cache_write
        write_1h = 0
    prompt_total = usage.prompt_tokens
    if not usage.prompt_tokens_include_cache:
        prompt_total += cache_read + cache_write
    prompt_text = prompt_total - cache_read - cache_write
    prompt_text -= (usage.input_audio_tokens or 0) + (usage.input_image_tokens or 0)
    reasoning = usage.reasoning_tokens or 0
    output_total = usage.completion_tokens
    if not usage.completion_tokens_include_reasoning:
        output_total += reasoning
    output_text = output_total - reasoning
    output_text -= (usage.output_audio_tokens or 0) + (usage.output_image_tokens or 0)
    if prompt_text < 0 or output_text < 0:
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
    context = billing.context_input_tokens
    if context is None:
        context = prompt_total

    quantities: tuple[tuple[PricingMetric, int], ...] = (
        ("input_tokens", prompt_text),
        ("output_tokens", output_text),
        ("cache_read_tokens", cache_read),
        ("cache_write_5m_tokens", write_5m or 0),
        ("cache_write_1h_tokens", write_1h or 0),
        ("reasoning_tokens", reasoning),
        ("input_audio_tokens", usage.input_audio_tokens or 0),
        ("input_image_tokens", usage.input_image_tokens or 0),
        ("output_audio_tokens", usage.output_audio_tokens or 0),
        ("output_image_tokens", usage.output_image_tokens or 0),
    )
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        regular_cost = Decimal(0)
        cache_cost = Decimal(0)
        for metric, quantity in quantities:
            if quantity == 0:
                continue
            selected = _select_rate(pricing, metric, tier, context)
            if selected is None and not any(
                rate.metric == metric for rate in pricing.rates
            ):
                fallback_metric = _token_fallback_metric(metric)
                if fallback_metric is not None:
                    selected = _select_rate(pricing, fallback_metric, tier, context)
            if selected is None:
                return _unavailable(tier, ModelPricingUnavailableReason.MISSING_PRICE)
            if selected.usd_per_unit is None:
                return _unavailable(tier, ModelPricingUnavailableReason.INVALID_PRICE)
            amount = Decimal(quantity) * selected.usd_per_unit
            if metric in {
                "cache_read_tokens",
                "cache_write_5m_tokens",
                "cache_write_1h_tokens",
            }:
                cache_cost += amount
            else:
                regular_cost += amount

        route_multiplier = _routing_multiplier(pricing, billing)
        residency_multiplier = _residency_multiplier(pricing, billing)
        if route_multiplier is None or residency_multiplier is None:
            return _unavailable(tier, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
        total = (regular_cost * route_multiplier + cache_cost) * residency_multiplier
        for component in billing.components:
            if isinstance(component.quantity, bool) or not isinstance(
                component.quantity, int | float
            ):
                return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
            quantity = _decimal_nonnegative(component.quantity)
            if quantity is None:
                return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
            if component.kind in {
                "web_search",
                "file_search",
                "code_interpreter",
                "input_images",
                "output_images",
            } and not _valid_count(component.quantity):
                return _unavailable(tier, ModelPricingUnavailableReason.INVALID_USAGE)
            if quantity == 0:
                continue
            if component.kind == "web_search":
                selected = _select_search_rate(
                    pricing, tier, component.search_context_size
                )
            else:
                selected = _select_rate(pricing, component.kind, tier, context)
            if selected is None:
                return _unavailable(tier, ModelPricingUnavailableReason.MISSING_PRICE)
            if selected.usd_per_unit is None:
                return _unavailable(tier, ModelPricingUnavailableReason.INVALID_PRICE)
            total += quantity * selected.usd_per_unit
        cost = float(total)
    if not math.isfinite(cost) or cost < 0:
        return _unavailable(tier, ModelPricingUnavailableReason.INVALID_PRICE)
    return ModelCostEstimate(cost_usd=cost, unavailable_reason=None, service_tier=tier)


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
        if not _has_required_genai_prices(
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


def _has_required_genai_prices(
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


def _threshold_value(value: str | None) -> int | None:
    if value is None:
        return None
    if len(value) > 20:
        raise ValueError("The source token threshold is not supported.")
    threshold = int(value[:-1]) * 1000 if value.endswith("k") else int(value)
    if threshold <= 0:
        raise ValueError("The source token threshold must be positive.")
    return threshold


def _decimal_nonnegative(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation, ValueError:
        return None
    if not result.is_finite() or result < 0:
        return None
    numeric = float(result)
    if not math.isfinite(numeric) or numeric == 0 and result != 0:
        return None
    return result


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


def _has_character_billing(metadata: Mapping[str, object]) -> bool:
    """Separate character tariffs require quantity evidence, never content."""
    for key in ("input_cost_per_character", "output_cost_per_character"):
        if key in metadata:
            if metadata[key] is None:
                continue
            rate = _decimal_nonnegative(metadata[key])
            if rate is None or rate > 0:
                return True
    return False


def _select_rate(
    pricing: ModelPricing,
    metric: PricingMetric,
    tier: str,
    context: int,
) -> ModelPriceRate | None:
    exact = [
        rate
        for rate in pricing.rates
        if rate.metric == metric and rate.service_tier == tier
    ]
    if not exact and _unit_fee(metric):
        exact = [
            rate
            for rate in pricing.rates
            if rate.metric == metric and rate.service_tier == "all"
        ]
    crossed = [
        rate.above_input_tokens
        for rate in pricing.rates
        if rate.metric == "input_tokens"
        and rate.above_input_tokens is not None
        and context > rate.above_input_tokens
    ]
    threshold = max(crossed) if crossed else None
    if threshold is not None:
        matching = [rate for rate in exact if rate.above_input_tokens == threshold]
        if matching:
            return _single_rate(matching)
        if metric == "input_tokens" or any(
            rate.metric == metric and rate.above_input_tokens == threshold
            for rate in pricing.rates
        ):
            return None
    applicable = [
        rate
        for rate in exact
        if rate.above_input_tokens is None or context > rate.above_input_tokens
    ]
    if not applicable:
        return None
    highest = max(rate.above_input_tokens or 0 for rate in applicable)
    return _single_rate(
        [rate for rate in applicable if (rate.above_input_tokens or 0) == highest]
    )


def _single_rate(rates: list[ModelPriceRate]) -> ModelPriceRate:
    first = rates[0]
    if any(rate.usd_per_unit != first.usd_per_unit for rate in rates[1:]):
        return dataclasses.replace(first, usd_per_unit=None)
    return first


def _token_fallback_metric(metric: PricingMetric) -> PricingMetric | None:
    # Existing token-accounting rules price reasoning/output modalities at the
    # output tariff, and input image tokens at the input tariff when unsplit.
    if metric in {"reasoning_tokens", "output_audio_tokens", "output_image_tokens"}:
        return "output_tokens"
    if metric == "input_image_tokens":
        return "input_tokens"
    return None


def _unit_fee(metric: PricingMetric) -> bool:
    """Unmarked per-tool/media-unit fees apply independently of token tiers."""
    return metric in {
        "web_search",
        "file_search",
        "code_interpreter",
        "input_images",
        "output_images",
        "input_audio_seconds",
        "input_video_seconds",
        "output_audio_seconds",
        "output_video_seconds",
    }


def _decode_search_rates(
    metadata: Mapping[str, object], rates: list[ModelPriceRate]
) -> None:
    for tier in ("standard", "priority", "flex"):
        key = "search_context_cost_per_query" + (
            "" if tier == "standard" else f"_{tier}"
        )
        value = metadata.get(key)
        if value is None:
            continue
        rate_tier = "all" if tier == "standard" else tier
        if not isinstance(value, dict):
            rates.append(ModelPriceRate("web_search", rate_tier, None, None, None))
            continue
        for size in ("low", "medium", "high"):
            context_size: SearchContextSize = size
            rate = value.get(f"search_context_size_{size}")
            if rate is not None:
                rates.append(
                    ModelPriceRate(
                        "web_search",
                        rate_tier,
                        None,
                        context_size,
                        _decimal_nonnegative(rate),
                    )
                )


def _select_search_rate(
    pricing: ModelPricing, tier: str, size: SearchContextSize | None
) -> ModelPriceRate | None:
    rates = [
        rate
        for rate in pricing.rates
        if rate.metric == "web_search" and rate.service_tier == tier
    ]
    if not rates:
        rates = [
            rate
            for rate in pricing.rates
            if rate.metric == "web_search" and rate.service_tier == "all"
        ]
    if size is not None:
        matching = [
            rate
            for rate in rates
            if rate.search_context_size == size or rate.search_context_size is None
        ]
        return _single_rate(matching) if matching else None
    sizes = {rate.search_context_size for rate in rates}
    if sizes == {"low", "medium", "high"}:
        if (
            all(rate.usd_per_unit is not None for rate in rates)
            and len({rate.usd_per_unit for rate in rates}) > 1
        ):
            return None
        return _single_rate(rates)
    return None


def _decode_generic_second_rates(
    metadata: Mapping[str, object], rates: list[ModelPriceRate]
) -> None:
    for tier in ("standard", "priority", "flex"):
        key = "output_cost_per_second" + ("" if tier == "standard" else f"_{tier}")
        if key not in metadata:
            continue
        rate_tier = "all" if tier == "standard" else tier
        for metric in ("output_audio_seconds", "output_video_seconds"):
            typed_metric: PricingMetric = metric
            if not any(
                rate.metric == metric and rate.service_tier == rate_tier
                for rate in rates
            ):
                rates.append(
                    ModelPriceRate(
                        typed_metric,
                        rate_tier,
                        None,
                        None,
                        _decimal_nonnegative(metadata[key]),
                    )
                )


def _decode_multipliers(
    metadata: Mapping[str, object], multipliers: list[ModelPriceMultiplier]
) -> None:
    provider_values = metadata.get("provider_specific_entry")
    if isinstance(provider_values, dict):
        for key, value in provider_values.items():
            if isinstance(key, str):
                kind: Literal["inference_geo", "speed", "data_residency"] = (
                    "speed" if key == "fast" else "inference_geo"
                )
                multipliers.append(
                    ModelPriceMultiplier(kind, key.lower(), _decimal_nonnegative(value))
                )
    for key, value in metadata.items():
        prefix = "regional_processing_uplift_multiplier_"
        if key.startswith(prefix):
            multipliers.append(
                ModelPriceMultiplier(
                    "data_residency",
                    key[len(prefix) :].lower(),
                    _decimal_nonnegative(value),
                )
            )


def _routing_multiplier(
    pricing: ModelPricing, billing: ModelPricingBilling
) -> Decimal | None:
    if pricing.provider not in {
        LLMProvider.ANTHROPIC,
        LLMProvider.AWS_BEDROCK,
        LLMProvider.GOOGLE_VERTEX_AI,
    }:
        return (
            Decimal(1)
            if billing.inference_geo is None and billing.speed is None
            else None
        )
    multiplier = Decimal(1)
    for kind, value in (
        ("inference_geo", billing.inference_geo),
        ("speed", billing.speed),
    ):
        if value is None or value.lower() in {"global", "not_available", "standard"}:
            continue
        matching = [
            entry
            for entry in pricing.multipliers
            if entry.kind == kind and entry.value == value.lower()
        ]
        if not matching or matching[0].multiplier is None:
            return None
        multiplier *= matching[0].multiplier
    return multiplier


def _residency_multiplier(
    pricing: ModelPricing, billing: ModelPricingBilling
) -> Decimal | None:
    if billing.data_residency is None:
        return Decimal(1)
    matching = [
        entry
        for entry in pricing.multipliers
        if entry.kind == "data_residency"
        and entry.value == billing.data_residency.lower()
    ]
    if not matching or matching[0].multiplier is None:
        return None
    return matching[0].multiplier
