"""Versioned durable model metadata decoded from the Pydantic ecosystem source."""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal, assert_never

from genai_prices.data_snapshot import DataSnapshot
from genai_prices.types import (
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    ConditionalPrice,
    MatchLogic,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
    TimeOfDateConstraint,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODEL_METADATA_SOURCE_SCHEMA_VERSION = "1"


class SourceStartsWithClause(BaseModel):
    """Match model identifiers by prefix."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["starts_with"] = "starts_with"
    value: str = Field(min_length=1)


class SourceEndsWithClause(BaseModel):
    """Match model identifiers by suffix."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ends_with"] = "ends_with"
    value: str = Field(min_length=1)


class SourceContainsClause(BaseModel):
    """Match model identifiers by contained text."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["contains"] = "contains"
    value: str = Field(min_length=1)


class SourceRegexClause(BaseModel):
    """Match model identifiers by regular expression."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["regex"] = "regex"
    value: str = Field(min_length=1)


class SourceEqualsClause(BaseModel):
    """Match one exact model identifier."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["equals"] = "equals"
    value: str = Field(min_length=1)


class SourceOrClause(BaseModel):
    """Match when any child clause matches."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["or"] = "or"
    clauses: list[SourceMatchClause] = Field(min_length=1)


class SourceAndClause(BaseModel):
    """Match when every child clause matches."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["and"] = "and"
    clauses: list[SourceMatchClause] = Field(min_length=1)


SourceMatchClause = Annotated[
    SourceStartsWithClause
    | SourceEndsWithClause
    | SourceContainsClause
    | SourceRegexClause
    | SourceEqualsClause
    | SourceOrClause
    | SourceAndClause,
    Field(discriminator="kind"),
]


class SourcePriceTier(BaseModel):
    """One threshold tier in a source price."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=0)
    price: Decimal = Field(ge=0)


class SourceScalarPrice(BaseModel):
    """One scalar price value."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["scalar"] = "scalar"
    value: Decimal = Field(ge=0)


class SourceTieredPrice(BaseModel):
    """One threshold-dependent price value."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["tiered"] = "tiered"
    base: Decimal = Field(ge=0)
    tiers: list[SourcePriceTier]

    @field_validator("tiers")
    @classmethod
    def validate_ordered_tiers(
        cls, value: list[SourcePriceTier]
    ) -> list[SourcePriceTier]:
        """Require strictly increasing tier thresholds."""
        starts = [tier.start for tier in value]
        if starts != sorted(set(starts)):
            raise ValueError("Price tier thresholds must be unique and ordered.")
        return value


SourcePriceValue = Annotated[
    SourceScalarPrice | SourceTieredPrice,
    Field(discriminator="kind"),
]


class SourceStartDatePriceConstraint(BaseModel):
    """Apply one price set from a UTC date."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["start_date"] = "start_date"
    start_date: datetime.date


class SourceTimeOfDayPriceConstraint(BaseModel):
    """Apply one price set during a UTC time interval."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["time_of_day"] = "time_of_day"
    start_time: datetime.time
    end_time: datetime.time


SourcePriceConstraint = Annotated[
    SourceStartDatePriceConstraint | SourceTimeOfDayPriceConstraint,
    Field(discriminator="kind"),
]


class SourcePriceSet(BaseModel):
    """One conditional set of source billing unit prices."""

    model_config = ConfigDict(frozen=True)

    constraint: SourcePriceConstraint | None
    prices: dict[str, SourcePriceValue]


class SourceModelRecord(BaseModel):
    """One canonical model and its source matching and pricing evidence."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str | None
    match: SourceMatchClause
    context_window: int | None = Field(ge=1)
    deprecated: bool | None
    prices: list[SourcePriceSet]


class SourceProviderRecord(BaseModel):
    """One canonical provider and its models."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    api_pattern: str = Field(min_length=1)
    model_match: SourceMatchClause | None
    provider_match: SourceMatchClause | None
    fallback_model_providers: list[str] | None
    models: list[SourceModelRecord]


