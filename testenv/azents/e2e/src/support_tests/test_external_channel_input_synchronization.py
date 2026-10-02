"""Deterministic coverage for public External Channel input observations."""

import json
from collections.abc import Callable

import pytest
import requests

from tests.required.public import external_channel_scenarios as scenarios

_PUBLIC_URL = "http://public.invalid"
_SESSION_ID = "session-evidence"
_INPUT: dict[str, object] = {
    "type": "external_channel_message",
    "provider": "slack",
    "external_message_id": "1710000000.000200",
    "prompt_role": "invocation",
    "body": "socket request",
    "original_url": None,
}


def _response(payload: dict[str, object]) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    return response


def _history(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "items": [
            {
                "id": f"{index:032x}",
                "kind": "external_channel_message",
                "payload": item,
            }
            for index, item in enumerate(items, start=1)
        ],
        "has_more": False,
        "next_cursor": None,
    }


def _live(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "mailbox_items": [
            {
                "kind": "external_channel_message",
                "items": [{"presentation": item} for item in items],
            }
        ]
    }


def _read_evidence() -> list[dict[str, object]]:
    return scenarios._external_channel_input_evidence(
        public_server_url=_PUBLIC_URL,
        token="synthetic-token",
        session_id=_SESSION_ID,
    )


def test_promotion_between_public_reads_does_not_lose_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move input from mailbox to history after exactly the first API read."""
    promoted = False

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int] | None = None,
    ) -> requests.Response:
        nonlocal promoted
        del headers, timeout
        if url.endswith("/live"):
            payload = _live([] if promoted else [_INPUT])
        else:
            assert url.endswith("/history")
            assert params == {"limit": 100}
            payload = _history([_INPUT] if promoted else [])
        promoted = True
        return _response(payload)

    monkeypatch.setattr(scenarios.requests, "get", get)

    evidence = _read_evidence()

    assert len(evidence) == 1
    assert evidence[0]["external_message_id"] == _INPUT["external_message_id"]


def test_live_and_history_overlap_counts_one_logical_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordered reads can overlap while an input is promoted."""

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int] | None = None,
    ) -> requests.Response:
        del headers, timeout, params
        return _response(
            _live([_INPUT]) if url.endswith("/live") else _history([_INPUT])
        )

    monkeypatch.setattr(scenarios.requests, "get", get)

    assert len(_read_evidence()) == 1


@pytest.mark.parametrize("promoted", [False, True])
def test_stable_input_is_visible_before_and_after_promotion(
    monkeypatch: pytest.MonkeyPatch,
    promoted: bool,
) -> None:
    """Read one input when it remains wholly in either public projection."""

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int] | None = None,
    ) -> requests.Response:
        del headers, timeout, params
        return _response(
            _live([] if promoted else [_INPUT])
            if url.endswith("/live")
            else _history([_INPUT] if promoted else [])
        )

    monkeypatch.setattr(scenarios.requests, "get", get)

    assert len(_read_evidence()) == 1


def test_live_and_history_disagreement_remains_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordering must preserve conflicting-projection detection."""

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int] | None = None,
    ) -> requests.Response:
        del headers, timeout, params
        return _response(
            _live([_INPUT])
            if url.endswith("/live")
            else _history([{**_INPUT, "body": "different input"}])
        )

    monkeypatch.setattr(scenarios.requests, "get", get)

    with pytest.raises(AssertionError, match="projections disagree"):
        _read_evidence()


def test_single_history_input_waits_for_durable_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binding existence must not substitute for history promotion."""
    reads = 0

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int],
    ) -> requests.Response:
        nonlocal reads
        del headers, timeout
        assert url.endswith("/history")
        assert params == {"limit": 100}
        reads += 1
        return _response(_history([] if reads == 1 else [_INPUT]))

    def wait(
        condition: Callable[[], list[dict[str, object]]],
        *,
        timeout: float,
        interval: float,
        message: str,
    ) -> list[dict[str, object]]:
        del timeout, interval, message
        assert condition() == []
        result = condition()
        assert len(result) == 1
        return result

    monkeypatch.setattr(scenarios.requests, "get", get)
    monkeypatch.setattr(scenarios, "wait_until", wait)

    evidence = scenarios._wait_for_single_external_channel_history_input(
        public_server_url=_PUBLIC_URL,
        token="synthetic-token",
        session_id=_SESSION_ID,
    )

    assert reads == 2
    assert evidence["external_message_id"] == _INPUT["external_message_id"]


def test_single_history_input_rejects_extra_logical_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readiness wait cannot filter out a real cardinality regression."""

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        params: dict[str, str | int],
    ) -> requests.Response:
        del headers, timeout
        assert url.endswith("/history")
        assert params == {"limit": 100}
        return _response(
            _history([_INPUT, {**_INPUT, "external_message_id": "different-message"}])
        )

    monkeypatch.setattr(scenarios.requests, "get", get)

    with pytest.raises(AssertionError, match="observed 2"):
        scenarios._wait_for_single_external_channel_history_input(
            public_server_url=_PUBLIC_URL,
            token="synthetic-token",
            session_id=_SESSION_ID,
        )
