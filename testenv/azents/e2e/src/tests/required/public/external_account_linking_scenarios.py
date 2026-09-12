"""Deterministic External Account linking E2E scenarios."""

import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import NamedTuple, cast
from urllib.parse import urlencode

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.discord_connection_configuration import (
    DiscordConnectionConfiguration,
)
from azentspublicclient.models.discord_connection_credentials import (
    DiscordConnectionCredentials,
)
from azentspublicclient.models.discord_connection_setup_request import (
    DiscordConnectionSetupRequest,
)
from azentspublicclient.models.external_channel_connection_status import (
    ExternalChannelConnectionStatus,
)
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
from azentspublicclient.models.workspace_user_role import WorkspaceUserRole
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer

from support.utils import authenticate_user, unique, wait_until
from tests.required.public import external_channel_scenarios as external_scenarios
from tests.required.public.test_security import _elevate_user

_SLACK_APP_ID = "A-E2E"
_SLACK_TEAM_ID = "T-E2E"
_SLACK_CHANNEL_ID = "C-E2E"
_SLACK_BOT_TOKEN = "xoxb-e2e-private"
_SLACK_SIGNING_SECRET = "e2e-signing-private"
_DISCORD_APPLICATION_ID = "100000000000000001"
_DISCORD_GUILD_ID = "200000000000000001"
_DISCORD_CHANNEL_ID = "400000000000000001"
_DISCORD_USER_ID = "600000000000000001"
_DISCORD_BOT_TOKEN = "discord-e2e-private"


class _SlackWorkspace(NamedTuple):
    """One API-created Workspace with an active fake Slack connection."""

    token: str
    email: str
    handle: str
    agent_id: str
    connection_id: str


class _DiscordWorkspace(NamedTuple):
    """One API-created Workspace with an active fake Discord connection."""

    token: str
    email: str
    handle: str
    agent_id: str
    connection_id: str


class _LinkedSlackAccount(NamedTuple):
    """One confirmed Slack link and the exact elevated browser Session."""

    link_id: str
    elevated_token: str


class _SessionBinding(NamedTuple):
    """One provider-created exact Session and Binding."""

    session_id: str
    binding_id: str


