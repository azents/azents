"""Operation pricing capture uses only explicit local generic source authority."""

import dataclasses
from collections.abc import Callable
from typing import Never

import pytest
from pydantic_ai.usage import RequestUsage

from azents.core.enums import LLMProvider
from azents.core.model_pricing import ModelPricingUnavailableReason
from azents.engine.events.engine_adapter import _capture_model_pricing
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.types import TokenUsagePayload
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import (
    make_test_model_metadata_service,
    make_test_source_payload,
    make_test_source_snapshot,
)


@dataclasses.dataclass(frozen=True)
class _ObservedMetadataService(ModelMetadataService):
    """Count authoritative local captures without adding a remote path."""

    captures: list[str]

    async def capture(self) -> ModelMetadataSourceSnapshot | None:
        """Observe one call and delegate to the static test source."""
        self.captures.append("capture")
        return await super().capture()


def _source(
    *,
    provider_id: str = "openai",
    model_id: str = "model",
) -> ModelMetadataSourceSnapshot:
    return make_test_source_snapshot(
        make_test_source_payload(
            {
                model_id: {
                    "litellm_provider": provider_id,
                    "max_input_tokens": 128_000,
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                }
            }
        )
    )


def _observed_source(
    snapshot: ModelMetadataSourceSnapshot | None,
) -> _ObservedMetadataService:
    """Build a deterministic explicit source reader for operation tests."""
    base = make_test_model_metadata_service(snapshot=snapshot)
    return _ObservedMetadataService(
        session_manager=base.session_manager,
        source_snapshot_repository=base.source_snapshot_repository,
        captures=[],
    )


async def test_pricing_captures_source_once_with_semantic_identity() -> None:
    """The estimator input uses exact selected model and snapshot provenance."""
    source = _source()
    metadata = _observed_source(source)
    pricing = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.OPENAI,
        model_identifier="model",
    )
    assert metadata.captures == ["capture"]
    assert pricing.provider is LLMProvider.OPENAI
    assert pricing.model_identifier == "model"
    assert pricing.source_snapshot_id == source.id
    assert pricing.source_hash == source.source_hash
    assert pricing.source_model_key == "model"
    assert pricing.unavailable_reason is None


async def test_missing_source_preserves_semantic_charge_identity() -> None:
    """Missing prices are explicit evidence rather than an execution failure."""
    metadata = _observed_source(None)
    pricing = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.OPENROUTER,
        model_identifier="publisher/exact-model",
    )
    assert metadata.captures == ["capture"]
    assert pricing.provider is LLMProvider.OPENROUTER
    assert pricing.model_identifier == "publisher/exact-model"
    assert pricing.source_snapshot_id is None
    assert pricing.source_hash is None
    assert pricing.source_model_key is None
    assert pricing.unavailable_reason is not None


async def test_conflicting_provider_does_not_borrow_price_source() -> None:
    """One provider cannot borrow another provider's canonical model price."""
    source = _source(model_id="same")
    metadata = _observed_source(source)
    pricing = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.OPENAI,
        model_identifier="same",
    )
    assert metadata.captures == ["capture"]
    assert pricing.source_model_key == "same"
    assert pricing.unavailable_reason is None
    conflicting = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.GOOGLE_GEMINI,
        model_identifier="same",
    )
    assert (
        conflicting.unavailable_reason is ModelPricingUnavailableReason.MODEL_UNMATCHED
    )


def _forbidden_price_callback(
    entrypoint: str, calls: list[str]
) -> Callable[..., Never]:
    """Record even a swallowed forbidden call before failing the operation."""

    def forbidden(*_args: object, **_kwargs: object) -> Never:
        calls.append(entrypoint)
        raise AssertionError(f"Retired price authority invoked: {entrypoint}")

    return forbidden


@pytest.mark.parametrize("source_available", [True, False])
async def test_capture_and_estimate_do_not_use_transitive_price_authority(
    monkeypatch: pytest.MonkeyPatch, source_available: bool
) -> None:
    """Allow local stock usage extraction, but forbid all old pricing/update paths."""
    forbidden_calls: list[str] = []
    # These are real installed entrypoints, not synthetic module stubs. The public
    # UpdatePrices alias is the same class, so class-method patches cover both paths.
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

    # Do not poison get_snapshot: retained Pydantic adapters legitimately use its
    # bundled provider rules to extract counters, independently of price authority.
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

    metadata = _observed_source(_source() if source_available else None)
    pricing = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.OPENAI,
        model_identifier="model",
    )
    assert metadata.captures == ["capture"]
    assert pricing.request_timestamp.utcoffset() is not None
    usage = TokenUsagePayload(
        prompt_tokens=extracted.input_tokens,
        completion_tokens=extracted.output_tokens,
        total_tokens=extracted.input_tokens + extracted.output_tokens,
        raw={},
        cached_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=None,
        cost_usd=None,
        raw_hidden_params=None,
    )
    result = apply_model_usage_pricing(
        usage,
        provider="openai",
        model_identifier="model",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    if source_available:
        assert result.cost_usd == pytest.approx(0.000020)
        assert result.cost_provenance is not None
        assert result.cost_provenance.method == "estimated"
        assert result.cost_provenance.source_hash == pricing.source_hash
    else:
        assert (
            pricing.unavailable_reason
            is ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
        )
        assert result.cost_usd is None
        assert result.cost_provenance is None

    reported = apply_model_usage_pricing(
        usage,
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
    assert reported.cost_provenance.source_snapshot_id is None
    assert forbidden_calls == []
