"""Snapshot-local pricing fixtures, independent of producer libraries."""

import dataclasses
import datetime
import json

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_pricing import (
    CapturedModelPricing,
    ModelPricingBilling,
    ModelPricingComponentUsage,
    ModelPricingUnavailableReason,
    ModelPricingUsage,
    capture_model_pricing,
    estimate_model_cost,
    normalize_model_pricing,
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


def _plain_usage(prompt: int, output: int) -> ModelPricingUsage:
    return dataclasses.replace(
        _usage(),
        prompt_tokens=prompt,
        completion_tokens=output,
        cached_input_tokens=None,
        cache_write_input_tokens=None,
        reasoning_tokens=None,
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


def _prices() -> dict[str, object]:
    return {
        "input_cost_per_token": 0.000001,
        "output_cost_per_token": 0.000002,
        "cache_read_input_token_cost": 0.0000005,
        "cache_creation_input_token_cost": 0.0000015,
    }


def _pricing(
    fields: dict[str, object], *, timestamp: datetime.datetime | None = None
) -> CapturedModelPricing:
    source = decode_catalog_source(
        json.dumps(
            {"selected-exact-id": {"litellm_provider": "openai", **fields}}
        ).encode()
    ).models[0]
    timestamp = timestamp or datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC)
    return capture_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="selected-exact-id",
        definition=normalize_model_pricing(
            source_key="litellm_catalog",
            source_model=source,
            collected_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
        ),
        request_timestamp=timestamp,
    )


def test_inclusive_cache_and_reasoning_partitioned_once() -> None:
    pricing = _pricing(_prices())
    result = estimate_model_cost(pricing=pricing, usage=_usage(), billing=_billing())
    exclusive = estimate_model_cost(
        pricing=pricing,
        usage=dataclasses.replace(
            _usage(),
            prompt_tokens=5,
            completion_tokens=4,
            prompt_tokens_include_cache=False,
            completion_tokens_include_reasoning=False,
        ),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.0000205)
    assert exclusive == result
    assert result.unavailable_reason is None


def test_explicit_reasoning_tariff_replaces_generic_output_subset() -> None:
    result = estimate_model_cost(
        pricing=_pricing({**_prices(), "output_cost_per_reasoning_token": 0.000007}),
        usage=_usage(),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.0000255)


def test_exclusive_reasoning_without_visible_output_is_not_lost() -> None:
    result = estimate_model_cost(
        pricing=_pricing({"output_cost_per_token": 0.000002}),
        usage=dataclasses.replace(
            _plain_usage(0, 0),
            reasoning_tokens=5,
            completion_tokens_include_reasoning=False,
        ),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.000010)


@pytest.mark.parametrize(
    "tier", ["priority", "fast", "ON_DEMAND_PRIORITY", "flex", "batches", "ultrafast"]
)
def test_missing_service_tier_does_not_substitute_standard(tier: str) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_TIER


@pytest.mark.parametrize("tier", ["priority", "flex", "batches", "ultrafast"])
def test_explicit_service_tier_rates_are_used(tier: str) -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                **_prices(),
                f"input_cost_per_token_{tier}": 0.000003,
                f"output_cost_per_token_{tier}": 0.000004,
            }
        ),
        usage=_plain_usage(10, 5),
        billing=dataclasses.replace(_billing(), service_tier=tier),
    )
    assert result.cost_usd == pytest.approx(0.00005)


def test_missing_premium_cache_tariff_makes_whole_total_unavailable() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                **_prices(),
                "input_cost_per_token_priority": 0.000003,
                "output_cost_per_token_priority": 0.000004,
            }
        ),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), service_tier="priority"),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


@pytest.mark.parametrize(
    "changes",
    [
        {"input_audio_tokens": 1},
        {"input_image_tokens": 1},
        {"output_audio_tokens": 1},
        {"output_image_tokens": 1},
        {"cache_write_5m_tokens": 1, "cache_write_1h_tokens": 2},
    ],
)
def test_missing_used_specialized_tariff_never_falls_back(
    changes: dict[str, int],
) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_prices()),
        usage=dataclasses.replace(_usage(), **changes),
        billing=_billing(),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_explicit_media_and_search_rates_have_correct_units() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
                "input_cost_per_audio_token": 0.000003,
                "search_context_cost_per_query": {
                    "search_context_size_low": 0.01,
                    "search_context_size_medium": 0.01,
                    "search_context_size_high": 0.01,
                },
            }
        ),
        usage=dataclasses.replace(_plain_usage(10, 5), input_audio_tokens=2),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="web_search", quantity=1, search_context_size=None
                ),
            ),
        ),
    )
    assert result.cost_usd == pytest.approx(0.010024)


