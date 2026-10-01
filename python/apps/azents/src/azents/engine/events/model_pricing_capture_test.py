"""Operation pricing capture uses only explicit local source authority."""

import dataclasses
import datetime

from azents.core.enums import LLMProvider
from azents.core.model_pricing import ModelPricingUnavailableReason
from azents.engine.events.engine_adapter import _capture_model_pricing
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import make_test_model_metadata_service


@dataclasses.dataclass(frozen=True)
class _ObservedMetadataService(ModelMetadataService):
    """Count authoritative local captures without adding a remote path."""

    captures: list[str]

    async def capture(self) -> LiteLLMSourceSnapshot | None:
        """Observe one call and delegate to the static test source."""
        self.captures.append("capture")
        return await super().capture()


def _observed_source(
    snapshot: LiteLLMSourceSnapshot | None,
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
    source = LiteLLMSourceSnapshot(
        id="a" * 32,
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="b" * 64,
        model_count=1,
        litellm_version=None,
        loaded_source="remote",
        payload={
            "openai/model": {
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
            }
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )
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
    assert pricing.source_model_key == "openai/model"
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


async def test_conflicting_bare_candidate_does_not_hide_correct_price_source() -> None:
    source = LiteLLMSourceSnapshot(
        id="a" * 32,
        source_key="litellm_model_cost",
        source_url=None,
        source_hash="b" * 64,
        model_count=2,
        litellm_version=None,
        loaded_source="remote",
        payload={
            "same": {
                "litellm_provider": "anthropic",
                "input_cost_per_token": 99.0,
                "output_cost_per_token": 99.0,
            },
            "openai/same": {
                "litellm_provider": "openai",
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
            },
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )
    metadata = _observed_source(source)
    pricing = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.OPENAI,
        model_identifier="same",
    )
    assert metadata.captures == ["capture"]
    assert pricing.source_model_key == "openai/same"
    assert pricing.unavailable_reason is None
    conflicting = await _capture_model_pricing(
        metadata_service=metadata,
        provider=LLMProvider.GOOGLE_GEMINI,
        model_identifier="same",
    )
    assert (
        conflicting.unavailable_reason is ModelPricingUnavailableReason.MODEL_UNMATCHED
    )