def _object(value: object) -> dict[str, object]:
    """Validate one JSON object used by the E2E flow."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AssertionError("Expected a JSON object with string keys.")
    return value


def _list(value: object) -> list[object]:
    """Validate one JSON list used by the E2E flow."""
    if not isinstance(value, list):
        raise AssertionError("Expected a JSON list.")
    return value


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _link_url(server_url: str, path: str) -> str:
    return f"{server_url}/external-channel/v1/{path.lstrip('/')}"


def _json_response(response: requests.Response) -> dict[str, object]:
    response.raise_for_status()
    return _object(response.json())


def _error_code(response: requests.Response) -> str | None:
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return None
    code = detail.get("code")
    return code if isinstance(code, str) else None


def _require_sanitized_evidence(
    rendered: str,
    secrets: tuple[str, ...],
) -> None:
    """Fail without echoing secret values into pytest or JUnit output."""
    if any(secret and secret in rendered for secret in secrets):
        raise AssertionError(
            "Sanitized provider evidence exposed transient secret material."
        )


def _setup_slack_workspace(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
    slack_provider_fake_url: str,
) -> _SlackWorkspace:
    """Create one real Workspace/Agent/Slack connection through public APIs."""
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    created = external_scenarios._create_agent(
        public_api_client,
        admin_api_client,
        public_server_url,
        runtime_profile_provider_id=None,
    )
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=created.agent_id,
        handle=created.handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_SLACK_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_SLACK_BOT_TOKEN,
                signing_secret=_SLACK_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=_auth(created.token),
    )
    request.addfinalizer(
        lambda: external_api.external_channel_v1_disconnect_connection(
            agent_id=created.agent_id,
            connection_id=setup.connection.id,
            handle=created.handle,
            _headers=_auth(created.token),
        )
    )
    validated = external_api.external_channel_v1_validate_connection(
        agent_id=created.agent_id,
        connection_id=setup.connection.id,
        handle=created.handle,
        _headers=_auth(created.token),
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE
    return _SlackWorkspace(
        token=created.token,
        email=created.email,
        handle=created.handle,
        agent_id=created.agent_id,
        connection_id=setup.connection.id,
    )


def _setup_discord_workspace(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
    discord_provider_fake_url: str,
) -> _DiscordWorkspace:
    """Create one real Workspace/Agent/Discord connection through public APIs."""
    requests.post(
        f"{discord_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{discord_provider_fake_url}/__testenv/configure",
        json={
            "allow_synthetic_roots": True,
            "guild_commands": [
                {
                    "id": "500000000000000101",
                    "name": "Ask an Azents Agent",
                    "type": 3,
                },
                {
                    "id": "500000000000000102",
                    "name": "azents",
                    "type": 1,
                    "description": "Stale description.",
                },
            ],
        },
        timeout=5,
    ).raise_for_status()
    created = external_scenarios._create_agent(
        public_api_client,
        admin_api_client,
        public_server_url,
        runtime_profile_provider_id=None,
    )
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_discord_connection(
        agent_id=created.agent_id,
        handle=created.handle,
        discord_connection_setup_request=DiscordConnectionSetupRequest(
            app_id=_DISCORD_APPLICATION_ID,
            configuration=DiscordConnectionConfiguration(
                target_guild_id=_DISCORD_GUILD_ID,
                suppress_url_previews=True,
                thread_auto_archive_duration_minutes=1440,
            ),
            credentials=DiscordConnectionCredentials(
                bot_token=_DISCORD_BOT_TOKEN,
            ),
        ),
        _headers=_auth(created.token),
    )
    request.addfinalizer(
        lambda: external_api.external_channel_v1_disconnect_connection(
            agent_id=created.agent_id,
            connection_id=setup.connection.id,
            handle=created.handle,
            _headers=_auth(created.token),
        )
    )
    assert setup.connection.status is ExternalChannelConnectionStatus.ACTIVE
    return _DiscordWorkspace(
        token=created.token,
        email=created.email,
        handle=created.handle,
        agent_id=created.agent_id,
        connection_id=setup.connection.id,
    )


def _slack_transient_view(
    fake_url: str,
    *,
    scope: str,
    after_hash: str | None = None,
) -> dict[str, object] | None:
    response = requests.get(
        f"{fake_url}/__testenv/transient-view",
        params={"scope": scope},
        timeout=5,
    )
    response.raise_for_status()
    payload = _object(response.json())
    view_hash = payload.get("view_hash")
    if not isinstance(view_hash, str) or view_hash == after_hash:
        return None
    return payload


def _slack_personal_view(fake_url: str) -> dict[str, object] | None:
    for scope in ("setup", "settings", "unknown"):
        view = _slack_transient_view(fake_url, scope=scope)
        if view is None:
            continue
        action_ids = view.get("action_ids")
        if isinstance(action_ids, list) and "azents_account_link_start" in action_ids:
            return view
    return None


def _post_slack_interaction(callback_url: str, payload: dict[str, object]) -> None:
    body = urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode()
    response = requests.post(
        callback_url,
        data=body,
        headers=external_scenarios._signed_headers(
            body,
            content_type="application/x-www-form-urlencoded",
        ),
        timeout=10,
    )
    assert response.status_code == 200


def _slack_action_value(view: dict[str, object], action_id: str) -> str:
    values = view.get("action_values")
    if not isinstance(values, dict):
        raise AssertionError(f"Slack view omitted {action_id} action values.")
    value = values.get(action_id)
    if not isinstance(value, str) or not value:
        raise AssertionError(f"Slack view omitted {action_id} signed scope.")
    return value


def _open_slack_link_origin(
    *,
    callback_url: str,
    fake_url: str,
    user_id: str,
) -> tuple[str, dict[str, object]]:
    """Open settings and create one origin through the signed native CTA."""
    existing_code_view = _slack_transient_view(
        fake_url,
        scope="account_link_code",
    )
    previous_code_hash = (
        existing_code_view.get("view_hash") if existing_code_view is not None else None
    )
    assert previous_code_hash is None or isinstance(previous_code_hash, str)
    external_scenarios._open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        channel_id=_SLACK_CHANNEL_ID,
        user_id=user_id,
    )
    settings_view = _object(
        wait_until(
            lambda: _slack_personal_view(fake_url),
            timeout=15,
            interval=0.2,
            message="Slack optional account link control was not rendered",
        )
    )
    _post_slack_interaction(
        callback_url,
        {
            "type": "block_actions",
            "api_app_id": _SLACK_APP_ID,
            "team": {"id": _SLACK_TEAM_ID},
            "user": {"id": user_id},
            "channel": {"id": _SLACK_CHANNEL_ID},
            "trigger_id": f"trigger-link-{unique()}",
            "actions": [
                {
                    "action_id": "azents_account_link_start",
                    "value": _slack_action_value(
                        settings_view,
                        "azents_account_link_start",
                    ),
                }
            ],
            "view": {
                "id": settings_view["view_id"],
                "hash": settings_view["view_hash"],
                "private_metadata": settings_view["private_metadata"],
            },
        },
    )
    code_view = _object(
        wait_until(
            lambda: _slack_transient_view(
                fake_url,
                scope="account_link_code",
                after_hash=previous_code_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Slack account link code modal was not rendered",
        )
    )
    link_paths = code_view.get("link_paths")
    assert isinstance(link_paths, list)
    path = next(
        (
            item
            for item in link_paths
            if isinstance(item, str) and item.startswith("/external-channel/link/")
        ),
        None,
    )
    assert isinstance(path, str)
    return path.rsplit("/", 1)[-1], code_view


def _submit_slack_link_code(
    *,
    callback_url: str,
    user_id: str,
    view: dict[str, object],
    code: str,
) -> None:
    """Submit one browser code through the signed original Slack actor modal."""
    _post_slack_interaction(
        callback_url,
        {
            "type": "view_submission",
            "api_app_id": _SLACK_APP_ID,
            "team": {"id": _SLACK_TEAM_ID},
            "user": {"id": user_id},
            "trigger_id": f"trigger-code-{unique()}",
            "view": {
                "id": view["view_id"],
                "hash": view["view_hash"],
                "callback_id": "azents_account_link_code",
                "private_metadata": view["private_metadata"],
                "state": {
                    "values": {
                        "azents_account_link_code": {
                            "value": {"type": "plain_text_input", "value": code}
                        }
                    }
                },
            },
        },
    )


def _create_candidate(
    *,
    server_url: str,
    origin_id: str,
    token: str,
) -> requests.Response:
    return requests.post(
        _link_url(server_url, f"account-link-origins/{origin_id}/candidates"),
        headers=_auth(token),
        timeout=10,
    )


def _candidate(
    *,
    server_url: str,
    candidate_id: str,
    token: str,
) -> requests.Response:
    return requests.get(
        _link_url(server_url, f"account-link-candidates/{candidate_id}"),
        headers=_auth(token),
        timeout=10,
    )


def _confirm_candidate(
    *,
    server_url: str,
    candidate_id: str,
    token: str,
) -> requests.Response:
    return requests.post(
        _link_url(server_url, f"account-link-candidates/{candidate_id}/confirm"),
        headers=_auth(token),
        timeout=10,
    )


def _origin(
    *,
    server_url: str,
    origin_id: str,
    token: str,
) -> dict[str, object]:
    return _json_response(
        requests.get(
            _link_url(server_url, f"account-link-origins/{origin_id}"),
            headers=_auth(token),
            timeout=10,
        )
    )


def _invite_member(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    *,
    owner_token: str,
    handle: str,
) -> tuple[str, str]:
    """Create and join one ordinary Workspace member through supported APIs."""
    email = f"external-link-member-{unique()}@example.com"
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=email,
    )
    invitation_api = InvitationV1Api(public_api_client)
    invitation = invitation_api.invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=email, role=WorkspaceUserRole.MEMBER),
        _headers=_auth(owner_token),
    )
    invitation_api.invitation_v1_accept_invitation(
        invitation.id,
        _headers=_auth(token),
    )
    return token, email


def _complete_slack_link(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    fake_url: str,
    workspace: _SlackWorkspace,
    user_id: str,
) -> _LinkedSlackAccount:
    """Complete one Slack link without persisting its browser code in evidence."""
    callback_url = f"{server_url}/external-channel/v1/slack/events"
    origin_id, code_view = _open_slack_link_origin(
        callback_url=callback_url,
        fake_url=fake_url,
        user_id=user_id,
    )
    elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        workspace.token,
        workspace.email,
    )
    created = _json_response(
        _create_candidate(
            server_url=server_url,
            origin_id=origin_id,
            token=elevated,
        )
    )
    candidate_id = created["id"]
    code = created["code"]
    assert isinstance(candidate_id, str)
    assert isinstance(code, str)
    _submit_slack_link_code(
        callback_url=callback_url,
        user_id=user_id,
        view=code_view,
        code=code,
    )
    wait_until(
        lambda: (
            _json_response(
                _candidate(
                    server_url=server_url,
                    candidate_id=candidate_id,
                    token=workspace.token,
                )
            )["status"]
            == "provider_verified"
        ),
        timeout=15,
        interval=0.2,
        message="Slack provider proof did not become authoritative",
    )
    linked = _json_response(
        _confirm_candidate(
            server_url=server_url,
            candidate_id=candidate_id,
            token=elevated,
        )
    )
    link_id = linked["id"]
    assert isinstance(link_id, str)
    return _LinkedSlackAccount(link_id=link_id, elevated_token=elevated)


def _seed_slack_setup_claim(
    *,
    callback_url: str,
    fake_url: str,
    user_id: str,
) -> None:
    """Create guest setup state through one real signed Slack invocation."""
    root_timestamp = f"{int(time.time()) - 60}.000100"
    requests.post(
        f"{fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": user_id,
                        "ts": root_timestamp,
                        "text": "Start deterministic linked model setup.",
                    }
                ]
            ]
        },
        timeout=5,
    ).raise_for_status()
    event_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-link-model-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _SLACK_APP_ID,
            "team_id": _SLACK_TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": _SLACK_CHANNEL_ID,
                "channel_type": "channel",
                "user": user_id,
                "text": "<@U-BOT-E2E> start setup",
                "ts": root_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    response = requests.post(
        callback_url,
        data=event_body,
        headers=external_scenarios._signed_headers(event_body),
        timeout=10,
    )
    assert response.status_code == 200

    def setup_delivery_ready() -> bool:
        state = _json_response(requests.get(f"{fake_url}/__testenv/state", timeout=5))
        counts = state.get("request_counts")
        return isinstance(counts, dict) and counts.get("chat.postMessage", 0) >= 1

    wait_until(
        setup_delivery_ready,
        timeout=15,
        interval=0.2,
        message="Slack invocation did not create guest setup controls",
    )


def _open_slack_settings_view(
    *,
    callback_url: str,
    fake_url: str,
    user_id: str,
    scope: str,
    required_action: str | None,
) -> dict[str, object]:
    existing = _slack_transient_view(fake_url, scope=scope)
    previous_hash = existing.get("view_hash") if existing is not None else None
    assert previous_hash is None or isinstance(previous_hash, str)
    external_scenarios._open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        channel_id=_SLACK_CHANNEL_ID,
        user_id=user_id,
    )

    def current() -> dict[str, object] | None:
        return _slack_transient_view(
            fake_url,
            scope=scope,
            after_hash=previous_hash,
        )

    view = _object(
        wait_until(
            current,
            timeout=15,
            interval=0.2,
            message=f"Slack {scope} view was not rendered",
        )
    )
    if required_action is not None:
        actions = view.get("action_ids")
        safe_actions = (
            [action for action in actions if isinstance(action, str)]
            if isinstance(actions, list)
            else []
        )
        assert required_action in safe_actions, (
            f"Slack {scope} view omitted {required_action}; "
            f"safe actions={safe_actions!r}"
        )
    return view


def _session_binding(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _SlackWorkspace,
) -> _SessionBinding | None:
    chat_api = ChatV1Api(public_api_client)
    external_api = ExternalChannelV1Api(public_api_client)
    sessions = chat_api.chat_v1_list_agent_sessions(
        agent_id=workspace.agent_id,
        _headers=_auth(workspace.token),
    )
    for session in sessions.items:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=workspace.agent_id,
            session_id=session.id,
            handle=workspace.handle,
            _headers=_auth(workspace.token),
        )
        if len(projection.items) == 1:
            return _SessionBinding(
                session_id=session.id,
                binding_id=projection.items[0].id,
            )
    return None


def _submit_slack_model_action(
    *,
    callback_url: str,
    user_id: str,
    view: dict[str, object],
    action_id: str,
    selected_option: str | None,
) -> None:
    """Submit one signed Slack model button or Select control."""
    action: dict[str, object] = {"action_id": action_id}
    if selected_option is None:
        action["value"] = _slack_action_value(view, action_id)
    else:
        action["selected_option"] = {"value": selected_option}
    _post_slack_interaction(
        callback_url,
        {
            "type": "block_actions",
            "api_app_id": _SLACK_APP_ID,
            "team": {"id": _SLACK_TEAM_ID},
            "user": {"id": user_id},
            "channel": {"id": _SLACK_CHANNEL_ID},
            "trigger_id": f"trigger-model-{unique()}",
            "actions": [action],
            "view": {
                "id": view["view_id"],
                "hash": view["view_hash"],
                "private_metadata": view["private_metadata"],
            },
        },
    )


def _slack_model_apply_payload(
    *,
    user_id: str,
    view: dict[str, object],
    trigger_id: str,
) -> dict[str, object]:
    """Build one replayable explicit Apply callback without draft values."""
    return {
        "type": "view_submission",
        "api_app_id": _SLACK_APP_ID,
        "team": {"id": _SLACK_TEAM_ID},
        "user": {"id": user_id},
        "trigger_id": trigger_id,
        "view": {
            "id": view["view_id"],
            "hash": view["view_hash"],
            "callback_id": "azents_model_apply",
            "private_metadata": view["private_metadata"],
            "state": {"values": {}},
        },
    }


def _session_detail(
    *,
    server_url: str,
    workspace: _SlackWorkspace,
    session_id: str,
) -> dict[str, object]:
    return _json_response(
        requests.get(
            (f"{server_url}/chat/v1/agents/{workspace.agent_id}/sessions/{session_id}"),
            headers=_auth(workspace.token),
            timeout=10,
        )
    )


def _replace_web_model(
    *,
    server_url: str,
    token: str,
    session_id: str,
    target_label: str,
) -> dict[str, object]:
    return _json_response(
        requests.put(
            f"{server_url}/chat/v1/sessions/{session_id}/model-profile",
            headers={**_auth(token), "Content-Type": "application/json"},
            json={
                "client_request_id": f"external-link-web-{unique()}",
                "model_target_label": target_label,
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            timeout=10,
        )
    )


def _configure_agent_model_options(
    *,
    server_url: str,
    workspace: _SlackWorkspace,
) -> None:
    """Register two existing catalog models through the public Agent API."""
    agent_url = (
        f"{server_url}/agent/v1/workspaces/{workspace.handle}"
        f"/agents/{workspace.agent_id}"
    )
    agent = _json_response(
        requests.get(
            agent_url,
            headers=_auth(workspace.token),
            timeout=10,
        )
    )
    selection = agent.get("model_selection")
    assert isinstance(selection, dict)
    integration_id = selection.get("llm_provider_integration_id")
    assert isinstance(integration_id, str)
    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{workspace.handle}/"
        f"llm-provider-integrations/{integration_id}/catalog-entries"
    )

    def catalog() -> list[dict[str, object]] | None:
        payload = _json_response(
            requests.get(
                entries_url,
                headers=_auth(workspace.token),
                timeout=10,
            )
        )
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return None
        typed = [item for item in entries if isinstance(item, dict)]
        identifiers = {
            item.get("provider_model_identifier")
            for item in typed
            if isinstance(item.get("provider_model_identifier"), str)
        }
        return typed if {"gpt-5.5", "gpt-5.5-mini"}.issubset(identifiers) else None

    entries = wait_until(
        catalog,
        timeout=15,
        interval=0.2,
        message="Agent model catalog did not expose two deterministic options",
    )
    assert entries is not None
    by_identifier = {
        item["provider_model_identifier"]: item
        for item in entries
        if isinstance(item.get("provider_model_identifier"), str)
    }

    def model_selection(identifier: str) -> dict[str, object]:
        return {
            "llm_provider_integration_id": integration_id,
            "model_identifier": identifier,
        }

    response = requests.patch(
        agent_url,
        headers={**_auth(workspace.token), "Content-Type": "application/json"},
        json={
            "selectable_model_options": [
                {
                    "label": "Quality",
                    "model_selection": model_selection(
                        str(by_identifier["gpt-5.5"]["provider_model_identifier"])
                    ),
                    "settings": {"builtin_tools": []},
                },
                {
                    "label": "Fast",
                    "model_selection": model_selection(
                        str(by_identifier["gpt-5.5-mini"]["provider_model_identifier"])
                    ),
                    "settings": {"builtin_tools": []},
                },
            ],
            "main_model_label": "Quality",
            "lightweight_model_label": "Fast",
        },
        timeout=10,
    )
    response.raise_for_status()


def test_slack_account_link_security_recovery_and_unlink(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Enforce actor, Session, and terminal state through real callbacks."""
    workspace = _setup_slack_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    origin_id, code_view = _open_slack_link_origin(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-LINK-OWNER",
    )

    not_elevated = _create_candidate(
        server_url=azents_public_server_url,
        origin_id=origin_id,
        token=workspace.token,
    )
    assert not_elevated.status_code == 403
    elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        workspace.token,
        workspace.email,
    )
    created_response = _create_candidate(
        server_url=azents_public_server_url,
        origin_id=origin_id,
        token=elevated,
    )
    created = _json_response(created_response)
    assert created_response.headers.get("Cache-Control") == "no-store"
    candidate_id = created["id"]
    code = created["code"]
    assert isinstance(candidate_id, str)
    assert isinstance(code, str)

    status = _json_response(
        _candidate(
            server_url=azents_public_server_url,
            candidate_id=candidate_id,
            token=workspace.token,
        )
    )
    assert status["status"] == "pending_provider_proof"
    if "code" in status:
        raise AssertionError(
            "Candidate status response exposed one-time code material."
        )

    existing_rejection = _slack_transient_view(
        slack_provider_fake_url,
        scope="unknown",
    )
    existing_rejection_hash = (
        existing_rejection.get("view_hash") if existing_rejection is not None else None
    )
    assert existing_rejection_hash is None or isinstance(
        existing_rejection_hash,
        str,
    )
    _submit_slack_link_code(
        callback_url=callback_url,
        user_id="U-FORWARDED-ACTOR",
        view=code_view,
        code=code,
    )
    wait_until(
        lambda: _slack_transient_view(
            slack_provider_fake_url,
            scope="unknown",
            after_hash=existing_rejection_hash,
        ),
        timeout=15,
        interval=0.2,
        message="Wrong-actor Slack proof rejection did not finish",
    )
    assert (
        _origin(
            server_url=azents_public_server_url,
            origin_id=origin_id,
            token=workspace.token,
        )["invalid_code_count"]
        == 0
    )
    assert (
        _json_response(
            _candidate(
                server_url=azents_public_server_url,
                candidate_id=candidate_id,
                token=workspace.token,
            )
        )["status"]
        == "pending_provider_proof"
    )

    _submit_slack_link_code(
        callback_url=callback_url,
        user_id="U-LINK-OWNER",
        view=code_view,
        code="invalid-browser-code",
    )
    wait_until(
        lambda: (
            _origin(
                server_url=azents_public_server_url,
                origin_id=origin_id,
                token=workspace.token,
            )["invalid_code_count"]
            == 1
        ),
        timeout=15,
        interval=0.2,
        message="Slack invalid-code attempt was not recorded",
    )

    _submit_slack_link_code(
        callback_url=callback_url,
        user_id="U-LINK-OWNER",
        view=code_view,
        code=code,
    )
    wait_until(
        lambda: (
            _json_response(
                _candidate(
                    server_url=azents_public_server_url,
                    candidate_id=candidate_id,
                    token=workspace.token,
                )
            )["status"]
            == "provider_verified"
        ),
        timeout=15,
        interval=0.2,
        message="Slack provider proof did not become authoritative",
    )

    other_session_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=workspace.email,
    )
    wrong_session = _candidate(
        server_url=azents_public_server_url,
        candidate_id=candidate_id,
        token=other_session_token,
    )
    assert wrong_session.status_code == 404
    assert _error_code(wrong_session) == "resource_not_found"

    cancelled_created = _json_response(
        _create_candidate(
            server_url=azents_public_server_url,
            origin_id=origin_id,
            token=elevated,
        )
    )
    cancelled_id = cancelled_created["id"]
    assert isinstance(cancelled_id, str)
    cancelled = _json_response(
        requests.delete(
            _link_url(
                azents_public_server_url,
                f"account-link-candidates/{cancelled_id}",
            ),
            headers=_auth(workspace.token),
            timeout=10,
        )
    )
    assert cancelled["status"] == "cancelled"
    terminal = _confirm_candidate(
        server_url=azents_public_server_url,
        candidate_id=cancelled_id,
        token=elevated,
    )
    assert terminal.status_code == 409
    assert _error_code(terminal) == "candidate_terminal"

    linked = _json_response(
        _confirm_candidate(
            server_url=azents_public_server_url,
            candidate_id=candidate_id,
            token=elevated,
        )
    )
    assert linked["provider"] == "slack"
    assert linked["identity_scope"] == _SLACK_TEAM_ID
    assert linked["state"] == "active"
    replayed = _json_response(
        _confirm_candidate(
            server_url=azents_public_server_url,
            candidate_id=candidate_id,
            token=elevated,
        )
    )
    assert replayed["id"] == linked["id"]

    listed = _json_response(
        requests.get(
            _link_url(azents_public_server_url, "account-links"),
            headers=_auth(workspace.token),
            timeout=10,
        )
    )
    assert [
        item["id"] for item in _list(listed["items"]) if isinstance(item, dict)
    ] == [linked["id"]]
    disconnected = _json_response(
        requests.delete(
            _link_url(azents_public_server_url, f"account-links/{linked['id']}"),
            headers=_auth(elevated),
            timeout=10,
        )
    )
    assert disconnected["state"] == "revoked"

    provider_state = _json_response(
        requests.get(f"{slack_provider_fake_url}/__testenv/state", timeout=5)
    )
    rendered = str(provider_state)
    _require_sanitized_evidence(
        rendered,
        (code, workspace.email, _SLACK_BOT_TOKEN, "invalid-browser-code"),
    )
    assert provider_state["deliveries"] == []


