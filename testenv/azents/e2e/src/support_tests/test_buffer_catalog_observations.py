"""Docker-free typed buffer, catalog and fallback observation regressions."""

import json
from datetime import UTC, datetime
from typing import TypedDict

import pytest
import requests
from azentspublicclient.models.live_event_list_response import LiveEventListResponse
from azentspublicclient.models.pending_mailbox_envelope import PendingMailboxEnvelope
from azentspublicclient.models.selectable_model_option_response import (
    SelectableModelOptionResponse,
)
from pydantic import ValidationError

from support.observations import HistoryPageObservation, MailboxObservation
from tests.required.public import test_chat_input_buffer as buffer_flow
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
                "scheduling_mode": "queued",
                "created_at": "2026-10-13T00:00:00Z",
                "items": [
                    {
                        "id": "mailbox-1:item-1",
                        "mailbox_item_id": "mailbox-1",
                        "item_key": "item-1",
                        "kind": "user_message",
                        "state": "pending",
                        "created_at": "2026-10-13T00:00:00Z",
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
    with pytest.raises(ValueError):
        _BufferLive.model_validate(_live(["not user text"]))


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


def _running_live() -> dict[str, object]:
    return {
        "partial_history": {"items": []},
        "mailbox_items": [],
        "session_run_state": "running",
        "run": {
            "run_id": "run-1",
            "phase": "waiting_for_model",
            "status": "running",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            "using_fallback": False,
            "model_call_started_at": None,
        },
    }


class _PollLocation(TypedDict):
    server_url: str
    token: str
    session_id: str


@pytest.mark.parametrize("boundary", ["idle", "running", "interrupted", "matched"])
def test_real_rest_polling_preserves_generated_and_adopted_mailbox_contracts(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    """Exercise every former generated-serializer callsite with native mailboxes."""
    live_wire = _live("pending text")
    if boundary == "running":
        live_wire.update(_running_live())
        live_wire["mailbox_items"] = _live("pending text")["mailbox_items"]
    else:
        live_wire["run"] = None
    generated = LiveEventListResponse.from_dict(live_wire)
    assert generated is not None
    assert isinstance(generated.mailbox_items[0], PendingMailboxEnvelope)
    observation = _BufferLive.model_validate(live_wire)
    assert not isinstance(observation, LiveEventListResponse)
    assert isinstance(observation.mailbox_items[0], MailboxObservation)
    history_wire: dict[str, object] = {
        "items": [
            {
                **_event("user_message", {"content": "target"}),
                "created_at": "2026-10-13T00:00:00Z",
            },
            {
                **_event("run_marker", {"status": "interrupted"}),
                "created_at": "2026-10-13T00:00:00Z",
            },
        ],
        "has_more": False,
        "next_cursor": None,
    }
    history_response = _catalog_response(history_wire)
    live_response = _catalog_response(live_wire)
    paths: list[str] = []

    def get(url: str, *, headers: dict[str, str], timeout: int) -> requests.Response:
        paths.append(url)
        return history_response if url.endswith("/history") else live_response

    monkeypatch.setattr(requests, "get", get)
    kwargs: _PollLocation = {
        "server_url": "https://example.test",
        "token": "token",
        "session_id": "session-1",
    }
    if boundary == "idle":
        buffer_flow._wait_for_idle_rest_state(**kwargs, expected_message="target")
    elif boundary == "running":
        buffer_flow._wait_for_running_rest_state(**kwargs, expected_message="target")
    elif boundary == "interrupted":
        returned_history = buffer_flow._wait_for_interrupted_idle_state(**kwargs)
        assert _run_marker_statuses(returned_history) == ["interrupted"]
    else:
        state = buffer_flow._wait_for_rest_state(
            **kwargs, expected_message="target", expected_pending=["pending text"]
        )
        assert isinstance(state.live.mailbox_items[0], MailboxObservation)
        assert _input_buffer_contents(state.live) == ["pending text"]
        assert _message_contents(state.history) == ["target"]
    assert len(paths) == 2


@pytest.mark.parametrize("location", ["mailbox", "outer", "history", "run"])
def test_full_live_identity_absence_assertion_retains_native_and_opaque_fields(
    location: str,
) -> None:
    """An ID anywhere in the complete live evidence must still fail absence."""
    identifier = "mailbox-1"
    if location == "mailbox":
        live_wire = _live("pending")
    elif location == "run":
        live_wire = _running_live()
        run = live_wire["run"]
        assert isinstance(run, dict)
        run["opaque_extension"] = {"reference": identifier}
    else:
        history: dict[str, object] = {"items": []}
        live_wire = {
            "partial_history": history,
            "mailbox_items": [],
            "session_run_state": "idle",
            "run": None,
        }
        if location == "outer":
            live_wire["opaque_extension"] = {"reference": identifier}
        else:
            history["opaque_extension"] = {"reference": identifier}
    live = _BufferLive.model_validate(live_wire)
    with pytest.raises(AssertionError):
        assert identifier not in live.model_dump_json()


def test_full_live_identity_absence_passes_only_when_evidence_is_absent() -> None:
    live = _BufferLive.model_validate(
        {
            "partial_history": {"items": []},
            "mailbox_items": [],
            "session_run_state": "idle",
            "run": None,
        }
    )
    assert live.run is None
    assert "run" in live.model_fields_set
    assert "mailbox-1" not in live.model_dump_json()
