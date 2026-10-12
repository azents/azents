"""Team session public API E2E tests."""

from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from pydantic import JsonValue, StrictStr, TypeAdapter, ValidationError

from support.observations import (
    ExtensionObservation,
    InputMessageObservation,
    MailboxObservation,
    decode_history_page,
)
from support.utils import (
    create_agent_setup,
    create_chat_session_with_agent,
    create_two_member_team_session,
    unique,
    wait_until,
)

_JSON_OBJECT = TypeAdapter(dict[str, object])


class _SessionList(ExtensionObservation):
    items: list[AgentSessionResponse]


class _UserMessage(InputMessageObservation):
    content: StrictStr | list[dict[str, JsonValue]]
    sender_user_id: StrictStr | None = None


class _Snapshot(ExtensionObservation):
    mailbox_items: list[MailboxObservation]


class _Write(ExtensionObservation):
    session_id: StrictStr
    snapshot: _Snapshot


class _Live(ExtensionObservation):
    mailbox_items: list[MailboxObservation]


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
) -> list[AgentSessionResponse]:
    """Fetch agent-scoped session list items."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
    )
    return _SessionList.model_validate(payload).items


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
        payload={"existing_project_paths": [], "setup_actions": []},
    )
    session = AgentSessionResponse.model_validate(payload)
    if session.primary_kind is not None:
        raise AssertionError(f"Created session must be non-primary: {payload!r}")
    return session.id


def _write_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> _Write:
    """Write a message to an explicit session."""
    return _Write.model_validate(
        _post_json(
            server_url=server_url,
            token=token,
            path=f"/chat/v1/sessions/{session_id}/inputs",
            payload={
                "agent_id": agent_id,
                "client_request_id": client_request_id,
                "message": message,
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
        )
    )


def _write_first_session_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    message: str,
    client_request_id: str,
) -> _Write:
    """Create a non-primary session with its first message."""
    return _Write.model_validate(
        _post_json(
            server_url=server_url,
            token=token,
            path=f"/chat/v1/agents/{agent_id}/sessions/messages",
            payload={
                "client_request_id": client_request_id,
                "message": message,
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
                "existing_project_paths": [],
                "setup_actions": [],
            },
        )
    )


def _mailbox_item_contents(
    raw_items: list[MailboxObservation], *, label: str
) -> list[str]:
    """Return content strings from pending mailbox item presentations."""
    contents: list[str] = []
    for envelope in raw_items:
        for item in envelope.items:
            presentation = item.presentation
            if presentation.type != "user_message":
                continue
            if isinstance(presentation.content, str):
                contents.append(presentation.content)
    return contents


def _snapshot_input_contents(write_response: _Write) -> list[str]:
    """Return input contents from the write response snapshot."""
    snapshot = write_response.snapshot
    return _mailbox_item_contents(
        snapshot.mailbox_items,
        label="snapshot mailbox items",
    )


def _history_user_message_payload(
    *,
    server_url: str,
    token: str,
    session_id: str,
    content: str,
) -> _UserMessage:
    """Return one durable UserMessage payload from Session history."""
    history = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/history?limit=100",
    )
    for event in decode_history_page(history).items:
        if event.kind != "user_message":
            continue
        payload = _UserMessage.model_validate(event.payload)
        if payload.content == content:
            return payload
    raise AssertionError(f"History did not include UserMessage: {content!r}")


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
    return _mailbox_item_contents(
        _Live.model_validate(payload).mailbox_items,
        label="live mailbox items",
    )


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
    agent = create_agent_setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    primary_session = _get_json(
        server_url=azents_public_server_url,
        token=agent.access_token,
        path=f"/chat/v1/agents/{agent.agent_id}/team-primary-session",
    )
    primary_session_id = AgentSessionResponse.model_validate(primary_session).id
    if not isinstance(primary_session_id, str):
        raise AssertionError(
            f"Team primary session response did not include id: {primary_session!r}"
        )
    secondary_session_id = _create_secondary_session(
        server_url=azents_public_server_url,
        token=agent.access_token,
        agent_id=agent.agent_id,
    )
    setup = _TeamSessionSetup(
        token=agent.access_token,
        primary_session_id=primary_session_id,
        secondary_session_id=secondary_session_id,
        agent_id=agent.agent_id,
    )

    items = _session_items(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
    )

    assert len(items) >= 2
    assert items[0].id == setup.primary_session_id
    assert items[0].primary_kind == "team_primary"
    assert items[1].id == setup.secondary_session_id
    assert items[1].primary_kind is None
    assert all(item.agent_id == setup.agent_id for item in items)


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

    created_session_id = response.session_id
    if not isinstance(created_session_id, str):
        raise AssertionError(f"Write response did not include session_id: {response!r}")
    assert created_session_id != primary_session_id
    assert message in _snapshot_input_contents(response)

    after_items = _session_items(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    before_ids = {item.id for item in before_items}
    created_items = [item for item in after_items if item.id == created_session_id]
    assert len(created_items) == 1
    assert created_session_id not in before_ids
    assert created_items[0].primary_kind is None
    assert created_items[0].agent_id == agent_id


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

    assert response.session_id == setup.secondary_session_id
    assert message in _snapshot_input_contents(response)
    assert message not in _live_input_contents(
        server_url=azents_public_server_url,
        token=setup.token,
        session_id=setup.primary_session_id,
    )


def test_two_members_retain_independent_sender_provenance_in_one_team_session(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Two members write to one Team Session without sharing sender identity."""
    setup = create_two_member_team_session(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    owner_message = f"Owner Team Session message {unique()}"
    member_message = f"Member Team Session message {unique()}"

    owner_write = _write_message(
        server_url=azents_public_server_url,
        token=setup.owner_access_token,
        session_id=setup.session_id,
        agent_id=setup.agent_id,
        message=owner_message,
        client_request_id=f"team-session-owner-{unique()}",
    )
    member_write = _write_message(
        server_url=azents_public_server_url,
        token=setup.member_access_token,
        session_id=setup.session_id,
        agent_id=setup.agent_id,
        message=member_message,
        client_request_id=f"team-session-member-{unique()}",
    )

    assert owner_write.session_id == setup.session_id
    assert member_write.session_id == setup.session_id
    owner_payload = wait_until(
        lambda: _history_user_message_payload(
            server_url=azents_public_server_url,
            token=setup.owner_access_token,
            session_id=setup.session_id,
            content=owner_message,
        ),
        timeout=30,
        interval=0.2,
        message="Owner message did not reach durable history",
    )
    member_payload = wait_until(
        lambda: _history_user_message_payload(
            server_url=azents_public_server_url,
            token=setup.owner_access_token,
            session_id=setup.session_id,
            content=member_message,
        ),
        timeout=30,
        interval=0.2,
        message="Member message did not reach durable history",
    )
    assert owner_payload.sender_user_id == setup.owner_user_id
    assert member_payload.sender_user_id == setup.member_user_id
    assert owner_payload.sender_user_id != member_payload.sender_user_id

    member_sessions = _session_items(
        server_url=azents_public_server_url,
        token=setup.member_access_token,
        agent_id=setup.agent_id,
    )
    assert any(item.id == setup.session_id for item in member_sessions)
