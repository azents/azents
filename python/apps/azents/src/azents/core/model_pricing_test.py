"""Golden billing rules use explicit source fixtures, never a package price map."""

import dataclasses
import datetime
from collections.abc import Mapping
from decimal import Decimal, localcontext

import pytest
from genai_prices.data_snapshot import get_snapshot

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    SourceEqualsClause,
    SourceModelRecord,
    SourcePriceSet,
    SourcePriceTier,
    SourceProviderRecord,
    SourceScalarPrice,
    SourceStartDatePriceConstraint,
    SourceTieredPrice,
    encode_data_snapshot,
    lookup_source_model,
)
from azents.core.model_pricing import (
    GenAIModelPricing,
    ModelCostEstimate,
    ModelPricing,
    ModelPricingBilling,
    ModelPricingComponentUsage,
    ModelPricingUnavailableReason,
    ModelPricingUsage,
    estimate_model_cost,
    normalize_genai_model_pricing,
    normalize_model_pricing,
)


def _pricing(metadata: Mapping[str, object]) -> ModelPricing:
    return normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="publisher/exact-model",
        source_snapshot_id="snapshot-before-stream",
        source_hash="captured-hash",
        source_model_key="openai/publisher/exact-model",
        metadata=metadata,
    )


def _usage() -> ModelPricingUsage:
    return ModelPricingUsage(
        prompt_tokens=10,
        completion_tokens=5,
        cached_input_tokens=2,
        cache_write_input_tokens=3,
        reasoning_tokens=1,
        prompt_tokens_include_cache=True,
        completion_tokens_include_reasoning=True,
        cache_write_5m_tokens=None,
        cache_write_1h_tokens=None,
        input_audio_tokens=None,
        input_image_tokens=None,
        output_audio_tokens=None,
        output_image_tokens=None,
    )


def _billing() -> ModelPricingBilling:
    return ModelPricingBilling(
        service_tier=None,
        context_input_tokens=None,
        components=(),
        unknown_billable_components=False,
        inference_geo=None,
        speed=None,
        data_residency=None,
    )


def _standard_prices() -> dict[str, object]:
    return {
        "input_cost_per_token": 0.1,
        "output_cost_per_token": 0.2,
        "cache_read_input_token_cost": 0.01,
        "cache_creation_input_token_cost": 0.15,
    }


def _estimate(pricing: ModelPricing) -> ModelCostEstimate:
    return estimate_model_cost(pricing=pricing, usage=_usage(), billing=_billing())


def _genai_pricing(
    prices: list[SourcePriceSet],
    *,
    request_timestamp: datetime.datetime | None = None,
) -> GenAIModelPricing:
    model = SourceModelRecord(
        id="exact-model",
        name="Exact model",
        match=SourceEqualsClause(value="exact-model"),
        context_window=128_000,
        deprecated=False,
        prices=prices,
    )
    provider = SourceProviderRecord(
        id="openai",
        name="OpenAI",
        api_pattern=r"https://api\.openai\.com/.*",
        model_match=None,
        provider_match=None,
        fallback_model_providers=None,
        models=[model],
    )
    return normalize_genai_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="exact-model",
        source_snapshot_id="snapshot-before-stream",
        source_hash="captured-hash",
        source_provider=provider,
        source_model=model,
        request_timestamp=request_timestamp
        or datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def test_genai_prices_inclusive_cache_and_reasoning_parity() -> None:
    """Canonical source evaluation partitions inclusive token totals once."""
    pricing = _genai_pricing(
        [
            SourcePriceSet(
                constraint=None,
                prices={
                    "input_mtok": SourceScalarPrice(value=Decimal("1")),
                    "output_mtok": SourceScalarPrice(value=Decimal("2")),
                    "cache_read_mtok": SourceScalarPrice(value=Decimal("0.5")),
                    "cache_write_mtok": SourceScalarPrice(value=Decimal("1.5")),
                },
            )
        ]
    )

    result = estimate_model_cost(
        pricing=pricing,
        usage=_usage(),
        billing=_billing(),
    )

    assert result.cost_usd == pytest.approx(0.0000205)
    assert result.unavailable_reason is None


