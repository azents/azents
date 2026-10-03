"""Captured catalog pricing and provider-charge integration contracts."""

import datetime
import json

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import CatalogSourceModel, decode_catalog_source
from azents.core.model_pricing import (
    CapturedModelPricing,
    capture_model_pricing,
    normalize_model_pricing,
)
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.types import TokenUsagePayload


def _pricing(
    *,
    provider: LLMProvider,
    model_identifier: str,
    source_model: CatalogSourceModel,
    request_timestamp: datetime.datetime,
) -> CapturedModelPricing:
    """Normalize outside dispatch and capture only the saved definition."""
    return capture_model_pricing(
        provider=provider,
        model_identifier=model_identifier,
        definition=normalize_model_pricing(
            source_key="litellm_catalog",
            source_model=source_model,
            collected_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
        ),
        request_timestamp=request_timestamp,
    )


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


@pytest.mark.parametrize("charge", [0.0, 0.12])
def test_reported_charge_survives_absent_price_authority(charge: float) -> None:
    """A native charge cannot become unavailable with the optional source."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="publisher/model",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=charge,
    )
    assert result.cost_usd == charge
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "provider_reported"
    assert result.cost_provenance.source_key is None


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
        pricing=_pricing(
            provider=LLMProvider.OPENAI,
            model_identifier="selected-model",
            source_model=decode_catalog_source(
                b'{"selected-model":{"litellm_provider":"openai",'
                b'"input_cost_per_token":0.1,'
                b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
                b'"cache_creation_input_token_cost":0.15}}'
            ).models[0],
            request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
        ),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(1.97)
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "estimated"
    assert result.cost_provenance.source_key == "litellm_catalog"
    assert result.cost_provenance.collected_at == datetime.datetime(
        2026, 10, 1, tzinfo=datetime.UTC
    )
    assert "source_hash" not in result.cost_provenance.model_dump()
    assert "source_snapshot_id" not in result.cost_provenance.model_dump()


@pytest.mark.parametrize(
    "item_type", ["code_interpreter_call", "image_generation_call"]
)
def test_output_item_count_does_not_invent_session_or_media_quantity(
    item_type: str,
) -> None:
    pricing = _pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="selected-model",
        source_model=decode_catalog_source(
            b'{"selected-model":{"litellm_provider":"openai",'
            b'"input_cost_per_token":0.1,'
            b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
            b'"cache_creation_input_token_cost":0.15,'
            b'"code_interpreter_cost_per_session":0.03}}'
        ).models[0],
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openai",
        model_identifier="selected-model",
        pricing=pricing,
        service_tier=None,
        output_item_types=[item_type],
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


@pytest.mark.parametrize(
    "raw",
    [
        {"input_tokens_details": "malformed"},
        {"output_tokens_details": {"audio_tokens": "2"}},
        {"audio_tokens": 2},
        {"cache_creation": False},
    ],
)
def test_malformed_or_undirected_breakdown_does_not_produce_a_partial_estimate(
    raw: dict[str, object],
) -> None:
    pricing = _pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="m",
        source_model=decode_catalog_source(
            b'{"m":{"litellm_provider":"openai","input_cost_per_token":0.1,'
            b'"output_cost_per_token":0.2,"cache_read_input_token_cost":0.01,'
            b'"cache_creation_input_token_cost":0.15}}'
        ).models[0],
        request_timestamp=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    result = apply_model_usage_pricing(
        _usage(raw),
        provider="openai",
        model_identifier="m",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd is None
    reported = apply_model_usage_pricing(
        _usage(raw),
        provider="openai",
        model_identifier="m",
        pricing=pricing,
        service_tier=None,
        output_item_types=["image_generation_call"],
        reported_charge=0.0,
    )
    assert reported.cost_usd == 0
    assert reported.cost_provenance is not None
    assert reported.cost_provenance.method == "provider_reported"


def test_upstream_computed_cost_is_not_adopted_without_native_charge() -> None:
    usage = _usage({}).model_copy(
        update={"cost_usd": 99.0, "raw_hidden_params": {"response_cost": 99.0}}
    )
    result = apply_model_usage_pricing(
        usage,
        provider="openai",
        model_identifier="m",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


def _google_estimate(
    raw: dict[str, object], *, cached: int | None, charge: float | None
) -> TokenUsagePayload:
    source = decode_catalog_source(
        b'{"gemini/selected-model":{"litellm_provider":"gemini",'
        b'"input_cost_per_token":0.1,"output_cost_per_token":0.2,'
        b'"input_cost_per_image_token":0.7,"input_cost_per_audio_token":0.6,'
        b'"output_cost_per_image_token":0.8,"output_cost_per_audio_token":0.9,'
        b'"cache_read_input_token_cost":0.01}}'
    ).models[0]
    pricing = _pricing(
        provider=LLMProvider.GOOGLE_GEMINI,
        model_identifier="selected-model",
        source_model=source,
        request_timestamp=datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC),
    )
    return apply_model_usage_pricing(
        TokenUsagePayload(
            prompt_tokens=7,
            completion_tokens=2,
            total_tokens=9,
            cached_tokens=cached,
            cache_creation_tokens=None,
            reasoning_tokens=None,
            cost_usd=None,
            raw=raw,
            raw_hidden_params=None,
        ),
        provider="google_gemini",
        model_identifier="selected-model",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=charge,
    )


def _google_raw() -> dict[str, object]:
    return {
        "promptTokenCount": 7,
        "candidatesTokenCount": 2,
        "promptTokensDetails": [
            {"modality": "TEXT", "tokenCount": 3},
            {"modality": "IMAGE", "tokenCount": 4},
        ],
    }


def test_google_directed_media_partition_is_not_priced_as_ordinary_tokens() -> None:
    result = _google_estimate(_google_raw(), cached=None, charge=None)
    assert result.cost_usd == pytest.approx(3.5)
    assert result.cost_provenance is not None
    assert result.cost_provenance.source_model_key == "gemini/selected-model"
    audio = _google_raw()
    audio["promptTokensDetails"] = [
        {"modality": "TEXT", "tokenCount": 3},
        {"modality": "AUDIO", "tokenCount": 4},
    ]
    audio["candidatesTokensDetails"] = [
        {"modality": "TEXT", "tokenCount": 1},
        {"modality": "AUDIO", "tokenCount": 1},
    ]
    assert _google_estimate(audio, cached=None, charge=None).cost_usd == pytest.approx(
        3.8
    )


def test_google_text_only_cache_receipt_keeps_media_and_cache_disjoint() -> None:
    raw = _google_raw()
    raw.update(
        cachedContentTokenCount=2,
        cacheTokensDetails=[{"modality": "TEXT", "tokenCount": 2}],
    )
    assert _google_estimate(raw, cached=2, charge=None).cost_usd == pytest.approx(3.32)


def test_google_snake_case_receipts_are_native_modality_partitions() -> None:
    raw: dict[str, object] = {
        "prompt_token_count": 7,
        "candidates_token_count": 2,
        "cached_content_token_count": 2,
        "prompt_tokens_details": [
            {"modality": "TEXT", "token_count": 3},
            {"modality": "IMAGE", "token_count": 4},
        ],
        "cache_tokens_details": [{"modality": "TEXT", "token_count": 2}],
    }
    assert _google_estimate(raw, cached=2, charge=None).cost_usd == pytest.approx(3.32)


@pytest.mark.parametrize(
    ("raw_cache", "normalized_cache", "expected"),
    [(2, 1, None), (2, None, None), (0, 2, None), (None, 2, 3.32)],
)
def test_google_cache_receipt_matches_normalized_billed_counter(
    raw_cache: int | None, normalized_cache: int | None, expected: float | None
) -> None:
    raw = _google_raw()
    raw["cacheTokensDetails"] = [{"modality": "TEXT", "tokenCount": 2}]
    if raw_cache is not None:
        raw["cachedContentTokenCount"] = raw_cache
    result = _google_estimate(raw, cached=normalized_cache, charge=None)
    if expected is None:
        assert result.cost_usd is None
        assert result.cost_provenance is None
    else:
        assert result.cost_usd == pytest.approx(expected)


def test_google_normalized_cache_without_partition_cannot_overlap_media() -> None:
    result = _google_estimate(_google_raw(), cached=2, charge=None)
    assert result.cost_usd is None
    assert result.cost_provenance is None


@pytest.mark.parametrize(
    "change",
    [
        {"promptTokensDetails": None},
        {"promptTokensDetails": [{"modality": "IMAGE", "tokenCount": True}]},
        {"promptTokensDetails": [{"modality": "IMAGE", "tokenCount": "7"}]},
        {"promptTokensDetails": [{"modality": "IMAGE", "tokenCount": 8}]},
        {"promptTokensDetails": [{"modality": "VIDEO", "tokenCount": 7}]},
        {
            "promptTokensDetails": [
                {"modality": "IMAGE", "tokenCount": 4},
                {"modality": "IMAGE", "tokenCount": 3},
            ]
        },
        {"input_image_tokens": 1},
        {"cachedContentTokenCount": 2},
        {
            "cachedContentTokenCount": 2,
            "cacheTokensDetails": [{"modality": "IMAGE", "tokenCount": 2}],
        },
        {"toolUsePromptTokenCount": 1},
        {"candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 3}]},
    ],
)
def test_google_incomplete_or_unadopted_partition_leaves_whole_cost_unknown(
    change: dict[str, object],
) -> None:
    raw = {**_google_raw(), **change}
    before = json.dumps(raw)
    result = _google_estimate(
        raw, cached=2 if "cachedContentTokenCount" in raw else None, charge=None
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None
    assert json.dumps(raw) == before
    reported = _google_estimate(raw, cached=None, charge=0.0)
    assert reported.cost_usd == 0.0
    assert reported.cost_provenance is not None
    assert reported.cost_provenance.method == "provider_reported"
