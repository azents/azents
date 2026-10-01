"""Durable Pydantic ecosystem model metadata source tests."""

import datetime
from decimal import Decimal

import pytest
from genai_prices import Usage
from genai_prices.data_snapshot import DataSnapshot, get_snapshot
from genai_prices.types import (
    ClauseContains,
    ClauseEquals,
    ClauseOr,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
)
from pydantic import ValidationError

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourcePriceTier,
    SourceTieredPrice,
    encode_data_snapshot,
    lookup_source_model,
)


def _provider(*, models: list[ModelInfo]) -> Provider:
    return Provider(
        id="openai",
        name="OpenAI",
        api_pattern=r"https://api\.openai\.com/.*",
        pricing_urls=None,
        description=None,
        price_comments=None,
        model_match=ClauseContains(contains="gpt"),
        provider_match=ClauseEquals(equals="openai"),
        extractors=None,
        fallback_model_providers=None,
        models=models,
    )


def _model(identifier: str) -> ModelInfo:
    return ModelInfo(
        id=identifier,
        match=ClauseOr(
            or_=[
                ClauseEquals(equals=identifier),
                ClauseEquals(equals=f"{identifier}-latest"),
            ]
        ),
        name="Model",
        description=None,
        context_window=128_000,
        price_comments=None,
        deprecated=False,
        prices=[
            ConditionalPrice(
                constraint=None,
                prices=ModelPrice(
                    input_mtok=Decimal("1.00"),
                    output_mtok=Decimal("3.00"),
                ),
            ),
            ConditionalPrice(
                constraint=StartDateConstraint(start_date=datetime.date(2026, 1, 1)),
                prices=ModelPrice(
                    input_mtok=TieredPrices(
                        base=Decimal("2.00"),
                        tiers=[Tier(start=200_000, price=Decimal("4.00"))],
                    ),
                    output_mtok=Decimal("6.00"),
                ),
            ),
        ],
    )


def test_round_trip_preserves_match_context_and_pricing() -> None:
    """Persisted data reconstructs an isolated pricing snapshot."""
    payload = encode_data_snapshot(
        DataSnapshot(
            providers=[_provider(models=[_model("gpt-test")])],
            from_auto_update=True,
        )
    )

    restored = ModelMetadataSourcePayload.model_validate(
        payload.model_dump(mode="json")
    ).to_data_snapshot()
    provider, model = restored.find_provider_model(
        "gpt-test-latest",
        provider=None,
        provider_id="openai",
        provider_api_url=None,
    )
    price = model.calc_price(
        Usage(input_tokens=250_000, output_tokens=10_000),
        provider,
        genai_request_timestamp=datetime.datetime(
            2026, 2, 1, tzinfo=datetime.timezone.utc
        ),
    )

    assert model.context_window == 128_000
    assert price.input_price == Decimal("1.000000")
    assert price.output_price == Decimal("0.060000")
    assert price.total_price == Decimal("1.060000")


def test_hash_is_stable_for_provider_and_model_order() -> None:
    """Source ordering does not create a new durable content identity."""
    first = _provider(models=[_model("gpt-b"), _model("gpt-a")])
    second = Provider(
        id="anthropic",
        name="Anthropic",
        api_pattern=r"https://api\.anthropic\.com/.*",
        pricing_urls=None,
        description=None,
        price_comments=None,
        model_match=None,
        provider_match=None,
        extractors=None,
        fallback_model_providers=None,
        models=[],
    )

    left = encode_data_snapshot(
        DataSnapshot(providers=[first, second], from_auto_update=False)
    )
    right = encode_data_snapshot(
        DataSnapshot(
            providers=[second, _provider(models=list(reversed(first.models)))],
            from_auto_update=False,
        )
    )

    assert left.content_hash() == right.content_hash()
    assert left.canonical_bytes() == right.canonical_bytes()


def test_installed_snapshot_provider_round_trips() -> None:
    """The pinned library's current OpenAI source shape is supported."""
    openai = next(
        provider for provider in get_snapshot().providers if provider.id == "openai"
    )
    payload = encode_data_snapshot(
        DataSnapshot(providers=[openai], from_auto_update=False)
    )

    restored = payload.to_data_snapshot()
    provider, model = restored.find_provider_model(
        "chatgpt-4o-latest",
        provider=None,
        provider_id="openai",
        provider_api_url=None,
    )

    assert provider.id == "openai"
    assert model.id == "chatgpt-4o-latest"
    assert model.context_window == 128_000


def test_persisted_lookup_preserves_fallback_provider_matching() -> None:
    """A hosting provider can resolve a model owned by its fallback provider."""
    payload = encode_data_snapshot(get_snapshot())

    match = lookup_source_model(
        payload,
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model_identifier="claude-2",
    )

    assert match is not None
    assert match.provider.id == "anthropic"
    assert match.model.id == "claude-2"


def test_tier_thresholds_must_be_unique_and_ordered() -> None:
    """Malformed upstream tier order cannot become durable authority."""
    with pytest.raises(ValidationError):
        SourceTieredPrice(
            base=Decimal("1"),
            tiers=[
                SourcePriceTier(start=10, price=Decimal("2")),
                SourcePriceTier(start=10, price=Decimal("3")),
            ],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("name", ""),
        ("api_pattern", ""),
    ],
)
def test_provider_identity_fields_must_not_be_empty(
    field: str,
    value: str,
) -> None:
    """Malformed provider records cannot become durable source authority."""
    provider = {
        "id": "openai",
        "name": "OpenAI",
        "api_pattern": r"https://api\.openai\.com/.*",
        "model_match": None,
        "provider_match": None,
        "fallback_model_providers": None,
        "models": [],
    }
    provider[field] = value

    with pytest.raises(ValidationError):
        ModelMetadataSourcePayload.model_validate({"providers": [provider]})


def test_provider_and_model_identities_must_be_unique() -> None:
    """Ambiguous canonical identities fail before hashing or persistence."""
    provider = encode_data_snapshot(
        DataSnapshot(
            providers=[_provider(models=[_model("gpt-test")])],
            from_auto_update=False,
        )
    ).providers[0]

    with pytest.raises(ValidationError, match="provider IDs must be unique"):
        ModelMetadataSourcePayload(providers=[provider, provider])

    duplicate_model_provider = provider.model_copy(
        update={"models": [provider.models[0], provider.models[0]]}
    )
    with pytest.raises(
        ValidationError,
        match="IDs for provider openai must be unique",
    ):
        ModelMetadataSourcePayload(providers=[duplicate_model_provider])