def test_ttl_specific_write_rates_partition_aggregate() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {**_prices(), "cache_creation_input_token_cost_above_1hr": 0.000003}
        ),
        usage=dataclasses.replace(
            _usage(), cache_write_5m_tokens=1, cache_write_1h_tokens=2
        ),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.0000235)


@pytest.mark.parametrize(
    "changes",
    [
        {"cache_write_5m_tokens": 2, "cache_write_1h_tokens": 2},
        {"cached_input_tokens": 20},
        {"reasoning_tokens": 6},
        {"prompt_tokens": -1},
        {"completion_tokens": True},
        {"input_image_tokens": 100},
    ],
)
def test_invalid_usage_remainders_and_ttl_totals(changes: dict[str, int]) -> None:
    result = estimate_model_cost(
        pricing=_pricing(_prices()),
        usage=dataclasses.replace(_usage(), **changes),
        billing=_billing(),
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_USAGE
    assert result.cost_usd is None


@pytest.mark.parametrize(("prompt", "expected"), [(10, 0.00001), (11, 0.000033)])
def test_context_threshold_is_strict_and_whole_request(
    prompt: int, expected: float
) -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token": 0.000001,
                "input_cost_per_token_above_10_tokens": 0.000003,
            }
        ),
        usage=_plain_usage(prompt, 0),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(expected)


def test_context_uses_inclusive_prompt_or_directed_billing_context() -> None:
    pricing = _pricing(
        {
            "input_cost_per_token": 0.000001,
            "input_cost_per_token_above_9_tokens": 0.000003,
            "cache_read_input_token_cost": 0.0000005,
        }
    )
    usage = dataclasses.replace(_plain_usage(10, 0), cached_input_tokens=8)
    inclusive = estimate_model_cost(pricing=pricing, usage=usage, billing=_billing())
    directed = estimate_model_cost(
        pricing=pricing,
        usage=usage,
        billing=dataclasses.replace(_billing(), context_input_tokens=9),
    )
    assert inclusive.cost_usd == pytest.approx(0.000010)
    assert directed.cost_usd == pytest.approx(0.000006)


@pytest.mark.parametrize(
    "field",
    [
        "input_cost_per_token_priority_above_10_tokens",
        "input_cost_per_token_above_10_tokens_priority",
    ],
)
def test_context_tier_suffix_orders_are_equivalent(field: str) -> None:
    result = estimate_model_cost(
        pricing=_pricing({"input_cost_per_token_priority": 0.000001, field: 0.000003}),
        usage=_plain_usage(11, 0),
        billing=dataclasses.replace(_billing(), service_tier="priority"),
    )
    assert result.cost_usd == pytest.approx(0.000033)


def test_missing_high_context_premium_rate_is_not_base_fallback() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token_priority": 0.000001,
                "input_cost_per_token_above_10_tokens": 0.000003,
            }
        ),
        usage=_plain_usage(11, 0),
        billing=dataclasses.replace(_billing(), service_tier="priority"),
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


@pytest.mark.parametrize(
    ("window", "hour", "expected"),
    [
        ("01:00-05:00", 1, 0.00002),
        ("01:00-05:00", 5, 0.00001),
        ("22:00-02:00", 23, 0.00002),
        ("22:00-02:00", 2, 0.00001),
        ("00:00-00:00", 12, 0.00002),
    ],
)
def test_off_peak_captured_time_boundaries(
    window: str, hour: int, expected: float
) -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token": 0.000001,
                "off_peak_pricing": {
                    "hours_utc": window,
                    "input_cost_per_token": 0.000002,
                },
            },
            timestamp=datetime.datetime(2026, 10, 2, hour, tzinfo=datetime.UTC),
        ),
        usage=_plain_usage(10, 0),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(expected)


def test_off_peak_weekday_calendar_does_not_move_utc_hours() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token": 0.000001,
                "off_peak_pricing": {
                    "weekday_timezone": "Asia/Seoul",
                    "windows": [{"hours_utc": "22:00-02:00", "weekdays": ["monday"]}],
                    "input_cost_per_token": 0.000002,
                },
            },
            timestamp=datetime.datetime(2026, 10, 4, 23, tzinfo=datetime.UTC),
        ),
        usage=_plain_usage(10, 0),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.00002)


