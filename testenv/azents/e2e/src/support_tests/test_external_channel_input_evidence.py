"""Pure regressions for bounded complete External Channel input evidence.

HTTP responses are injected into the actual scenario helpers. These tests do not
open listeners, run containers, or read or mutate product databases.
"""

import json
from collections.abc import Callable
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from pydantic import ValidationError

from tests.required.public import external_channel_scenarios as scenarios

_SERVER = "http://injected-evidence.invalid"
_SESSION_ID = "s" * 32
_TOKEN = "injected-token"


class _Call(NamedTuple):
    """One observed request with decoded public API query parameters."""

    path: str
    query: dict[str, list[str]]


def _response(payload: dict[str, object], *, url: str) -> requests.Response:
    """Construct a real response without acquiring a network connection."""
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.encoding = "utf-8"
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload).encode()
    return response


def _install_get(
    monkeypatch: pytest.MonkeyPatch,
    payload_for: Callable[[_Call], dict[str, object]],
) -> list[_Call]:
    calls: list[_Call] = []

    def get(url: str, **kwargs: object) -> requests.Response:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        params = kwargs.get("params")
        if params is not None:
            assert isinstance(params, dict)
            for key, value in params.items():
                assert isinstance(key, str)
                if value is not None:
                    query[key] = [str(value)]
        assert kwargs.get("headers") == {"Authorization": f"Bearer {_TOKEN}"}
        assert kwargs.get("timeout") == 10
        call = _Call(path=parsed.path, query=query)
        calls.append(call)
        return _response(payload_for(call), url=url)

    monkeypatch.setattr(scenarios.requests, "get", get)
    return calls


def _input_event(index: int) -> dict[str, object]:
    """Create one public-projection input with stable provider identity."""
    return {
        "id": f"{index:032x}",
        "session_id": _SESSION_ID,
        "kind": "external_channel_message",
        "payload": {
            "provider": "discord",
            "external_message_id": f"discord:guild:{index}",
            "prompt_role": "invocation",
            "body": f"participant input {index}",
            "original_url": f"https://discord.com/channels/guild/channel/{index}",
        },
        "schema_version": "1",
        "created_at": "2026-10-03T00:00:00Z",
    }


def _held_event(index: int) -> dict[str, object]:
    return {
        "id": f"{index:032x}",
        "session_id": _SESSION_ID,
        "kind": "client_tool_result",
        "payload": {"call_id": f"held-progress-{index}", "output": "Work is held"},
        "schema_version": "1",
        "created_at": "2026-10-03T00:00:00Z",
    }


def _page(events: list[dict[str, object]], *, has_more: bool) -> dict[str, object]:
    return {
        "items": events,
        "has_more": has_more,
        "next_cursor": events[0]["id"] if events else None,
    }


def _read_inputs(*, include_pending: bool) -> list[scenarios._ExternalInputEvidence]:
    return scenarios._external_channel_input_evidence(
        public_server_url=_SERVER,
        token=_TOKEN,
        session_id=_SESSION_ID,
        include_pending=include_pending,
    )


@pytest.mark.parametrize("input_count", [3, 4])
def test_old_inputs_survive_more_than_one_page_of_held_events(
    monkeypatch: pytest.MonkeyPatch,
    input_count: int,
) -> None:
    """Recent Tool churn must not become a false negative for promoted inputs."""
    events = [
        *[_input_event(index) for index in range(1, input_count + 1)],
        *[_held_event(index) for index in range(100, 340)],
    ]

    def payload_for(call: _Call) -> dict[str, object]:
        assert call.path == f"/chat/v1/sessions/{_SESSION_ID}/history"
        assert call.query["limit"] == ["100"]
        assert "after" not in call.query
        before = call.query.get("before")
        candidates = events
        if before is not None:
            candidates = [event for event in events if str(event["id"]) < before[0]]
        return _page(candidates[-100:], has_more=len(candidates) > 100)

    calls = _install_get(monkeypatch, payload_for)
    evidence = _read_inputs(include_pending=False)

    assert len(evidence) == input_count
    assert {item.external_message_id for item in evidence} == {
        f"discord:guild:{index}" for index in range(1, input_count + 1)
    }
    assert {item.body for item in evidence} == {
        f"participant input {index}" for index in range(1, input_count + 1)
    }
    assert len(calls) == 3
    assert "before" not in calls[0].query
    assert calls[1].query["before"] == [str(events[-100]["id"])]
    assert calls[2].query["before"] == [str(events[-200]["id"])]
    assert all(call.path.endswith("/history") for call in calls)


