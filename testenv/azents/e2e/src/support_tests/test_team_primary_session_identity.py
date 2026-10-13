"""Listener-free primary Session identity ingress and helper integration tests."""

import json
import traceback
from collections.abc import Mapping
from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.models.agent_session_response import AgentSessionResponse

from support import utils


def _response(payload: object, *, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = json.dumps(payload).encode()
    return response


def _producer_payload() -> dict[str, object]:
    """Use the current schema-derived Session producer shape, including nulls."""
    session = AgentSessionResponse(
        id="session-id",
        agent_id="agent-id",
        current_model_target_label=None,
        current_reasoning_effort=None,
        current_enabled_execution_options=[],
        title=None,
        title_source=None,
        status="active",
        primary_kind="team_primary",
        product_mode=None,
        run_state="idle",
        pinned=False,
        unread_terminal_run_id=None,
        auto_archive_after=None,
        archived_at=None,
        purge_after=None,
        archive_retention_days_snapshot=None,
        created_at="2026-10-14T00:00:00Z",
        updated_at="2026-10-14T00:00:00Z",
    )
    return session.model_dump(mode="json")


@pytest.mark.parametrize("identity", ["session-id", ""])
def test_identity_projection_preserves_current_string_contract(
    identity: str,
) -> None:
    payload = _producer_payload()
    payload["id"] = identity
    payload["future_extension"] = {"private": "synthetic-private-value"}
    decoded = utils._decode_team_primary_session_response(_response(payload))
    assert decoded.id == identity
    assert decoded.model_dump() == {"id": identity}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        False,
        0,
        "",
        [],
        {},
        {"id": None},
        {"id": False},
        {"id": 0},
        {"id": 1.0},
        {"id": []},
        {"id": {}},
    ],
)
def test_primary_identity_rejects_missing_or_malformed_owned_fields(
    payload: object,
) -> None:
    with pytest.raises(RuntimeError, match="did not include a valid id"):
        utils._decode_team_primary_session_response(_response(payload))


def test_primary_identity_validation_diagnostics_do_not_expose_private_values() -> None:
    response = _response(
        {"id": {"credential": "synthetic-private-value"}, "secret": "hidden-value"}
    )
    with pytest.raises(RuntimeError) as failure:
        utils._decode_team_primary_session_response(response)
    diagnostic = "".join(traceback.format_exception(failure.value))
    assert "synthetic-private-value" not in diagnostic
    assert "hidden-value" not in diagnostic


def test_primary_identity_json_error_is_redacted() -> None:
    response = _response(None)
    response._content = b'synthetic-private-value {"id":'
    with pytest.raises(RuntimeError, match="not valid JSON") as failure:
        utils._decode_team_primary_session_response(response)
    assert "synthetic-private-value" not in "".join(
        traceback.format_exception(failure.value)
    )


def test_primary_identity_keeps_http_failures_visible() -> None:
    with pytest.raises(requests.HTTPError):
        utils._decode_team_primary_session_response(
            _response({"id": "session-id"}, status=503)
        )


@dataclass(frozen=True)
class _Call:
    method: str
    url: str
    headers: Mapping[str, str]
    payload: object
    timeout: int


def test_session_setup_uses_decoded_identity_for_actual_input_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the real helper with no transport or Runtime initialization."""
    calls: list[_Call] = []
    setup = utils.AgentSetup("token", "user@example.com", "workspace", "agent-id")

    def create_setup(
        public: azentspublicclient.ApiClient,
        admin: azentsadminclient.ApiClient,
        server_url: str,
    ) -> utils.AgentSetup:
        return setup

    def start_runtime(
        public: azentspublicclient.ApiClient,
        *,
        token: str,
        workspace_handle: str,
        agent_id: str,
    ) -> None:
        assert (token, workspace_handle, agent_id) == (
            setup.access_token,
            setup.workspace_handle,
            setup.agent_id,
        )

    def get(
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: int,
    ) -> requests.Response:
        calls.append(_Call("GET", url, headers, None, timeout))
        return _response(_producer_payload())

    def post(
        url: str,
        *,
        headers: Mapping[str, str],
        json: object,
        timeout: int,
    ) -> requests.Response:
        calls.append(_Call("POST", url, headers, json, timeout))
        return _response({"accepted": True})

    monkeypatch.setattr(utils, "create_agent_setup", create_setup)
    monkeypatch.setattr(utils, "start_and_wait_for_agent_runtime", start_runtime)
    monkeypatch.setattr(utils.http_requests, "get", get)
    monkeypatch.setattr(utils.http_requests, "post", post)
    with (
        azentspublicclient.ApiClient() as public,
        azentsadminclient.ApiClient() as admin,
    ):
        result = utils.create_agent_session_setup(public, admin, "https://api.invalid")
    assert result.session_id == "session-id"
    assert [call.url for call in calls] == [
        "https://api.invalid/chat/v1/agents/agent-id/team-primary-session",
        "https://api.invalid/chat/v1/sessions/session-id/inputs",
    ]
    assert calls[0].headers == {"Authorization": "Bearer token"}
    assert calls[1].headers == {
        "Authorization": "Bearer token",
        "Content-Type": "application/json",
    }
    assert calls[0].timeout == calls[1].timeout == 10
    assert isinstance(calls[1].payload, dict)
    assert calls[1].payload["agent_id"] == "agent-id"
    assert calls[1].payload["message"] == "init"
    assert calls[1].payload["inference_profile"] == {
        "model_target_label": "default",
        "reasoning_effort": None,
        "enabled_execution_options": [],
    }
