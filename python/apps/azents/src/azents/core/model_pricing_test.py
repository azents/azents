"""Golden billing rules use explicit source fixtures, never a package price map."""

import dataclasses
import datetime
from decimal import Decimal

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
    SourceTimeOfDayPriceConstraint,
    encode_data_snapshot,
    lookup_source_model,
)
from azents.core.model_pricing import (
    GenAIModelPricing,
    ModelPricingBilling,
    ModelPricingComponentUsage,
    ModelPricingUnavailableReason,
    ModelPricingUsage,
    estimate_model_cost,
    normalize_genai_model_pricing,
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


@pytest.mark.parametrize(
    ("usage", "billing"),
    [
        (
            dataclasses.replace(
                _usage(),
                cached_input_tokens=1,
                cache_write_input_tokens=None,
                reasoning_tokens=None,
            ),
            _billing(),
        ),
        (
            dataclasses.replace(
                _usage(),
                cached_input_tokens=None,
                cache_write_input_tokens=None,
                reasoning_tokens=None,
                input_audio_tokens=1,
            ),
            _billing(),
        ),
        (
            dataclasses.replace(
                _usage(),
                cached_input_tokens=None,
                cache_write_input_tokens=None,
                reasoning_tokens=None,
            ),
            dataclasses.replace(
                _billing(),
                components=(
                    ModelPricingComponentUsage(
                        kind="web_search",
                        quantity=1,
                        search_context_size=None,
                    ),
                ),
            ),
        ),
    ],
)
def test_genai_prices_missing_used_specialized_rate_is_unknown(
    usage: ModelPricingUsage,
    billing: ModelPricingBilling,
) -> None:
    """The generic calculator cannot label a partial token subtotal complete."""
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
        usage=usage,
        billing=billing,
    )

    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_genai_prices_prices_separately_identified_media_and_tools() -> None:
    """Explicit media and tool rates replace or extend generic token rates."""
    result = estimate_model_cost(
        pricing=_genai_pricing(
            [
                SourcePriceSet(
                    constraint=None,
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("1")),
                        "output_mtok": SourceScalarPrice(value=Decimal("2")),
                        "input_audio_mtok": SourceScalarPrice(value=Decimal("3")),
                        "web_searches_kcount": SourceScalarPrice(value=Decimal("10")),
                    },
                )
            ]
        ),
        usage=dataclasses.replace(
            _usage(),
            cached_input_tokens=None,
            cache_write_input_tokens=None,
            reasoning_tokens=None,
            input_audio_tokens=2,
        ),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="web_search",
                    quantity=1,
                    search_context_size=None,
                ),
            ),
        ),
    )

    assert result.cost_usd == pytest.approx(0.010024)
    assert result.unavailable_reason is None


def test_genai_prices_rejects_inconsistent_cache_ttl_partition() -> None:
    """TTL-specific counts must partition the captured cache-write total."""
    result = estimate_model_cost(
        pricing=_genai_pricing(
            [
                SourcePriceSet(
                    constraint=None,
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("1")),
                        "output_mtok": SourceScalarPrice(value=Decimal("2")),
                        "cache_read_mtok": SourceScalarPrice(value=Decimal("0.5")),
                        "cache_write_5m_mtok": SourceScalarPrice(value=Decimal("1")),
                        "cache_write_1h_mtok": SourceScalarPrice(value=Decimal("2")),
                    },
                )
            ]
        ),
        usage=dataclasses.replace(
            _usage(),
            cache_write_5m_tokens=2,
            cache_write_1h_tokens=2,
        ),
        billing=_billing(),
    )

    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_USAGE


def test_genai_prices_reasoning_exclusive_usage_requires_output_coverage() -> None:
    """Reasoning outside the completion total cannot disappear from the estimate."""
    result = estimate_model_cost(
        pricing=_genai_pricing(
            [
                SourcePriceSet(
                    constraint=None,
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("1")),
                    },
                )
            ]
        ),
        usage=dataclasses.replace(
            _usage(),
            completion_tokens=0,
            cached_input_tokens=None,
            cache_write_input_tokens=None,
            reasoning_tokens=5,
            completion_tokens_include_reasoning=False,
        ),
        billing=_billing(),
    )

    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


@pytest.mark.parametrize(
    ("start_time", "end_time", "hour", "expected"),
    [
        (datetime.time(1), datetime.time(5), 3, 0.00002),
        (datetime.time(1), datetime.time(5), 12, 0.00001),
        (datetime.time(22), datetime.time(2), 23, 0.00002),
        (datetime.time(22), datetime.time(2), 12, 0.00001),
    ],
)
def test_genai_prices_time_of_day_rules_match_normal_and_overnight_windows(
    start_time: datetime.time,
    end_time: datetime.time,
    hour: int,
    expected: float,
) -> None:
    """UTC time conditions retain genai-prices normal and wraparound semantics."""
    result = estimate_model_cost(
        pricing=_genai_pricing(
            [
                SourcePriceSet(
                    constraint=None,
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("1")),
                        "output_mtok": SourceScalarPrice(value=Decimal("0")),
                    },
                ),
                SourcePriceSet(
                    constraint=SourceTimeOfDayPriceConstraint(
                        start_time=start_time,
                        end_time=end_time,
                    ),
                    prices={
                        "input_mtok": SourceScalarPrice(value=Decimal("2")),
                        "output_mtok": SourceScalarPrice(value=Decimal("0")),
                    },
                ),
            ],
            request_timestamp=datetime.datetime(
                2026,
                10,
                1,
                hour,
                tzinfo=datetime.UTC,
            ),
        ),
        usage=dataclasses.replace(
            _usage(),
            completion_tokens=0,
            cached_input_tokens=None,
            cache_write_input_tokens=None,
            reasoning_tokens=None,
        ),
        billing=_billing(),
    )

    assert result.cost_usd == pytest.approx(expected)
    assert result.unavailable_reason is None


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