def test_slack_account_link_conflict_is_nondisclosing(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Keep independent origins while an active link wins without owner disclosure."""
    workspace = _setup_slack_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
    )
    member_token, member_email = _invite_member(
        public_api_client,
        admin_api_client,
        owner_token=workspace.token,
        handle=workspace.handle,
    )
    owner_elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        workspace.token,
        workspace.email,
    )
    member_elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        member_token,
        member_email,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    first_origin, first_view = _open_slack_link_origin(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-CONFLICT",
    )
    second_origin, second_view = _open_slack_link_origin(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-CONFLICT",
    )
    first = _json_response(
        _create_candidate(
            server_url=azents_public_server_url,
            origin_id=first_origin,
            token=owner_elevated,
        )
    )
    second = _json_response(
        _create_candidate(
            server_url=azents_public_server_url,
            origin_id=second_origin,
            token=member_elevated,
        )
    )
    for view, candidate in ((first_view, first), (second_view, second)):
        code = candidate["code"]
        assert isinstance(code, str)
        _submit_slack_link_code(
            callback_url=callback_url,
            user_id="U-CONFLICT",
            view=view,
            code=code,
        )
    first_id = first["id"]
    second_id = second["id"]
    assert isinstance(first_id, str)
    assert isinstance(second_id, str)
    wait_until(
        lambda: (
            _json_response(
                _candidate(
                    server_url=azents_public_server_url,
                    candidate_id=second_id,
                    token=member_token,
                )
            )["status"]
            == "provider_verified"
        ),
        timeout=15,
        interval=0.2,
        message="Second independent Slack proof was not verified",
    )
    _json_response(
        _confirm_candidate(
            server_url=azents_public_server_url,
            candidate_id=first_id,
            token=owner_elevated,
        )
    )
    conflict = _confirm_candidate(
        server_url=azents_public_server_url,
        candidate_id=second_id,
        token=member_elevated,
    )
    assert conflict.status_code == 409
    assert _error_code(conflict) == "conflict"
    assert workspace.email not in conflict.text
    assert member_email not in conflict.text


def test_slack_linked_model_draft_stale_notice_failure_and_replay(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Keep drafts explicit and preserve saved state across notice failure."""
    workspace = _setup_slack_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
    )
    _configure_agent_model_options(
        server_url=azents_public_server_url,
        workspace=workspace,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    _seed_slack_setup_claim(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-MODEL-OWNER",
    )

    setup_view = _open_slack_settings_view(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-MODEL-OWNER",
        scope="setup",
        required_action=None,
    )
    external_scenarios._submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        user_id="U-MODEL-OWNER",
        setup_view=setup_view,
        location="channel",
    )
    binding = wait_until(
        lambda: _session_binding(
            public_api_client=public_api_client,
            workspace=workspace,
        ),
        timeout=15,
        interval=0.2,
        message="Slack setup did not create an exact Session Binding",
    )
    assert isinstance(binding, _SessionBinding)
    linked = _complete_slack_link(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        fake_url=slack_provider_fake_url,
        workspace=workspace,
        user_id="U-MODEL-OWNER",
    )
    initial = _session_detail(
        server_url=azents_public_server_url,
        workspace=workspace,
        session_id=binding.session_id,
    )
    initial_target = initial["current_model_target_label"]
    assert initial_target is None

    settings_view = _open_slack_settings_view(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-MODEL-OWNER",
        scope="settings",
        required_action="azents_model_open",
    )
    previous_model = _slack_transient_view(
        slack_provider_fake_url,
        scope="model",
    )
    previous_hash = (
        previous_model.get("view_hash") if previous_model is not None else None
    )
    assert previous_hash is None or isinstance(previous_hash, str)
    _submit_slack_model_action(
        callback_url=callback_url,
        user_id="U-MODEL-OWNER",
        view=settings_view,
        action_id="azents_model_open",
        selected_option=None,
    )
    model_view = _object(
        wait_until(
            lambda: _slack_transient_view(
                slack_provider_fake_url,
                scope="model",
                after_hash=previous_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Slack linked model editor was not rendered",
        )
    )
    labels = model_view.get("option_labels")
    assert isinstance(labels, dict)
    model_labels = labels.get("azents_model_select")
    assert isinstance(model_labels, dict)
    option_entries = [
        (option_id, label)
        for option_id, label in model_labels.items()
        if isinstance(option_id, str) and isinstance(label, str)
    ]
    assert len(option_entries) >= 2, (
        "The deterministic model catalog needs two authorized options."
    )
    draft_option, draft_target = option_entries[0]
    _, web_target = option_entries[1]
    before_select_hash = model_view["view_hash"]
    assert isinstance(before_select_hash, str)
    _submit_slack_model_action(
        callback_url=callback_url,
        user_id="U-MODEL-OWNER",
        view=model_view,
        action_id="azents_model_select",
        selected_option=draft_option,
    )
    selected_view = _object(
        wait_until(
            lambda: _slack_transient_view(
                slack_provider_fake_url,
                scope="model",
                after_hash=before_select_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Slack model draft selection did not rerender",
        )
    )
    assert (
        _session_detail(
            server_url=azents_public_server_url,
            workspace=workspace,
            session_id=binding.session_id,
        )["current_model_target_label"]
        == initial_target
    )

    _replace_web_model(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=binding.session_id,
        target_label=web_target,
    )
    stale_hash = selected_view["view_hash"]
    assert isinstance(stale_hash, str)
    stale_apply = _slack_model_apply_payload(
        user_id="U-MODEL-OWNER",
        view=selected_view,
        trigger_id=f"trigger-stale-{unique()}",
    )
    _post_slack_interaction(callback_url, stale_apply)
    wait_until(
        lambda: _slack_transient_view(
            slack_provider_fake_url,
            scope="model",
            after_hash=stale_hash,
        ),
        timeout=15,
        interval=0.2,
        message="Slack stale model draft did not refresh authoritative state",
    )
    assert (
        _session_detail(
            server_url=azents_public_server_url,
            workspace=workspace,
            session_id=binding.session_id,
        )["current_model_target_label"]
        == web_target
    )

    fresh_settings = _open_slack_settings_view(
        callback_url=callback_url,
        fake_url=slack_provider_fake_url,
        user_id="U-MODEL-OWNER",
        scope="settings",
        required_action="azents_model_open",
    )
    current_model = _slack_transient_view(
        slack_provider_fake_url,
        scope="model",
    )
    current_hash = current_model.get("view_hash") if current_model is not None else None
    assert current_hash is None or isinstance(current_hash, str)
    _submit_slack_model_action(
        callback_url=callback_url,
        user_id="U-MODEL-OWNER",
        view=fresh_settings,
        action_id="azents_model_open",
        selected_option=None,
    )
    fresh_model = _object(
        wait_until(
            lambda: _slack_transient_view(
                slack_provider_fake_url,
                scope="model",
                after_hash=current_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Fresh Slack model editor was not rendered",
        )
    )
    fresh_labels = fresh_model.get("option_labels")
    assert isinstance(fresh_labels, dict)
    fresh_model_labels = fresh_labels.get("azents_model_select")
    assert isinstance(fresh_model_labels, dict)
    fresh_draft_option = next(
        (
            option_id
            for option_id, label in fresh_model_labels.items()
            if isinstance(option_id, str) and label == draft_target
        ),
        None,
    )
    assert isinstance(fresh_draft_option, str)
    fresh_hash = fresh_model["view_hash"]
    assert isinstance(fresh_hash, str)
    _submit_slack_model_action(
        callback_url=callback_url,
        user_id="U-MODEL-OWNER",
        view=fresh_model,
        action_id="azents_model_select",
        selected_option=fresh_draft_option,
    )
    final_view = _object(
        wait_until(
            lambda: _slack_transient_view(
                slack_provider_fake_url,
                scope="model",
                after_hash=fresh_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Fresh Slack model draft did not update",
        )
    )
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={"delivery_scenarios": {"chat.postMessage": "failed"}},
        timeout=5,
    ).raise_for_status()
    apply_payload = _slack_model_apply_payload(
        user_id="U-MODEL-OWNER",
        view=final_view,
        trigger_id=f"trigger-apply-{unique()}",
    )
    _post_slack_interaction(callback_url, apply_payload)
    wait_until(
        lambda: (
            _session_detail(
                server_url=azents_public_server_url,
                workspace=workspace,
                session_id=binding.session_id,
            )["current_model_target_label"]
            == draft_target
        ),
        timeout=15,
        interval=0.2,
        message="Slack native Apply did not commit the shared model",
    )

    def apply_completed_once() -> bool:
        state = _json_response(
            requests.get(f"{slack_provider_fake_url}/__testenv/state", timeout=5)
        )
        counts = state.get("request_counts")
        views = state.get("views")
        return (
            isinstance(counts, dict)
            and counts.get("chat.postMessage") == 1
            and counts.get("views.open") == 1
            and isinstance(views, list)
            and len(views) == 1
            and isinstance(views[0], dict)
            and views[0].get("operation") == "views.open"
            and views[0].get("control_scope") == "model"
        )

    wait_until(
        apply_completed_once,
        timeout=15,
        interval=0.2,
        message="Slack Apply did not complete with one private result view",
    )
    applied_session = _session_detail(
        server_url=azents_public_server_url,
        workspace=workspace,
        session_id=binding.session_id,
    )
    _post_slack_interaction(callback_url, apply_payload)
    assert apply_completed_once()
    replayed_session = _session_detail(
        server_url=azents_public_server_url,
        workspace=workspace,
        session_id=binding.session_id,
    )
    for key in (
        "current_model_target_label",
        "current_reasoning_effort",
        "current_enabled_execution_options",
        "updated_at",
    ):
        assert replayed_session[key] == applied_session[key]
    assert replayed_session["current_model_target_label"] == draft_target
    requests.delete(
        _link_url(azents_public_server_url, f"account-links/{linked.link_id}"),
        headers=_auth(linked.elevated_token),
        timeout=10,
    ).raise_for_status()


def _discord_component(
    *,
    fake_url: str,
    interaction_id: str,
    custom_id: str,
    interaction_type: int,
    code: str | None = None,
) -> requests.Response:
    data: dict[str, object] = {"custom_id": custom_id}
    if interaction_type == 5:
        assert code is not None
        data["components"] = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 4,
                        "custom_id": "azents_account_link_code",
                        "value": code,
                    }
                ],
            }
        ]
    return requests.post(
        f"{fake_url}/__testenv/interactions",
        json={
            "id": interaction_id,
            "type": interaction_type,
            "application_id": _DISCORD_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "channel": {"id": _DISCORD_CHANNEL_ID, "type": 0},
            "member": {
                "user": {
                    "id": _DISCORD_USER_ID,
                    "username": "external-link-user",
                    "global_name": "External Link User",
                }
            },
            "token": f"token-{interaction_id}",
            "message": {"id": f"message-{interaction_id}"},
            "data": data,
        },
        timeout=10,
    )


