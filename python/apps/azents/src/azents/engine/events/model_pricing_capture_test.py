"""Physical pricing capture uses saved rules without any dataset authority."""

import datetime
from collections.abc import Callable
from typing import Never

import pytest
from pydantic_ai.usage import RequestUsage

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_pricing import (
    ModelPricingDefinition,
    ModelPricingUnavailableReason,
    normalize_model_pricing,
)
from azents.engine.events.engine_adapter import _capture_model_pricing
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.types import TokenUsagePayload


def _definition(rate: str = "0.000001") -> ModelPricingDefinition:
    model = decode_catalog_source(
        (
            '{"model":{"litellm_provider":"openai",'
            f'"input_cost_per_token":{rate},"output_cost_per_token":0.000002}}}}'
        ).encode()
    ).models[0]
    return normalize_model_pricing(
        source_key="litellm_catalog",
        source_model=model,
        collected_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def _usage() -> TokenUsagePayload:
    return TokenUsagePayload(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw={},
        cached_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=None,
        cost_usd=None,
        raw_hidden_params=None,
    )


def _forbidden_price_callback(
    entrypoint: str, calls: list[str]
) -> Callable[..., Never]:
    def forbidden(*_args: object, **_kwargs: object) -> Never:
        calls.append(entrypoint)
        raise AssertionError(f"Forbidden price authority invoked: {entrypoint}")

    return forbidden


@pytest.mark.parametrize("price_available", [True, False])
def test_capture_has_zero_source_reads_or_price_interpretation(
    monkeypatch: pytest.MonkeyPatch, price_available: bool
) -> None:
    """Even missing saved prices cannot trigger a source restore or lazy fill."""
    definition = _definition() if price_available else None
    calls: list[str] = []
    for entrypoint in (
        "azents.services.model_metadata.ModelMetadataService.capture_for_context",
        "azents.repos.model_metadata_read.ModelMetadataReadRepository.capture_for_context",
        "azents.core.catalog_price_rules.decode_catalog_price_rules",
        "azents.core.model_pricing.decode_catalog_price_rules",
        "azents.core.model_catalog_source.decode_catalog_source",
        "hashlib.sha256",
    ):
        monkeypatch.setattr(entrypoint, _forbidden_price_callback(entrypoint, calls))
    for _ in range(3):
        pricing = _capture_model_pricing(
            definition=definition,
            provider=LLMProvider.OPENAI,
            model_identifier="model",
        )
        assert pricing.provider is LLMProvider.OPENAI
        assert pricing.model_identifier == "model"
        assert pricing.request_timestamp.utcoffset() is not None
        assert pricing.rules is (definition.rules if definition is not None else None)
    assert calls == []


def test_capture_keeps_saved_prices_after_current_definition_changes() -> None:
    """The current catalog is not an execution pricing authority."""
    saved = _definition()
    current = _definition("0.000003")
    assert saved != current
    pricing = _capture_model_pricing(
        definition=saved, provider=LLMProvider.OPENAI, model_identifier="model"
    )
    result = apply_model_usage_pricing(
        _usage(),
        provider="openai",
        model_identifier="model",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(0.000020)
    assert result.cost_provenance is not None
    assert result.cost_provenance.collected_at == saved.collected_at
    assert "source_snapshot_id" not in result.cost_provenance.model_dump()
    assert "source_hash" not in result.cost_provenance.model_dump()


def test_missing_definition_preserves_semantic_charge_identity() -> None:
    pricing = _capture_model_pricing(
        definition=None,
        provider=LLMProvider.OPENROUTER,
        model_identifier="publisher/exact-model",
    )
    assert pricing.provider is LLMProvider.OPENROUTER
    assert pricing.model_identifier == "publisher/exact-model"
    assert pricing.source_key is None
    assert pricing.source_model_key is None
    assert pricing.rules is None
    assert (
        pricing.unavailable_reason is ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    )


@pytest.mark.parametrize("price_available", [True, False])
def test_capture_and_estimate_do_not_use_transitive_price_authority(
    monkeypatch: pytest.MonkeyPatch, price_available: bool
) -> None:
    """Stock counter extraction is independent of every transitive price helper."""
    definition = _definition() if price_available else None
    forbidden_calls: list[str] = []
    for entrypoint in (
        "genai_prices.calc_price",
        "genai_prices.data_snapshot.DataSnapshot.calc",
        "genai_prices.types.ExtractedUsage.calc_price",
        "genai_prices.types.ModelInfo.calc_price",
        "genai_prices.types.ModelPrice.calc_price",
        "genai_prices.update_prices.UpdatePrices.fetch",
        "genai_prices.update_prices.UpdatePrices.start",
    ):
        monkeypatch.setattr(
            entrypoint, _forbidden_price_callback(entrypoint, forbidden_calls)
        )
    extracted = RequestUsage.extract(
        {
            "model": "usage-extraction-fixture",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        provider="openai",
        provider_url="https://api.openai.com/v1",
        provider_fallback="openai",
        api_flavor="chat",
    )
    assert extracted.input_tokens == 10
    assert extracted.output_tokens == 5
    pricing = _capture_model_pricing(
        definition=definition, provider=LLMProvider.OPENAI, model_identifier="model"
    )
    result = apply_model_usage_pricing(
        _usage(),
        provider="openai",
        model_identifier="model",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    if price_available:
        assert result.cost_usd == pytest.approx(0.000020)
        assert result.cost_provenance is not None
        assert result.cost_provenance.method == "estimated"
    else:
        assert result.cost_usd is None
        assert result.cost_provenance is None
    reported = apply_model_usage_pricing(
        _usage(),
        provider="openai",
        model_identifier="model",
        pricing=pricing,
        service_tier="priority",
        output_item_types=["image_generation_call"],
        reported_charge=0.0,
    )
    assert reported.cost_usd == 0.0
    assert reported.cost_provenance is not None
    assert reported.cost_provenance.method == "provider_reported"
    assert reported.cost_provenance.source_key is None
    assert forbidden_calls == []
