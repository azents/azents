"""Interpret captured catalog pricing evidence into immutable bounded rules."""

from __future__ import annotations

import dataclasses
import datetime
import json
import re
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from azents.core.model_catalog_source import CatalogPriceEvidence, CatalogSourceModel


class PriceMetric(StrEnum):
    INPUT = "input_tokens"
    OUTPUT = "output_tokens"
    CACHE_READ = "cache_read_tokens"
    CACHE_WRITE = "cache_write_tokens"
    CACHE_WRITE_1H = "cache_write_1h_tokens"
    REASONING = "reasoning_tokens"
    INPUT_AUDIO = "input_audio_tokens"
    INPUT_IMAGE = "input_image_tokens"
    OUTPUT_AUDIO = "output_audio_tokens"
    OUTPUT_IMAGE = "output_image_tokens"
    WEB_SEARCH = "web_search"
    MAPS_GROUNDING = "maps_grounding"
    FILE_SEARCH = "file_search"
    CODE_SESSION = "code_interpreter"
    INPUT_IMAGES = "input_images"
    OUTPUT_IMAGES = "output_images"
    INPUT_AUDIO_SECONDS = "input_audio_seconds"
    INPUT_VIDEO_SECONDS = "input_video_seconds"
    OUTPUT_AUDIO_SECONDS = "output_audio_seconds"
    OUTPUT_VIDEO_SECONDS = "output_video_seconds"


class PriceTier(StrEnum):
    STANDARD = "standard"
    PRIORITY = "priority"
    FLEX = "flex"
    BATCHES = "batches"
    ULTRAFAST = "ultrafast"


@dataclasses.dataclass(frozen=True)
class CatalogPriceRate:
    """A whole-quantity tariff, not a progressive marginal bracket."""

    metric: PriceMetric
    tier: PriceTier | None
    above_input_tokens: int | None
    usd_per_unit: Decimal | None
    search_context_size: Literal["low", "medium", "high"] | None


@dataclasses.dataclass(frozen=True)
class CatalogPriceIssue:
    """A required but uninterpretable dimension that prevents a partial total."""

    source_field: str
    metrics: tuple[PriceMetric, ...]
    dimension: Literal["residency", "geography", "speed"] | None
    invalid: bool


@dataclasses.dataclass(frozen=True)
class CatalogTimeWindow:
    """UTC minute window with an independently scoped weekday calendar."""

    start_minute: int
    end_minute: int
    weekdays: frozenset[int] | None


@dataclasses.dataclass(frozen=True)
class CatalogOffPeakRule:
    windows: tuple[CatalogTimeWindow, ...]
    weekday_timezone: str
    overrides: tuple[CatalogPriceRate, ...]

    def applies(self, timestamp: datetime.datetime) -> bool:
        """Match the captured instant, including all-day and overnight windows."""
        utc = timestamp.astimezone(datetime.UTC)
        minute = utc.hour * 60 + utc.minute
        weekday = utc.astimezone(ZoneInfo(self.weekday_timezone)).isoweekday()
        for window in self.windows:
            if window.weekdays is not None and weekday not in window.weekdays:
                continue
            start, end = window.start_minute, window.end_minute
            if (
                start == end
                or start < end
                and start <= minute < end
                or start > end
                and (minute >= start or minute < end)
            ):
                return True
        return False


@dataclasses.dataclass(frozen=True)
class CatalogPriceRules:
    rates: tuple[CatalogPriceRate, ...]
    off_peak: CatalogOffPeakRule | None
    issues: tuple[CatalogPriceIssue, ...]