@pytest.mark.parametrize("tier", ["priority", "fast", "ON_DEMAND_PRIORITY"])
def test_genai_prices_unsupported_priority_remains_unknown(tier: str) -> None:
    """Generic standard prices never become a fabricated premium estimate."""
    result = estimate_model_cost(
        pricing=_genai_pricing(
            [
                SourcePriceSet(
                    constraint=None,
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("1")),
                        "output_mtok": SourceScalarPrice(value=Decimal("2")),
                    },
                )
            ]
        ),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )

    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_TIER
    assert result.service_tier == "priority"


def test_genai_prices_conditional_and_tiered_rules_use_capture_time() -> None:
    """Captured request time selects the conditional set before tier evaluation."""
    pricing = _genai_pricing(
        [
            SourcePriceSet(
                constraint=None,
                prices={
                    "input_mtok": SourceScalarPrice(value=Decimal("1")),
                    "output_mtok": SourceScalarPrice(value=Decimal("0")),
                },
            ),
            SourcePriceSet(
                constraint=SourceStartDatePriceConstraint(
                    start_date=datetime.date(2026, 9, 1)
                ),
                prices={
                    "input_mtok": SourceTieredPrice(
                        base=Decimal("2"),
                        tiers=[
                            SourcePriceTier(start=10, price=Decimal("3")),
                        ],
                    ),
                    "output_mtok": SourceScalarPrice(value=Decimal("0")),
                },
            ),
        ]
    )
    usage = dataclasses.replace(
        _usage(),
        prompt_tokens=11,
        completion_tokens=0,
        cached_input_tokens=None,
        cache_write_input_tokens=None,
        reasoning_tokens=None,
    )

    result = estimate_model_cost(
        pricing=pricing,
        usage=usage,
        billing=_billing(),
    )

    assert result.cost_usd == pytest.approx(0.000033)
    assert result.unavailable_reason is None


def test_genai_prices_replays_captured_model_without_rematching_canonical_id() -> None:
    """Canonical IDs that miss their own clause still retain captured pricing."""
    model_identifier = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    match = lookup_source_model(
        encode_data_snapshot(get_snapshot()),
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier=model_identifier,
    )
    assert match is not None
    assert match.model.id == "regional.anthropic.claude-sonnet-4-20250514-v1:0"
    pricing = normalize_genai_model_pricing(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier=model_identifier,
        source_snapshot_id="snapshot-before-stream",
        source_hash="captured-hash",
        source_provider=match.provider,
        source_model=match.model,
        request_timestamp=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )

    result = estimate_model_cost(
        pricing=pricing,
        usage=dataclasses.replace(
            _usage(),
            cached_input_tokens=None,
            cache_write_input_tokens=None,
            reasoning_tokens=None,
        ),
        billing=_billing(),
    )

    assert result.cost_usd is not None
    assert result.unavailable_reason is None


def test_openai_inclusive_cache_and_reasoning_golden() -> None:
    """Charge 5 fresh inputs, 2 reads, 3 writes and 5 outputs exactly once."""
    result = _estimate(_pricing(_standard_prices()))
    assert result.cost_usd == pytest.approx(1.97)
    assert result.unavailable_reason is None
    assert result.service_tier == "standard"


def test_exclusive_cache_and_reasoning_counts_are_normalized_once() -> None:
    """Provider-native fresh/text counts yield the same billable partition."""
    usage = dataclasses.replace(
        _usage(),
        prompt_tokens=5,
        completion_tokens=4,
        prompt_tokens_include_cache=False,
        completion_tokens_include_reasoning=False,
    )
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=usage, billing=_billing()
    )
    assert result.cost_usd == pytest.approx(1.97)


@pytest.mark.parametrize("tier", ["priority", "fast", "ON_DEMAND_PRIORITY"])
def test_priority_and_fast_use_only_explicit_priority_rates(tier: str) -> None:
    metadata = {key + "_priority": value for key, value in _standard_prices().items()}
    result = estimate_model_cost(
        pricing=_pricing(metadata),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )
    assert result.cost_usd == pytest.approx(1.97)
    assert result.service_tier == "priority"


@pytest.mark.parametrize("tier", ["priority", "fast", "flex"])
def test_missing_tier_rates_never_use_standard(tier: str) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_flex_uses_explicit_flex_rates() -> None:
    metadata = {
        key + "_flex": float(value) / 2
        for key, value in _standard_prices().items()
        if isinstance(value, float)
    }
    result = estimate_model_cost(
        pricing=_pricing(metadata),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier="flex"),
    )
    assert result.cost_usd == pytest.approx(0.985)


@pytest.mark.parametrize("tier", ["premium-unknown", "batch"])
def test_unknown_tier_is_unavailable_not_invented_standard(tier: str) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_TIER


