"""Captured generic pricing and provider-charge integration contracts."""

import pytest

from azents.core.enums import LLMProvider
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.types import TokenUsagePayload
from azents.testing.model_metadata import make_test_model_pricing


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


def test_reported_charge_survives_absent_price_authority() -> None:
    """A native charge cannot become unavailable with the optional source."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="publisher/model",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=0.12,
    )
    assert result.cost_usd == 0.12
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
        pricing=make_test_model_pricing(
            provider=LLMProvider.OPENAI,
            model_identifier="selected-model",
        ),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(1.97)
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "estimated"
    assert result.cost_provenance.source_snapshot_id == "source-snapshot-1"
