"""Pure contracts for the Slack fake's transient-view absence and handoff wire."""

import json
from collections.abc import Mapping
from typing import NamedTuple

import pytest
import requests
from pydantic import ValidationError

from support import slack_provider_fake
from tests.required.public import external_channel_scenarios as scenarios


class _Reply(NamedTuple):
    status: int
    payload: dict[str, object]


class _CaptureHandler(slack_provider_fake.SlackHTTPHandler):
    """Exercise the actual GET route without initializing a socket handler."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.reply: _Reply | None = None

    def _json_response(
        self,
        status: int,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.reply = _Reply(status, dict(payload))


class _Request(NamedTuple):
    url: str
    scope: str
    timeout: int


def _response(payload: object, *, status: int = 200) -> requests.Response:
    """Provide real response decoding/status handling without transport I/O."""
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = json.dumps(payload).encode()
    return response


@pytest.mark.parametrize(
    ("scope", "callback_id"),
    [("setup", "azents_conversation_setup"), ("selector", "azents_agent_selector")],
)
def test_actual_producer_absence_and_private_handoff_stay_separate(
    monkeypatch: pytest.MonkeyPatch, scope: str, callback_id: str
) -> None:
    state = slack_provider_fake.FakeState()
    monkeypatch.setattr(slack_provider_fake.SlackHTTPHandler, "state", state)
    assert state.transient_view(scope) is None
    absent = _CaptureHandler(f"/__testenv/transient-view?scope={scope}")
    absent.do_GET()
    assert absent.reply is not None
    assert absent.reply == _Reply(200, {})
    assert scenarios._decode_transient_view(absent.reply.payload) is None

    private_metadata = "synthetic-secret-handoff"
    recorded = state.record_view(
        operation="views.open",
        requested_view_id=None,
        callback_id=callback_id,
        private_metadata=private_metadata,
        route_ids=["route-1"],
        has_submit=True,
        control_handoff={},
    )
    ready = _CaptureHandler(f"/__testenv/transient-view?scope={scope}")
    ready.do_GET()
    assert ready.reply is not None and ready.reply.status == 200
    decoded = scenarios._decode_transient_view(ready.reply.payload)
    assert decoded is not None
    assert decoded.private_metadata == private_metadata
    assert decoded.view_id == recorded.view_id
    assert decoded.route_ids == ["route-1"]
    public_evidence = json.dumps(state.evidence(), sort_keys=True)
    assert private_metadata not in public_evidence
    assert "private_metadata" not in public_evidence
    assert "view_id" not in public_evidence
    assert "view_hash" not in public_evidence


@pytest.mark.parametrize("scope", ["setup", "selector"])
@pytest.mark.parametrize("absent", [None, {}], ids=["wire-null", "wire-empty-object"])
def test_actual_helpers_poll_absence_then_decode_ready_view(
    monkeypatch: pytest.MonkeyPatch, scope: str, absent: object
) -> None:
    payload = {
        "private_metadata": "synthetic-signed-handoff",
        "view_id": "V-test",
        "view_hash": "hash-test",
        "route_ids": ["route-test"],
        "future_extension": {"preserved": True},
    }
    responses = [_response(absent), _response(payload)]
    calls: list[_Request] = []

    def get(url: str, *, params: dict[str, str], timeout: int) -> requests.Response:
        calls.append(_Request(url, params["scope"], timeout))
        return responses.pop(0)

    monkeypatch.setattr(scenarios.requests, "get", get)
    helper = (
        scenarios._latest_setup_view
        if scope == "setup"
        else scenarios._latest_selector_view
    )
    assert helper("https://provider.example.invalid") is None
    decoded = helper("https://provider.example.invalid")
    assert decoded is not None
    assert decoded.private_metadata == payload["private_metadata"]
    assert decoded.model_dump()["future_extension"] == {"preserved": True}
    assert calls == [
        _Request("https://provider.example.invalid/__testenv/transient-view", scope, 5),
        _Request("https://provider.example.invalid/__testenv/transient-view", scope, 5),
    ]


@pytest.mark.parametrize("scope", ["setup", "selector"])
@pytest.mark.parametrize(
    "malformed",
    [
        False,
        0,
        0.0,
        "",
        [],
        ["view"],
        "opaque",
        {"view_id": "V-test"},
        {"future_extension": None},
        {"private_metadata": None},
        {"private_metadata": 1},
        {"private_metadata": False},
        {"private_metadata": []},
        {"private_metadata": {}},
        {"private_metadata": "signed", "view_id": 1},
        {"private_metadata": "signed", "route_ids": [1]},
    ],
)
def test_nonempty_or_nonobject_malformed_wire_is_not_absence(
    monkeypatch: pytest.MonkeyPatch, scope: str, malformed: object
) -> None:
    def get(url: str, *, params: dict[str, str], timeout: int) -> requests.Response:
        return _response(malformed)

    monkeypatch.setattr(scenarios.requests, "get", get)
    helper = (
        scenarios._latest_setup_view
        if scope == "setup"
        else scenarios._latest_selector_view
    )
    with pytest.raises(ValidationError):
        helper("https://provider.example.invalid")


@pytest.mark.parametrize("scope", ["setup", "selector"])
def test_http_failure_does_not_become_not_ready(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    def get(url: str, *, params: dict[str, str], timeout: int) -> requests.Response:
        return _response({}, status=500)

    monkeypatch.setattr(scenarios.requests, "get", get)
    helper = (
        scenarios._latest_setup_view
        if scope == "setup"
        else scenarios._latest_selector_view
    )
    with pytest.raises(requests.HTTPError):
        helper("https://provider.example.invalid")


def test_metadata_stays_required_while_nullable_view_identity_is_preserved() -> None:
    with pytest.raises(ValidationError):
        scenarios._TransientView.model_validate({})
    ready = scenarios._decode_transient_view(
        {"private_metadata": "signed", "view_id": None, "view_hash": None}
    )
    assert ready is not None
    assert ready.private_metadata == "signed"
    assert ready.view_id is None and ready.view_hash is None