def _discord_transient(fake_url: str) -> dict[str, object] | None:
    response = requests.get(
        f"{fake_url}/__testenv/transient-interaction",
        params={"channel_id": _DISCORD_CHANNEL_ID},
        timeout=5,
    )
    response.raise_for_status()
    payload = _object(response.json())
    return payload if payload.get("custom_ids") else None


def _discord_completed_interaction(
    fake_url: str,
    *,
    interaction_id: str,
) -> dict[str, object] | None:
    """Return one interaction after its deferred original response is edited."""
    state = _json_response(requests.get(f"{fake_url}/__testenv/state", timeout=5))
    interactions = state.get("interactions")
    if not isinstance(interactions, list):
        return None
    for item in interactions:
        if (
            isinstance(item, dict)
            and item.get("interaction_id") == interaction_id
            and item.get("completed_response_type") == 7
        ):
            return item
    return None


def test_discord_account_link_happy_path_is_ephemeral_and_unlinks(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[DockerContainer]
    ],
) -> None:
    """Complete Discord type-3/type-9/type-5 proof with private-only evidence."""
    del azents_external_channel_gateway_factory
    workspace = _setup_discord_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        discord_provider_fake_url,
    )
    command_id = wait_until(
        lambda: external_scenarios._discord_command_id(
            discord_provider_fake_url,
            role="azents_settings",
        ),
        timeout=15,
        interval=0.2,
        message="Discord settings command was not reconciled",
    )
    opened = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "710000000000000001",
            "type": 2,
            "application_id": _DISCORD_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "channel": {"id": _DISCORD_CHANNEL_ID, "type": 0},
            "member": {
                "user": {
                    "id": _DISCORD_USER_ID,
                    "username": "external-link-user",
                    "global_name": "External Link User",
                }
            },
            "data": {
                "id": command_id,
                "name": "azents",
                "type": 1,
            },
        },
        timeout=10,
    )
    opened.raise_for_status()
    assert opened.json() == {"status": 200, "response_type": 4}
    start_id = wait_until(
        lambda: (
            requests.get(
                f"{discord_provider_fake_url}/__testenv/transient-component",
                params={"scope": "account_link", "channel_id": _DISCORD_CHANNEL_ID},
                timeout=5,
            )
            .json()
            .get("custom_id")
        ),
        timeout=15,
        interval=0.2,
        message="Discord optional link control was not rendered",
    )
    assert isinstance(start_id, str) and start_id.startswith("al1:s:")
    started = _discord_component(
        fake_url=discord_provider_fake_url,
        interaction_id="710000000000000002",
        custom_id=start_id,
        interaction_type=3,
    )
    started.raise_for_status()
    assert started.json() == {"status": 200, "response_type": 6}
    wait_until(
        lambda: _discord_completed_interaction(
            discord_provider_fake_url,
            interaction_id="710000000000000002",
        ),
        timeout=15,
        interval=0.2,
        message="Discord link start did not complete its deferred update",
    )
    started_controls = _object(
        wait_until(
            lambda: (
                handoff
                if (handoff := _discord_transient(discord_provider_fake_url))
                and any(
                    isinstance(path, str) and path.startswith("/external-channel/link/")
                    for path in _list(handoff.get("link_paths"))
                )
                else None
            ),
            timeout=15,
            interval=0.2,
            message="Discord link-start controls were not rendered",
        )
    )
    link_paths = started_controls["link_paths"]
    assert isinstance(link_paths, list)
    link_path = next(
        item
        for item in link_paths
        if isinstance(item, str) and item.startswith("/external-channel/link/")
    )
    origin_id = link_path.rsplit("/", 1)[-1]
    enter_id = next(
        item
        for item in _list(started_controls["custom_ids"])
        if isinstance(item, str) and item.startswith("al1:e:")
    )
    modal = _discord_component(
        fake_url=discord_provider_fake_url,
        interaction_id="710000000000000003",
        custom_id=enter_id,
        interaction_type=3,
    )
    modal.raise_for_status()
    assert modal.json() == {"status": 200, "response_type": 9}
    modal_controls = _object(
        wait_until(
            lambda: (
                handoff
                if (handoff := _discord_transient(discord_provider_fake_url))
                and handoff.get("response_type") == 9
                else None
            ),
            timeout=15,
            interval=0.2,
            message="Discord account link code modal was not rendered",
        )
    )
    modal_id = next(
        item
        for item in _list(modal_controls["custom_ids"])
        if isinstance(item, str) and item.startswith("al1:e:")
    )
    assert modal_controls["input_custom_ids"] == ["azents_account_link_code"]

    elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        workspace.token,
        workspace.email,
    )
    created = _json_response(
        _create_candidate(
            server_url=azents_public_server_url,
            origin_id=origin_id,
            token=elevated,
        )
    )
    candidate_id = created["id"]
    code = created["code"]
    assert isinstance(candidate_id, str)
    assert isinstance(code, str)
    verified = _discord_component(
        fake_url=discord_provider_fake_url,
        interaction_id="710000000000000004",
        custom_id=modal_id,
        interaction_type=5,
        code=code,
    )
    verified.raise_for_status()
    assert verified.json() == {"status": 200, "response_type": 5}
    wait_until(
        lambda: _discord_completed_interaction(
            discord_provider_fake_url,
            interaction_id="710000000000000004",
        ),
        timeout=15,
        interval=0.2,
        message="Discord account proof did not complete its deferred update",
    )
    wait_until(
        lambda: (
            _json_response(
                _candidate(
                    server_url=azents_public_server_url,
                    candidate_id=candidate_id,
                    token=workspace.token,
                )
            )["status"]
            == "provider_verified"
        ),
        timeout=15,
        interval=0.2,
        message="Discord provider proof did not become authoritative",
    )
    linked = _json_response(
        _confirm_candidate(
            server_url=azents_public_server_url,
            candidate_id=candidate_id,
            token=elevated,
        )
    )
    assert linked["provider"] == "discord"
    assert linked["identity_scope"] == "global"
    assert linked["state"] == "active"
    unlinked = _json_response(
        requests.delete(
            _link_url(azents_public_server_url, f"account-links/{linked['id']}"),
            headers=_auth(elevated),
            timeout=10,
        )
    )
    assert unlinked["state"] == "revoked"

    provider_state = _json_response(
        requests.get(f"{discord_provider_fake_url}/__testenv/state", timeout=5)
    )
    interactions = [
        item for item in _list(provider_state["interactions"]) if isinstance(item, dict)
    ]
    assert interactions[0].get("ephemeral") is True
    assert any(item.get("response_type") == 9 for item in interactions)
    rendered = str(provider_state)
    _require_sanitized_evidence(
        rendered,
        (
            code,
            workspace.email,
            _DISCORD_BOT_TOKEN,
            "token-710000000000000004",
        ),
    )