@pytest.mark.parametrize("rate", [-1, True, float("inf"), float("nan"), "not-a-number"])
def test_invalid_required_price_does_not_become_zero(rate: object) -> None:
    metadata = _standard_prices()
    metadata["input_cost_per_token"] = rate
    result = _estimate(_pricing(metadata))
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_PRICE


def test_zero_rates_are_valid_zero() -> None:
    prices = {key: 0 for key in _standard_prices()}
    result = _estimate(_pricing(prices))
    assert result.cost_usd == 0
    assert result.unavailable_reason is None


def test_missing_used_cache_price_invalidates_complete_total() -> None:
    prices = _standard_prices()
    del prices["cache_creation_input_token_cost"]
    result = _estimate(_pricing(prices))
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_unused_cache_price_is_not_required() -> None:
    usage = dataclasses.replace(
        _usage(), cached_input_tokens=None, cache_write_input_tokens=None
    )
    result = estimate_model_cost(
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        usage=usage,
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(2)


def test_ttl_cache_write_partition_is_not_added_twice() -> None:
    prices = _standard_prices()
    prices["cache_creation_input_token_cost_above_1hr"] = 0.25
    usage = dataclasses.replace(
        _usage(), cache_write_5m_tokens=1, cache_write_1h_tokens=2
    )
    result = estimate_model_cost(
        pricing=_pricing(prices), usage=usage, billing=_billing()
    )
    assert result.cost_usd == pytest.approx(2.17)


def test_ttl_partition_must_agree_with_total() -> None:
    usage = dataclasses.replace(
        _usage(), cache_write_5m_tokens=2, cache_write_1h_tokens=2
    )
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=usage, billing=_billing()
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_USAGE


def test_missing_long_ttl_price_does_not_use_short_price() -> None:
    usage = dataclasses.replace(
        _usage(), cache_write_5m_tokens=1, cache_write_1h_tokens=2
    )
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=usage, billing=_billing()
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


@pytest.mark.parametrize("context, expected", [(200_000, 1.97), (200_001, 3.94)])
def test_context_threshold_applies_to_whole_usage_after_strict_boundary(
    context: int, expected: float
) -> None:
    prices = _standard_prices()
    prices.update(
        {
            key + "_above_200k_tokens": float(value) * 2
            for key, value in _standard_prices().items()
            if isinstance(value, float)
        }
    )
    result = estimate_model_cost(
        pricing=_pricing(prices),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), context_input_tokens=context),
    )
    assert result.cost_usd == pytest.approx(expected)


def test_largest_crossed_context_threshold_wins() -> None:
    prices = _standard_prices()
    prices.update(
        {
            key + "_above_100_tokens": float(value) * 2
            for key, value in _standard_prices().items()
            if isinstance(value, float)
        }
    )
    prices.update(
        {
            key + "_above_200_tokens": float(value) * 3
            for key, value in _standard_prices().items()
            if isinstance(value, float)
        }
    )
    result = estimate_model_cost(
        pricing=_pricing(prices),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), context_input_tokens=201),
    )
    assert result.cost_usd == pytest.approx(5.91)


