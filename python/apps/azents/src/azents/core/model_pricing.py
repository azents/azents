"""Immutable snapshot-local pricing with explicit usage and billing semantics."""

from __future__ import annotations

import dataclasses
import datetime
import math
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal

from azents.core.catalog_price_rules import (
    CatalogPriceIssue,
    CatalogPriceRules,
    PriceMetric,
    PriceTier,
    decode_catalog_price_rules,
)
from azents.core.enums import LLMProvider
from azents.core.model_catalog_identity import (
    provider_namespace_matches,
    source_model_matches,
)
from azents.core.model_catalog_source import CatalogSourceModel

CATALOG_PRICE_ESTIMATOR_VERSION = "1"


class ModelPricingUnavailableReason(StrEnum):
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
class CapturedModelPricing:
    """Interpreted immutable evidence for one operation, never a live source handle."""

    provider: LLMProvider
    model_identifier: str
    source_snapshot_id: str | None
    source_hash: str | None
    source_model_key: str | None
    estimator_version: str
    rules: CatalogPriceRules | None
    request_timestamp: datetime.datetime
    unavailable_reason: ModelPricingUnavailableReason | None


@dataclasses.dataclass(frozen=True)
class ModelPricingUsage:
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
    kind: PricingComponentKind
    quantity: int | float
    search_context_size: SearchContextSize | None


@dataclasses.dataclass(frozen=True)
class ModelPricingBilling:
    service_tier: str | None
    context_input_tokens: int | None
    components: tuple[ModelPricingComponentUsage, ...]
    unknown_billable_components: bool
    inference_geo: str | None
    speed: str | None
    data_residency: str | None


@dataclasses.dataclass(frozen=True)
class ModelCostEstimate:
    cost_usd: float | None
    unavailable_reason: ModelPricingUnavailableReason | None
    service_tier: str


_COMPONENT_METRICS: dict[PricingComponentKind, PriceMetric] = {
    "web_search": PriceMetric.WEB_SEARCH,
    "file_search": PriceMetric.FILE_SEARCH,
    "code_interpreter": PriceMetric.CODE_SESSION,
    "input_images": PriceMetric.INPUT_IMAGES,
    "output_images": PriceMetric.OUTPUT_IMAGES,
    "input_audio_seconds": PriceMetric.INPUT_AUDIO_SECONDS,
    "input_video_seconds": PriceMetric.INPUT_VIDEO_SECONDS,
    "output_audio_seconds": PriceMetric.OUTPUT_AUDIO_SECONDS,
    "output_video_seconds": PriceMetric.OUTPUT_VIDEO_SECONDS,
}
_FRACTIONAL_METRICS = frozenset(
    {
        PriceMetric.INPUT_AUDIO_SECONDS,
        PriceMetric.INPUT_VIDEO_SECONDS,
        PriceMetric.OUTPUT_AUDIO_SECONDS,
        PriceMetric.OUTPUT_VIDEO_SECONDS,
    }
)


def normalize_model_pricing(
    *,
    provider: LLMProvider,
    model_identifier: str,
    source_snapshot_id: str | None,
    source_hash: str | None,
    source_model: CatalogSourceModel | None,
    request_timestamp: datetime.datetime,
) -> CapturedModelPricing:
    """Freeze an exact source match and decode its price rules once.

    :param source_model: scoped model already resolved by the source lookup boundary
    :param request_timestamp: aware operation time used for deterministic conditions
    :returns: immutable rules or an explicit unavailable capture
    """
    if request_timestamp.utcoffset() is None:
        raise ValueError("Pricing capture requires an aware request timestamp.")
    if source_snapshot_id is None or source_hash is None:
        reason = ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    elif source_model is None:
        reason = ModelPricingUnavailableReason.MODEL_UNMATCHED
    elif not provider_namespace_matches(
        provider=provider, source_provider=source_model.provider
    ):
        reason = ModelPricingUnavailableReason.PROVIDER_MISMATCH
    elif not source_model_matches(
        provider=provider,
        model_identifier=model_identifier,
        source_model=source_model,
    ):
        reason = ModelPricingUnavailableReason.MODEL_UNMATCHED
    else:
        reason = None
    return CapturedModelPricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id=source_snapshot_id,
        source_hash=source_hash,
        source_model_key=source_model.source_key if source_model is not None else None,
        estimator_version=CATALOG_PRICE_ESTIMATOR_VERSION,
        rules=(
            decode_catalog_price_rules(source_model)
            if source_model is not None and reason is None
            else None
        ),
        request_timestamp=request_timestamp,
        unavailable_reason=reason,
    )


@dataclasses.dataclass(frozen=True)
class _QuantitySet:
    values: tuple[tuple[PriceMetric, int], ...]
    inclusive_prompt: int


def _valid_count(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 2**63 - 1
    )


