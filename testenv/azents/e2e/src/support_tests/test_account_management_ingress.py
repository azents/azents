"""Listener-free current account-management response and storage ingress tests."""

import json
import traceback
from unittest.mock import Mock

import pytest
import requests

from tests.required.public import test_github_setup_wizard as wizard
from tests.required.public import test_github_user_toolkit as github
from tests.required.public import test_user_sessions as sessions
from tests.web.public import test_github_user_toolkit as browser


def _response(payload: object, *, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = json.dumps(payload).encode()
    return response


def _candidate() -> dict[str, object]:
    return {
        "attempt_id": "attempt-1",
        "account_id": 1,
        "account_login": "connected-user",
        "account_avatar_url": None,
        "app_id": "123",
        "source": "byoa_user",
        "sharing_scope": "workspace_shared",
    }


def test_generated_connect_and_candidate_contracts_keep_wire_extensions() -> None:
    payload = {
        "attempt_id": "attempt-1",
        "authorization_url": "https://github.invalid/oauth?state=state-1",
        "install_url": "https://github.invalid/install",
        "extension": {"opaque": [None, 3]},
    }
    result = github._response(_response(payload), github._Connect, label="connect")
    assert result.authorization_url == payload["authorization_url"]
    assert result.model_dump(exclude_unset=True) == payload
    candidate = github._decode(_candidate(), github._Candidate, label="candidate")
    assert candidate.account_login == "connected-user"
    assert candidate.account_avatar_url is None


@pytest.mark.parametrize("invalid", [None, False, 1, [], {}])
def test_generated_candidate_identity_rejects_coercion_without_private_diagnostics(
    invalid: object,
) -> None:
    payload = {**_candidate(), "attempt_id": invalid, "secret": "PRIVATE-OAUTH"}
    with pytest.raises(AssertionError) as failure:
        github._response(_response(payload), github._Candidate, label="candidate")
    assert "PRIVATE-OAUTH" not in "".join(traceback.format_exception(failure.value))


@pytest.mark.parametrize("phase", ["AUTHORIZING", "REVIEW", "ERROR"])
@pytest.mark.parametrize("agent_id", [None, "agent-1"])
def test_creation_storage_matches_current_typescript_producer(
    phase: str,
    agent_id: str | None,
) -> None:
    payload: dict[str, object] = {
        "handle": "workspace",
        "attemptId": "attempt-1",
        "phase": phase,
        "returnPath": "/w/workspace/toolkits/new",
    }
    if agent_id is not None:
        payload["agentId"] = agent_id
        payload["returnPath"] = (
            "/w/workspace/agents/agent-1/settings/capabilities#agent-toolkits"
        )
    result = browser._creation_context(json.dumps(payload))
    assert result.attempt_id == "attempt-1"
    assert result.agent_id == agent_id
    assert result.model_dump(by_alias=True, exclude_unset=True) == payload


@pytest.mark.parametrize(
    "patch",
    [
        {"agentId": None},
        {"agentId": 1},
        {"attemptId": True},
        {"attemptId": "invalid.attempt"},
        {"phase": "UNKNOWN"},
        {"returnPath": "/w/other/toolkits/new"},
        {"handle": ""},
        {"future": "PRIVATE"},
    ],
)
def test_creation_storage_rejects_invalid_owned_fields_and_unknown_extensions(
    patch: dict[str, object],
) -> None:
    payload = {
        "handle": "workspace",
        "attemptId": "attempt-1",
        "phase": "REVIEW",
        "returnPath": "/w/workspace/toolkits/new",
        **patch,
    }
    with pytest.raises(AssertionError) as failure:
        browser._creation_context(json.dumps(payload))
    assert "PRIVATE" not in "".join(traceback.format_exception(failure.value))


@pytest.mark.parametrize("payload", [{}, {"session_id": None}, {"session_id": 1}])
def test_created_session_requires_current_identity(payload: object) -> None:
    with pytest.raises(AssertionError):
        sessions._response_model(
            _response(payload), sessions._CreatedSession, label="create"
        )


def test_session_page_and_create_operation_drive_typed_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sessions.requests,
        "get",
        Mock(
            return_value=_response(
                {
                    "items": [{"id": "private", "primary_kind": None, "future": [1]}],
                    "next_cursor": None,
                }
            )
        ),
    )
    page = sessions._user_session_items(
        server_url="https://invalid", token="token", agent_id="agent"
    )
    assert page[0].id == "private"
    assert page[0].primary_kind is None
    monkeypatch.setattr(
        sessions.requests,
        "post",
        Mock(
            return_value=_response(
                {
                    "session_id": "private",
                    "future": {"opaque": True},
                }
            )
        ),
    )
    created = sessions._write_user_first_message(
        server_url="https://invalid",
        token="token",
        agent_id="agent",
        message="current input",
        client_request_id="request",
    )
    assert created.session_id == "private"
    assert created.model_dump(exclude_unset=True)["future"] == {"opaque": True}


