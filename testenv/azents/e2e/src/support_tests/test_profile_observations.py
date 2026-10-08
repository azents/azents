"""Docker-free contracts for inference-profile observation ingress."""

import json

import pytest
from pydantic import ValidationError

from support.profile_observations import (
    CatalogSourceObservation,
    ProfileBarrierObservation,
    ProfileProviderRequestObservation,
    decode_mock_profile_journal,
    decode_profile_history,
    decode_profile_provider_journal,
    profile_history_event_wire,
)


def _history_page() -> dict[str, object]:
    """Represent the real generated history envelope, without live fixtures."""
    return {
        "items": [
            {
                "id": "event-1",
                "session_id": "session-1",
                "kind": "user_message",
                "payload": {
                    "content": "Prepared profile message",
                    "opaque_extension": {"nested": [None, True, 3]},
                },
                "schema_version": "1",
                "created_at": "2026-10-03T10:00:00Z",
                "future_event_extension": {"ready": True},
            }
        ],
        "has_more": False,
        "future_page_extension": ["opaque", None],
    }


def test_provider_request_decodes_decision_fields_and_relays_opaque_extensions() -> (
    None
):
    """Typed selection must preserve the provider body used for correlation."""
    wire = {
        "model": "gpt-6-astra",
        "service_tier": "ultrafast",
        "max_output_tokens": 4000,
        "reasoning": {"effort": "high", "future_reasoning": {"unknown": None}},
        "input": [{"role": "user", "content": [{"text": "Prepared profile"}]}],
        "future_provider_field": {"nested": [None, False, 4]},
    }
    request = decode_profile_provider_journal([wire])[0]
    assert request.model == "gpt-6-astra"
    assert request.service_tier == "ultrafast"
    assert request.max_output_tokens == 4000
    assert request.reasoning is not None
    assert request.reasoning.effort == "high"
    assert json.loads(request.serialized()) == wire


def test_provider_tier_preserves_omitted_and_explicit_null() -> None:
    """An omitted tier is distinct from an explicitly present null wire value."""
    omitted = ProfileProviderRequestObservation.model_validate({"model": "gpt-5.5"})
    explicit = ProfileProviderRequestObservation.model_validate(
        {"model": "gpt-5.5", "service_tier": None}
    )
    assert omitted.service_tier is None and explicit.service_tier is None
    assert "service_tier" not in omitted.model_fields_set
    assert "service_tier" in explicit.model_fields_set
    assert "service_tier" not in json.loads(omitted.serialized())
    assert json.loads(explicit.serialized())["service_tier"] is None


@pytest.mark.parametrize(
    "wire",
    [
        {"model": 123},
        {"service_tier": True},
        {"max_tokens": "4000"},
        {"max_output_tokens": True},
        {"reasoning": {"effort": 2}},
    ],
)
def test_provider_decision_fields_reject_coercion(wire: object) -> None:
    """Readiness and model comparisons never gain validity through coercion."""
    with pytest.raises(ValidationError):
        decode_profile_provider_journal([wire])


def test_mock_journal_owns_the_body_envelope() -> None:
    """The mocked provider journal uses a typed nested request body."""
    request = decode_mock_profile_journal(
        [
            {
                "body": {"model": "gpt-5.5-mini", "max_tokens": 4000},
                "future_journal_field": "opaque",
            }
        ]
    )[0]
    assert request.body.model == "gpt-5.5-mini"
    assert request.body.max_tokens == 4000
    assert request.model_extra == {"future_journal_field": "opaque"}
    with pytest.raises(ValidationError):
        decode_mock_profile_journal([{"body": None}])


@pytest.mark.parametrize("value", ["true", 1, None])
def test_barrier_requires_authoritative_boolean(value: object) -> None:
    """A truthy malformed fixture field cannot release a readiness poll."""
    with pytest.raises(ValidationError):
        ProfileBarrierObservation.model_validate({"reached": value})


def test_barrier_and_catalog_ack_tolerate_fixture_extensions() -> None:
    """Forward-compatible fixture metadata does not invalidate observed fields."""
    barrier = ProfileBarrierObservation.model_validate(
        {"reached": True, "future_barrier_metadata": {"request": "opaque"}}
    )
    source = CatalogSourceObservation.model_validate(
        {"variant": "refreshed", "future_source_metadata": None}
    )
    assert barrier.reached is True
    assert source.variant == "refreshed"
    assert source.model_extra == {"future_source_metadata": None}


def test_generated_history_preserves_unknown_envelope_and_opaque_payload() -> None:
    """Unknown envelope evidence remains inspectable by negative wire assertions."""
    page = decode_profile_history(_history_page())
    assert page.has_more is False
    assert page.model_extra == {"future_page_extension": ["opaque", None]}
    event = page.items[0]
    assert event.id == "event-1"
    assert event.kind == "user_message"
    assert event.additional_properties == {"future_event_extension": {"ready": True}}
    assert event.payload["opaque_extension"] == {"nested": [None, True, 3]}


def test_history_omission_preserves_generated_defaults_and_fields_set() -> None:
    """Missing pagination and nullable event fields remain genuinely unset."""
    page = decode_profile_history(_history_page())
    assert page.has_newer is False
    assert "has_newer" not in page.model_fields_set
    assert page.next_cursor is None
    assert "next_cursor" not in page.model_fields_set
    assert "previous_cursor" not in page.model_fields_set
    event = page.items[0]
    assert event.external_id is None
    assert "external_id" not in event.model_fields_set
    assert "external_id" not in profile_history_event_wire(event)


def test_history_explicit_null_cursor_remains_set() -> None:
    """A nullable cursor supplied as null is distinct from an omitted cursor."""
    page = decode_profile_history({**_history_page(), "next_cursor": None})
    assert page.next_cursor is None
    assert "next_cursor" in page.model_fields_set
    assert page.has_newer is False
    assert "has_newer" not in page.model_fields_set
    assert page.model_dump(mode="json", exclude_unset=True)["next_cursor"] is None


def test_generated_history_does_not_erase_unexpected_inference_summary() -> None:
    """The journey's absence assertion must detect an unexpected wire field."""
    wire = {
        "items": [
            {
                "id": "event-1",
                "session_id": "session-1",
                "kind": "user_message",
                "payload": {"content": "Prepared profile"},
                "schema_version": "1",
                "created_at": "2026-10-03T10:00:00Z",
                "inference_run_summary": {"unexpected": "wire evidence"},
            }
        ],
        "has_more": False,
    }
    event = decode_profile_history(wire).items[0]
    assert "inference_run_summary" in event.additional_properties


def test_history_egress_encodes_timestamps_and_flattens_unknown_envelope() -> None:
    """Compatibility consumers receive JSON values, not generated datetimes."""
    event = decode_profile_history(_history_page()).items[0]
    wire = profile_history_event_wire(event)
    assert isinstance(wire["created_at"], str)
    assert wire["future_event_extension"] == {"ready": True}
    assert "additional_properties" not in wire
    assert json.loads(json.dumps(wire)) == wire


@pytest.mark.parametrize(
    "wire",
    [
        {"items": [], "has_more": "false"},
        {"items": [{"id": 1}], "has_more": False},
        {"items": None, "has_more": False},
    ],
)
def test_generated_history_rejects_malformed_required_evidence(wire: object) -> None:
    """Missing identities and malformed metadata fail at observation ingress."""
    with pytest.raises(ValidationError):
        decode_profile_history(wire)
