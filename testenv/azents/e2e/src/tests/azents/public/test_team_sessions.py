"""Team session public API E2E tests."""

from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import requests
from pydantic import TypeAdapter, ValidationError

from support.utils import create_chat_session_with_agent, unique

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _TeamSessionSetup:
    """Created team session E2E state."""

    token: str
    primary_session_id: str
    secondary_session_id: str
    agent_id: str


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


def _response_payload(raw_payload: object) -> dict[str, object]:
    """Validate an event payload JSON object."""
    try:
        return _JSON_OBJECT.validate_python(raw_payload)
    except ValidationError as exc:
        raise AssertionError(
            f"Event payload is not an object: {raw_payload!r}"
        ) from exc


def _get_json(
    *,
    server_url: str,
    token: str,
    path: str,
) -> dict[str, object]:
    """Call a public GET endpoint and return a JSON object."""
    response = requests.get(
        f"{server_url}{path}",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label=f"GET {path} response")


def _post_json(
    *,
    server_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Call a public POST endpoint and return a JSON object."""
    response = requests.post(
        f"{server_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label=f"POST {path} response")


def _session_items(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> list[dict[str, object]]:
    """Fetch agent-scoped session list items."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
    )
    return _object_items(payload.get("items"), label="session list items")


def _create_secondary_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create a non-primary team session through the product API."""
    payload = _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
        payload={},
    )
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Create session response did not include id: {payload!r}")
    if payload.get("primary_kind") is not None:
        raise AssertionError(f"Created session must be non-primary: {payload!r}")
    return session_id


def _write_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """Write a message to an explicit session."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/messages",
        payload={
            "agent_id": agent_id,
            "client_request_id": client_request_id,
            "message": message,
        },
    )


def _write_first_session_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> dict[str, object]:
    """Create a non-primary session with its first message."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions/messages",
        payload={
            "client_request_id": client_request_id,
            "message": message,
        },
    )


def _event_contents(events: list[dict[str, object]]) -> list[str]:
    """Return event payload contents."""
    contents: list[str] = []
    for event in events:
        raw_payload = event.get("payload")
        event_payload = _response_payload(raw_payload)
        content = event_payload.get("content")
        if isinstance(content, str):
            contents.append(content)
    return contents


def _snapshot_input_contents(write_response: dict[str, object]) -> list[str]:
    """Return input contents from the write response snapshot."""
    snapshot = _response_payload(write_response.get("snapshot"))
    events = _object_items(snapshot.get("input_buffer_events"), label="snapshot inputs")
    return _event_contents(events)


def _live_input_contents(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> list[str]:
    """Return pending live input contents for a session."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/live",
    )
    events = _object_items(payload.get("input_buffers"), label="live inputs")
    return _event_contents(events)


def _setup_team_sessions(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_url: str,
) -> _TeamSessionSetup:
    """Create an agent with primary and secondary team sessions."""
    token, primary_session_id, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        public_url,
    )
    secondary_session_id = _create_secondary_session(
        server_url=public_url,
        token=token,
        agent_id=agent_id,
    )
    return _TeamSessionSetup(
        token=token,
        primary_session_id=primary_session_id,
        secondary_session_id=secondary_session_id,
        agent_id=agent_id,
    )


def test_agent_scoped_team_session_list_has_primary_first(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Agent session list exposes primary first and non-primary metadata."""
    setup = _setup_team_sessions(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        public_url=azents_public_server_url,
    )

    items = _session_items(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
    )

    assert len(items) >= 2
    assert items[0].get("id") == setup.primary_session_id
    assert items[0].get("primary_kind") == "team_primary"
    assert items[1].get("id") == setup.secondary_session_id
    assert items[1].get("primary_kind") is None
    assert all(item.get("agent_id") == setup.agent_id for item in items)


def test_first_message_creates_non_primary_team_session(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """First-message session creation avoids a pre-created empty session."""
    token, primary_session_id, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    before_items = _session_items(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    message = f"First draft team session message {unique()}"

    response = _write_first_session_message(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        message=message,
        client_request_id=f"team-session-first-message-{unique()}",
    )

    created_session_id = response.get("session_id")
    if not isinstance(created_session_id, str):
        raise AssertionError(f"Write response did not include session_id: {response!r}")
    assert created_session_id != primary_session_id
    assert message in _snapshot_input_contents(response)

    after_items = _session_items(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    before_ids = {item.get("id") for item in before_items}
    created_items = [
        item for item in after_items if item.get("id") == created_session_id
    ]
    assert len(created_items) == 1
    assert created_session_id not in before_ids
    assert created_items[0].get("primary_kind") is None
    assert created_items[0].get("agent_id") == agent_id


def test_secondary_team_session_write_is_session_isolated(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Writing to a non-primary team session does not target primary live state."""
    setup = _setup_team_sessions(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        public_url=azents_public_server_url,
    )
    message = f"Secondary team session message {unique()}"

    response = _write_message(
        server_url=azents_public_server_url,
        token=setup.token,
        session_id=setup.secondary_session_id,
        agent_id=setup.agent_id,
        message=message,
        client_request_id=f"team-session-e2e-{unique()}",
    )

    assert response.get("session_id") == setup.secondary_session_id
    assert message in _snapshot_input_contents(response)
    assert message not in _live_input_contents(
        server_url=azents_public_server_url,
        token=setup.token,
        session_id=setup.primary_session_id,
    )