def test_priority_threshold_cannot_fall_back_to_standard_threshold() -> None:
    prices = {key + "_priority": value for key, value in _standard_prices().items()}
    prices["input_cost_per_token_above_200k_tokens"] = 0.5
    result = estimate_model_cost(
        pricing=_pricing(prices),
        usage=_usage(),
        billing=dataclasses.replace(
            _billing(), service_tier="priority", context_input_tokens=200_001
        ),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_priority_threshold_accepts_both_source_key_orders() -> None:
    prices = {
        key + "_priority_above_200k_tokens": value
        for key, value in _standard_prices().items()
    }
    result = estimate_model_cost(
        pricing=_pricing(prices),
        usage=_usage(),
        billing=dataclasses.replace(
            _billing(), service_tier="priority", context_input_tokens=200_001
        ),
    )
    assert result.cost_usd == pytest.approx(1.97)


def test_source_capture_is_immutable_and_has_exact_provenance() -> None:
    metadata = _standard_prices()
    captured = _pricing(metadata)
    metadata["input_cost_per_token"] = 99
    assert _estimate(captured).cost_usd == pytest.approx(1.97)
    assert captured.source_snapshot_id == "snapshot-before-stream"
    assert captured.source_hash == "captured-hash"
    assert captured.source_model_key == "openai/publisher/exact-model"
    assert captured.model_identifier == "publisher/exact-model"
    assert captured.estimator_version == "1"
    with pytest.raises(dataclasses.FrozenInstanceError):
        captured.model_identifier = "another-model"  # ty: ignore[invalid-assignment] -- Runtime immutability is the assertion.


def test_absent_source_preserves_selection_identity() -> None:
    pricing = normalize_model_pricing(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model_identifier="projects/p/locations/l/publishers/anthropic/models/exact",
        source_snapshot_id=None,
        source_hash=None,
        source_model_key=None,
        metadata=None,
    )
    assert pricing.model_identifier.endswith("/models/exact")
    result = _estimate(pricing)
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.SOURCE_UNAVAILABLE


def test_exact_match_miss_keeps_existing_snapshot_provenance() -> None:
    pricing = normalize_model_pricing(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier="arn:aws:bedrock:region:account:inference-profile/model",
        source_snapshot_id="snapshot",
        source_hash="hash",
        source_model_key=None,
        metadata=None,
    )
    assert pricing.source_snapshot_id == "snapshot"
    assert (
        _estimate(pricing).unavailable_reason
        is ModelPricingUnavailableReason.MODEL_UNMATCHED
    )


def test_specialized_reasoning_tariff_does_not_duplicate_output_total() -> None:
    prices = _standard_prices()
    prices["output_cost_per_reasoning_token"] = 0.4
    assert _estimate(_pricing(prices)).cost_usd == pytest.approx(2.17)


def test_media_token_breakdown_replaces_generic_portion() -> None:
    prices = _standard_prices()
    prices["input_cost_per_audio_token"] = 0.3
    prices["output_cost_per_audio_token"] = 0.5
    prices["input_cost_per_image_token"] = 0.4
    prices["output_cost_per_image_token"] = 0.6
    usage = dataclasses.replace(
        _usage(),
        input_audio_tokens=1,
        input_image_tokens=1,
        output_audio_tokens=1,
        output_image_tokens=1,
    )
    result = estimate_model_cost(
        pricing=_pricing(prices), usage=usage, billing=_billing()
    )
    assert result.cost_usd == pytest.approx(3.17)


def test_unpriced_audio_input_makes_total_unknown() -> None:
    usage = dataclasses.replace(_usage(), input_audio_tokens=1)
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=usage, billing=_billing()
    )
    assert result.cost_usd is None


def test_explicit_tools_and_media_units_are_added_once() -> None:
    prices = _standard_prices()
    prices.update(
        {
            "search_context_cost_per_query": {"search_context_size_medium": 0.01},
            "file_search_cost_per_1k_calls": 2.5,
            "code_interpreter_cost_per_session": 0.03,
            "input_cost_per_image": 0.005,
            "input_cost_per_audio_per_second": 0.001,
            "input_cost_per_video_per_second": 0.002,
        }
    )
    billing = dataclasses.replace(
        _billing(),
        components=(
            ModelPricingComponentUsage("web_search", 2, "medium"),
            ModelPricingComponentUsage("file_search", 4, None),
            ModelPricingComponentUsage("code_interpreter", 1, None),
            ModelPricingComponentUsage("input_images", 3, None),
            ModelPricingComponentUsage("input_audio_seconds", 1.5, None),
            ModelPricingComponentUsage("input_video_seconds", 2, None),
        ),
    )
    result = estimate_model_cost(
        pricing=_pricing(prices), usage=_usage(), billing=billing
    )
    assert result.cost_usd == pytest.approx(2.0505)


def test_unknown_billable_activity_is_not_hidden_by_token_subtotal() -> None:
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), unknown_billable_components=True),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNKNOWN_COMPONENT


def test_unpriced_tool_does_not_return_partial_token_total() -> None:
    billing = dataclasses.replace(
        _billing(), components=(ModelPricingComponentUsage("web_search", 1, "medium"),)
    )
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=_usage(), billing=billing
    )
    assert result.cost_usd is None


