"""Apply explicitly captured price authority to normalized model usage."""

import dataclasses
import logging
import math
from collections.abc import Mapping, Sequence

from azents.core.model_pricing import (
    CapturedModelPricing,
    ModelPricingBilling,
    ModelPricingComponentUsage,
    ModelPricingUsage,
    estimate_model_cost,
)
from azents.core.type_guards import is_string_object_dict
from azents.engine.events.types import ModelCostProvenance, TokenUsagePayload

logger = logging.getLogger(__name__)

_TOKEN_ONLY_OUTPUT_TYPES = frozenset(
    {"message", "reasoning", "function_call", "custom_tool_call"}
)


@dataclasses.dataclass(frozen=True)
class _BillingQuantity:
    """One native billing quantity and whether its supplied value is invalid."""

    value: int | None
    invalid: bool


@dataclasses.dataclass(frozen=True)
class _UsageBillingDetails:
    """Directed native usage counters retained by Responses normalization."""

    cache_write_5m_tokens: int | None
    cache_write_1h_tokens: int | None
    input_audio_tokens: int | None
    input_image_tokens: int | None
    output_audio_tokens: int | None
    output_image_tokens: int | None
    unknown_billable_components: bool


def _quantity(*values: object) -> _BillingQuantity:
    """Decode a native integer without guessing a count from malformed input."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            return _BillingQuantity(value=value, invalid=value < 0)
        return _BillingQuantity(value=None, invalid=True)
    return _BillingQuantity(value=None, invalid=False)


def _details(value: object) -> Mapping[str, object]:
    """Narrow an optional native detail object at the decoder boundary."""
    return value if is_string_object_dict(value) else {}


def _decode_usage_billing_details(raw: Mapping[str, object]) -> _UsageBillingDetails:
    """Decode only directed cache/media billing quantities, never model content."""
    input_details = _details(raw.get("input_tokens_details")) or _details(
        raw.get("prompt_tokens_details")
    )
    output_details = _details(raw.get("output_tokens_details")) or _details(
        raw.get("completion_tokens_details")
    )
    cache_creation = _details(raw.get("cache_creation"))
    write_5m = _quantity(
        raw.get("cache_write_5m_tokens"),
        cache_creation.get("ephemeral_5m_input_tokens"),
        input_details.get("cache_write_5m_tokens"),
    )
    write_1h = _quantity(
        raw.get("cache_write_1h_tokens"),
        cache_creation.get("ephemeral_1h_input_tokens"),
        input_details.get("cache_write_1h_tokens"),
    )
    input_audio = _quantity(
        raw.get("input_audio_tokens"), input_details.get("audio_tokens")
    )
    input_image = _quantity(
        raw.get("input_image_tokens"), input_details.get("image_tokens")
    )
    output_audio = _quantity(
        raw.get("output_audio_tokens"), output_details.get("audio_tokens")
    )
    output_image = _quantity(
        raw.get("output_image_tokens"), output_details.get("image_tokens")
    )
    quantities = (
        write_5m,
        write_1h,
        input_audio,
        input_image,
        output_audio,
        output_image,
    )
    # Undirected media counts cannot be assigned an input/output billing rate.
    unknown_media = any(
        raw.get(key) not in (None, 0) for key in ("audio_tokens", "image_tokens")
    )
    return _UsageBillingDetails(
        cache_write_5m_tokens=write_5m.value,
        cache_write_1h_tokens=write_1h.value,
        input_audio_tokens=input_audio.value,
        input_image_tokens=input_image.value,
        output_audio_tokens=output_audio.value,
        output_image_tokens=output_image.value,
        unknown_billable_components=unknown_media
        or any(quantity.invalid for quantity in quantities),
    )


def apply_model_usage_pricing(
    usage: TokenUsagePayload,
    *,
    provider: str,
    model_identifier: str,
    pricing: CapturedModelPricing | None,
    service_tier: str | None,
    output_item_types: Sequence[str],
    reported_charge: float | None,
) -> TokenUsagePayload:
    """Apply a native charge or a captured, content-free estimate.

    :param usage: Responses common totals, including cache and reasoning counters
    :param provider: authoritative selected provider identity
    :param model_identifier: authoritative selected model identifier
    :param pricing: immutable captured source pricing, or unavailable authority
    :param service_tier: provider-returned applicable service tier
    :param output_item_types: billable output categories, never output content
    :param reported_charge: mapped native charge, not a library estimate
    :returns: usage with truthful nullable cost and explicit known provenance
    """
    if (
        reported_charge is not None
        and not isinstance(reported_charge, bool)
        and math.isfinite(reported_charge)
        and reported_charge >= 0
    ):
        provenance = ModelCostProvenance(
            method="provider_reported",
            provider=pricing.provider.value if pricing is not None else provider,
            model_identifier=(
                pricing.model_identifier if pricing is not None else model_identifier
            ),
            service_tier=service_tier,
            source_snapshot_id=None,
            source_hash=None,
            source_model_key=None,
            estimator_version=None,
        )
        return usage.model_copy(
            update={"cost_usd": reported_charge, "cost_provenance": provenance}
        )
    if pricing is None:
        return usage.model_copy(update={"cost_usd": None, "cost_provenance": None})

    details = _decode_usage_billing_details(usage.raw)
    if usage.cache_creation_tokens is None and (
        details.cache_write_5m_tokens is not None
        or details.cache_write_1h_tokens is not None
    ):
        usage = usage.model_copy(
            update={
                "cache_creation_tokens": (
                    (details.cache_write_5m_tokens or 0)
                    + (details.cache_write_1h_tokens or 0)
                )
            }
        )
    components: list[ModelPricingComponentUsage] = []
    unknown_billable_components = details.unknown_billable_components
    for item_type in output_item_types:
        if item_type in {"web_search_call", "file_search_call"}:
            components.append(
                ModelPricingComponentUsage(
                    kind=(
                        "web_search"
                        if item_type == "web_search_call"
                        else "file_search"
                    ),
                    quantity=1,
                    search_context_size=None,
                )
            )
        elif item_type not in _TOKEN_ONLY_OUTPUT_TYPES:
            # Session-priced code and generated media need native billing
            # quantities. An output item count is not that evidence.
            unknown_billable_components = True

    # Both current normalizers consume inclusive Responses IR counts. A future
    # native adapter must normalize cache-exclusive input and reasoning-exclusive
    # output before using this boundary; hosting provider identity is insufficient
    # to decide how its native counters are partitioned.
    estimate = estimate_model_cost(
        pricing=pricing,
        usage=ModelPricingUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cached_input_tokens=usage.cached_tokens,
            cache_write_input_tokens=usage.cache_creation_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            prompt_tokens_include_cache=True,
            completion_tokens_include_reasoning=True,
            cache_write_5m_tokens=details.cache_write_5m_tokens,
            cache_write_1h_tokens=details.cache_write_1h_tokens,
            input_audio_tokens=details.input_audio_tokens,
            input_image_tokens=details.input_image_tokens,
            output_audio_tokens=details.output_audio_tokens,
            output_image_tokens=details.output_image_tokens,
        ),
        billing=ModelPricingBilling(
            service_tier=service_tier,
            context_input_tokens=None,
            components=tuple(components),
            unknown_billable_components=unknown_billable_components,
            inference_geo=None,
            speed=None,
            data_residency=None,
        ),
    )
    if estimate.cost_usd is None:
        logger.debug(
            "Model cost estimate unavailable",
            extra={
                "provider": provider,
                "model": model_identifier,
                "source_snapshot_id": pricing.source_snapshot_id,
                "price_unavailable_reason": estimate.unavailable_reason,
            },
        )
    provenance = (
        ModelCostProvenance(
            method="estimated",
            provider=pricing.provider.value,
            model_identifier=pricing.model_identifier,
            service_tier=estimate.service_tier,
            source_snapshot_id=pricing.source_snapshot_id,
            source_hash=pricing.source_hash,
            source_model_key=pricing.source_model_key,
            estimator_version=pricing.estimator_version,
        )
        if estimate.cost_usd is not None
        else None
    )
    return usage.model_copy(
        update={"cost_usd": estimate.cost_usd, "cost_provenance": provenance}
    )