_BASE_METRICS = {
    "cache_creation_input_token_cost_above_1hr": PriceMetric.CACHE_WRITE_1H,
    "cache_creation_input_token_cost": PriceMetric.CACHE_WRITE,
    "cache_read_input_token_cost": PriceMetric.CACHE_READ,
    "input_cost_per_token": PriceMetric.INPUT,
    "output_cost_per_token": PriceMetric.OUTPUT,
    "output_cost_per_reasoning_token": PriceMetric.REASONING,
    "input_cost_per_audio_token": PriceMetric.INPUT_AUDIO,
    "input_cost_per_image_token": PriceMetric.INPUT_IMAGE,
    "output_cost_per_audio_token": PriceMetric.OUTPUT_AUDIO,
    "output_cost_per_image_token": PriceMetric.OUTPUT_IMAGE,
    "input_cost_per_image": PriceMetric.INPUT_IMAGES,
    "output_cost_per_image": PriceMetric.OUTPUT_IMAGES,
    "input_cost_per_audio_per_second": PriceMetric.INPUT_AUDIO_SECONDS,
    "input_cost_per_video_per_second": PriceMetric.INPUT_VIDEO_SECONDS,
    "output_cost_per_audio_per_second": PriceMetric.OUTPUT_AUDIO_SECONDS,
    "output_cost_per_video_per_second": PriceMetric.OUTPUT_VIDEO_SECONDS,
    "file_search_cost_per_1k_calls": PriceMetric.FILE_SEARCH,
    "code_interpreter_cost_per_session": PriceMetric.CODE_SESSION,
}
_ORDERED_BASES = tuple(sorted(_BASE_METRICS, key=len, reverse=True))
_UNIT_METRICS = frozenset(
    {
        PriceMetric.WEB_SEARCH,
        PriceMetric.FILE_SEARCH,
        PriceMetric.CODE_SESSION,
        PriceMetric.INPUT_IMAGES,
        PriceMetric.OUTPUT_IMAGES,
        PriceMetric.INPUT_AUDIO_SECONDS,
        PriceMetric.INPUT_VIDEO_SECONDS,
        PriceMetric.OUTPUT_AUDIO_SECONDS,
        PriceMetric.OUTPUT_VIDEO_SECONDS,
    }
)
_TIER_PATTERN = "priority|flex|batches|ultrafast"
_SUFFIX = re.compile(
    rf"^(?:_({_TIER_PATTERN}))?"
    rf"(?:_above_([1-9][0-9]*(?:k)?)_tokens)?"
    rf"(?:_({_TIER_PATTERN}))?$"
)
_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_WEEKDAYS = {
    "mon": 1,
    "monday": 1,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "wed": 3,
    "wednesday": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "fri": 5,
    "friday": 5,
    "sat": 6,
    "saturday": 6,
    "sun": 7,
    "sunday": 7,
}


class _WindowInput(BaseModel):
    """Source-only partial option bag, decoded before rule evaluation."""

    model_config = ConfigDict(extra="forbid")
    hours_utc: StrictStr | tuple[StrictStr, ...]
    weekdays: tuple[StrictInt | StrictStr, ...] | None = None


