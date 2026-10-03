"""Apply explicitly captured price authority to normalized model usage."""

import dataclasses
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

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


type _NativeTokenCount = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class _GoogleModalityCount(BaseModel):
    """One bounded, directed native modality counter."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    modality: Literal[
        "TEXT", "IMAGE", "AUDIO", "VIDEO", "DOCUMENT", "MODALITY_UNSPECIFIED"
    ]
    token_count: _NativeTokenCount = Field(
        validation_alias=AliasChoices("tokenCount", "token_count")
    )


type _GoogleModalityCounts = Annotated[list[_GoogleModalityCount], Field(max_length=6)]


class _GoogleUsageParts(BaseModel):
    """The supportable Google billing partition, independent of model content."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    prompt_total: _NativeTokenCount | None = Field(
        default=None,
        validation_alias=AliasChoices("promptTokenCount", "prompt_token_count"),
    )
    output_total: _NativeTokenCount | None = Field(
        default=None,
        validation_alias=AliasChoices("candidatesTokenCount", "candidates_token_count"),
    )
    cache_total: _NativeTokenCount | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "cachedContentTokenCount", "cached_content_token_count"
        ),
    )
    tool_total: _NativeTokenCount | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "toolUsePromptTokenCount", "tool_use_prompt_token_count"
        ),
    )
    prompt: _GoogleModalityCounts | None = Field(
        default=None,
        validation_alias=AliasChoices("promptTokensDetails", "prompt_tokens_details"),
    )
    output: _GoogleModalityCounts | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "candidatesTokensDetails", "candidates_tokens_details"
        ),
    )
    cache: _GoogleModalityCounts | None = Field(
        default=None,
        validation_alias=AliasChoices("cacheTokensDetails", "cache_tokens_details"),
    )
    tool: _GoogleModalityCounts | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "toolUsePromptTokensDetails", "tool_use_prompt_tokens_details"
        ),
    )


@dataclasses.dataclass(frozen=True)
class _GoogleDirectedUsage:
    input_audio: int | None
    input_image: int | None
    output_audio: int | None
    output_image: int | None
    invalid: bool
    recognized: bool


def _google_partition(
    rows: _GoogleModalityCounts | None, total: int | None, *, declared: bool
) -> dict[str, int] | None:
    """Reject incomplete or contradictory modality receipts, not the request."""
    if rows is None:
        if declared:
            raise ValueError("Declared Google modality counters are null.")
        return None
    partition: dict[str, int] = {row.modality: row.token_count for row in rows}
    if len(partition) != len(rows) or total is None or sum(partition.values()) != total:
        raise ValueError("Google modality counters do not partition their total.")
    if any(
        count > 0 and modality not in {"TEXT", "IMAGE", "AUDIO"}
        for modality, count in partition.items()
    ):
        raise ValueError("Google billing modality has no adopted token tariff.")
    return partition


