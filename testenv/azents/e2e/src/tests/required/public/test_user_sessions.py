"""User Session public API E2E tests."""

from __future__ import annotations

from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import requests
from pydantic import TypeAdapter, ValidationError

from support.utils import (
    create_chat_session_with_agent,
    create_two_member_team_session,
    unique,
)

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _UserSessionSetup:
    """Two-member workspace with one owner-created User Session."""

    owner_token: str
    member_token: str
    agent_id: str
    user_session_id: str
    team_primary_session_id: str


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth headers."""
    return {"Authorization": f"Bearer {token}"}


def _response_object(
    response: requests.Response,
    *,
    label: str,
) -> dict[str, object]:
    """Validate a JSON object response."""
    try:
        return _JSON_OBJECT.validate_json(response.text)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {response.text!r}") from exc


def _object_items(raw_items: object, *, label: str) -> list[dict[str, object]]:
    """Validate a JSON object list."""
    try:
        return _JSON_OBJECT_LIST.validate_python(raw_items)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {raw_items!r}") from exc


def _get_json(
    *,
    server_url: str,
    token: str,
    path: str,
    expected_status: int = 200,
) -> dict[str, object] | None:
    """Call a public GET endpoint and optionally return a JSON object."""
    response = requests.get(
        f"{server_url}{path}",
        headers=_headers(token),
        timeout=10,
    )
    if response.status_code != expected_status:
        raise AssertionError(
            f"GET {path} expected {expected_status}, got {response.status_code}: "
            f"{response.text!r}"
        )
    if expected_status >= 400:
        return None
    return _response_object(response, label=f"GET {path} response")


def _post_json(
    *,
    server_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
    expected_status: int = 200,
) -> dict[str, object] | None:
    """Call a public POST endpoint and optionally return a JSON object."""
    response = requests.post(
        f"{server_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    if response.status_code != expected_status:
        raise AssertionError(
            f"POST {path} expected {expected_status}, got {response.status_code}: "
            f"{response.text!r}"
        )
    if expected_status >= 400:
        return None
    return _response_object(response, label=f"POST {path} response")


def _team_session_items(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> list[dict[str, object]]:
    """Fetch Team Session list items."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
    )
    assert payload is not None
    return _object_items(payload.get("items"), label="team session list items")


def _user_session_items(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> list[dict[str, object]]:
    """Fetch requester-owned User Session list items."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/user-sessions",
    )
    assert payload is not None
    return _object_items(payload.get("items"), label="user session list items")


def _write_user_first_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """Create a User Session with its first message."""
    payload = _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/user-sessions/messages",
        payload={
            "client_request_id": client_request_id,
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
            "existing_project_paths": [],
            "setup_actions": [],
        },
    )
    assert payload is not None
    return payload


def _setup_owner_user_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _UserSessionSetup:
    """Create a two-member workspace and one owner User Session."""
    setup = create_two_member_team_session(
        public_api_client,
        admin_api_client,
        server_url,
    )
    response = _write_user_first_message(
        server_url=server_url,
        token=setup.owner_access_token,
        agent_id=setup.agent_id,
        message=f"Owner private session {unique()}",
        client_request_id=f"user-session-owner-{unique()}",
    )
    user_session_id = response.get("session_id")
    if not isinstance(user_session_id, str):
        raise AssertionError(
            f"User first-message response missing session_id: {response!r}"
        )
    return _UserSessionSetup(
        owner_token=setup.owner_access_token,
        member_token=setup.member_access_token,
        agent_id=setup.agent_id,
        user_session_id=user_session_id,
        team_primary_session_id=setup.session_id,
    )


def test_owner_can_create_two_user_sessions_isolated_from_team_list(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Owner User Sessions appear only in the User list and never as primary."""
    token, primary_session_id, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    first_message = f"First private session {unique()}"
    second_message = f"Second private session {unique()}"

    first = _write_user_first_message(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        message=first_message,
        client_request_id=f"user-session-first-{unique()}",
    )
    second = _write_user_first_message(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        message=second_message,
        client_request_id=f"user-session-second-{unique()}",
    )
    first_id = first.get("session_id")
    second_id = second.get("session_id")
    if not isinstance(first_id, str) or not isinstance(second_id, str):
        raise AssertionError(f"Missing session ids: {first!r} {second!r}")
    assert first_id != second_id
    assert first_id != primary_session_id
    assert second_id != primary_session_id

    user_items = _user_session_items(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    user_ids = {item.get("id") for item in user_items}
    assert first_id in user_ids
    assert second_id in user_ids
    assert all(item.get("primary_kind") is None for item in user_items)

    team_items = _team_session_items(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    team_ids = {item.get("id") for item in team_items}
    assert primary_session_id in team_ids
    assert first_id not in team_ids
    assert second_id not in team_ids


def test_non_owner_member_cannot_discover_or_open_user_session(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Non-owner Workspace members receive not-found-safe denials."""
    setup = _setup_owner_user_session(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )

    member_user_items = _user_session_items(
        server_url=azents_public_server_url,
        token=setup.member_token,
        agent_id=setup.agent_id,
    )
    assert all(item.get("id") != setup.user_session_id for item in member_user_items)

    member_team_items = _team_session_items(
        server_url=azents_public_server_url,
        token=setup.member_token,
        agent_id=setup.agent_id,
    )
    assert all(item.get("id") != setup.user_session_id for item in member_team_items)
    assert any(
        item.get("id") == setup.team_primary_session_id for item in member_team_items
    )

    _get_json(
        server_url=azents_public_server_url,
        token=setup.member_token,
        path=(f"/chat/v1/agents/{setup.agent_id}/sessions/{setup.user_session_id}"),
        expected_status=404,
    )
    _post_json(
        server_url=azents_public_server_url,
        token=setup.member_token,
        path=f"/chat/v1/sessions/{setup.user_session_id}/inputs",
        payload={
            "agent_id": setup.agent_id,
            "client_request_id": f"user-session-denied-{unique()}",
            "message": f"Denied write {unique()}",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        expected_status=404,
    )
    _get_json(
        server_url=azents_public_server_url,
        token=setup.member_token,
        path=f"/chat/v1/sessions/{setup.user_session_id}/live",
        expected_status=404,
    )
    _get_json(
        server_url=azents_public_server_url,
        token=setup.member_token,
        path=f"/chat/v1/sessions/{setup.user_session_id}/history?limit=20",
        expected_status=404,
    )


def test_team_first_message_path_remains_on_team_list(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Existing Team first-message creation remains Team-list visible."""
    token, primary_session_id, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    message = f"Team first message remains team {unique()}"
    response = _post_json(
        server_url=azents_public_server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions/messages",
        payload={
            "client_request_id": f"team-session-control-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
            "existing_project_paths": [],
            "setup_actions": [],
        },
    )
    assert response is not None
    created_session_id = response.get("session_id")
    if not isinstance(created_session_id, str):
        raise AssertionError(f"Team write missing session_id: {response!r}")
    assert created_session_id != primary_session_id

    team_ids = {
        item.get("id")
        for item in _team_session_items(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
    }
    user_ids = {
        item.get("id")
        for item in _user_session_items(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
    }
    assert created_session_id in team_ids
    assert created_session_id not in user_ids