class ModelMetadataSourcePayload(BaseModel):
    """JSON-safe source snapshot used by catalog and runtime operations."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = MODEL_METADATA_SOURCE_SCHEMA_VERSION
    providers: list[SourceProviderRecord]

    @model_validator(mode="after")
    def validate_unique_identities(self) -> ModelMetadataSourcePayload:
        """Reject ambiguous provider and model identities."""
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("Model metadata provider IDs must be unique.")
        for provider in self.providers:
            model_ids = [model.id for model in provider.models]
            if len(model_ids) != len(set(model_ids)):
                raise ValueError(
                    f"Model metadata IDs for provider {provider.id} must be unique."
                )
        return self

    @property
    def provider_count(self) -> int:
        """Return the number of stored providers."""
        return len(self.providers)

    @property
    def model_count(self) -> int:
        """Return the number of stored models."""
        return sum(len(provider.models) for provider in self.providers)

    def canonical_bytes(self) -> bytes:
        """Serialize stable JSON for content-addressed persistence."""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def content_hash(self) -> str:
        """Return the stable SHA-256 hash of canonical content."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_data_snapshot(self) -> DataSnapshot:
        """Reconstruct an isolated genai-prices snapshot."""
        return DataSnapshot(
            providers=[_decode_provider(provider) for provider in self.providers],
            from_auto_update=False,
        )


def encode_data_snapshot(snapshot: DataSnapshot) -> ModelMetadataSourcePayload:
    """Encode one typed genai-prices snapshot into durable source data."""
    providers = [_encode_provider(provider) for provider in snapshot.providers]
    providers.sort(key=lambda provider: provider.id)
    return ModelMetadataSourcePayload(providers=providers)


def _encode_provider(provider: Provider) -> SourceProviderRecord:
    models = [_encode_model(model) for model in provider.models]
    models.sort(key=lambda model: model.id)
    return SourceProviderRecord(
        id=provider.id,
        name=provider.name,
        api_pattern=provider.api_pattern,
        model_match=(
            _encode_match(provider.model_match)
            if provider.model_match is not None
            else None
        ),
        provider_match=(
            _encode_match(provider.provider_match)
            if provider.provider_match is not None
            else None
        ),
        fallback_model_providers=(
            sorted(provider.fallback_model_providers)
            if provider.fallback_model_providers is not None
            else None
        ),
        models=models,
    )


def _encode_model(model: ModelInfo) -> SourceModelRecord:
    prices = model.prices
    if isinstance(prices, ModelPrice):
        encoded_prices = [
            SourcePriceSet(constraint=None, prices=_encode_price_values(prices))
        ]
    else:
        encoded_prices = [_encode_conditional_price(price) for price in prices]
    return SourceModelRecord(
        id=model.id,
        name=model.name,
        match=_encode_match(model.match),
        context_window=model.context_window,
        deprecated=model.deprecated,
        prices=encoded_prices,
    )


def _encode_conditional_price(price: ConditionalPrice) -> SourcePriceSet:
    constraint = price.constraint
    if constraint is None:
        encoded_constraint = None
    elif isinstance(constraint, StartDateConstraint):
        encoded_constraint = SourceStartDatePriceConstraint(
            start_date=constraint.start_date
        )
    elif isinstance(constraint, TimeOfDateConstraint):
        encoded_constraint = SourceTimeOfDayPriceConstraint(
            start_time=constraint.start_time,
            end_time=constraint.end_time,
        )
    else:
        assert_never(constraint)
    return SourcePriceSet(
        constraint=encoded_constraint,
        prices=_encode_price_values(price.prices),
    )


def _encode_price_values(price: ModelPrice) -> dict[str, SourcePriceValue]:
    result: dict[str, SourcePriceValue] = {}
    for key, value in sorted(price.__dict__.items()):
        if key.startswith("_") or value is None:
            continue
        if isinstance(value, Decimal):
            result[key] = SourceScalarPrice(value=value)
        elif isinstance(value, TieredPrices):
            result[key] = SourceTieredPrice(
                base=value.base,
                tiers=[
                    SourcePriceTier(start=tier.start, price=tier.price)
                    for tier in value.tiers
                ],
            )
        else:
            raise ValueError(f"Unsupported source price value for {key}.")
    return result


