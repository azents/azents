"""Operation pricing capture uses only explicit local generic source authority."""

import dataclasses
import datetime
from decimal import Decimal

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourcePriceSet,
    SourceProviderRecord,
    SourceScalarPrice,
)
from azents.core.model_pricing import ModelPricingUnavailableReason
from azents.engine.events.engine_adapter import _capture_model_pricing
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_metadata import make_test_model_metadata_service


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
    payload = ModelMetadataSourcePayload(
        providers=[
            SourceProviderRecord(
                id=provider_id,
                name=provider_id,
                api_pattern=f"https://{provider_id}.example/.*",
                model_match=None,
                provider_match=None,
                fallback_model_providers=None,
                models=[
                    SourceModelRecord(
                        id=model_id,
                        name=model_id,
                        match=SourceEqualsClause(value=model_id),
                        context_window=128_000,
                        deprecated=False,
                        prices=[
                            SourcePriceSet(
                                constraint=None,
                                prices={
                                    "input_mtok": SourceScalarPrice(value=Decimal("1")),
                                    "output_mtok": SourceScalarPrice(
                                        value=Decimal("2")
                                    ),
                                },
                            )
                        ],
                    )
                ],
            )
        ]
    )
    return ModelMetadataSourceSnapshot(
        id="a" * 32,
        source_key="genai_prices",
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
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
