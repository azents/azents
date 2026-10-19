"""Docker-free regressions for OAuth, semantic and Team Session observations."""

import json

import pytest
import requests
from azentspublicclient.models.session_context_response import SessionContextResponse
from pydantic import ValidationError

from tests.required.public import external_account_linking_scenarios as linking
from tests.required.public.external_account_linking_scenarios import (
    _decode_settings_view,
    _error_code,
    _ErrorResponse,
    _GlobalLink,
    _LinkList,
    _OAuthSection,
    _OAuthStart,
    _ProviderAvailabilityList,
    _RequestCounts,
    _SettingsView,
    _slack_setup_confirmation,
)
from tests.required.public.test_provider_tool_semantic_transcript import (
    _compaction_request,
    _last_user_text,
    _provider_semantic_event,
    _request_for_prompt,
    _SemanticRequest,
    _serialized_input,
    _TextPayload,
)
from tests.required.public.test_team_sessions import (
    _Live,
    _mailbox_item_contents,
    _snapshot_input_contents,
    _UserMessage,
    _Write,
)


def test_oauth_response_projections_preserve_declared_fields_and_extensions() -> None:
    section = _OAuthSection.model_validate(
        {"admin_version": 3, "callback_url": None, "future": True}
    )
    assert section.admin_version == 3
    assert section.callback_url is None
    assert section.model_extra == {"future": True}
    assert _OAuthStart.model_validate(
        {"authorization_url": "https://example.test/auth"}
    ).authorization_url.endswith("/auth")
    providers = _ProviderAvailabilityList.model_validate(
        {"items": [{"provider": "slack", "available": False, "callback_url": None}]}
    )
    assert not providers.items[0].available
    link = _GlobalLink.model_validate(
        {
            "id": "link",
            "identity_scope": "global",
            "provider_user_id": "user",
            "provider_display_label": "Label",
        }
    )
    assert _LinkList.model_validate({"items": [link.model_dump()]}).items == [link]
    assert _decode_settings_view({}) is None
    view = _SettingsView.model_validate(
        {
            "view_hash": "hash",
            "private_metadata": None,
            "action_ids": ["model"],
            "link_paths": ["/account"],
        }
    )
    assert view.action_ids == ["model"] and view.link_paths == ["/account"]
    counts = _RequestCounts.model_validate({"request_counts": {"history": 2}})
    assert counts.request_counts["history"] == 2
    assert counts.request_counts.get("missing", 0) == 0


@pytest.mark.parametrize("metadata", [None, "unavailable", "signed-current-view"])
def test_setup_wait_rejects_fresh_nonconfirmation_settings(
    monkeypatch: pytest.MonkeyPatch, metadata: str | None
) -> None:
    view = _SettingsView(
        view_hash="fresh",
        private_metadata=metadata,
        action_ids=[],
        link_paths=[],
    )
    monkeypatch.setattr(linking, "_transient_slack_view", lambda *args, **kwargs: view)
    assert _slack_setup_confirmation("http://invalid.test", after_hash="old") is None


def test_setup_wait_accepts_only_the_completed_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = _SettingsView(
        view_hash="fresh", private_metadata="completed", action_ids=[], link_paths=[]
    )
    observations: list[tuple[str, str, str | None]] = []

    def transient(
        fake_url: str, *, scope: str, after_hash: str | None
    ) -> _SettingsView:
        observations.append((fake_url, scope, after_hash))
        return completed

    monkeypatch.setattr(linking, "_transient_slack_view", transient)
    assert (
        _slack_setup_confirmation("http://invalid.test", after_hash="old") == completed
    )
    assert observations == [("http://invalid.test", "settings", "old")]


@pytest.mark.parametrize("absent", [True, False])
def test_setup_wait_does_not_reuse_absent_or_stale_completion(
    monkeypatch: pytest.MonkeyPatch, *, absent: bool
) -> None:
    payload: dict[str, object] = (
        {}
        if absent
        else {
            "view_hash": "old",
            "private_metadata": "completed",
            "action_ids": [],
            "link_paths": [],
        }
    )
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    monkeypatch.setattr(linking.requests, "get", lambda *args, **kwargs: response)
    assert _slack_setup_confirmation("http://invalid.test", after_hash="old") is None


