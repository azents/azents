"""Docker-free typed buffer, catalog and fallback observation regressions."""

import json
from datetime import UTC, datetime

import pytest
import requests
from azentspublicclient.models.selectable_model_option_response import (
    SelectableModelOptionResponse,
)
from pydantic import ValidationError

from support.observations import HistoryPageObservation
from tests.required.public.test_chat_input_buffer import (
    _BufferLive,
    _find_user_message_id,
    _input_buffer_contents,
    _message_contents,
    _pending_buffers,
    _run_marker_statuses,
)
from tests.required.public.test_model_quota_fallback import (
    _candidate_selection,
    _RouteMarker,
)
from tests.required.public.test_model_selection import _wait_for_initial_catalog_sync


def _event(kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "event-1",
        "session_id": "session-1",
        "kind": kind,
        "payload": payload,
        "schema_version": "1",
        "created_at": datetime(2026, 10, 13, tzinfo=UTC),
    }


def _live(content: object) -> dict[str, object]:
    return {
        "partial_history": {"items": []},
        "mailbox_items": [
            {
                "mailbox_item_id": "mailbox-1",
                "session_id": "session-1",
                "kind": "user_message",
                "items": [
                    {
                        "id": "mailbox-1:item-1",
                        "item_key": "item-1",
                        "presentation": {"type": "user_message", "content": content},
                    }
                ],
            }
        ],
        "session_run_state": "idle",
    }


def test_pending_buffer_uses_declared_identity_and_text() -> None:
    live = _BufferLive.model_validate(_live("pending text"))
    assert _input_buffer_contents(live) == ["pending text"]
    pending = _pending_buffers(live)[0]
    assert (pending.id, pending.mailbox_item_id, pending.item_key) == (
        "mailbox-1:item-1",
        "mailbox-1",
        "item-1",
    )


def test_malformed_mailbox_identity_fails_at_ingress() -> None:
    payload = _live("pending")
    payload["mailbox_items"] = [{"mailbox_item_id": 1}]
    with pytest.raises(ValidationError):
        _BufferLive.model_validate(payload)


def test_non_text_user_mailbox_is_not_silently_discarded() -> None:
    live = _BufferLive.model_validate(_live(["not user text"]))
    with pytest.raises(AssertionError, match="invalid user mailbox presentation"):
        _pending_buffers(live)


def test_history_selects_validated_marker_and_user_identity() -> None:
    page = HistoryPageObservation.model_validate(
        {
            "items": [
                _event("user_message", {"content": "target"}),
                _event("run_marker", {"status": "interrupted"}),
                _event("assistant_message", {"content": [{"type": "text"}]}),
            ],
            "has_more": False,
            "next_cursor": None,
        }
    )
    assert _message_contents(page) == ["target"]
    assert _find_user_message_id(page, "target") == "event-1"
    assert _run_marker_statuses(page) == ["interrupted"]


def test_missing_run_status_fails_instead_of_polling_success() -> None:
    page = HistoryPageObservation.model_validate(
        {"items": [_event("run_marker", {})], "has_more": False}
    )
    with pytest.raises(ValidationError):
        _run_marker_statuses(page)


@pytest.mark.parametrize("ordinal", [True, "2"])
def test_fallback_route_rejects_coerced_candidate_ordinal(ordinal: object) -> None:
    with pytest.raises(ValidationError):
        _RouteMarker.model_validate(
            {
                "applied_model_route": {
                    "candidate_ordinal": ordinal,
                    "candidate_role": "fallback",
                    "model_identifier": "secondary",
                }
            }
        )


def test_route_preserves_extension_evidence() -> None:
    marker = _RouteMarker.model_validate(
        {
            "applied_model_route": {
                "candidate_ordinal": 2,
                "candidate_role": "fallback",
                "model_identifier": "secondary",
                "operation_kind": "foreground",
            }
        }
    )
    assert marker.applied_model_route.candidate_ordinal == 2
    assert marker.applied_model_route.model_extra == {"operation_kind": "foreground"}


def test_missing_candidate_selection_rejected_by_generated_contract() -> None:
    with pytest.raises(ValidationError):
        SelectableModelOptionResponse.model_validate(
            {"label": "Quality", "candidates": [{"model_selection": {}}]}
        )
    assert callable(_candidate_selection)


def _catalog_response(payload: dict[str, object]) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    return response


def test_catalog_poll_rejects_malformed_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _catalog_response(
        {"catalog_scope": "integration", "latest_sync": {"status": "succeeded"}}
    )

    def get(url: str, *, headers: dict[str, str], timeout: int) -> requests.Response:
        return response

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValidationError):
        _wait_for_initial_catalog_sync("https://example.test", "token", "ws", "llm")


def test_catalog_poll_accepts_valid_terminal_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _catalog_response(
        {
            "catalog_id": "catalog",
            "catalog_scope": "integration",
            "last_success_at": None,
            "latest_sync": {
                "status": "succeeded",
                "started_at": "2026-10-13T00:00:00Z",
                "finished_at": None,
                "failure_code": None,
                "failure_message": None,
                "action_hint": None,
                "fetched_count": 1,
                "matched_count": 1,
                "skipped_count": 0,
                "hidden_count": 0,
            },
            "stale": False,
            "sync_available_at": None,
            "automatic_retry_blocked": False,
            "entries": [],
            "total": 0,
            "limit": 100,
            "offset": 0,
        }
    )

    def get(url: str, *, headers: dict[str, str], timeout: int) -> requests.Response:
        return response

    monkeypatch.setattr(requests, "get", get)
    assert (
        _wait_for_initial_catalog_sync("https://example.test", "token", "ws", "llm")
        is response
    )