@pytest.mark.parametrize("conflicting_live", [False, True])
def test_live_and_paged_history_retain_consistency_check(
    monkeypatch: pytest.MonkeyPatch,
    conflicting_live: bool,
) -> None:
    """Paging must preserve live/history agreement and logical-ID deduplication."""
    event = _input_event(1)
    payload = event["payload"]
    assert isinstance(payload, dict)
    presentation = {str(key): value for key, value in payload.items()}
    presentation["type"] = "external_channel_message"
    if conflicting_live:
        presentation["body"] = "conflicting body"

    def payload_for(call: _Call) -> dict[str, object]:
        if call.path.endswith("/history"):
            return _page([event], has_more=False)
        assert call.path == f"/chat/v1/sessions/{_SESSION_ID}/live"
        return {
            "mailbox_items": [
                {
                    "kind": "external_channel_message",
                    "items": [{"presentation": presentation}],
                },
            ],
        }

    calls = _install_get(monkeypatch, payload_for)
    if conflicting_live:
        with pytest.raises(AssertionError, match="disagree"):
            _read_inputs(include_pending=True)
    else:
        evidence = _read_inputs(include_pending=True)
        assert len(evidence) == 1
        assert evidence[0].external_message_id == "discord:guild:1"
    assert sum(call.path.endswith("/live") for call in calls) == 1


@pytest.mark.parametrize("has_more", [None, "false", 0])
def test_invalid_has_more_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    has_more: object,
) -> None:
    """Malformed pagination must not produce a silently partial input count."""
    payload = _page([_input_event(1)], has_more=False)
    payload["has_more"] = has_more
    calls = _install_get(monkeypatch, lambda _: payload)
    with pytest.raises(AssertionError):
        _read_inputs(include_pending=False)
    assert len(calls) == 1


def test_missing_cursor_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A nonterminal page without a cursor is not complete history evidence."""
    payload = _page([_input_event(1)], has_more=True)
    payload["next_cursor"] = None
    calls = _install_get(monkeypatch, lambda _: payload)
    with pytest.raises(AssertionError):
        _read_inputs(include_pending=False)
    assert len(calls) == 1


def test_repeated_cursor_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cursor cycles cannot fabricate exhaustion or loop until a test timeout."""
    pages: list[dict[str, object]] = [
        _page([_held_event(3)], has_more=True),
        {
            "items": [_input_event(2)],
            "has_more": True,
            "next_cursor": f"{3:032x}",
        },
    ]
    calls = _install_get(monkeypatch, lambda _: pages.pop(0))
    with pytest.raises(AssertionError):
        _read_inputs(include_pending=False)
    assert len(calls) == 2


def test_page_overlap_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overlapping public pages cannot silently deduplicate a broken cursor."""
    pages = [
        _page([_held_event(3)], has_more=True),
        _page([_input_event(2), _held_event(3)], has_more=False),
    ]
    calls = _install_get(monkeypatch, lambda _: pages.pop(0))
    with pytest.raises(AssertionError):
        _read_inputs(include_pending=False)
    assert len(calls) == 2


def test_twenty_page_cap_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bounded sampler must reject unexhausted 2,000-event evidence."""
    page_number = 0

    def payload_for(call: _Call) -> dict[str, object]:
        nonlocal page_number
        assert call.path.endswith("/history")
        assert call.query["limit"] == ["100"]
        start = 2_000 - 100 * (page_number + 1)
        page_number += 1
        return _page(
            [_held_event(index) for index in range(start, start + 100)],
            has_more=True,
        )

    calls = _install_get(monkeypatch, payload_for)
    with pytest.raises(AssertionError):
        _read_inputs(include_pending=False)
    assert len(calls) == 20
    assert all(call.path.endswith("/history") for call in calls)


@pytest.mark.parametrize("counter", [True, "1", None])
def test_provider_counters_reject_coercible_and_null_evidence(
    monkeypatch: pytest.MonkeyPatch, counter: object
) -> None:
    """Provider polling must never mistake malformed counters for readiness."""
    payload: dict[str, object] = {
        "request_counts": {"chat.update": counter},
        "deliveries": [],
    }

    def get(url: str, *, timeout: int) -> requests.Response:
        assert timeout == 5
        return _response(payload, url=url)

    monkeypatch.setattr(scenarios.requests, "get", get)
    with pytest.raises(ValidationError):
        scenarios._provider_observation(_SERVER)