def test_off_peak_partial_override_keeps_output_and_one_hour_cache() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                **_prices(),
                "cache_creation_input_token_cost_above_1hr": 0.000003,
                "off_peak_pricing": {
                    "hours_utc": "00:00-00:00",
                    "cache_creation_input_token_cost": 0,
                },
            }
        ),
        usage=dataclasses.replace(
            _usage(), cache_write_5m_tokens=1, cache_write_1h_tokens=2
        ),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.000022)


def test_off_peak_reasoning_override_is_not_generic_output() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                **_prices(),
                "off_peak_pricing": {
                    "hours_utc": "00:00-00:00",
                    "output_cost_per_reasoning_token": 0.000007,
                },
            }
        ),
        usage=_usage(),
        billing=_billing(),
    )
    assert result.cost_usd == pytest.approx(0.0000255)


@pytest.mark.parametrize(
    "rule",
    [
        {"hours_utc": "00:00-00:00", "weekday_timezone": "Not/A_Zone"},
        {"hours_utc": "25:00-26:00"},
        {"hours_utc": "00:00-00:00", "input_cost_per_token": True},
        {"hours_utc": "00:00-00:00", "input_cost_per_token": None},
    ],
)
def test_invalid_required_time_rule_is_unavailable(rule: dict[str, object]) -> None:
    result = estimate_model_cost(
        pricing=_pricing({**_prices(), "off_peak_pricing": rule}),
        usage=_usage(),
        billing=_billing(),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_PRICE


def test_source_absent_and_unmatched_model_definitions_are_explicit() -> None:
    timestamp = datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC)
    for source_key, expected in [
        (None, ModelPricingUnavailableReason.SOURCE_UNAVAILABLE),
        ("litellm_catalog", ModelPricingUnavailableReason.MODEL_UNMATCHED),
    ]:
        pricing = normalize_model_pricing(
            source_key=source_key,
            source_model=None,
            collected_at=timestamp,
        )
        assert pricing.unavailable_reason is expected


def test_capture_requires_aware_time_and_preserves_literal_identity() -> None:
    pricing = _pricing(_prices())
    assert pricing.model_identifier == "selected-exact-id"
    assert pricing.source_model_key == "selected-exact-id"
    with pytest.raises(ValueError, match="aware"):
        _pricing(_prices(), timestamp=datetime.datetime(2026, 10, 2))


def test_missing_saved_definition_stays_unavailable_without_source_fallback() -> None:
    captured = capture_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="selected-model",
        definition=None,
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    assert (
        captured.unavailable_reason is ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    )
    assert captured.rules is None


def test_verified_producer_prefix_keeps_execution_identity_literal() -> None:
    source = decode_catalog_source(
        b'{"gemini/literal-model":{"litellm_provider":"gemini",'
        b'"input_cost_per_token":0.000001}}'
    ).models[0]
    captured = capture_model_pricing(
        provider=LLMProvider.GOOGLE_GEMINI,
        model_identifier="literal-model",
        definition=normalize_model_pricing(
            source_key="litellm_catalog",
            source_model=source,
            collected_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
        ),
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    assert captured.model_identifier == "literal-model"
    assert captured.source_model_key == "gemini/literal-model"
    assert captured.unavailable_reason is None
    result = estimate_model_cost(
        pricing=captured, usage=_plain_usage(10, 0), billing=_billing()
    )
    assert result.cost_usd == pytest.approx(0.00001)


def test_captured_price_rules_do_not_rematch_after_refresh() -> None:
    old = _pricing({"input_cost_per_token": 0.000001})
    newer = _pricing({"input_cost_per_token": 0.000003})
    old_result = estimate_model_cost(
        pricing=old, usage=_plain_usage(10, 0), billing=_billing()
    )
    new_result = estimate_model_cost(
        pricing=newer, usage=_plain_usage(10, 0), billing=_billing()
    )
    assert old_result.cost_usd == pytest.approx(0.00001)
    assert new_result.cost_usd == pytest.approx(0.00003)
    assert (
        estimate_model_cost(pricing=old, usage=_plain_usage(10, 0), billing=_billing())
        == old_result
    )


def test_historical_schedule_is_not_fabricated_from_current_rates() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                **_prices(),
                "historical_pricing": {"start_date": "2020-01-01", "rate": 0.1},
            }
        ),
        usage=_usage(),
        billing=_billing(),
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_RULE


@pytest.mark.parametrize("rate", [None, 0])
def test_missing_price_and_explicit_zero_remain_distinct(rate: int | None) -> None:
    result = estimate_model_cost(
        pricing=_pricing({"input_cost_per_token": rate}),
        usage=_plain_usage(10, 0),
        billing=_billing(),
    )
    if rate is None:
        assert result.cost_usd is None
        assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE
    else:
        assert result.cost_usd == 0
        assert result.unavailable_reason is None