def test_status_null_and_literal_wire_equality_remain_visible() -> None:
    result = github._response(
        _response({"connection": None}), github._Status, label="status"
    )
    assert result.connection is None
    assert result.model_dump(exclude_unset=True) == {"connection": None}


def test_session_identity_keeps_plain_string_and_optional_primary_contract() -> None:
    created = sessions._response_model(
        _response({"session_id": ""}), sessions._CreatedSession, label="create"
    )
    assert created.session_id == ""
    page = sessions._response_model(
        _response({"items": [{"id": ""}]}), sessions._SessionPage, label="list"
    )
    assert page.items[0].id == ""
    assert page.items[0].primary_kind is None


def test_operation_http_decode_uses_declared_connect_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = Mock(
        return_value=_response(
            {
                "attempt_id": "attempt-1",
                "authorization_url": "https://github.invalid/authorize",
                "install_url": "https://github.invalid/install",
            }
        )
    )
    monkeypatch.setattr(github.requests, "post", post)
    result = github._operation(
        "https://api.invalid/github-user",
        "token",
        "connect",
        body=None,
        model=github._Connect,
    )
    assert result.attempt_id == "attempt-1"
    assert post.call_args.kwargs["json"] is None
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
    assert post.call_args.kwargs["timeout"] == 15


def test_setup_verification_decodes_discriminated_identity_and_opaque_extensions() -> (
    None
):
    payload = {
        "identity": {"type": "app", "app_id": "123", "name": "App", "slug": "app"},
        "installations": [
            {"installation_id": "501", "account_login": None, "status": "denied"}
        ],
        "connectivity": {"status": "ready", "message": None},
        "provider_extension": {"opaque": True},
    }
    result = github._decode(payload, wizard._Verification, label="verification")
    assert isinstance(result.identity, wizard._AppIdentity)
    assert result.identity.app_id == "123"
    assert result.installations[0].account_login is None
    assert result.model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize(
    "payload", [None, {"identity": {"type": "unknown"}}, {"items": [1]}]
)
def test_invalid_operation_shapes_fail_at_ingress(payload: object) -> None:
    with pytest.raises(AssertionError):
        github._decode(payload, wizard._Verification, label="verification")


def test_json_and_http_errors_stay_redacted_or_visible() -> None:
    response = _response({})
    response._content = b'PRIVATE {"id":'
    with pytest.raises(AssertionError) as failure:
        github._response(response, github._Status, label="status")
    assert "PRIVATE" not in "".join(traceback.format_exception(failure.value))
    with pytest.raises(requests.HTTPError):
        github._response(_response({}, status=503), github._Status, label="status")


def test_unpublished_config_omissions_keep_existing_bag_of_options_defaults() -> None:
    config = github._decode({}, github._GitHubConfig, label="settings")
    assert config.timeout == 30
    assert config.inject_runtime_environment is False
    assert config.toolsets == ["repos", "issues", "pull_requests", "users"]
    with pytest.raises(AssertionError):
        github._decode(
            {"inject_runtime_environment": "true"},
            github._GitHubConfig,
            label="settings",
        )
