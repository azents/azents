"""Docker-free validation for provider-tool live and durable observations."""

import pytest
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.live_event_list_response import LiveEventListResponse
from pydantic import ValidationError

from support.observations import decode_history_page
from tests.required.public.test_provider_tool_live_activity import (
    _AssistantPayload,
    _live_events,
    _provider_call_event,
    _provider_history_appended,
    _provider_upsert_with_status,
    _ProviderAction,
    _ProviderCallPayload,
)


def _event(
    *, kind: str = "provider_tool_call", status: str | None = "running"
) -> dict[str, object]:
    return {
        "id": "event-1",
        "session_id": "session-1",
        "kind": kind,
        "payload": {"call_id": "call-1", "name": "web_search", "status": status},
        "adapter": "azents-live",
        "external_id": "call-1",
        "schema_version": "1",
        "created_at": "2026-10-13T00:00:00Z",
    }


def test_live_and_durable_boundaries_keep_provider_identity() -> None:
    event = _event()
    live = LiveEventListResponse.model_validate(
        {
            "partial_history": {"items": [event]},
            "mailbox_items": [],
            "session_run_state": "running",
        }
    )
    selected = _provider_call_event(_live_events(live), status="running")
    assert selected is not None
    assert selected.payload.call_id == selected.event.external_id == "call-1"
    assert selected.event.adapter == "azents-live"
    history = decode_history_page(
        {
            "items": [_event(status="completed")],
            "has_more": False,
            "has_newer": False,
            "next_cursor": None,
        }
    )
    assert _provider_call_event(history.items, status="running") is None
    assert _provider_call_event(history.items, status="completed") is not None


@pytest.mark.parametrize(
    "action_type,status,expected",
    [
        ("live_event_upserted", "running", True),
        ("live_event_upserted", "completed", False),
        ("history_event_appended", "running", False),
    ],
)
def test_upsert_predicate_decodes_declared_action_variant(
    action_type: str, status: str, expected: bool
) -> None:
    action = _ProviderAction.model_validate(
        {"type": action_type, "session_id": "session-1", "event": _event(status=status)}
    )
    assert _provider_upsert_with_status("running")(action) is expected
    assert _provider_history_appended(action) is False


def test_durable_completion_and_live_removal_keep_declared_fields() -> None:
    action = _ProviderAction.model_validate(
        {
            "type": "history_event_appended",
            "session_id": "session-1",
            "event": _event(status="completed"),
        }
    )
    assert _provider_history_appended(action)
    removal = _ProviderAction.model_validate_json(
        '{"type":"live_event_removed","session_id":"session-1","event_id":"event-1","future":true}'
    )
    assert removal.event_id == "event-1"
    assert removal.session_id == "session-1"
    assert removal.model_extra == {"future": True}


@pytest.mark.parametrize(
    "action_type",
    ["live_event_upserted", "history_event_appended", "live_event_removed"],
)
def test_interpreted_action_rejects_missing_variant_field(action_type: str) -> None:
    with pytest.raises(ValidationError):
        _ProviderAction.model_validate({"type": action_type, "session_id": "session-1"})


@pytest.mark.parametrize("field", ["call_id", "name", "status"])
@pytest.mark.parametrize("value", [True, 3, [], {}])
def test_provider_decision_fields_reject_primitive_coercion(
    field: str, value: object
) -> None:
    payload = {
        "call_id": "call-1",
        "name": "web_search",
        "status": "running",
        field: value,
    }
    with pytest.raises(ValidationError):
        _provider_call_event(
            [ChatEventResponse.model_validate({**_event(), "payload": payload})],
            status="running",
        )


@pytest.mark.parametrize("field", ["call_id", "name"])
def test_required_provider_identifiers_reject_null(field: str) -> None:
    payload = {"call_id": "call-1", "name": "web_search", "status": None, field: None}
    with pytest.raises(ValidationError):
        _ProviderCallPayload.model_validate(payload)


def test_canonical_nullable_status_and_structured_assistant_are_nonmatches() -> None:
    event = ChatEventResponse.model_validate(_event(status=None))
    assert _provider_call_event([event], status="running") is None
    assert _provider_call_event([event], status="completed") is None
    assistant = _AssistantPayload.model_validate(
        {"content": [{"type": "output_text", "text": "structured output"}]}
    )
    assert not isinstance(assistant.content, str)
    assert assistant.content != "PROVIDER_TOOL_LIVE_ACTIVITY_COMPLETED"


def test_unrelated_payload_is_opaque_until_its_kind_is_interpreted() -> None:
    event = ChatEventResponse.model_validate(
        {**_event(kind="reasoning"), "payload": {"native": True}}
    )
    assert _provider_call_event([event], status="running") is None
    payload = _ProviderCallPayload.model_validate(
        {
            "call_id": "call-1",
            "name": "web_search",
            "status": "running",
            "future": {"opaque": True},
        }
    )
    assert payload.model_extra == {"future": {"opaque": True}}
    assert (
        _AssistantPayload.model_validate({"content": "completed"}).content
        == "completed"
    )
    with pytest.raises(ValidationError):
        _AssistantPayload.model_validate({"content": False})