def _quantities(usage: ModelPricingUsage) -> _QuantitySet | None:
    if (
        not all(
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
        or not _valid_count(usage.prompt_tokens)
        or not _valid_count(usage.completion_tokens)
    ):
        return None
    if not isinstance(usage.prompt_tokens_include_cache, bool) or not isinstance(
        usage.completion_tokens_include_reasoning, bool
    ):
        return None
    read = usage.cached_input_tokens or 0
    write = usage.cache_write_input_tokens or 0
    if (
        usage.cache_write_5m_tokens is not None
        or usage.cache_write_1h_tokens is not None
    ):
        write_5m, write_1h = (
            usage.cache_write_5m_tokens or 0,
            usage.cache_write_1h_tokens or 0,
        )
        if usage.cache_write_input_tokens is not None and write != write_5m + write_1h:
            return None
        write = write_5m + write_1h
    else:
        write_5m, write_1h = write, 0
    prompt = usage.prompt_tokens + (
        0 if usage.prompt_tokens_include_cache else read + write
    )
    reasoning = usage.reasoning_tokens or 0
    output = usage.completion_tokens + (
        0 if usage.completion_tokens_include_reasoning else reasoning
    )
    ordinary_input = (
        prompt
        - read
        - write
        - (usage.input_audio_tokens or 0)
        - (usage.input_image_tokens or 0)
    )
    ordinary_output = (
        output
        - reasoning
        - (usage.output_audio_tokens or 0)
        - (usage.output_image_tokens or 0)
    )
    if ordinary_input < 0 or ordinary_output < 0:
        return None
    return _QuantitySet(
        values=(
            (PriceMetric.INPUT, ordinary_input),
            (PriceMetric.OUTPUT, ordinary_output),
            (PriceMetric.CACHE_READ, read),
            (PriceMetric.CACHE_WRITE, write_5m),
            (PriceMetric.CACHE_WRITE_1H, write_1h),
            (PriceMetric.REASONING, reasoning),
            (PriceMetric.INPUT_AUDIO, usage.input_audio_tokens or 0),
            (PriceMetric.INPUT_IMAGE, usage.input_image_tokens or 0),
            (PriceMetric.OUTPUT_AUDIO, usage.output_audio_tokens or 0),
            (PriceMetric.OUTPUT_IMAGE, usage.output_image_tokens or 0),
        ),
        inclusive_prompt=prompt,
    )


def _issue_applies(
    issue: CatalogPriceIssue,
    quantities: dict[PriceMetric, Decimal],
    billing: ModelPricingBilling,
) -> bool:
    if issue.dimension is not None:
        return {
            "residency": billing.data_residency,
            "geography": billing.inference_geo,
            "speed": billing.speed,
        }[issue.dimension] is not None
    return all(quantities.get(metric, Decimal(0)) > 0 for metric in issue.metrics)


@dataclasses.dataclass(frozen=True)
class _RateSelection:
    value: Decimal | None
    reason: ModelPricingUnavailableReason | None


def _select_rate(
    rules: CatalogPriceRules,
    metric: PriceMetric,
    tier: PriceTier,
    context: int,
    search_size: SearchContextSize | None,
) -> _RateSelection:
    scoped = [
        rate for rate in rules.rates if rate.metric == metric and rate.tier == tier
    ]
    if not scoped:
        scoped = [
            rate for rate in rules.rates if rate.metric == metric and rate.tier is None
        ]
    applicable = [
        rate
        for rate in scoped
        if rate.above_input_tokens is None or context > rate.above_input_tokens
    ]
    if not applicable:
        return _RateSelection(None, ModelPricingUnavailableReason.MISSING_PRICE)
    # A bracket declared for a used metric on another tier cannot silently fall
    # back to a cheaper base tariff on the selected tier.
    crossed = [
        rate.above_input_tokens
        for rate in rules.rates
        if rate.metric == metric
        and rate.above_input_tokens is not None
        and context > rate.above_input_tokens
    ]
    threshold = max(crossed) if crossed else None
    if threshold is not None:
        applicable = [
            rate for rate in applicable if rate.above_input_tokens == threshold
        ]
    if not applicable:
        return _RateSelection(None, ModelPricingUnavailableReason.MISSING_PRICE)
    if metric is PriceMetric.WEB_SEARCH:
        if search_size is not None:
            applicable = [
                rate for rate in applicable if rate.search_context_size == search_size
            ]
        elif {rate.search_context_size for rate in applicable} != {
            "low",
            "medium",
            "high",
        }:
            return _RateSelection(None, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
    if not applicable or any(rate.usd_per_unit is None for rate in applicable):
        return _RateSelection(None, ModelPricingUnavailableReason.MISSING_PRICE)
    values = {rate.usd_per_unit for rate in applicable}
    if len(values) != 1:
        return _RateSelection(None, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
    value = applicable[0].usd_per_unit
    if value is None or not value.is_finite() or value < 0:
        return _RateSelection(None, ModelPricingUnavailableReason.INVALID_PRICE)
    return _RateSelection(value, None)


def _normalize_tier(value: str | None) -> str:
    if value is None or value.lower() in {"default", "standard", "auto", "on_demand"}:
        return "standard"
    if value.lower() in {"fast", "priority", "on_demand_priority"}:
        return "priority"
    return value.lower()


def _unavailable(tier: str, reason: ModelPricingUnavailableReason) -> ModelCostEstimate:
    return ModelCostEstimate(None, reason, tier)


def estimate_model_cost(
    *,
    pricing: CapturedModelPricing,
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> ModelCostEstimate:
    """Compute a complete local total or a typed unavailable result.

    :param pricing: rules frozen before the operation, including captured timestamp
    :param usage: normalized counters with explicit cache/reasoning inclusion flags
    :param billing: directed billing evidence, never inferred from generated content
    :returns: finite complete USD estimate, or an unavailable reason
    """
    tier_name = _normalize_tier(billing.service_tier)
    if pricing.unavailable_reason is not None:
        return _unavailable(tier_name, pricing.unavailable_reason)
    rules = pricing.rules
    if rules is None:
        return _unavailable(tier_name, ModelPricingUnavailableReason.SOURCE_UNAVAILABLE)
    try:
        tier = PriceTier(tier_name)
    except ValueError:
        return _unavailable(tier_name, ModelPricingUnavailableReason.UNSUPPORTED_TIER)
    if billing.unknown_billable_components:
        return _unavailable(tier_name, ModelPricingUnavailableReason.UNKNOWN_COMPONENT)
    counters = _quantities(usage)
    if counters is None or (
        billing.context_input_tokens is not None
        and not _valid_count(billing.context_input_tokens)
    ):
        return _unavailable(tier_name, ModelPricingUnavailableReason.INVALID_USAGE)
    context = billing.context_input_tokens
    if context is None:
        context = counters.inclusive_prompt
    quantities = {metric: Decimal(value) for metric, value in counters.values}
    components: list[tuple[PriceMetric, Decimal, SearchContextSize | None]] = []
    for component in billing.components:
        value = component.quantity
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 0
        ):
            return _unavailable(tier_name, ModelPricingUnavailableReason.INVALID_USAGE)
        metric = _COMPONENT_METRICS.get(component.kind)
        if metric is None:
            return _unavailable(
                tier_name, ModelPricingUnavailableReason.UNKNOWN_COMPONENT
            )
        if metric not in _FRACTIONAL_METRICS and not _valid_count(value):
            return _unavailable(tier_name, ModelPricingUnavailableReason.INVALID_USAGE)
        quantity = Decimal(str(value))
        quantities[metric] = quantities.get(metric, Decimal(0)) + quantity
        components.append((metric, quantity, component.search_context_size))
    for issue in rules.issues:
        if _issue_applies(issue, quantities, billing):
            return _unavailable(
                tier_name,
                ModelPricingUnavailableReason.INVALID_PRICE
                if issue.invalid
                else ModelPricingUnavailableReason.UNSUPPORTED_RULE,
            )
    if any(
        value is not None
        for value in (billing.inference_geo, billing.speed, billing.data_residency)
    ):
        return _unavailable(tier_name, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
    if not rules.rates and rules.off_peak is None:
        return _unavailable(tier_name, ModelPricingUnavailableReason.MISSING_PRICE)
    if (
        tier is not PriceTier.STANDARD
        and any(count > 0 for _, count in counters.values)
        and not any(rate.tier == tier for rate in rules.rates)
    ):
        return _unavailable(tier_name, ModelPricingUnavailableReason.UNSUPPORTED_TIER)
    off_peak = rules.off_peak
    active_off_peak = off_peak is not None and off_peak.applies(
        pricing.request_timestamp
    )
    if active_off_peak and tier is not PriceTier.STANDARD:
        # Overrides name standard rates, not a premium or batch schedule.
        return _unavailable(tier_name, ModelPricingUnavailableReason.UNSUPPORTED_RULE)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        total = Decimal(0)
        for metric, quantity, search_size in (
            *((metric, Decimal(value), None) for metric, value in counters.values),
            *components,
        ):
            if quantity == 0:
                continue
            effective_metric = metric
            has_reasoning_override = (
                active_off_peak
                and off_peak is not None
                and any(
                    rate.metric is PriceMetric.REASONING for rate in off_peak.overrides
                )
            )
            if (
                metric is PriceMetric.REASONING
                and not has_reasoning_override
                and not any(
                    rate.metric is PriceMetric.REASONING for rate in rules.rates
                )
            ):
                effective_metric = PriceMetric.OUTPUT
            selected = _select_rate(rules, effective_metric, tier, context, search_size)
            if active_off_peak and off_peak is not None:
                override = next(
                    (
                        rate
                        for rate in off_peak.overrides
                        if rate.metric == effective_metric
                    ),
                    None,
                )
                if override is not None:
                    selected = _RateSelection(override.usd_per_unit, None)
            if selected.reason is not None:
                return _unavailable(tier_name, selected.reason)
            if selected.value is None:
                return _unavailable(
                    tier_name, ModelPricingUnavailableReason.MISSING_PRICE
                )
            total += quantity * selected.value
        cost = float(total)
    if not math.isfinite(cost) or cost < 0:
        return _unavailable(tier_name, ModelPricingUnavailableReason.INVALID_PRICE)
    return ModelCostEstimate(cost, None, tier_name)
