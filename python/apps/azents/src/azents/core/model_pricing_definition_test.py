"""Lossless persisted pricing and read-only historical selection contracts."""

import datetime
import json
import re
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic.json_schema import JsonSchemaMode

from azents.core.agent import AgentModelSelection, AgentModelSelectionInput
from azents.core.catalog_price_rules import CatalogPriceRate, PriceMetric, PriceTier
from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_pricing import (
    ModelPricingDefinition,
    ModelPricingUnavailableReason,
    capture_model_pricing,
    normalize_model_pricing,
)
from azents.engine.events.types import ModelCostProvenance
from azents.testing.model_selection import make_test_model_selection


@pytest.mark.parametrize("mode", ["validation", "serialization"])
@pytest.mark.parametrize(
    "amount",
    [
        Decimal("1E-7"),
        Decimal("1E+7"),
        Decimal("0"),
        Decimal("-0"),
        Decimal("0.00000012345678901234567890123456789"),
        None,
    ],
)
def test_normalized_rate_wire_json_matches_schema_losslessly(
    mode: JsonSchemaMode, amount: Decimal | None
) -> None:
    """Every published Decimal representation satisfies the generated-client schema."""
    rate = CatalogPriceRate(
        metric=PriceMetric.INPUT,
        tier=PriceTier.STANDARD,
        above_input_tokens=None,
        usd_per_unit=amount,
        search_context_size=None,
    )
    adapter = TypeAdapter(CatalogPriceRate)
    wire = adapter.dump_json(rate)
    value = json.loads(wire)["usd_per_unit"]
    variants = adapter.json_schema(mode=mode)["properties"]["usd_per_unit"]["anyOf"]
    if amount is None:
        assert value is None
        assert {"type": "null"} in variants
    else:
        string_schema = next(item for item in variants if item.get("type") == "string")
        assert isinstance(value, str)
        assert re.fullmatch(string_schema["pattern"], value) is not None
        assert Decimal(value) == amount
    assert adapter.validate_json(wire) == rate


def _definition() -> ModelPricingDefinition:
    source = decode_catalog_source(
        b'{"model":{"litellm_provider":"openai",'
        b'"input_cost_per_token":0.00000012345678901234567890123456789,'
        b'"output_cost_per_token":0.000002,'
        b'"input_cost_per_token_priority":0.000003,'
        b'"input_cost_per_token_above_200k_tokens":0.000004,'
        b'"cache_creation_input_token_cost_above_1hr":0.000005,'
        b'"input_cost_per_audio_token":null,'
        b'"input_cost_per_token_inference_geo":0.000001}}'
    ).models[0]
    return normalize_model_pricing(
        source_key="litellm_catalog",
        source_model=source,
        collected_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def test_price_definition_round_trip_preserves_decimal_rules_and_issues() -> None:
    definition = _definition()
    encoded = definition.model_dump_json()
    restored = ModelPricingDefinition.model_validate_json(encoded)
    assert restored == definition
    assert restored.rules is not None
    assert any(
        rate.usd_per_unit == Decimal("0.00000012345678901234567890123456789")
        for rate in restored.rules.rates
    )
    serialized_rules = definition.model_dump(mode="json")["rules"]
    assert all(
        rate["usd_per_unit"] is None or isinstance(rate["usd_per_unit"], str)
        for rate in serialized_rules["rates"]
    )
    assert restored.rules.issues
    assert set(restored.model_dump()) == {
        "rules",
        "unavailable_reason",
        "source_key",
        "source_model_key",
        "collected_at",
    }


def test_selected_definition_survives_selection_json_round_trip() -> None:
    selection = make_test_model_selection().model_copy(
        update={"pricing": _definition()}
    )
    restored = AgentModelSelection.model_validate_json(selection.model_dump_json())
    assert restored.pricing == selection.pricing
    assert restored.pricing is not None
    with pytest.raises(ValidationError, match="frozen"):
        # Exercise the runtime mutation guard that the type checker also forbids.
        restored.pricing.source_key = "different"  # ty: ignore[invalid-assignment]


def test_historical_selection_absence_is_read_only_and_stays_unavailable() -> None:
    original = make_test_model_selection().model_dump(mode="json")
    del original["pricing"]
    before = dict(original)
    decoded = AgentModelSelection.model_validate(original)
    assert original == before
    assert "pricing" not in original
    assert decoded.pricing is None
    captured = capture_model_pricing(
        provider=decoded.provider,
        model_identifier=decoded.model_identifier,
        definition=decoded.pricing,
        request_timestamp=datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC),
    )
    assert captured.rules is None
    assert (
        captured.unavailable_reason is ModelPricingUnavailableReason.SOURCE_UNAVAILABLE
    )


def test_selection_mutation_cannot_supply_price_authority() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AgentModelSelectionInput.model_validate(
            {
                "llm_provider_integration_id": "integration",
                "model_identifier": "model",
                "pricing": _definition().model_dump(mode="json"),
            }
        )


def test_historical_provenance_keeps_opaque_fields_without_mutation() -> None:
    original = {
        "method": "estimated",
        "provider": "openai",
        "model_identifier": "model",
        "service_tier": "standard",
        "source_snapshot_id": "historical-source",
        "source_hash": "historical-hash",
        "source_model_key": "model",
        "estimator_version": "1",
    }
    before = dict(original)
    decoded = ModelCostProvenance.model_validate(original)
    assert original == before
    assert decoded.source_key is None
    assert decoded.collected_at is None
    assert decoded.model_dump()["source_snapshot_id"] == "historical-source"
    assert decoded.model_dump()["source_hash"] == "historical-hash"


def test_collection_and_dispatch_times_have_independent_authority() -> None:
    definition = _definition()
    dispatch = datetime.datetime(2026, 10, 3, 19, tzinfo=datetime.UTC)
    captured = capture_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="model",
        definition=definition,
        request_timestamp=dispatch,
    )
    assert captured.collected_at == definition.collected_at
    assert captured.request_timestamp == dispatch
    assert captured.collected_at != captured.request_timestamp
    with pytest.raises(ValidationError, match="timezone-aware"):
        ModelPricingDefinition.model_validate(
            {
                **definition.model_dump(),
                "collected_at": datetime.datetime(2026, 10, 3),
            }
        )


def test_price_definition_rejects_ambiguous_availability_and_extra_authority() -> None:
    for values in (
        {"rules": None, "unavailable_reason": None},
        {
            "rules": _definition().rules,
            "unavailable_reason": ModelPricingUnavailableReason.MODEL_UNMATCHED,
        },
        {"source_hash": "new-hash"},
    ):
        with pytest.raises(ValidationError):
            ModelPricingDefinition.model_validate(
                {**_definition().model_dump(), **values}
            )