def test_search_context_can_be_unknown_only_when_all_prices_agree() -> None:
    prices = _standard_prices()
    prices["search_context_cost_per_query"] = {
        "search_context_size_low": 0.01,
        "search_context_size_medium": 0.01,
        "search_context_size_high": 0.01,
    }
    billing = dataclasses.replace(
        _billing(), components=(ModelPricingComponentUsage("web_search", 1, None),)
    )
    assert estimate_model_cost(
        pricing=_pricing(prices), usage=_usage(), billing=billing
    ).cost_usd == pytest.approx(1.98)
    prices["search_context_cost_per_query"] = {
        "search_context_size_low": 0.01,
        "search_context_size_medium": 0.02,
        "search_context_size_high": 0.03,
    }
    missing_context = estimate_model_cost(
        pricing=_pricing(prices), usage=_usage(), billing=billing
    )
    assert missing_context.cost_usd is None
    assert missing_context.unavailable_reason == "missing_price"


@pytest.mark.parametrize(
    "usage",
    [
        dataclasses.replace(_usage(), prompt_tokens=-1),
        dataclasses.replace(_usage(), completion_tokens=True),
        dataclasses.replace(_usage(), cached_input_tokens=20),
        dataclasses.replace(_usage(), reasoning_tokens=6),
    ],
)
def test_invalid_or_inconsistent_quantities_are_unknown(
    usage: ModelPricingUsage,
) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()), usage=usage, billing=_billing()
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_USAGE


def test_route_multiplier_keeps_cache_rates_unchanged() -> None:
    prices = _standard_prices()
    prices["provider_specific_entry"] = {"us": 1.1, "fast": 2}
    pricing = dataclasses.replace(_pricing(prices), provider=LLMProvider.ANTHROPIC)
    billing = dataclasses.replace(_billing(), inference_geo="us", speed="fast")
    result = estimate_model_cost(pricing=pricing, usage=_usage(), billing=billing)
    assert result.cost_usd == pytest.approx(3.77)


def test_residency_multiplier_applies_to_all_token_costs() -> None:
    prices = _standard_prices()
    prices["regional_processing_uplift_multiplier_eu"] = 1.1
    result = estimate_model_cost(
        pricing=_pricing(prices),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), data_residency="eu"),
    )
    assert result.cost_usd == pytest.approx(2.167)


def test_unknown_billing_multiplier_is_not_fabricated() -> None:
    result = estimate_model_cost(
        pricing=_pricing(_standard_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), data_residency="eu"),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_RULE


def test_numeric_decimal_strings_are_decoded_at_ingress() -> None:
    prices = {key: str(value) for key, value in _standard_prices().items()}
    assert _estimate(_pricing(prices)).cost_usd == pytest.approx(1.97)


def test_unsupported_currency_is_unknown() -> None:
    prices = _standard_prices()
    prices["currency"] = "EUR"
    assert (
        _estimate(_pricing(prices)).unavailable_reason
        is ModelPricingUnavailableReason.UNSUPPORTED_RULE
    )


def test_calculation_does_not_depend_on_ambient_decimal_precision() -> None:
    captured = _pricing(_standard_prices())
    with localcontext() as context:
        context.prec = 2
        result = _estimate(captured)
    assert result.cost_usd == pytest.approx(1.97)
    assert captured.rates[0].usd_per_unit == Decimal("0.1")


@pytest.mark.parametrize(
    "provider, source_provider",
    [
        (LLMProvider.OPENAI, "anthropic"),
        (LLMProvider.CHATGPT_OAUTH, "gemini"),
        (LLMProvider.ANTHROPIC, "openai"),
        (LLMProvider.GOOGLE_GEMINI, "anthropic"),
    ],
)
def test_bare_source_model_rejects_conflicting_provider_tariff(
    provider: LLMProvider,
    source_provider: str,
) -> None:
    metadata = _standard_prices()
    metadata["litellm_provider"] = source_provider
    pricing = normalize_model_pricing(
        provider=provider,
        model_identifier="same-opaque-model-id",
        source_snapshot_id="snapshot",
        source_hash="hash",
        source_model_key="same-opaque-model-id",
        metadata=metadata,
    )
    assert _estimate(pricing).cost_usd is None
    assert pricing.unavailable_reason is ModelPricingUnavailableReason.PROVIDER_MISMATCH
    assert pricing.source_model_key == "same-opaque-model-id"


def test_bare_legacy_source_without_provider_flag_remains_matchable() -> None:
    pricing = normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="exact-model",
        source_snapshot_id="snapshot",
        source_hash="hash",
        source_model_key="exact-model",
        metadata=_standard_prices(),
    )
    assert _estimate(pricing).cost_usd == pytest.approx(1.97)