def test_absent_prices_are_not_an_invented_zero_total() -> None:
    result = estimate_model_cost(
        pricing=_pricing({}), usage=_plain_usage(0, 0), billing=_billing()
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


@pytest.mark.parametrize("size,expected", [(None, None), ("low", 0.01), ("high", 0.03)])
def test_search_context_ambiguity_prevents_partial_total(
    size: str | None, expected: float | None
) -> None:
    billing = _billing()
    component = ModelPricingComponentUsage(
        kind="web_search", quantity=1, search_context_size=None
    )
    if size == "low":
        component = dataclasses.replace(component, search_context_size="low")
    elif size == "high":
        component = dataclasses.replace(component, search_context_size="high")
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "search_context_cost_per_query": {
                    "search_context_size_low": 0.01,
                    "search_context_size_medium": 0.02,
                    "search_context_size_high": 0.03,
                }
            }
        ),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(billing, components=(component,)),
    )
    assert result.cost_usd == expected


def test_file_search_uses_per_thousand_calls_without_inferring_capability() -> None:
    result = estimate_model_cost(
        pricing=_pricing({"file_search_cost_per_1k_calls": 2.5}),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="file_search", quantity=2, search_context_size=None
                ),
            ),
        ),
    )
    assert result.cost_usd == pytest.approx(0.005)


def test_unknown_billable_components_never_publish_token_subtotal() -> None:
    result = estimate_model_cost(
        pricing=_pricing(_prices()),
        usage=_usage(),
        billing=dataclasses.replace(_billing(), unknown_billable_components=True),
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNKNOWN_COMPONENT


@pytest.mark.parametrize("quantity", [True, -1, float("nan"), float("inf"), 1.5])
def test_invalid_discrete_component_quantities_are_rejected(quantity: float) -> None:
    result = estimate_model_cost(
        pricing=_pricing({"code_interpreter_cost_per_session": 0.03}),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="code_interpreter", quantity=quantity, search_context_size=None
                ),
            ),
        ),
    )
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_USAGE


def test_unused_maps_tariff_does_not_block_a_known_web_search_price() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "google_maps_grounding_cost_per_query": 0.025,
                "search_context_cost_per_query": {
                    "search_context_size_low": 0.01,
                    "search_context_size_medium": 0.01,
                    "search_context_size_high": 0.01,
                },
            }
        ),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="web_search", quantity=1, search_context_size=None
                ),
            ),
        ),
    )
    assert result.cost_usd == 0.01


def test_explicit_session_and_fractional_duration_require_their_units() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "code_interpreter_cost_per_session": 0.03,
                "input_cost_per_audio_per_second": 0.01,
            }
        ),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="code_interpreter", quantity=2, search_context_size=None
                ),
                ModelPricingComponentUsage(
                    kind="input_audio_seconds", quantity=1.5, search_context_size=None
                ),
            ),
        ),
    )
    assert result.cost_usd == pytest.approx(0.075)


def test_missing_file_search_fee_never_returns_a_token_subtotal() -> None:
    result = estimate_model_cost(
        pricing=_pricing(_prices()),
        usage=_usage(),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="file_search", quantity=1, search_context_size=None
                ),
            ),
        ),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.MISSING_PRICE


def test_conflicting_equivalent_tariffs_cannot_choose_the_cheaper_price() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {
                "input_cost_per_token_priority_above_10_tokens": 0.1,
                "input_cost_per_token_above_10_tokens_priority": 0.2,
            }
        ),
        usage=_plain_usage(11, 0),
        billing=dataclasses.replace(_billing(), service_tier="priority"),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.UNSUPPORTED_RULE


def test_infinite_final_conversion_is_unavailable_not_an_execution_error() -> None:
    result = estimate_model_cost(
        pricing=_pricing({"input_cost_per_token": 1e300}),
        usage=_plain_usage(2**63 - 1, 0),
        billing=_billing(),
    )
    assert result.cost_usd is None
    assert result.unavailable_reason is ModelPricingUnavailableReason.INVALID_PRICE


def test_known_search_size_can_use_its_partial_source_table() -> None:
    result = estimate_model_cost(
        pricing=_pricing(
            {"search_context_cost_per_query": {"search_context_size_low": 0.01}}
        ),
        usage=_plain_usage(0, 0),
        billing=dataclasses.replace(
            _billing(),
            components=(
                ModelPricingComponentUsage(
                    kind="web_search", quantity=1, search_context_size="low"
                ),
            ),
        ),
    )
    assert result.cost_usd == 0.01