@pytest.mark.parametrize("value", [True, "3", None, [], {}])
def test_admin_version_and_provider_counts_reject_malformed_primitives(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _OAuthSection.model_validate({"admin_version": value, "callback_url": None})
    with pytest.raises(ValidationError):
        _RequestCounts.model_validate({"request_counts": {"history": value}})


def test_account_link_error_optional_detail_remains_a_nonmatch() -> None:
    assert (
        _ErrorResponse.model_validate({"detail": "ordinary HTTP error"}).detail
        == "ordinary HTTP error"
    )
    response = requests.Response()
    response.status_code = 409
    response._content = b'{"detail":{"code":"conflict","message":"Expected conflict"}}'
    assert _error_code(response) == "conflict"
    response._content = b'{"detail":"ordinary HTTP error"}'
    assert _error_code(response) is None


@pytest.mark.parametrize(
    "content",
    [
        "prompt",
        [
            {"type": "input_text", "text": "pro"},
            {"type": "input_text", "text": "mpt"},
            {"type": "input_image", "image_url": "https://example.test/image"},
        ],
    ],
)
def test_responses_last_user_text_uses_typed_projection(content: object) -> None:
    request = _SemanticRequest.model_validate(
        {
            "input": [
                {"role": "user", "content": content},
                {
                    "type": "web_search_call",
                    "id": "search",
                    "action": {"query": "opaque"},
                },
            ],
            "instructions": None,
            "tools": [],
        }
    )
    assert _last_user_text(request) == "prompt"
    assert _request_for_prompt([request], "prompt") is request
    assert "opaque" in _serialized_input(request)


def test_semantic_request_retains_nullable_fields_and_unknown_native_payload() -> None:
    request = _SemanticRequest.model_validate(
        {"input": None, "instructions": None, "tools": None, "future": {"value": 1}}
    )
    assert _last_user_text(request) is None
    compact = _SemanticRequest.model_validate(
        {
            "input": [{"role": "user", "content": None}],
            "instructions": (
                "You are a context compaction engine for a long-running agent. More"
            ),
        }
    )
    assert _last_user_text(compact) is None
    assert _compaction_request([request, compact]) is compact
    assert request.model_extra == {"future": {"value": 1}}
    malformed = _SemanticRequest.model_validate(
        {"input": [{"role": "user", "content": [{"type": "input_text", "text": True}]}]}
    )
    with pytest.raises(ValidationError):
        _last_user_text(malformed)
    assert not isinstance(
        _TextPayload.model_validate(
            {"content": [{"type": "output_text", "text": "structured"}]}
        ).content,
        str,
    )
    with pytest.raises(ValidationError):
        _TextPayload.model_validate({"content": True})


def test_context_provider_semantics_use_generated_event_and_nullable_reference() -> (
    None
):
    context = SessionContextResponse.model_validate(
        {
            "session": {"id": "session", "agent_id": "agent", "title": None},
            "stats": {
                "total_events": 1,
                "user_messages": 0,
                "assistant_messages": 0,
                "reasoning_events": 0,
                "tool_calls": 1,
                "tool_results": 0,
                "turn_markers": 0,
            },
            "breakdown": [{"key": "tool", "tokens": 30, "percent": 10}],
            "raw_events": [
                {
                    "id": "event",
                    "kind": "provider_tool_call",
                    "payload": {
                        "name": "web_search",
                        "status": None,
                        "semantic": {
                            "input": None,
                            "references": [{"uri": None}],
                            "output": [
                                {"type": "output_text", "text": "opaque output"}
                            ],
                        },
                    },
                    "schema_version": "1",
                    "created_at": "2026-10-13T00:00:00Z",
                }
            ],
        }
    )
    selected = _provider_semantic_event(context)
    assert selected.id == "event"
    assert context.breakdown[0].tokens == 30


def _mailbox_wire() -> list[dict[str, object]]:
    return [
        {
            "mailbox_item_id": "mailbox",
            "session_id": "session",
            "kind": "user_message",
            "items": [
                {
                    "id": "mailbox:item",
                    "item_key": "item",
                    "presentation": {"type": "user_message", "content": "message"},
                },
                {
                    "id": "mailbox:other",
                    "item_key": "other",
                    "presentation": {
                        "type": "agent_message",
                        "content": {"opaque": True},
                    },
                },
            ],
        }
    ]


def test_team_mailbox_and_write_are_typed_without_rejecting_other_presentations() -> (
    None
):
    wire: dict[str, object] = {
        "session_id": "session",
        "snapshot": {"mailbox_items": _mailbox_wire(), "future": True},
    }
    assert _Write.model_validate(wire).session_id == "session"
    assert _snapshot_input_contents(_Write.model_validate(wire)) == ["message"]
    live = _Live.model_validate({"mailbox_items": _mailbox_wire()})
    assert _mailbox_item_contents(live.mailbox_items, label="live") == ["message"]
    structured = _UserMessage.model_validate(
        {
            "content": [{"type": "input_text", "text": "structured"}],
            "sender_user_id": None,
        }
    )
    assert structured.sender_user_id is None
    assert _UserMessage.model_validate({"content": "historical"}).sender_user_id is None
    with pytest.raises(ValidationError):
        _UserMessage.model_validate({"content": "message", "sender_user_id": True})