def _google_directed_usage(
    raw: Mapping[str, object], *, normalized_cached_tokens: int | None
) -> _GoogleDirectedUsage:
    """Consume native modality receipts; uncertain cache/media overlap is unknown."""
    if not any(
        key in raw
        for key in (
            "promptTokenCount",
            "prompt_token_count",
            "candidatesTokenCount",
            "candidates_token_count",
            "cachedContentTokenCount",
            "cached_content_token_count",
            "promptTokensDetails",
            "candidatesTokensDetails",
            "cacheTokensDetails",
            "toolUsePromptTokenCount",
            "tool_use_prompt_token_count",
            "toolUsePromptTokensDetails",
        )
    ):
        return _GoogleDirectedUsage(None, None, None, None, False, False)
    unavailable = _GoogleDirectedUsage(None, None, None, None, True, True)
    try:
        parts = _GoogleUsageParts.model_validate(dict(raw))
        normalized_cache = _quantity(normalized_cached_tokens)
        if normalized_cache.invalid:
            return unavailable
        cache_total = normalized_cache.value or 0
        if cache_total > 2**63 - 1 or (
            "cache_total" in parts.model_fields_set
            and (parts.cache_total is None or parts.cache_total != cache_total)
        ):
            return unavailable
        prompt = _google_partition(
            parts.prompt,
            parts.prompt_total,
            declared="prompt" in parts.model_fields_set,
        )
        output = _google_partition(
            parts.output,
            parts.output_total,
            declared="output" in parts.model_fields_set,
        )
        cache = _google_partition(
            parts.cache, cache_total, declared="cache" in parts.model_fields_set
        )
        tool = _google_partition(
            parts.tool, parts.tool_total, declared="tool" in parts.model_fields_set
        )
        if parts.tool_total or tool and sum(tool.values()):
            return unavailable
        if cache is not None:
            if prompt is not None and any(
                count > prompt.get(modality, 0) for modality, count in cache.items()
            ):
                return unavailable
            # Dedicated cached-media rates/quantities are not in the adopted
            # estimator contract. Do not replace them with ordinary cache prices.
            if cache.get("IMAGE", 0) or cache.get("AUDIO", 0):
                return unavailable
        if (
            cache_total
            and prompt is not None
            and (prompt.get("IMAGE", 0) or prompt.get("AUDIO", 0))
            and cache is None
        ):
            return unavailable
        if (
            cache_total
            and parts.prompt_total is not None
            and cache_total > parts.prompt_total
        ):
            return unavailable
        return _GoogleDirectedUsage(
            input_audio=prompt.get("AUDIO", 0) if prompt is not None else None,
            input_image=prompt.get("IMAGE", 0) if prompt is not None else None,
            output_audio=output.get("AUDIO", 0) if output is not None else None,
            output_image=output.get("IMAGE", 0) if output is not None else None,
            invalid=False,
            recognized=True,
        )
    except ValidationError, ValueError:
        return unavailable


def _merge_quantity(
    original: _BillingQuantity, directed: int | None
) -> _BillingQuantity:
    """Preserve a consistent explicit quantity without choosing between conflicts."""
    if directed is None:
        return original
    return _BillingQuantity(
        value=directed,
        invalid=original.invalid
        or original.value is not None
        and original.value != directed,
    )


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


def _decode_usage_billing_details(
    raw: Mapping[str, object], *, normalized_cached_tokens: int | None
) -> _UsageBillingDetails:
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
    google = _google_directed_usage(
        raw, normalized_cached_tokens=normalized_cached_tokens
    )
    input_audio = _merge_quantity(input_audio, google.input_audio)
    input_image = _merge_quantity(input_image, google.input_image)
    output_audio = _merge_quantity(output_audio, google.output_audio)
    output_image = _merge_quantity(output_image, google.output_image)
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
    malformed_details = any(
        raw.get(key) is not None
        and not is_string_object_dict(raw[key])
        and not (
            google.recognized
            and key == "prompt_tokens_details"
            and isinstance(raw[key], list)
        )
        for key in (
            "input_tokens_details",
            "prompt_tokens_details",
            "output_tokens_details",
            "completion_tokens_details",
            "cache_creation",
        )
    )
    return _UsageBillingDetails(
        cache_write_5m_tokens=write_5m.value,
        cache_write_1h_tokens=write_1h.value,
        input_audio_tokens=input_audio.value,
        input_image_tokens=input_image.value,
        output_audio_tokens=output_audio.value,
        output_image_tokens=output_image.value,
        unknown_billable_components=google.invalid
        or unknown_media
        or malformed_details
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
            source_key=None,
            source_model_key=None,
            collected_at=None,
            estimator_version=None,
        )
        return usage.model_copy(
            update={"cost_usd": reported_charge, "cost_provenance": provenance}
        )
    if pricing is None:
        return usage.model_copy(update={"cost_usd": None, "cost_provenance": None})

    details = _decode_usage_billing_details(
        usage.raw, normalized_cached_tokens=usage.cached_tokens
    )
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
                "source_key": pricing.source_key,
                "price_unavailable_reason": estimate.unavailable_reason,
            },
        )
    provenance = (
        ModelCostProvenance(
            method="estimated",
            provider=pricing.provider.value,
            model_identifier=pricing.model_identifier,
            service_tier=estimate.service_tier,
            source_key=pricing.source_key,
            source_model_key=pricing.source_model_key,
            collected_at=pricing.collected_at,
            estimator_version=pricing.estimator_version,
        )
        if estimate.cost_usd is not None
        else None
    )
    return usage.model_copy(
        update={"cost_usd": estimate.cost_usd, "cost_provenance": provenance}
    )
