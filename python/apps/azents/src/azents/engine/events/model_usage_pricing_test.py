"""Captured-price and provider-charge integration contracts."""

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_pricing import (
    ModelCostEstimate,
    ModelPricing,
    ModelPricingBilling,
    ModelPricingUsage,
    estimate_model_cost,
    normalize_model_pricing,
)
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.protocols import NativeEvent
from azents.engine.events.responses_output import ResponsesOutputNormalizer
from azents.engine.events.types import TokenUsagePayload


class _CommonNormalizer(ResponsesOutputNormalizer):
    """Concrete common Responses route for price integration contracts."""

    adapter = "test"


def _pricing(metadata: dict[str, object] | None) -> ModelPricing:
    """Create a captured source view with fixed semantic/provenance identity."""
    return normalize_model_pricing(
        provider=LLMProvider.OPENAI,
        model_identifier="selected-model",
        source_snapshot_id="snapshot-1",
        source_hash="source-hash-1",
        source_model_key="openai/selected-model",
        metadata=metadata,
    )


def _usage(raw: dict[str, object]) -> TokenUsagePayload:
    """Create inclusive common Responses counters, not native family counters."""
    return TokenUsagePayload(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw=raw,
        cached_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=1,
        cost_usd=None,
        raw_hidden_params=None,
    )


def test_reported_charge_survives_absent_price_authority() -> None:
    """A native charge cannot become unavailable with the optional source."""
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="publisher/model",
        pricing=None,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=0.12,
    )
    assert result.cost_usd == 0.12
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "provider_reported"
    assert result.cost_provenance.provider == "openrouter"
    assert result.cost_provenance.model_identifier == "publisher/model"
    assert result.cost_provenance.source_snapshot_id is None


def test_reported_charge_uses_semantic_identity_from_unavailable_source_view() -> None:
    """An unavailable captured price still supplies the selected raw model ID."""
    pricing = normalize_model_pricing(
        provider=LLMProvider.OPENROUTER,
        model_identifier="publisher/model",
        source_snapshot_id=None,
        source_hash=None,
        source_model_key=None,
        metadata=None,
    )
    result = apply_model_usage_pricing(
        _usage({}),
        provider="openrouter",
        model_identifier="openrouter/publisher/model",
        pricing=pricing,
        service_tier=None,
        output_item_types=["message"],
        reported_charge=0.12,
    )
    assert result.cost_usd == 0.12
    assert result.cost_provenance is not None
    assert result.cost_provenance.model_identifier == "publisher/model"
    assert result.cost_provenance.source_hash is None


@pytest.mark.parametrize("reported_charge", [True, -1.0, float("nan"), float("inf")])
def test_invalid_reported_charge_stays_unknown_without_source(
    reported_charge: float,
) -> None:
    """Neither bools nor invalid native amounts become a zero charge."""
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