def _encode_match(match: MatchLogic) -> SourceMatchClause:
    match match:
        case ClauseStartsWith(starts_with=value):
            return SourceStartsWithClause(value=value)
        case ClauseEndsWith(ends_with=value):
            return SourceEndsWithClause(value=value)
        case ClauseContains(contains=value):
            return SourceContainsClause(value=value)
        case ClauseRegex(regex=value):
            return SourceRegexClause(value=value)
        case ClauseEquals(equals=value):
            return SourceEqualsClause(value=value)
        case ClauseOr(or_=clauses):
            return SourceOrClause(clauses=[_encode_match(clause) for clause in clauses])
        case ClauseAnd(and_=clauses):
            return SourceAndClause(
                clauses=[_encode_match(clause) for clause in clauses]
            )
        case _ as unreachable:
            assert_never(unreachable)


def _decode_provider(provider: SourceProviderRecord) -> Provider:
    return Provider(
        id=provider.id,
        name=provider.name,
        api_pattern=provider.api_pattern,
        pricing_urls=None,
        description=None,
        price_comments=None,
        model_match=(
            _decode_match(provider.model_match)
            if provider.model_match is not None
            else None
        ),
        provider_match=(
            _decode_match(provider.provider_match)
            if provider.provider_match is not None
            else None
        ),
        extractors=None,
        fallback_model_providers=provider.fallback_model_providers,
        models=[_decode_model(model) for model in provider.models],
    )


def _decode_model(model: SourceModelRecord) -> ModelInfo:
    prices: ModelPrice | list[ConditionalPrice]
    if len(model.prices) == 1 and model.prices[0].constraint is None:
        prices = _decode_model_price(model.prices[0].prices)
    else:
        prices = [
            ConditionalPrice(
                constraint=(
                    _decode_price_constraint(price.constraint)
                    if price.constraint is not None
                    else None
                ),
                prices=_decode_model_price(price.prices),
            )
            for price in model.prices
        ]
    return ModelInfo(
        id=model.id,
        match=_decode_match(model.match),
        name=model.name,
        description=None,
        context_window=model.context_window,
        price_comments=None,
        deprecated=model.deprecated,
        prices=prices,
    )


def _decode_model_price(prices: dict[str, SourcePriceValue]) -> ModelPrice:
    values: dict[str, Decimal | TieredPrices | None] = {}
    for key, price in prices.items():
        if isinstance(price, SourceScalarPrice):
            values[key] = price.value
        elif isinstance(price, SourceTieredPrice):
            values[key] = TieredPrices(
                base=price.base,
                tiers=[
                    Tier(start=tier.start, price=tier.price) for tier in price.tiers
                ],
            )
        else:
            assert_never(price)
    return ModelPrice(**values)


def _decode_price_constraint(
    constraint: SourcePriceConstraint,
) -> StartDateConstraint | TimeOfDateConstraint:
    if isinstance(constraint, SourceStartDatePriceConstraint):
        return StartDateConstraint(start_date=constraint.start_date)
    if isinstance(constraint, SourceTimeOfDayPriceConstraint):
        return TimeOfDateConstraint(
            start_time=constraint.start_time,
            end_time=constraint.end_time,
        )
    assert_never(constraint)


def _decode_match(match: SourceMatchClause) -> MatchLogic:
    if isinstance(match, SourceStartsWithClause):
        return ClauseStartsWith(starts_with=match.value)
    if isinstance(match, SourceEndsWithClause):
        return ClauseEndsWith(ends_with=match.value)
    if isinstance(match, SourceContainsClause):
        return ClauseContains(contains=match.value)
    if isinstance(match, SourceRegexClause):
        return ClauseRegex(regex=match.value)
    if isinstance(match, SourceEqualsClause):
        return ClauseEquals(equals=match.value)
    if isinstance(match, SourceOrClause):
        return ClauseOr(or_=[_decode_match(clause) for clause in match.clauses])
    if isinstance(match, SourceAndClause):
        return ClauseAnd(and_=[_decode_match(clause) for clause in match.clauses])
    assert_never(match)