def _browser_password_elevation(driver: WebDriver) -> None:
    """Complete the existing password elevation without exposing auth material."""
    wait = WebDriverWait(driver, 30)
    wait.until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[text()='Verify your identity']")
        )
    )
    wait.until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Password']"))
    ).click()
    password = wait.until(ec.element_to_be_clickable((By.NAME, "password")))
    password.send_keys("TestPass123!", Keys.ENTER)


def run_web_external_account_link_management(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Verify personal context, owner list, elevation, and mobile-safe unlink."""
    workspace = _setup_slack_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
    )
    linked = _complete_slack_link(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        fake_url=slack_provider_fake_url,
        workspace=workspace,
        user_id="U-WEB-OWNER",
    )
    external_scenarios._login_main_web(
        browser_driver,
        main_web_url=azents_main_web_url,
        email=workspace.email,
    )
    browser_driver.set_window_size(390, 844)
    browser_driver.get(f"{azents_main_web_url}/account/external-accounts")
    wait = WebDriverWait(browser_driver, 30)
    root = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-account-links"]')
        )
    )
    assert "External accounts" in root.text
    row = wait.until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                f'[data-testid="external-account-link-{linked.link_id}"]',
            )
        )
    )
    assert "U-WEB-OWNER" in row.text
    assert "Slack" in row.text
    assert "Connected" in row.text
    has_horizontal_overflow = cast(
        bool,
        browser_driver.execute_script(
            "return document.documentElement.scrollWidth > "
            "document.documentElement.clientWidth;"
        ),
    )
    assert has_horizontal_overflow is False

    row.find_element(By.XPATH, ".//button[normalize-space()='Disconnect']").click()
    modal = wait.until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                "//*[@role='dialog' and "
                ".//*[normalize-space()='Disconnect external account?']]",
            )
        )
    )
    assert "guest" in modal.text.lower()
    wait.until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Disconnect account']")
        )
    ).click()
    _browser_password_elevation(browser_driver)

    wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-account-links"]')
        )
    )
    disconnected_row = wait.until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                f'[data-testid="external-account-link-{linked.link_id}"]',
            )
        )
    )
    wait.until(lambda _: "Disconnected" in disconnected_row.text)

    def authoritative_revoked() -> bool:
        listed = _json_response(
            requests.get(
                _link_url(azents_public_server_url, "account-links"),
                headers=_auth(workspace.token),
                timeout=10,
            )
        )
        return any(
            isinstance(item, dict)
            and item.get("id") == linked.link_id
            and item.get("state") == "revoked"
            for item in _list(listed["items"])
        )

    wait_until(
        authoritative_revoked,
        timeout=15,
        interval=0.2,
        message="Web disconnect did not reach authoritative revoked state",
    )
    browser_driver.set_window_size(1280, 844)