def test_estimator_input_is_content_free_and_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra raw content never reaches the estimator or doubles reasoning."""
    captured: list[tuple[ModelPricingUsage, ModelPricingBilling]] = []

    def capture(
        *,
        pricing: ModelPricing,
        usage: ModelPricingUsage,
        billing: ModelPricingBilling,
    ) -> ModelCostEstimate:
        captured.append((usage, billing))
        return estimate_model_cost(pricing=pricing, usage=usage, billing=billing)

    monkeypatch.setattr(
        "azents.engine.events.model_usage_pricing.estimate_model_cost", capture
    )
    result = apply_model_usage_pricing(
        _usage({"untrusted_output_canary": "never-estimator-input"}),
        provider="openai",
        model_identifier="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(2.0)
    assert len(captured) == 1
    captured_usage, captured_billing = captured[0]
    assert captured_usage.prompt_tokens_include_cache is True
    assert captured_usage.completion_tokens_include_reasoning is True
    assert "never-estimator-input" not in repr(captured_usage)
    assert "never-estimator-input" not in repr(captured_billing)
    assert result.cost_provenance is not None
    assert result.cost_provenance.method == "estimated"
    assert result.cost_provenance.source_hash == "source-hash-1"


def test_unpriced_media_does_not_produce_a_token_subtotal() -> None:
    """Directed audio usage requires its applicable media rate."""
    result = apply_model_usage_pricing(
        _usage({"input_tokens_details": {"audio_tokens": 2}}),
        provider="openai",
        model_identifier="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


def test_directed_media_tokens_do_not_double_count_common_totals() -> None:
    """Audio-specific billing partitions the inclusive prompt counter."""
    result = apply_model_usage_pricing(
        _usage({"input_tokens_details": {"audio_tokens": 2}}),
        provider="openai",
        model_identifier="selected-model",
        pricing=_pricing(
            {
                "input_cost_per_token": 0.1,
                "output_cost_per_token": 0.2,
                "input_cost_per_audio_token": 0.3,
            }
        ),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cost_usd == pytest.approx(2.4)


def test_cache_ttl_quantities_are_not_a_second_input_total() -> None:
    """Native cache TTL detail partitions the same common prompt input."""
    result = apply_model_usage_pricing(
        _usage(
            {
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 2,
                    "ephemeral_1h_input_tokens": 3,
                }
            }
        ),
        provider="openai",
        model_identifier="selected-model",
        pricing=_pricing(
            {
                "input_cost_per_token": 0.1,
                "output_cost_per_token": 0.2,
                "cache_creation_input_token_cost": 0.15,
                "cache_creation_input_token_cost_above_1hr": 0.25,
            }
        ),
        service_tier=None,
        output_item_types=["message"],
        reported_charge=None,
    )
    assert result.cache_creation_tokens == 5
    assert result.cost_usd == pytest.approx(2.55)


@pytest.mark.parametrize(
    "raw, output_item_types",
    [
        ({"audio_tokens": 2}, ["message"]),
        ({"input_tokens_details": {"audio_tokens": "not-a-count"}}, ["message"]),
        ({}, ["image_generation_call"]),
        ({}, ["code_interpreter_call"]),
    ],
)
def test_unknown_billable_components_make_the_total_unknown(
    raw: dict[str, object], output_item_types: list[str]
) -> None:
    """Unused standard rates cannot fabricate media or session charges."""
    result = apply_model_usage_pricing(
        _usage(raw),
        provider="openai",
        model_identifier="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        service_tier=None,
        output_item_types=output_item_types,
        reported_charge=None,
    )
    assert result.cost_usd is None
    assert result.cost_provenance is None


def test_common_stream_freezes_price_and_request_tier() -> None:
    """Later mutable config cannot standard-price a captured priority request."""
    normalizer = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        operation="sampling",
        integration=None,
    )
    normalizer.service_tier = "priority"
    first = normalizer.start("session-1")
    normalizer.service_tier = None
    second = normalizer.start("session-2")
    normalizer.pricing = None
    third = normalizer.start("session-3")
    completed = NativeEvent(
        type="ResponseCompletedEvent",
        item={
            "response": {
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "output": [],
            }
        },
    )
    first.process_event(completed)
    second.process_event(completed)
    third.process_event(completed)
    first_usage = first.complete().usage
    second_usage = second.complete().usage
    third_usage = third.complete().usage
    assert first_usage is not None
    assert second_usage is not None
    assert third_usage is not None
    assert first_usage.cost_usd is None
    assert second_usage.cost_usd == pytest.approx(2.0)
    assert third_usage.cost_usd is None
    assert second_usage.cost_provenance is not None
    assert second_usage.cost_provenance.source_snapshot_id == "snapshot-1"


def test_common_missing_usage_does_not_discard_prior_final_counters() -> None:
    """The previous normalization contract retained known usage on duplicates."""
    stream = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        operation="sampling",
        integration=None,
    ).start("session-1")
    stream.process_event(
        NativeEvent(
            type="ResponseCompletedEvent",
            item={
                "response": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "output": [],
                }
            },
        )
    )
    stream.process_event(
        NativeEvent(
            type="ResponseCompletedEvent",
            item={"response": {"output": []}},
        )
    )
    usage = stream.complete().usage
    assert usage is not None
    assert usage.total_tokens == 15
    assert usage.cost_usd == pytest.approx(2.0)


@pytest.mark.parametrize("priority_rates", [False, True])
def test_duplicate_without_usage_preserves_native_priority_billing(
    priority_rates: bool,
) -> None:
    metadata: dict[str, object] = {
        "input_cost_per_token": 0.1,
        "output_cost_per_token": 0.2,
    }
    if priority_rates:
        metadata.update(
            {
                "input_cost_per_token_priority": 0.2,
                "output_cost_per_token_priority": 0.4,
            }
        )
    stream = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing(metadata),
        operation="sampling",
        integration=None,
    ).start("session-1")
    stream.process_event(
        NativeEvent(
            type="ResponseCompletedEvent",
            item={
                "response": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "service_tier": "priority",
                    "output": [],
                }
            },
        )
    )
    stream.process_event(
        NativeEvent(type="ResponseCompletedEvent", item={"response": {"output": []}})
    )
    usage = stream.complete().usage
    assert usage is not None
    if priority_rates:
        assert usage.cost_usd == pytest.approx(4.0)
        assert usage.cost_provenance is not None
        assert usage.cost_provenance.service_tier == "priority"
    else:
        assert usage.cost_usd is None
        assert usage.cost_provenance is None


@pytest.mark.parametrize("priced_search", [False, True])
def test_duplicate_without_usage_preserves_response_only_billables(
    priced_search: bool,
) -> None:
    metadata: dict[str, object] = {
        "input_cost_per_token": 0.1,
        "output_cost_per_token": 0.2,
    }
    if priced_search:
        metadata["search_context_cost_per_query"] = {
            "search_context_size_low": 0.25,
            "search_context_size_medium": 0.25,
            "search_context_size_high": 0.25,
        }
    stream = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing(metadata),
        operation="sampling",
        integration=None,
    ).start("session-1")
    stream.process_event(
        NativeEvent(
            type="ResponseCompletedEvent",
            item={
                "response": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "output": [{"type": "web_search_call"}],
                }
            },
        )
    )
    stream.process_event(
        NativeEvent(type="ResponseCompletedEvent", item={"response": {"output": []}})
    )
    usage = stream.complete().usage
    assert usage is not None
    assert (
        usage.cost_usd == pytest.approx(2.25)
        if priced_search
        else usage.cost_usd is None
    )


def test_later_valid_usage_can_supersede_native_billing_tier() -> None:
    stream = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        operation="sampling",
        integration=None,
    ).start("session-1")
    for tier, tokens in (("priority", 10), ("default", 20)):
        stream.process_event(
            NativeEvent(
                type="ResponseCompletedEvent",
                item={
                    "response": {
                        "usage": {"input_tokens": tokens, "output_tokens": 5},
                        "service_tier": tier,
                        "output": [],
                    }
                },
            )
        )
    usage = stream.complete().usage
    assert usage is not None
    assert usage.prompt_tokens == 20
    assert usage.cost_usd == pytest.approx(3.0)
    assert usage.cost_provenance is not None
    assert usage.cost_provenance.service_tier == "standard"


def test_common_done_item_billables_are_not_lost_with_empty_terminal_output() -> None:
    """A used hosted tool cannot be omitted from an apparently token-only total."""
    stream = _CommonNormalizer(
        provider="openai",
        model="selected-model",
        pricing=_pricing({"input_cost_per_token": 0.1, "output_cost_per_token": 0.2}),
        operation="sampling",
        integration=None,
    ).start("session-1")
    stream.process_event(
        NativeEvent(
            type="OutputItemDoneEvent",
            item={
                "output_index": 0,
                "item": {
                    "type": "web_search_call",
                    "id": "search-1",
                    "status": "completed",
                    "action": {"type": "search", "query": "example"},
                },
            },
        )
    )
    stream.process_event(
        NativeEvent(
            type="ResponseCompletedEvent",
            item={
                "response": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "output": [],
                }
            },
        )
    )
    usage = stream.complete().usage
    assert usage is not None
    assert usage.cost_usd is None
    assert usage.cost_provenance is None
