"""Captured catalog pricing and provider-charge integration contracts."""

import datetime

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_pricing import normalize_model_pricing
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.types import TokenUsagePayload


def _usage(raw: dict[str, object]) -> TokenUsagePayload:
    """Create inclusive common Responses counters."""
    return TokenUsagePayload(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw=raw,
        cached_tokens=2,
        cache_creation_tokens=3,
        reasoning_tokens=1,
        cost_usd=None,
        raw_hidden_params=None,
    )


@pytest.mark.parametrize("charge", [0.0, 0.12])
def test_reported_charge_survives_absent_price_authority(charge: float) -> None:
    """A native charge cannot become unavailable with the optional source."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="publisher/model",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=charge,
    )
    assert result.cost_usd == charge
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "provider_reported"
    assert result.cost_provenance.source_snapshot_id is None


@pytest.mark.parametrize("reported_charge", [True, -1.0, float("nan"), float("inf")])
def test_invalid_reported_charge_stays_unknown_without_source(
    reported_charge: float,
) -> None:
    """Invalid native amounts do not become a zero charge."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="publisher/model",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=reported_charge,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


def test_generic_estimate_retains_captured_provenance() -> None:
    """The isolated generic evaluator returns a complete captured estimate."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openai",
        model_identifier="selected-model",
        pricing=normalize_model_pricing(
            provider=LLMProvider.OPENAI,
            model_identifier="selected-model",
            source_snapshot_id="source-snapshot-1",
            source_hash="source-hash",
            source_model=decode_catalog_source(
                b'{"selected-model":{"litellm_provider":"openai",'
                b'"input_cost_per_token":0.1,'
                b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
                b'"cache_creation_input_token_cost":0.15}}'
            ).models[0],
            request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
        ),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(1.97)
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "estimated"
    assert result.cost_provenance.source_snapshot_id == "source-snapshot-1"


@pytest.mark.parametrize(
    "item_type", ["code_interpreter_call", "image_generation_call"]
)
def test_output_item_count_does_not_invent_session_or_media_quantity(
    item_type: str,
) -> None:
    pricing = normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="selected-model",
        source_snapshot_id="s",
        source_hash="h",
        source_model=decode_catalog_source(
            b'{"selected-model":{"litellm_provider":"openai",'
            b'"input_cost_per_token":0.1,'
            b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
            b'"cache_creation_input_token_cost":0.15,'
            b'"code_interpreter_cost_per_session":0.03}}'
        ).models[0],
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openai",
        model_identifier="selected-model",
        pricing=pricing,
        service_tier=None,
        output_item_types=[item_type],
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


@pytest.mark.parametrize(
    "raw",
    [
        {"input_tokens_details": "malformed"},
        {"output_tokens_details": {"audio_tokens": "2"}},
        {"audio_tokens": 2},
        {"cache_creation": False},
    ],
)
def test_malformed_or_undirected_breakdown_does_not_produce_a_partial_estimate(
    raw: dict[str, object],
) -> None:
    pricing = normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="m",
        source_snapshot_id="s",
        source_hash="h",
        source_model=decode_catalog_source(
            b'{"m":{"litellm_provider":"openai","input_cost_per_token":0.1,'
            b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
            b'"cache_creation_input_token_cost":0.15}}'
        ).models[0],
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    result = apply_model_usage_pricing(
        _usage(raw),
        provider="openai",
        model_identifier="m",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd is None
    reported = apply_model_usage_pricing(
        _usage(raw),
        provider="openai",
        model_identifier="m",
        pricing=pricing,
        service_tier=None,
        output_item_types=["image_generation_call"],
        reported_charge=0.0,
    )
    assert reported.cost_usd == 0
    assert reported.cost_provenance is not None
    assert reported.cost_provenance.method == "provider_reported"


def test_upstream_computed_cost_is_not_adopted_without_native_charge() -> None:
    usage = _usage({}).model_copy(
        update={"cost_usd": 99.0, "raw_hidden_params": {"response_cost": 99.0}}
    )
    result = apply_model_usage_pricing(
        usage,
        provider="openai",
        model_identifier="m",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None