class _OffPeakInput(BaseModel):
    """Source field names stay confined to the price ingestion boundary."""

    model_config = ConfigDict(extra="forbid")
    hours_utc: StrictStr | tuple[StrictStr, ...] | None = None
    windows: tuple[_WindowInput, ...] | None = None
    weekday_timezone: StrictStr | None = None
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    output_cost_per_reasoning_token: Decimal | None = None
    cache_read_input_token_cost: Decimal | None = None
    cache_creation_input_token_cost: Decimal | None = None

    @field_validator(
        "input_cost_per_token",
        "output_cost_per_token",
        "output_cost_per_reasoning_token",
        "cache_read_input_token_cost",
        "cache_creation_input_token_cost",
        mode="before",
    )
    @classmethod
    def validate_rate(cls, value: object) -> Decimal | None:
        """Accept numeric source lexemes, not coerced string or boolean prices."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | Decimal):
            raise ValueError("Off-peak rates must be numbers.")
        decimal = Decimal(value)
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("Off-peak rates must be finite and nonnegative.")
        return decimal


class _SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_context_size_low: Decimal | None = None
    search_context_size_medium: Decimal | None = None
    search_context_size_high: Decimal | None = None

    @field_validator("*", mode="before")
    @classmethod
    def validate_rate(cls, value: object) -> Decimal | None:
        return _OffPeakInput.validate_rate(value)


def _minute(text: str) -> int:
    match = _CLOCK.fullmatch(text)
    if match is None:
        raise ValueError("Invalid UTC price-window time.")
    return int(match[1]) * 60 + int(match[2])


def _windows(raw: _WindowInput) -> tuple[CatalogTimeWindow, ...]:
    hours = (raw.hours_utc,) if isinstance(raw.hours_utc, str) else raw.hours_utc
    if not hours or len(hours) > 64:
        raise ValueError("A bounded nonempty UTC window list is required.")
    days: frozenset[int] | None = None
    if raw.weekdays is not None:
        values = [
            day if isinstance(day, int) else _WEEKDAYS.get(day.lower())
            for day in raw.weekdays
        ]
        if not values or any(day is None or not 1 <= day <= 7 for day in values):
            raise ValueError("Invalid price-window weekdays.")
        days = frozenset(day for day in values if day is not None)
    result: list[CatalogTimeWindow] = []
    for window in hours:
        start, end = window.split("-")
        result.append(CatalogTimeWindow(_minute(start), _minute(end), days))
    return tuple(result)


def _opaque_value(evidence: CatalogPriceEvidence) -> object:
    """Decode source JSON once, preserving decimal precision at ingress."""
    return json.loads(evidence.encoded_value, parse_float=Decimal)


def _off_peak(evidence: CatalogPriceEvidence) -> CatalogOffPeakRule:
    if evidence.kind != "structured":
        raise ValueError("Off-peak pricing must be a source object.")
    raw = _OffPeakInput.model_validate(_opaque_value(evidence))
    timezone = raw.weekday_timezone if raw.weekday_timezone is not None else "UTC"
    ZoneInfo(timezone)
    if raw.windows is not None and raw.hours_utc is not None:
        raise ValueError("Ambiguous off-peak window declarations.")
    windows = (
        raw.windows
        if raw.windows is not None
        else (_WindowInput(hours_utc=raw.hours_utc),)
        if raw.hours_utc is not None
        else ()
    )
    if not windows or len(windows) > 64:
        raise ValueError("Off-peak pricing requires bounded windows.")
    overrides: list[CatalogPriceRate] = []
    for key, metric, value in (
        ("input_cost_per_token", PriceMetric.INPUT, raw.input_cost_per_token),
        ("output_cost_per_token", PriceMetric.OUTPUT, raw.output_cost_per_token),
        (
            "output_cost_per_reasoning_token",
            PriceMetric.REASONING,
            raw.output_cost_per_reasoning_token,
        ),
        (
            "cache_read_input_token_cost",
            PriceMetric.CACHE_READ,
            raw.cache_read_input_token_cost,
        ),
        (
            "cache_creation_input_token_cost",
            PriceMetric.CACHE_WRITE,
            raw.cache_creation_input_token_cost,
        ),
    ):
        if key in raw.model_fields_set:
            if value is None:
                raise ValueError("An off-peak override cannot be null.")
            overrides.append(
                CatalogPriceRate(metric, PriceTier.STANDARD, None, value, None)
            )
    return CatalogOffPeakRule(
        tuple(item for window in windows for item in _windows(window)),
        timezone,
        tuple(overrides),
    )


def _issue(
    evidence: CatalogPriceEvidence,
    metrics: tuple[PriceMetric, ...],
    *,
    invalid: bool,
    dimension: Literal["residency", "geography", "speed"] | None = None,
) -> CatalogPriceIssue:
    return CatalogPriceIssue(evidence.source_field, metrics, dimension, invalid)


def _unsupported(evidence: CatalogPriceEvidence) -> CatalogPriceIssue:
    field = evidence.source_field
    if field == "google_maps_grounding_cost_per_query":
        return _issue(evidence, (PriceMetric.MAPS_GROUNDING,), invalid=False)
    if "regional_processing" in field or "residency" in field:
        return _issue(evidence, (), invalid=False, dimension="residency")
    if "inference_geo" in field:
        return _issue(evidence, (), invalid=False, dimension="geography")
    if "speed" in field:
        return _issue(evidence, (), invalid=False, dimension="speed")
    if "cache" in field and "audio" in field:
        return _issue(
            evidence,
            (
                PriceMetric.CACHE_WRITE
                if "creation" in field
                else PriceMetric.CACHE_READ,
                PriceMetric.INPUT_AUDIO,
            ),
            invalid=False,
        )
    if "cache" in field and "image" in field:
        return _issue(
            evidence, (PriceMetric.CACHE_READ, PriceMetric.INPUT_IMAGE), invalid=False
        )
    if "search" in field or "grounding" in field:
        return _issue(evidence, (PriceMetric.WEB_SEARCH,), invalid=False)
    if field.startswith("input_cost_per_character"):
        return _issue(evidence, (PriceMetric.INPUT,), invalid=False)
    if field.startswith("output_cost_per_character"):
        return _issue(evidence, (PriceMetric.OUTPUT,), invalid=False)
    # Unknown fixed/request fees or unclassified dimensions are not token-only totals.
    return _issue(evidence, (), invalid=False)


def decode_catalog_price_rules(source_model: CatalogSourceModel) -> CatalogPriceRules:
    """Normalize captured numeric/rule evidence once, without producer code.

    :param source_model: validated exact-scope source record captured for an operation
    :returns: immutable bounded rates and required unsupported-rule diagnostics
    """
    rates: list[CatalogPriceRate] = []
    issues: list[CatalogPriceIssue] = []
    off_peak: CatalogOffPeakRule | None = None
    for evidence in source_model.price_evidence:
        key = evidence.source_field
        if key == "currency":
            if _opaque_value(evidence) != "USD":
                issues.append(_issue(evidence, (), invalid=False))
            continue
        if key == "off_peak_pricing":
            try:
                off_peak = _off_peak(evidence)
            except ValueError, ZoneInfoNotFoundError:
                issues.append(_issue(evidence, (), invalid=True))
            continue
        if key.startswith("search_context_cost_per_query"):
            suffix = _SUFFIX.fullmatch(key[len("search_context_cost_per_query") :])
            try:
                if suffix is None or suffix[2] is not None:
                    raise ValueError("Unsupported search-price suffix.")
                if suffix[1] and suffix[3]:
                    raise ValueError("Duplicate search-price tier.")
                tier = (
                    PriceTier(suffix[1] or suffix[3])
                    if suffix[1] or suffix[3]
                    else None
                )
                search = _SearchInput.model_validate(_opaque_value(evidence))
                for size, value in (
                    ("low", search.search_context_size_low),
                    ("medium", search.search_context_size_medium),
                    ("high", search.search_context_size_high),
                ):
                    if f"search_context_size_{size}" not in search.model_fields_set:
                        continue
                    rates.append(
                        CatalogPriceRate(
                            PriceMetric.WEB_SEARCH, tier, None, value, size
                        )
                    )
            except ValidationError, ValueError:
                issues.append(_issue(evidence, (PriceMetric.WEB_SEARCH,), invalid=True))
            continue
        if key == "web_search_billing_unit":
            if _opaque_value(evidence) not in ("query", "per_query"):
                issues.append(
                    _issue(evidence, (PriceMetric.WEB_SEARCH,), invalid=False)
                )
            continue
        base = next(
            (
                name
                for name in _ORDERED_BASES
                if key == name or key.startswith(name + "_")
            ),
            None,
        )
        if base is None:
            issues.append(_unsupported(evidence))
            continue
        metric = _BASE_METRICS[base]
        suffix = _SUFFIX.fullmatch(key[len(base) :])
        if suffix is None:
            issues.append(_issue(evidence, (metric,), invalid=False))
            continue
        before, threshold_text, after = suffix.groups()
        if before and after:
            issues.append(_issue(evidence, (metric,), invalid=True))
            continue
        if evidence.kind not in {"number", "null"}:
            issues.append(_issue(evidence, (metric,), invalid=True))
            continue
        threshold = None
        if threshold_text is not None:
            threshold = (
                int(threshold_text[:-1]) * 1000
                if threshold_text.endswith("k")
                else int(threshold_text)
            )
            if threshold > 2**63 - 1:
                issues.append(_issue(evidence, (metric,), invalid=True))
                continue
        tier = (
            PriceTier(before or after)
            if before or after
            else None
            if metric in _UNIT_METRICS
            else PriceTier.STANDARD
        )
        value = evidence.number.decimal_value if evidence.number is not None else None
        if value is not None and metric is PriceMetric.FILE_SEARCH:
            with localcontext() as context:
                context.prec = 160
                value /= Decimal(1000)
        rates.append(CatalogPriceRate(metric, tier, threshold, value, None))
    return CatalogPriceRules(tuple(rates), off_peak, tuple(issues))
