"""Backend normalized pricing JSON round-trips through the generated public SDK."""

import datetime
from decimal import Decimal

import pytest
from azents.core.catalog_price_rules import (
    CatalogPriceRate,
    CatalogPriceRules,
    PriceMetric,
    PriceTier,
)
from azents.core.model_pricing import ModelPricingDefinition
from azentspublicclient.models.model_pricing_definition import (
    ModelPricingDefinition as ClientModelPricingDefinition,
)


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
def test_normalized_price_response_round_trips_through_generated_sdk(
    amount: Decimal | None,
) -> None:
    """Use the actual serializer/schema/SDK without converting rates to float."""
    definition = ModelPricingDefinition(
        rules=CatalogPriceRules(
            rates=(
                CatalogPriceRate(
                    metric=PriceMetric.INPUT,
                    tier=PriceTier.STANDARD,
                    above_input_tokens=None,
                    usd_per_unit=amount,
                    search_context_size=None,
                ),
            ),
            off_peak=None,
            issues=(),
        ),
        unavailable_reason=None,
        source_key="litellm_catalog",
        source_model_key="wire-model",
        collected_at=datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC),
    )
    wire = definition.model_dump(mode="json")
    client = ClientModelPricingDefinition.from_dict(wire)
    assert client is not None and client.rules is not None
    client_rate = client.rules.rates[0]
    if amount is None:
        assert client_rate.usd_per_unit is None
    else:
        assert isinstance(client_rate.usd_per_unit, str)
        assert Decimal(client_rate.usd_per_unit) == amount
    assert ModelPricingDefinition.model_validate(client.to_dict()) == definition
