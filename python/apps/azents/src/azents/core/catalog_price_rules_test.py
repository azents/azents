"""Price ingestion semantics are explicit and independent of producer execution."""

import datetime
import json
from decimal import Decimal

import pytest

from azents.core.catalog_price_rules import (
    CatalogPriceRules,
    PriceMetric,
    PriceTier,
    decode_catalog_price_rules,
)
from azents.core.model_catalog_source import decode_catalog_source


def _rules(fields: dict[str, object]) -> CatalogPriceRules:
    source = decode_catalog_source(
        json.dumps({"literal": {"litellm_provider": "openai", **fields}}).encode()
    ).models[0]
    return decode_catalog_price_rules(source)


def test_ttl_base_is_decoded_before_context_and_tariff_suffix() -> None:
    field = "cache_creation_input_token_cost_above_1hr_above_200k_tokens_batches"
    rules = _rules({field: 0.000003})
    [rate] = rules.rates
    assert rate.metric is PriceMetric.CACHE_WRITE_1H
    assert rate.above_input_tokens == 200_000
    assert rate.tier is PriceTier.BATCHES
    assert rate.usd_per_unit == Decimal("0.000003")
    assert rules.issues == ()


@pytest.mark.parametrize(
    "key",
    [
        "input_cost_per_token_priority_flex",
        "input_cost_per_token_priority_above_10_tokens_priority",
        "input_cost_per_token_above_10k_characters",
        "input_cost_per_token_new_rule",
    ],
)
def test_unsupported_or_duplicate_suffix_is_not_silently_ignored(key: str) -> None:
    rules = _rules({key: 0.1})
    assert rules.rates == ()
    assert len(rules.issues) == 1
    assert rules.issues[0].metrics == (PriceMetric.INPUT,)


def test_fractional_number_lexemes_do_not_take_a_float_round_trip() -> None:
    source = decode_catalog_source(
        b'{"m":{"litellm_provider":"openai",'
        b'"input_cost_per_token":0.12345678901234567890123456789}}'
    ).models[0]
    rules = decode_catalog_price_rules(source)
    assert rules.rates[0].usd_per_unit == Decimal("0.12345678901234567890123456789")


def test_non_usd_currency_is_an_unsupported_required_rule() -> None:
    rules = _rules({"input_cost_per_token": 0.1, "currency": "EUR"})
    assert len(rules.issues) == 1
    assert rules.issues[0].metrics == ()
    assert rules.issues[0].invalid is False


def test_unknown_request_fee_survives_as_required_unsupported_evidence() -> None:
    rules = _rules({"input_cost_per_token": 0.1, "input_cost_per_request": 0.01})
    assert rules.issues[0].source_field == "input_cost_per_request"
    assert rules.issues[0].metrics == ()


def test_weekday_and_hours_rule_is_typed_before_evaluation() -> None:
    rules = _rules(
        {
            "off_peak_pricing": {
                "windows": [
                    {"hours_utc": ["01:00-05:00", "22:00-02:00"], "weekdays": [5]},
                    {"hours_utc": "00:00-00:00", "weekdays": ["saturday"]},
                ],
                "input_cost_per_token": 0.000000001,
            }
        }
    )
    assert rules.off_peak is not None
    assert len(rules.off_peak.windows) == 3
    assert rules.off_peak.applies(
        datetime.datetime(2026, 10, 2, 23, tzinfo=datetime.UTC)
    )
    assert rules.off_peak.applies(
        datetime.datetime(2026, 10, 3, 12, tzinfo=datetime.UTC)
    )
    assert not rules.off_peak.applies(
        datetime.datetime(2026, 10, 4, 12, tzinfo=datetime.UTC)
    )


@pytest.mark.parametrize(
    "rule",
    [
        {},
        {"windows": []},
        {"hours_utc": [], "input_cost_per_token": 0},
        {"windows": [{"hours_utc": "00:00-00:00", "weekdays": [True]}]},
        {"windows": [{"hours_utc": "00:00-00:00", "weekdays": [8]}]},
        {"hours_utc": "00:00-00:00", "input_cost_per_token": "0"},
        {"hours_utc": "00:00-00:00", "unexpected_required_rule": True},
    ],
)
def test_invalid_consumed_offpeak_rules_become_explicit_issues(
    rule: dict[str, object],
) -> None:
    rules = _rules({"off_peak_pricing": rule})
    assert rules.off_peak is None
    assert len(rules.issues) == 1
    assert rules.issues[0].invalid


def test_source_price_rules_do_not_enable_capabilities() -> None:
    payload = decode_catalog_source(
        b'{"m":{"litellm_provider":"openai","supports_web_search":false,'
        b'"search_context_cost_per_query":{"search_context_size_low":0.01,'
        b'"search_context_size_medium":0.01,"search_context_size_high":0.01}}}'
    )
    rules = decode_catalog_price_rules(payload.models[0])
    assert len(rules.rates) == 3
    assert payload.models[0].facts.web_search.value is False