def test_provider_extensions_and_declared_nulls_survive_wire_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adjacent wire assertions retain extensions, omissions, and explicit null."""
    payload: dict[str, object] = {
        "request_counts": {"chat.update": 1},
        "deliveries": [{"outcome": "delivered", "session_path": None}],
        "future_provider_section": {"revision": 2},
    }

    def get(url: str, *, timeout: int) -> requests.Response:
        assert timeout == 5
        return _response(payload, url=url)

    monkeypatch.setattr(scenarios.requests, "get", get)
    observation = scenarios._provider_observation(_SERVER)
    assert observation.request_counts == {"chat.update": 1}
    assert observation.deliveries[0].session_path is None
    assert "session_path" in observation.deliveries[0].model_fields_set
    assert "safe_category" not in observation.deliveries[0].model_fields_set
    assert scenarios._provider_state(_SERVER) == payload


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_barrier_reached_requires_a_boolean(
    monkeypatch: pytest.MonkeyPatch, flag: object
) -> None:
    """A malformed synchronization response cannot release an ordering poll."""

    def get(url: str, *, timeout: int) -> requests.Response:
        assert timeout == 5
        return _response({"reached": flag}, url=url)

    monkeypatch.setattr(scenarios.requests, "get", get)
    with pytest.raises(ValidationError):
        scenarios._read_barrier(_SERVER)


@pytest.mark.parametrize("body", [123, True, ["text"], {"text": "opaque"}])
def test_external_input_text_rejects_malformed_history_payload(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    """Interpret external text strictly while the event envelope stays generated."""
    event = _input_event(1)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload["body"] = body
    _install_get(monkeypatch, lambda _: _page([event], has_more=False))
    with pytest.raises(ValidationError):
        _read_inputs(include_pending=False)


def test_unrelated_mailbox_payload_remains_opaque(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown mailbox item families must not acquire external-input invariants."""

    def payload_for(call: _Call) -> dict[str, object]:
        if call.path.endswith("/history"):
            event = _input_event(1)
            event["future_event_field"] = {"opaque": [1, None]}
            return _page([event], has_more=False)
        return {
            "mailbox_items": [
                {"kind": "command", "items": [{"presentation": {"body": [1, 2]}}]},
            ],
            "future_live_extension": True,
        }

    _install_get(monkeypatch, payload_for)
    evidence = _read_inputs(include_pending=True)
    assert [item.external_message_id for item in evidence] == ["discord:guild:1"]


def test_external_input_null_and_omitted_optional_text_have_same_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical deduplication preserves nullable optional presentation semantics."""
    event = _input_event(1)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload.pop("original_url")
    presentation = {**payload, "type": "external_channel_message", "original_url": None}

    def payload_for(call: _Call) -> dict[str, object]:
        if call.path.endswith("/history"):
            return _page([event], has_more=False)
        return {
            "mailbox_items": [
                {
                    "kind": "external_channel_message",
                    "items": [{"presentation": presentation}],
                }
            ]
        }

    _install_get(monkeypatch, payload_for)
    evidence = _read_inputs(include_pending=True)
    assert len(evidence) == 1
    assert evidence[0].original_url is None


def test_progress_journal_tolerates_extensions_but_validates_decision_fields() -> None:
    """The provider stage decoder checks fields used by the assembled journey."""
    decoded = scenarios._PROGRESS_OBSERVATIONS.validate_python(
        [
            {"binding": "b", "matched": True, "stage": None, "future_field": [1]},
        ]
    )
    assert decoded[0].matched is True
    assert decoded[0].stage is None
    with pytest.raises(ValidationError):
        scenarios._PROGRESS_OBSERVATIONS.validate_python([{"matched": "true"}])


def test_file_journal_decodes_per_call_output_metadata() -> None:
    """The file proxy emits a call-keyed mapping, with nullable diagnostic values."""
    decoded = scenarios._FILE_OBSERVATIONS.validate_python(
        [
            {
                "binding": "b",
                "stage": "after_process",
                "tool_outputs": {
                    "call-download": {"present": True, "length": None, "error": None},
                },
                "future_metadata": {"revision": 2},
            },
        ]
    )
    output = decoded[0].tool_outputs["call-download"]
    assert output.present is True
    assert output.length is None
    assert output.error is None
    with pytest.raises(ValidationError):
        scenarios._FILE_OBSERVATIONS.validate_python([{"tool_outputs": []}])