def test_raw_model_slash_is_not_a_trusted_provider_namespace() -> None:
    metadata = _standard_prices()
    metadata["litellm_provider"] = "anthropic"
    pricing = normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="publisher/exact-model",
        source_snapshot_id="snapshot",
        source_hash="hash",
        source_model_key="publisher/exact-model",
        metadata=metadata,
    )
    assert pricing.unavailable_reason is ModelPricingUnavailableReason.PROVIDER_MISMATCH
    assert pricing.model_identifier == "publisher/exact-model"
    assert _estimate(pricing).cost_usd is None


def test_namespaced_cloud_key_retains_existing_lookup_authority() -> None:
    metadata = _standard_prices()
    metadata["litellm_provider"] = "cloud-publisher-evidence"
    pricing = normalize_model_pricing(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model_identifier="projects/p/locations/l/publishers/anthropic/models/exact",
        source_snapshot_id="snapshot",
        source_hash="hash",
        source_model_key="vertex_ai/projects/p/locations/l/publishers/anthropic/models/exact",
        metadata=metadata,
    )
    assert _estimate(pricing).cost_usd == pytest.approx(1.97)
    assert pricing.model_identifier.endswith("/models/exact")


def test_character_tariffs_without_character_quantities_are_not_token_prices() -> None:
    metadata = _standard_prices()
    metadata["input_cost_per_character"] = 0.00001
    result = _estimate(_pricing(metadata))
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_RULE


def test_zero_or_null_character_tariff_does_not_override_token_pricing() -> None:
    metadata = _standard_prices()
    metadata["input_cost_per_character"] = 0
    metadata["output_cost_per_character"] = None
    assert _estimate(_pricing(metadata)).cost_usd == pytest.approx(1.97)


def test_unit_price_normalization_has_fixed_decimal_precision() -> None:
    metadata = _standard_prices()
    metadata["file_search_cost_per_1k_calls"] = 2.5678
    with localcontext() as context:
        context.prec = 2
        captured = _pricing(metadata)
    billing = dataclasses.replace(
        _billing(),
        components=(ModelPricingComponentUsage("file_search", 1, None),),
    )
    result = estimate_model_cost(pricing=captured, usage=_usage(), billing=billing)
    assert result.cost_usd == pytest.approx(1.9725678)


def test_conflicting_context_key_aliases_are_invalid_evidence() -> None:
    metadata = {key + "_priority": value for key, value in _standard_prices().items()}
    metadata["input_cost_per_token_priority_above_200k_tokens"] = 0.2
    metadata["input_cost_per_token_above_200k_tokens_priority"] = 0.3
    billing = dataclasses.replace(
        _billing(), service_tier="priority", context_input_tokens=200_001
    )
    result = estimate_model_cost(
        pricing=_pricing(metadata), usage=_usage(), billing=billing
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_PRICE


@pytest.mark.parametrize("value", ["1e1000000", "1e-1000000", 10**1000])
def test_out_of_range_prices_remain_unknown_without_decimal_failure(
    value: int | str,
) -> None:
    metadata = _standard_prices()
    metadata["input_cost_per_token"] = value
    assert _estimate(_pricing(metadata)).cost_usd is None


@pytest.mark.parametrize("threshold", ["0", "9" * 5000])
def test_invalid_source_threshold_cannot_fail_model_usage(threshold: str) -> None:
    metadata = _standard_prices()
    metadata[f"input_cost_per_token_above_{threshold}_tokens"] = 0.2
    result = _estimate(_pricing(metadata))
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_PRICE


def test_independent_tool_fee_does_not_require_fabricated_priority_fee() -> None:
    metadata = {key + "_priority": value for key, value in _standard_prices().items()}
    metadata["search_context_cost_per_query"] = {
        "search_context_size_medium": 0.01,
    }
    billing = dataclasses.replace(
        _billing(),
        service_tier="priority",
        components=(ModelPricingComponentUsage("web_search", 1, "medium"),),
    )
    result = estimate_model_cost(
        pricing=_pricing(metadata), usage=_usage(), billing=billing
    )
    assert result.cost_usd == pytest.approx(1.98)


def test_missing_tier_specific_token_component_is_not_generic_output() -> None:
    metadata = {key + "_priority": value for key, value in _standard_prices().items()}
    metadata["output_cost_per_reasoning_token"] = 0.4
    billing = dataclasses.replace(_billing(), service_tier="priority")
    result = estimate_model_cost(
        pricing=_pricing(metadata), usage=_usage(), billing=billing
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE
