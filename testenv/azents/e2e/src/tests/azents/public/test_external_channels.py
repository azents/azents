"""External Channel deterministic provider and management E2E journeys."""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, cast
from urllib.parse import urlencode

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.connection_access_policy_request import (
    ConnectionAccessPolicyRequest,
)
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.discord_connection_configuration import (
    DiscordConnectionConfiguration,
)
from azentspublicclient.models.discord_connection_credentials import (
    DiscordConnectionCredentials,
)
from azentspublicclient.models.discord_connection_setup_request import (
    DiscordConnectionSetupRequest,
)
from azentspublicclient.models.external_channel_access_grant_scope import (
    ExternalChannelAccessGrantScope,
)
from azentspublicclient.models.external_channel_access_request_status import (
    ExternalChannelAccessRequestStatus,
)
from azentspublicclient.models.external_channel_app_mode import ExternalChannelAppMode
from azentspublicclient.models.external_channel_channel_default_status import (
    ExternalChannelChannelDefaultStatus,
)
from azentspublicclient.models.external_channel_connection_status import (
    ExternalChannelConnectionStatus,
)
from azentspublicclient.models.external_channel_decision_input import (
    ExternalChannelDecisionInput,
)
from azentspublicclient.models.external_channel_response_mode import (
    ExternalChannelResponseMode,
)
from azentspublicclient.models.external_channel_route_catalog_status import (
    ExternalChannelRouteCatalogStatus,
)
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.external_channel_work_task_status import (
    ExternalChannelWorkTaskStatus,
)
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.multi_channel_default_request import (
    MultiChannelDefaultRequest,
)
from azentspublicclient.models.multi_route_create_request import MultiRouteCreateRequest
from azentspublicclient.models.response_mode_request import ResponseModeRequest
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
from azentspublicclient.models.workspace_user_role import WorkspaceUserRole
from docker.models.containers import Container
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
    wait_until,
)

_APP_ID = "A-E2E"
_TEAM_ID = "T-E2E"
_CHANNEL_ID = "C-E2E"
_BOT_TOKEN = "xoxb-e2e-private"
_SIGNING_SECRET = "e2e-signing-private"
_DISCORD_APPLICATION_ID = "100000000000000001"
_DISCORD_MULTI_APPLICATION_ID = "100000000000000002"
_DISCORD_SELECTOR_APPLICATION_ID = "100000000000000003"
_DISCORD_GUILD_ID = "200000000000000001"
_DISCORD_BOT_USER_ID = "300000000000000001"
_DISCORD_CHANNEL_ID = "400000000000000001"
_DISCORD_BOT_TOKEN = "discord-e2e-private"
_DISCORD_COMMAND_CONTRACTS = {
    "message_action": ("Ask an Azents Agent", 3),
    "azents_settings": ("Azents settings", 1),
    "conversation_settings": ("Conversation settings", 3),
}
_EXTERNAL_CHANNEL_LARGE_FILE_BYTES = 6 * 1024 * 1024


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
    *,
    runtime_profile_provider_id: str | None,
    shell_enabled: bool,
) -> tuple[str, str, str, str]:
    """Create an authenticated workspace administrator and one active Agent."""
    token, email, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        public_server_url,
        agent_count=1,
        runtime_profile_provider_id=runtime_profile_provider_id,
        shell_enabled=shell_enabled,
    )
    return token, email, handle, agent_ids[0]


def _wait_for_runtime_runner_ready(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Start and wait for the Agent Runtime Runner required by file transfer."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = {"Authorization": f"Bearer {token}"}
    api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace_handle,
        _headers=headers,
    )
    deadline = time.monotonic() + 120
    last_state: object | None = None
    while time.monotonic() < deadline:
        state = api.agent_runtime_v1_observe_agent_runtime(
            agent_id=agent_id,
            handle=workspace_handle,
            _headers=headers,
        )
        last_state = state
        if state.state.actions.use_runner:
            return
        time.sleep(1)
    raise AssertionError(f"Runtime Runner did not become ready: {last_state!r}")


def _create_workspace_agents(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
    *,
    agent_count: int,
    runtime_profile_provider_id: str | None,
    shell_enabled: bool,
) -> tuple[str, str, str, list[str]]:
    """Create one Workspace owner and a deterministic active Agent catalog."""
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"external-channel-{suffix}@example.com",
    )
    handle = f"external-channel-{suffix}"
    headers = {"Authorization": f"Bearer {token}"}
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"External Channel {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=(
            LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="__testenv_model_listing:deterministic-success",
                secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
            )
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        public_server_url,
        token,
        handle,
        integration.id,
    )
    runtime_profile_id = (
        create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id=runtime_profile_provider_id,
        )
        if runtime_profile_provider_id is not None
        else None
    )
    agent_api = AgentV1Api(public_api_client)
    agent_ids = [
        agent_api.agent_v1_create_agent(
            handle=handle,
            agent_create_request=AgentCreateRequest(
                name=f"External Channel Agent {index + 1} {suffix}",
                model_selection=model_selection,
                lightweight_model_selection=model_selection,
                type=AgentType.PUBLIC,
                runtime_profile_id=runtime_profile_id,
                shell_enabled=shell_enabled,
            ),
            _headers=headers,
        ).id
        for index in range(agent_count)
    ]
    return token, email, handle, agent_ids


def _invite_workspace_user(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    *,
    owner_token: str,
    handle: str,
    role: WorkspaceUserRole,
) -> str:
    """Create, invite, and accept one Workspace user through public APIs."""
    email = f"external-channel-{role.value}-{unique()}@example.com"
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=email,
    )
    invitation_api = InvitationV1Api(public_api_client)
    invitation = invitation_api.invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=email, role=role),
        _headers={"Authorization": f"Bearer {owner_token}"},
    )
    invitation_api.invitation_v1_accept_invitation(
        invitation.id,
        _headers={"Authorization": f"Bearer {token}"},
    )
    return token


def _signed_headers(
    body: bytes,
    *,
    content_type: str = "application/json",
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signing_base = b"v0:" + timestamp.encode() + b":" + body
    signature = (
        "v0="
        + hmac.new(
            _SIGNING_SECRET.encode(),
            signing_base,
            hashlib.sha256,
        ).hexdigest()
    )
    return {
        "Content-Type": content_type,
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }


def _provider_state(slack_provider_fake_url: str) -> dict[str, object]:
    response = requests.get(
        f"{slack_provider_fake_url}/__testenv/state",
        timeout=5,
    )
    response.raise_for_status()
    return cast(dict[str, object], response.json())


def _discord_provider_state(discord_provider_fake_url: str) -> dict[str, object]:
    """Return sanitized deterministic Discord fake evidence."""
    response = requests.get(
        f"{discord_provider_fake_url}/__testenv/state",
        timeout=5,
    )
    response.raise_for_status()
    return cast(dict[str, object], response.json())


def _discord_command_id(
    discord_provider_fake_url: str,
    *,
    role: str,
) -> str | None:
    """Return one transient current Discord command ID by required role."""
    response = requests.get(
        f"{discord_provider_fake_url}/__testenv/command-id",
        params={"role": role},
        timeout=5,
    )
    response.raise_for_status()
    command_id = response.json().get("command_id")
    return command_id if isinstance(command_id, str) and command_id else None


def _discord_settings_component_id(
    discord_provider_fake_url: str,
    *,
    action_code: str,
) -> str | None:
    """Consume transient settings controls until one requested action is found."""
    for _ in range(10):
        response = requests.get(
            f"{discord_provider_fake_url}/__testenv/transient-component",
            params={"scope": "settings"},
            timeout=5,
        )
        response.raise_for_status()
        custom_id = response.json().get("custom_id")
        if custom_id is None:
            return None
        if isinstance(custom_id, str) and custom_id.startswith(f"a:{action_code}:"):
            return custom_id
    raise AssertionError("Discord settings control queue exceeded its bounded size.")


def _open_discord_settings(
    *,
    discord_provider_fake_url: str,
    interaction_id: str,
    application_id: str,
    guild_id: str,
    channel_id: str,
    user_id: str,
) -> None:
    """Open parent settings through the capability-proven Discord command."""
    command_id = cast(
        str,
        wait_until(
            lambda: _discord_command_id(
                discord_provider_fake_url,
                role="azents_settings",
            ),
            timeout=15,
            interval=0.2,
            message="Discord settings command ID was not reconciled",
        ),
    )
    command_name, command_type = _DISCORD_COMMAND_CONTRACTS["azents_settings"]
    response = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": interaction_id,
            "type": 2,
            "application_id": application_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "channel": {"id": channel_id, "type": 0},
            "member": {"user": {"id": user_id}},
            "data": {
                "id": command_id,
                "name": command_name,
                "type": command_type,
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    assert response.json() == {"status": 200, "response_type": 4}


def _select_discord_setup_location(
    *,
    discord_provider_fake_url: str,
    interaction_id: str,
    application_id: str,
    guild_id: str,
    channel_id: str,
    user_id: str,
    custom_id: str,
) -> None:
    """Commit one signed Discord setup component through the real callback."""
    response = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": interaction_id,
            "type": 3,
            "application_id": application_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "channel": {"id": channel_id, "type": 0},
            "member": {"user": {"id": user_id}},
            "message": {"id": f"message-{interaction_id}"},
            "data": {"custom_id": custom_id},
        },
        timeout=10,
    )
    response.raise_for_status()
    assert response.json() == {"status": 200, "response_type": 7}


def _successful_session_paths(provider_state: dict[str, object]) -> list[str]:
    """Return sanitized Session routes from successful provider controls."""
    deliveries = provider_state.get("deliveries")
    if not isinstance(deliveries, list):
        return []
    paths: list[str] = []
    for raw_delivery in cast(list[object], deliveries):
        if not isinstance(raw_delivery, dict):
            continue
        delivery = cast(dict[str, object], raw_delivery)
        path = delivery.get("session_path")
        if delivery.get("outcome") in {
            "delivered",
            "created",
            "duplicate",
        } and isinstance(path, str):
            paths.append(path)
    return paths


def _successful_session_presence_states(
    provider_state: dict[str, object],
) -> list[str]:
    """Return sanitized joined/left evidence from successful provider controls."""
    deliveries = provider_state.get("deliveries")
    if not isinstance(deliveries, list):
        return []
    states: list[str] = []
    for raw_delivery in cast(list[object], deliveries):
        if not isinstance(raw_delivery, dict):
            continue
        delivery = cast(dict[str, object], raw_delivery)
        category = delivery.get("safe_category")
        if delivery.get("outcome") not in {"delivered", "created", "duplicate"}:
            continue
        if category == "session_presence_joined":
            states.append("joined")
        elif category == "session_presence_left":
            states.append("left")
    return states


def _external_channel_input_evidence(
    *,
    public_server_url: str,
    token: str,
    session_id: str,
    include_pending: bool = True,
) -> list[dict[str, object]]:
    """Read logical External Channel input through public live and history APIs."""
    history_response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    history_response.raise_for_status()

    candidates: list[dict[str, object]] = []
    if include_pending:
        live_response = requests.get(
            f"{public_server_url}/chat/v1/sessions/{session_id}/live",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        live_response.raise_for_status()
        live_payload = live_response.json()
        if isinstance(live_payload, dict):
            envelopes = cast(dict[str, object], live_payload).get("mailbox_items")
            if isinstance(envelopes, list):
                for raw_envelope in cast(list[object], envelopes):
                    if not isinstance(raw_envelope, dict):
                        continue
                    envelope = cast(dict[str, object], raw_envelope)
                    if envelope.get("kind") != "external_channel_invocation":
                        continue
                    raw_items = envelope.get("items")
                    if not isinstance(raw_items, list):
                        continue
                    for raw_item in cast(list[object], raw_items):
                        if not isinstance(raw_item, dict):
                            continue
                        presentation = cast(dict[str, object], raw_item).get(
                            "presentation"
                        )
                        if not isinstance(presentation, dict):
                            continue
                        presentation_item = cast(dict[str, object], presentation)
                        if presentation_item.get("type") == "external_channel_message":
                            candidates.append(presentation_item)

    history_payload = history_response.json()
    if isinstance(history_payload, dict):
        events = cast(dict[str, object], history_payload).get("items")
        if isinstance(events, list):
            for raw_event in cast(list[object], events):
                if not isinstance(raw_event, dict):
                    continue
                event = cast(dict[str, object], raw_event)
                event_payload = event.get("payload")
                if event.get("kind") == "external_channel_message" and isinstance(
                    event_payload, dict
                ):
                    candidates.append(cast(dict[str, object], event_payload))

    logical_items: dict[tuple[str, str], dict[str, object]] = {}
    for candidate in candidates:
        provider = candidate.get("provider")
        external_message_id = candidate.get("external_message_id")
        if not all(
            isinstance(value, str) and value
            for value in (provider, external_message_id)
        ):
            continue
        key = (cast(str, provider), cast(str, external_message_id))
        evidence = {
            "provider": provider,
            "external_message_id": external_message_id,
            "authorization": candidate.get("authorization"),
            "body": candidate.get("body"),
            "original_url": candidate.get("original_url"),
        }
        previous = logical_items.get(key)
        if previous is not None and previous != evidence:
            raise AssertionError(
                "Public live and history projections disagree for one "
                f"External Channel message: {key!r}"
            )
        logical_items[key] = evidence
    return list(logical_items.values())


def _approval_request_id(slack_provider_fake_url: str) -> str:
    state = _provider_state(slack_provider_fake_url)
    deliveries = state.get("deliveries")
    if not isinstance(deliveries, list):
        return ""
    for raw_delivery in cast(list[object], deliveries):
        if not isinstance(raw_delivery, dict):
            continue
        delivery = cast(dict[str, object], raw_delivery)
        request_id = delivery.get("approval_request_id")
        if isinstance(request_id, str) and request_id:
            return request_id
    return ""


def _selector_admission_id(slack_provider_fake_url: str) -> str:
    """Return the latest opaque admission exposed by a selector control."""
    deliveries = _provider_state(slack_provider_fake_url).get("deliveries")
    if not isinstance(deliveries, list):
        return ""
    for raw_delivery in reversed(cast(list[object], deliveries)):
        if not isinstance(raw_delivery, dict):
            continue
        admission_id = cast(dict[str, object], raw_delivery).get(
            "selector_admission_id"
        )
        if isinstance(admission_id, str) and admission_id:
            return admission_id
    return ""


def _latest_selector_view(
    slack_provider_fake_url: str,
) -> dict[str, object] | None:
    """Return the transient selector handoff without exposing it as evidence."""
    response = requests.get(
        f"{slack_provider_fake_url}/__testenv/transient-view",
        params={"scope": "selector"},
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    return cast(dict[str, object], payload) if isinstance(payload, dict) else None


def _latest_setup_view(
    slack_provider_fake_url: str,
) -> dict[str, object] | None:
    """Return the transient setup handoff without exposing it as evidence."""
    response = requests.get(
        f"{slack_provider_fake_url}/__testenv/transient-view",
        params={"scope": "setup"},
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    return cast(dict[str, object], payload) if isinstance(payload, dict) else None


def _open_slack_setup_modal(
    *,
    callback_url: str,
    app_id: str,
    team_id: str,
    channel_id: str,
    user_id: str,
) -> None:
    """Open the pending parent setup modal through Slack's signed command flow."""
    command_body = urlencode(
        {
            "command": "/azents",
            "text": "settings",
            "api_app_id": app_id,
            "team_id": team_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "trigger_id": f"trigger-setup-{unique()}",
        }
    ).encode()
    response = requests.post(
        callback_url,
        data=command_body,
        headers=_signed_headers(
            command_body,
            content_type="application/x-www-form-urlencoded",
        ),
        timeout=5,
    )
    assert response.status_code == 200


def _submit_slack_setup_location(
    *,
    callback_url: str,
    app_id: str,
    team_id: str,
    user_id: str,
    setup_view: dict[str, object],
    location: str = "threads",
) -> None:
    """Commit one signed Slack setup location selection through the real callback."""
    metadata = setup_view.get("private_metadata")
    view_id = setup_view.get("view_id")
    view_hash = setup_view.get("view_hash")
    assert isinstance(metadata, str) and metadata
    assert isinstance(view_id, str) and view_id
    assert isinstance(view_hash, str) and view_hash
    submission_payload = {
        "type": "view_submission",
        "api_app_id": app_id,
        "team": {"id": team_id},
        "user": {"id": user_id},
        "trigger_id": f"trigger-setup-submission-{unique()}",
        "view": {
            "id": view_id,
            "hash": view_hash,
            "callback_id": "azents_conversation_setup",
            "private_metadata": metadata,
            "state": {
                "values": {
                    "azents_conversation_location": {
                        "azents_conversation_location": {
                            "selected_option": {"value": location}
                        }
                    }
                }
            },
        },
    }
    submission_body = urlencode(
        {"payload": json.dumps(submission_payload, separators=(",", ":"))}
    ).encode()
    response = requests.post(
        callback_url,
        data=submission_body,
        headers=_signed_headers(
            submission_body,
            content_type="application/x-www-form-urlencoded",
        ),
        timeout=5,
    )
    assert response.status_code == 200


def _assert_no_pending_slack_participation_lifecycle(
    *,
    chat_api: ChatV1Api,
    external_api: ExternalChannelV1Api,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    baseline_session_ids: set[str] | None,
) -> None:
    """Assert setup has not created a Session or External Channel Binding."""
    sessions = chat_api.chat_v1_list_agent_sessions(
        agent_id=agent_id,
        _headers=headers,
    )
    if baseline_session_ids is not None:
        assert {session.id for session in sessions.items} == baseline_session_ids
    for session in sessions.items:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=session.id,
            handle=handle,
            _headers=headers,
        )
        assert projection.items == []


def _plan_delivery(slack_provider_fake_url: str) -> dict[str, object] | None:
    """Return the latest captured Slack Plan mutation."""
    deliveries = _provider_state(slack_provider_fake_url).get("deliveries")
    if not isinstance(deliveries, list):
        return None
    for raw_delivery in reversed(cast(list[object], deliveries)):
        if not isinstance(raw_delivery, dict):
            continue
        delivery = cast(dict[str, object], raw_delivery)
        blocks = delivery.get("blocks")
        if (
            delivery.get("operation") == "chat.update"
            and isinstance(blocks, list)
            and any(
                isinstance(block, dict)
                and cast(dict[str, object], block).get("type") == "plan"
                for block in cast(list[object], blocks)
            )
        ):
            return delivery
    return None


def _progress_request_evidence(openai_proxy_url: str) -> list[dict[str, object]]:
    """Return sanitized model-request evidence for the progress journey."""
    response = requests.get(
        f"{openai_proxy_url}/v1/_external_channel_progress_requests",
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [
        cast(dict[str, object], item)
        for item in cast(list[object], payload)
        if isinstance(item, dict)
    ]


def _file_request_evidence(openai_proxy_url: str) -> list[dict[str, object]]:
    """Return sanitized model-request evidence for the file-transfer journey."""
    response = requests.get(
        f"{openai_proxy_url}/v1/_external_channel_file_requests",
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [
        cast(dict[str, object], item)
        for item in cast(list[object], payload)
        if isinstance(item, dict)
    ]


def _channel_action_tool_evidence(
    public_server_url: str,
    token: str,
    session_id: str,
    *,
    call_ids: frozenset[str],
) -> list[dict[str, object]]:
    """Return sanitized Channel Action call and result evidence."""
    response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    items = cast(dict[str, object], payload).get("items")
    if not isinstance(items, list):
        return []
    evidence: list[dict[str, object]] = []
    for raw_event in cast(list[object], items):
        if not isinstance(raw_event, dict):
            continue
        event = cast(dict[str, object], raw_event)
        kind = event.get("kind")
        if kind not in {"client_tool_call", "client_tool_result"}:
            continue
        raw_payload = event.get("payload")
        if not isinstance(raw_payload, dict):
            continue
        event_payload = cast(dict[str, object], raw_payload)
        if event_payload.get("call_id") not in call_ids:
            continue
        item: dict[str, object] = {
            "kind": kind,
            "call_id": event_payload.get("call_id"),
            "name": event_payload.get("name"),
        }
        status = event_payload.get("status")
        if isinstance(status, str):
            item["status"] = status
        output = event_payload.get("output")
        if isinstance(output, list):
            texts = [
                cast(dict[str, object], part).get("text")
                for part in cast(list[object], output)
                if isinstance(part, dict)
                and isinstance(cast(dict[str, object], part).get("text"), str)
            ]
            if texts:
                item["output"] = " ".join(cast(list[str], texts))[:1_000]
        evidence.append(item)
    return evidence


def _matching_progress_request_evidence(
    openai_proxy_url: str,
    binding_id: str,
) -> list[dict[str, object]]:
    """Return request evidence after direct Channel Action progress is observed."""
    expected = {
        "binding": binding_id,
        "marker_present": True,
        "resolved_user_reference": True,
        "resolved_channel_reference": True,
        "search_tool_available": False,
        "progress_tool_available": True,
        "path": "/v1/responses",
        "matched": True,
        "stage": "after_progress",
    }
    evidence = _progress_request_evidence(openai_proxy_url)
    observed = sorted(
        {
            "user={user},channel={channel},search={search},progress={progress},"
            "matched={matched},stage={stage}".format(
                user=item.get("resolved_user_reference"),
                channel=item.get("resolved_channel_reference"),
                search=item.get("search_tool_available"),
                progress=item.get("progress_tool_available"),
                matched=item.get("matched"),
                stage=item.get("stage"),
            )
            for item in evidence
            if item.get("binding") == binding_id
        }
    )
    assert any(
        all(item.get(key) == value for key, value in expected.items())
        for item in evidence
    ), (
        "expected direct Channel Action progress without Tool Search; "
        f"observed={observed!r}"
    )
    return evidence


def _login_main_web(
    driver: WebDriver,
    *,
    main_web_url: str,
    email: str,
) -> None:
    """Log in through the real Main Web password flow."""
    driver.delete_all_cookies()
    driver.get(f"{main_web_url}/login")
    wait = WebDriverWait(driver, 30)
    email_input = wait.until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    wait.until(ec.url_contains("/login/password"))
    password_input = wait.until(ec.element_to_be_clickable((By.NAME, "password")))
    password_input.send_keys("TestPass123!", Keys.ENTER)
    wait.until(ec.url_contains("/workspaces"))


def test_http_admission_unknown_participant_and_approval_journey(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    slack_provider_fake_url: str,
) -> None:
    """Exercise connection setup, signed admission, dedupe, and idempotent approval."""
    del azents_engine_worker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    root_timestamp = f"{int(time.time()) - 60}.000100"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-EXTERNAL",
                        "ts": root_timestamp,
                        "text": "Please investigate the deterministic incident.",
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )

    def disconnect_connection() -> None:
        external_api.external_channel_v1_disconnect_connection(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    assert setup.connection.credentials_configured is True
    setup_json = setup.model_dump_json(by_alias=True)
    assert _BOT_TOKEN not in setup_json
    assert _SIGNING_SECRET not in setup_json
    restricted_policy = (
        external_api.external_channel_v1_update_connection_access_policy(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            connection_access_policy_request=ConnectionAccessPolicyRequest(
                open_access_enabled=False,
            ),
            _headers=headers,
        )
    )
    assert restricted_policy.open_access_enabled is False

    validated = external_api.external_channel_v1_validate_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE
    assert validated.identity is not None
    assert validated.identity.tenant_id == _TEAM_ID
    assert set(validated.credentials.configured_fields) == {
        "bot_token",
        "signing_secret",
    }
    assert validated.capabilities is not None
    assert validated.capabilities.thread_history is True

    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }
    challenge_body = json.dumps(
        {
            "type": "url_verification",
            "challenge": "deterministic-challenge",
        },
        separators=(",", ":"),
    ).encode()
    started = time.monotonic()
    challenge = requests.post(
        callback_url,
        data=challenge_body,
        headers=_signed_headers(challenge_body),
        timeout=5,
    )
    assert time.monotonic() - started < 2
    assert challenge.json() == {"challenge": "deterministic-challenge"}

    event_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _APP_ID,
            "team_id": _TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": _CHANNEL_ID,
                "channel_type": "channel",
                "user": "U-EXTERNAL",
                "text": "<@B-E2E> investigate",
                "ts": root_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    started = time.monotonic()
    first = requests.post(
        callback_url,
        data=event_body,
        headers=_signed_headers(event_body),
        timeout=5,
    )
    assert first.status_code == 200
    assert time.monotonic() - started < 2
    duplicate = requests.post(
        callback_url,
        data=event_body,
        headers=_signed_headers(event_body),
        timeout=5,
    )
    assert duplicate.status_code == 200

    request_id = wait_until(
        lambda: _approval_request_id(slack_provider_fake_url),
        timeout=15,
        interval=0.2,
        message="Unknown participant approval control message was not delivered",
    )

    approval = external_api.external_channel_v1_get_approval_request(
        access_request_id=request_id,
        _headers=headers,
    )
    assert approval.status is ExternalChannelAccessRequestStatus.PENDING
    assert approval.agent_id == agent_id
    assert approval.principal_provider_user_id
    assert approval.resource_label
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )

    decision = ExternalChannelDecisionInput(
        decision="allow_agent",
        summary="Deterministic E2E approval",
    )
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=decision,
        _headers=headers,
    )
    assert decided.status is ExternalChannelAccessRequestStatus.ALLOWED
    assert decided.agent_session_id is None
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    _open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        channel_id=_CHANNEL_ID,
        user_id="U-EXTERNAL",
    )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Approved Slack setup did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        user_id="U-EXTERNAL",
        setup_view=setup_view,
    )

    def binding_projection() -> tuple[str, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session.id, projection
        return None

    approved_session_id, bindings = cast(
        tuple[str, Any],
        wait_until(
            binding_projection,
            timeout=10,
            interval=0.2,
            message="Approved External Channel binding was not available",
        ),
    )
    assert len(bindings.items) == 1
    assert bindings.grants == []
    sessions = chat_api.chat_v1_list_agent_sessions(
        agent_id=agent_id,
        _headers=headers,
    )
    assert approved_session_id in [session.id for session in sessions.items]
    detail = chat_api.chat_v1_get_agent_session(
        agent_id=agent_id,
        session_id=approved_session_id,
        _headers=headers,
    )
    assert detail.id == approved_session_id
    agent_access = external_api.external_channel_v1_list_agent_access(
        agent_id=agent_id,
        handle=handle,
        _headers=headers,
    )
    assert len(agent_access.grants) == 1
    assert agent_access.grants[0].scope is ExternalChannelAccessGrantScope.AGENT
    assert agent_access.grants[0].agent_session_id is None
    input_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=token,
                        session_id=approved_session_id,
                        include_pending=False,
                    )
                )
                == 1
                else None
            ),
            timeout=30,
            interval=0.2,
            message="Approved Slack input was not promoted into Session history",
        ),
    )
    assert len(input_evidence) == 1
    logical_input = input_evidence[0]
    assert logical_input["provider"] == "slack"
    assert logical_input["external_message_id"]
    assert logical_input["authorization"] == "authorized_invocation"
    assert logical_input["body"] == "Please investigate the deterministic incident."
    assert logical_input["original_url"] == (
        f"https://example.slack.com/archives/{_CHANNEL_ID}/p"
        f"{root_timestamp.replace('.', '')}"
    )

    def settled_provider_controls() -> dict[str, object] | None:
        state = _provider_state(slack_provider_fake_url)
        counts = state.get("request_counts")
        if not isinstance(counts, dict):
            return None
        typed = cast(dict[str, Any], counts)
        if typed.get("chat.postMessage") == 4 and typed.get("chat.delete") == 1:
            return state
        return None

    provider_state = cast(
        dict[str, object],
        wait_until(
            settled_provider_controls,
            timeout=10,
            interval=0.2,
            message="Slack approval and initial progress controls did not settle",
        ),
    )
    request_counts = provider_state.get("request_counts")
    assert isinstance(request_counts, dict)
    typed_counts = cast(dict[str, Any], request_counts)
    assert "conversations.info" not in typed_counts
    # The initial callback, duplicate delivery, and Allow replay each revalidate
    # provider history before one mailbox input wins.
    assert typed_counts["conversations.history"] == 3
    assert typed_counts["chat.getPermalink"] == 3
    # One access-review control is deleted after approval. Durable acceptance then
    # delivers joined presence, initial progress, and the versioned settings control.
    assert typed_counts["chat.postMessage"] == 4
    assert typed_counts["chat.delete"] == 1
    assert _successful_session_paths(provider_state) == [
        f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}",
        f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}",
    ]
    assert _successful_session_presence_states(provider_state) == ["joined"]
    deliveries = cast(list[dict[str, object]], provider_state["deliveries"])
    assert any(
        delivery.get("session_path")
        == f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}"
        and delivery.get("safe_category") is None
        and delivery.get("action_ids")
        == ["view_azents_session", "azents_conversation_settings_open"]
        for delivery in deliveries
    )
    rendered_state = str(provider_state)
    assert _BOT_TOKEN not in rendered_state
    assert _SIGNING_SECRET not in rendered_state

    disconnected = external_api.external_channel_v1_disconnect_session_channel(
        agent_id=agent_id,
        session_id=approved_session_id,
        binding_id=bindings.items[0].id,
        handle=handle,
        _headers=headers,
    )
    assert len(disconnected.items) == 1
    assert disconnected.items[0].disconnected_at is not None

    disconnected_state = cast(
        dict[str, object],
        wait_until(
            lambda: (
                state
                if (
                    _successful_session_presence_states(
                        state := _provider_state(slack_provider_fake_url)
                    )
                    == ["joined", "left"]
                    and cast(dict[str, Any], state["request_counts"]).get("chat.delete")
                    == 2
                )
                else None
            ),
            timeout=10,
            interval=0.2,
            message="Manual Slack binding disconnect did not deliver leave presence",
        ),
    )
    disconnected_counts = cast(dict[str, Any], disconnected_state["request_counts"])
    assert disconnected_counts["chat.postMessage"] == 5
    assert disconnected_counts["chat.delete"] == 2
    assert _successful_session_paths(disconnected_state) == [
        f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}",
        f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}",
        f"/w/{handle}/agents/{agent_id}/sessions/{approved_session_id}",
    ]

    revocation_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _APP_ID,
            "team_id": _TEAM_ID,
            "event": {"type": "app_uninstalled"},
        },
        separators=(",", ":"),
    ).encode()
    revocation = requests.post(
        callback_url,
        data=revocation_body,
        headers=_signed_headers(revocation_body),
        timeout=5,
    )
    assert revocation.status_code == 200

    def revoked_connection() -> object | None:
        connections = external_api.external_channel_v1_list_connections(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        )
        return True if connections.items == [] else None

    wait_until(
        revoked_connection,
        timeout=10,
        interval=0.2,
        message="Slack uninstall did not remove the connection from active management",
    )


def test_connection_update_and_repeated_disconnect(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Correct a wrong App ID, then disconnect safely more than once."""
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id="A-WRONG",
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    assert setup.connection.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED

    updated = external_api.external_channel_v1_update_slack_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    assert updated.status is ExternalChannelConnectionStatus.ACTIVE
    assert updated.identity is not None
    assert updated.identity.app_id == _APP_ID

    first = external_api.external_channel_v1_disconnect_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert first.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert first.credentials_configured is False
    assert (
        external_api.external_channel_v1_list_connections(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        ).items
        == []
    )

    repeated = external_api.external_channel_v1_disconnect_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert repeated.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert repeated.credentials_configured is False


def test_slack_binding_response_modes_gate_and_preserve_context(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Exercise creation-time copy, mention gating, context, and mode updates."""
    del azents_engine_worker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    root_seconds = int(time.time()) - 60
    root_timestamp = f"{root_seconds}.000210"
    root_body = "Initial response-mode invocation"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-MODE",
                        "ts": root_timestamp,
                        "text": root_body,
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    initial = external_api.external_channel_v1_list_connections(
        agent_id=agent_id,
        handle=handle,
        _headers=headers,
    )
    assert initial.default_response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    saved_default = external_api.external_channel_v1_update_default_response_mode(
        agent_id=agent_id,
        handle=handle,
        response_mode_request=ResponseModeRequest(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
        _headers=headers,
    )
    assert saved_default.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )

    def disconnect_connection() -> None:
        external_api.external_channel_v1_disconnect_connection(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    external_api.external_channel_v1_validate_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }

    def send_event(event: dict[str, object]) -> None:
        body = json.dumps(
            {
                "type": "event_callback",
                "event_id": f"Ev-{unique()}",
                "event_time": int(time.time()),
                "api_app_id": _APP_ID,
                "team_id": _TEAM_ID,
                "event": event,
            },
            separators=(",", ":"),
        ).encode()
        response = requests.post(
            callback_url,
            data=body,
            headers=_signed_headers(body),
            timeout=5,
        )
        assert response.status_code == 200

    send_event(
        {
            "type": "app_mention",
            "channel": _CHANNEL_ID,
            "channel_type": "channel",
            "user": "U-MODE",
            "text": "<@B-E2E> start",
            "ts": root_timestamp,
        }
    )
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    _open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        channel_id=_CHANNEL_ID,
        user_id="U-MODE",
    )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Slack response-mode setup did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        user_id="U-MODE",
        setup_view=setup_view,
    )

    def find_binding() -> tuple[Any, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session, projection.items[0]
        return None

    session, binding = cast(
        tuple[Any, Any],
        wait_until(
            find_binding,
            timeout=15,
            interval=0.2,
            message="Slack response-mode invocation did not create one binding",
        ),
    )
    assert binding.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    wait_until(
        lambda: (
            evidence
            if len(
                evidence := _external_channel_input_evidence(
                    public_server_url=azents_public_server_url,
                    token=token,
                    session_id=session.id,
                    include_pending=False,
                )
            )
            == 1
            else None
        ),
        timeout=30,
        interval=0.2,
        message="Initial Slack response-mode input was not promoted",
    )

    before_counts = cast(
        dict[str, int],
        _provider_state(slack_provider_fake_url)["request_counts"],
    )
    before_history_reads = before_counts.get(
        "conversations.history", 0
    ) + before_counts.get("conversations.replies", 0)
    ordinary_timestamp = f"{root_seconds + 1}.000210"
    ordinary_body = "Context retained without an invocation"
    send_event(
        {
            "type": "message",
            "channel": _CHANNEL_ID,
            "channel_type": "channel",
            "user": "U-MODE",
            "text": ordinary_body,
            "ts": ordinary_timestamp,
            "thread_ts": root_timestamp,
        }
    )
    after_ignored_counts = cast(
        dict[str, int],
        _provider_state(slack_provider_fake_url)["request_counts"],
    )
    assert (
        after_ignored_counts.get("conversations.history", 0)
        + after_ignored_counts.get("conversations.replies", 0)
        == before_history_reads
    )
    assert (
        len(
            _external_channel_input_evidence(
                public_server_url=azents_public_server_url,
                token=token,
                session_id=session.id,
                include_pending=False,
            )
        )
        == 1
    )

    mention_timestamp = f"{root_seconds + 2}.000210"
    mention_body = "<@B-E2E> use the retained context"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-MODE",
                        "ts": mention_timestamp,
                        "thread_ts": root_timestamp,
                        "text": mention_body,
                    },
                    {
                        "user": "U-MODE",
                        "ts": ordinary_timestamp,
                        "thread_ts": root_timestamp,
                        "text": ordinary_body,
                    },
                    {
                        "user": "U-MODE",
                        "ts": root_timestamp,
                        "text": root_body,
                    },
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    send_event(
        {
            "type": "app_mention",
            "channel": _CHANNEL_ID,
            "channel_type": "channel",
            "user": "U-MODE",
            "text": mention_body,
            "ts": mention_timestamp,
            "thread_ts": root_timestamp,
        }
    )
    mention_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=token,
                        session_id=session.id,
                        include_pending=False,
                    )
                )
                == 3
                else None
            ),
            timeout=30,
            interval=0.2,
            message="Later Slack mention did not include retained context",
        ),
    )
    assert ordinary_body in {item["body"] for item in mention_evidence}

    updated = external_api.external_channel_v1_update_session_channel_response_mode(
        agent_id=agent_id,
        session_id=session.id,
        binding_id=binding.id,
        handle=handle,
        response_mode_request=ResponseModeRequest(
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES
        ),
        _headers=headers,
    )
    assert updated.response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    continuation_timestamp = f"{root_seconds + 3}.000210"
    continuation_body = "All-messages continuation"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-MODE",
                        "ts": continuation_timestamp,
                        "thread_ts": root_timestamp,
                        "text": continuation_body,
                    },
                    {
                        "user": "U-MODE",
                        "ts": mention_timestamp,
                        "thread_ts": root_timestamp,
                        "text": mention_body,
                    },
                    {
                        "user": "U-MODE",
                        "ts": ordinary_timestamp,
                        "thread_ts": root_timestamp,
                        "text": ordinary_body,
                    },
                    {
                        "user": "U-MODE",
                        "ts": root_timestamp,
                        "text": root_body,
                    },
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    send_event(
        {
            "type": "message",
            "channel": _CHANNEL_ID,
            "channel_type": "channel",
            "user": "U-MODE",
            "text": continuation_body,
            "ts": continuation_timestamp,
            "thread_ts": root_timestamp,
        }
    )
    continuation_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=token,
                        session_id=session.id,
                        include_pending=False,
                    )
                )
                == 4
                else None
            ),
            timeout=30,
            interval=0.2,
            message="All-messages Slack continuation was not admitted",
        ),
    )
    assert continuation_body in {item["body"] for item in continuation_evidence}

    disconnected = external_api.external_channel_v1_disconnect_session_channel(
        agent_id=agent_id,
        session_id=session.id,
        binding_id=binding.id,
        handle=handle,
        _headers=headers,
    )
    assert (
        disconnected.items[0].response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    )
    with pytest.raises(ApiException) as disconnected_update:
        external_api.external_channel_v1_update_session_channel_response_mode(
            agent_id=agent_id,
            session_id=session.id,
            binding_id=binding.id,
            handle=handle,
            response_mode_request=ResponseModeRequest(
                response_mode=ExternalChannelResponseMode.MENTION_ONLY
            ),
            _headers=headers,
        )
    assert cast(Any, disconnected_update.value).status == 404


def test_multi_app_workspace_management_default_and_disconnect_journey(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Exercise Workspace authority, catalog, generation fences, and lifecycle."""
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "provider_app_id": "A-MULTI-E2E",
            "provider_team_id": "T-MULTI-E2E",
            "provider_bot_user_id": "U-BOT-MULTI-E2E",
        },
        timeout=5,
    ).raise_for_status()
    owner_token, _, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        agent_count=2,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    manager_token = _invite_workspace_user(
        public_api_client,
        admin_api_client,
        owner_token=owner_token,
        handle=handle,
        role=WorkspaceUserRole.MANAGER,
    )
    member_token = _invite_workspace_user(
        public_api_client,
        admin_api_client,
        owner_token=owner_token,
        handle=handle,
        role=WorkspaceUserRole.MEMBER,
    )
    external_api = ExternalChannelV1Api(public_api_client)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}

    with pytest.raises(ApiException) as member_error:
        external_api.external_channel_v1_list_multi_slack_connections(
            handle=handle,
            _headers=member_headers,
        )
    assert cast(Any, member_error.value).status == 403

    setup = external_api.external_channel_v1_setup_multi_slack_connection(
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id="A-MULTI-E2E",
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=manager_headers,
    )
    validation = external_api.external_channel_v1_validate_multi_slack_connection(
        connection_id=setup.connection.id,
        handle=handle,
        _headers=manager_headers,
    )
    assert validation.status is ExternalChannelConnectionStatus.ACTIVE
    connection = setup.connection
    assert connection.app_mode is ExternalChannelAppMode.MULTI
    assert connection.status is ExternalChannelConnectionStatus.ACTIVE
    assert connection.active_agent_count == 0
    assert connection.configured_default_count == 0
    assert connection.credentials_configured is True
    setup_json = setup.model_dump_json(by_alias=True)
    assert _BOT_TOKEN not in setup_json
    assert _SIGNING_SECRET not in setup_json

    first_route = external_api.external_channel_v1_add_multi_slack_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[0]),
        _headers=manager_headers,
    )
    duplicate_route = external_api.external_channel_v1_add_multi_slack_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[0]),
        _headers=manager_headers,
    )
    second_route = external_api.external_channel_v1_add_multi_slack_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[1]),
        _headers=owner_headers,
    )
    assert duplicate_route.id == first_route.id
    routes = external_api.external_channel_v1_list_multi_slack_routes(
        connection_id=connection.id,
        handle=handle,
        _headers=manager_headers,
    )
    assert [route.id for route in routes.items] == [first_route.id, second_route.id]
    assert all(
        route.catalog_status is ExternalChannelRouteCatalogStatus.AVAILABLE
        for route in routes.items
    )

    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "provider_app_id": "A-MULTI-E2E-SECOND",
            "provider_team_id": "T-MULTI-E2E",
            "provider_bot_user_id": "U-BOT-MULTI-E2E",
        },
        timeout=5,
    ).raise_for_status()
    second_setup = external_api.external_channel_v1_setup_multi_slack_connection(
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id="A-MULTI-E2E-SECOND",
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=owner_headers,
    )
    shared_agent_route = external_api.external_channel_v1_add_multi_slack_route(
        connection_id=second_setup.connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[0]),
        _headers=owner_headers,
    )
    assert second_setup.connection.id != connection.id
    assert shared_agent_route.agent_id == agent_ids[0]

    current = external_api.external_channel_v1_get_multi_slack_connection(
        connection_id=connection.id,
        handle=handle,
        _headers=owner_headers,
    )
    channel_default = (
        external_api.external_channel_v1_replace_multi_slack_channel_default(
            connection_id=connection.id,
            provider_channel_id=_CHANNEL_ID,
            handle=handle,
            multi_channel_default_request=MultiChannelDefaultRequest(
                expected_generation=current.generation,
                route_id=first_route.id,
            ),
            _headers=manager_headers,
        )
    )
    assert channel_default.channel_default is not None
    assert channel_default.channel_default.route_id == first_route.id
    assert channel_default.channel_default.agent_id == agent_ids[0]
    assert (
        channel_default.channel_default.status
        is ExternalChannelChannelDefaultStatus.ACTIVE
    )
    assert channel_default.invalidated_participation_setting_count == 0
    assert channel_default.terminated_setup_claim_count == 0
    assert channel_default.disconnected_parent_binding_count == 0

    with pytest.raises(ApiException) as stale_error:
        external_api.external_channel_v1_clear_multi_slack_channel_default(
            connection_id=connection.id,
            provider_channel_id=_CHANNEL_ID,
            handle=handle,
            generation_fence_request=GenerationFenceRequest(
                expected_generation=current.generation,
            ),
            _headers=manager_headers,
        )
    assert cast(Any, stale_error.value).status == 409

    route_impact = external_api.external_channel_v1_get_multi_slack_route_impact(
        connection_id=connection.id,
        route_id=first_route.id,
        handle=handle,
        _headers=owner_headers,
    )
    assert route_impact.active_default_count == 1
    assert route_impact.active_binding_count == 0
    removed = external_api.external_channel_v1_remove_multi_slack_route(
        connection_id=connection.id,
        route_id=first_route.id,
        handle=handle,
        generation_fence_request=GenerationFenceRequest(
            expected_generation=route_impact.generation,
        ),
        _headers=manager_headers,
    )
    assert removed.route_id == first_route.id
    assert removed.active_default_count == 1

    routes_after_removal = external_api.external_channel_v1_list_multi_slack_routes(
        connection_id=connection.id,
        handle=handle,
        _headers=owner_headers,
    )
    by_id = {route.id: route for route in routes_after_removal.items}
    assert (
        by_id[first_route.id].catalog_status
        is ExternalChannelRouteCatalogStatus.REMOVED
    )
    assert (
        by_id[second_route.id].catalog_status
        is ExternalChannelRouteCatalogStatus.AVAILABLE
    )
    defaults = external_api.external_channel_v1_list_multi_slack_channel_defaults(
        connection_id=connection.id,
        handle=handle,
        _headers=owner_headers,
    )
    assert len(defaults.items) == 1
    assert defaults.items[0].status is ExternalChannelChannelDefaultStatus.INVALIDATED

    foreign_token, _, foreign_handle, _ = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        agent_count=1,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    with pytest.raises(ApiException) as foreign_error:
        external_api.external_channel_v1_get_multi_slack_connection(
            connection_id=connection.id,
            handle=foreign_handle,
            _headers={"Authorization": f"Bearer {foreign_token}"},
        )
    assert cast(Any, foreign_error.value).status == 404

    connection_impact = (
        external_api.external_channel_v1_get_multi_slack_connection_impact(
            connection_id=connection.id,
            handle=handle,
            _headers=manager_headers,
        )
    )
    assert connection_impact.active_route_count == 1
    disconnected = external_api.external_channel_v1_disconnect_multi_slack_connection(
        connection_id=connection.id,
        handle=handle,
        generation_fence_request=GenerationFenceRequest(
            expected_generation=connection_impact.generation,
        ),
        _headers=manager_headers,
    )
    assert disconnected.disconnected_route_count == 1
    historical = external_api.external_channel_v1_get_multi_slack_connection(
        connection_id=connection.id,
        handle=handle,
        _headers=owner_headers,
    )
    assert historical.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert historical.credentials_configured is False


def test_multi_app_mention_selector_deduplicates_and_binds_open_access_route(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    slack_provider_fake_url: str,
) -> None:
    """Select once from an unconfigured mention and bind the open route once."""
    del azents_engine_worker_container
    app_id = "A-MULTI-SELECTOR"
    team_id = "T-MULTI-SELECTOR"
    root_timestamp = f"{int(time.time()) - 60}.000500"
    source_text = "<@B-E2E> choose the incident Agent"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "provider_app_id": app_id,
            "provider_team_id": team_id,
            "provider_bot_user_id": "U-BOT-MULTI-SELECTOR",
            "history_pages": [
                [
                    {
                        "user": "U-SELECTOR",
                        "ts": root_timestamp,
                        "text": source_text,
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    owner_token, _, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        agent_count=2,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {owner_token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_multi_slack_connection(
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=app_id,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )

    def disconnect_connection() -> None:
        impact = external_api.external_channel_v1_get_multi_slack_connection_impact(
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )
        external_api.external_channel_v1_disconnect_multi_slack_connection(
            connection_id=setup.connection.id,
            handle=handle,
            generation_fence_request=GenerationFenceRequest(
                expected_generation=impact.generation
            ),
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    routes = [
        external_api.external_channel_v1_add_multi_slack_route(
            connection_id=setup.connection.id,
            handle=handle,
            multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_id),
            _headers=headers,
        )
        for agent_id in agent_ids
    ]
    assert (
        external_api.external_channel_v1_list_multi_slack_channel_defaults(
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        ).items
        == []
    )

    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids_by_agent = {
        agent_id: {
            session.id
            for session in chat_api.chat_v1_list_agent_sessions(
                agent_id=agent_id,
                _headers=headers,
            ).items
        }
        for agent_id in agent_ids
    }
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    event_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": app_id,
            "team_id": team_id,
            "event": {
                "type": "app_mention",
                "channel": _CHANNEL_ID,
                "channel_type": "channel",
                "user": "U-SELECTOR",
                "text": source_text,
                "ts": root_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    for _ in range(2):
        response = requests.post(
            callback_url,
            data=event_body,
            headers=_signed_headers(event_body),
            timeout=5,
        )
        assert response.status_code == 200

    selector_admission_id = wait_until(
        lambda: _selector_admission_id(slack_provider_fake_url),
        timeout=15,
        interval=0.2,
        message="Unconfigured Multi App mention did not produce a selector",
    )
    block_payload = {
        "type": "block_actions",
        "api_app_id": app_id,
        "team": {"id": team_id},
        "user": {"id": "U-SELECTOR"},
        "trigger_id": "trigger-selector-e2e",
        "channel": {"id": _CHANNEL_ID},
        "message": {
            "ts": root_timestamp,
            "thread_ts": root_timestamp,
        },
        "actions": [
            {
                "action_id": "azents_agent_selector_open",
                "value": selector_admission_id,
            }
        ],
    }
    block_body = urlencode(
        {"payload": json.dumps(block_payload, separators=(",", ":"))}
    ).encode()
    for _ in range(2):
        response = requests.post(
            callback_url,
            data=block_body,
            headers=_signed_headers(
                block_body,
                content_type="application/x-www-form-urlencoded",
            ),
            timeout=5,
        )
        assert response.status_code == 200

    selector_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_selector_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Selector interaction did not open a modal",
        ),
    )
    assert selector_view["route_ids"] == [route.id for route in routes]
    metadata = selector_view.get("private_metadata")
    assert isinstance(metadata, str)
    assert metadata

    submission_payload = {
        "type": "view_submission",
        "api_app_id": app_id,
        "team": {"id": team_id},
        "user": {"id": "U-SELECTOR"},
        "trigger_id": "trigger-selector-submission-e2e",
        "view": {
            "id": selector_view["view_id"],
            "hash": selector_view["view_hash"],
            "callback_id": "azents_agent_selector",
            "private_metadata": metadata,
            "state": {
                "values": {
                    "azents_agent_selector_route": {
                        "azents_agent_selector_route": {
                            "selected_option": {"value": routes[1].id}
                        }
                    }
                }
            },
        },
    }
    submission_body = urlencode(
        {"payload": json.dumps(submission_payload, separators=(",", ":"))}
    ).encode()
    response = requests.post(
        callback_url,
        data=submission_body,
        headers=_signed_headers(
            submission_body,
            content_type="application/x-www-form-urlencoded",
        ),
        timeout=5,
    )
    assert response.status_code == 200

    for selected_agent_id in agent_ids:
        _assert_no_pending_slack_participation_lifecycle(
            chat_api=chat_api,
            external_api=external_api,
            agent_id=selected_agent_id,
            handle=handle,
            headers=headers,
            baseline_session_ids=baseline_session_ids_by_agent[selected_agent_id],
        )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Selected Multi App route did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=app_id,
        team_id=team_id,
        user_id="U-SELECTOR",
        setup_view=setup_view,
    )

    def find_selected_binding() -> tuple[Any, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_ids[1],
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_ids[1],
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session, projection.items[0]
        return None

    selected_session, selected_binding = cast(
        tuple[Any, Any],
        wait_until(
            find_selected_binding,
            timeout=10,
            interval=0.2,
            message="Selected open-access Multi App route did not bind once",
        ),
    )
    assert selected_session.agent_id == agent_ids[1]
    assert selected_binding.provider.value == "slack"
    input_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=owner_token,
                        session_id=selected_session.id,
                        include_pending=False,
                    )
                )
                == 1
                else None
            ),
            timeout=15,
            interval=0.2,
            message="Slack Multi selector did not preserve its source invocation",
        ),
    )
    assert input_evidence[0]["provider"] == "slack"
    assert input_evidence[0]["external_message_id"]
    assert input_evidence[0]["authorization"] == "authorized_invocation"
    assert input_evidence[0]["body"] == source_text
    assert input_evidence[0]["original_url"] == (
        f"https://example.slack.com/archives/{_CHANNEL_ID}/p"
        f"{root_timestamp.replace('.', '')}"
    )
    assert _approval_request_id(slack_provider_fake_url) == ""
    provider_state = _provider_state(slack_provider_fake_url)
    request_counts = cast(dict[str, int], provider_state["request_counts"])
    views = cast(list[dict[str, object]], provider_state["views"])
    assert request_counts["views.open"] == len(views)
    assert 1 <= sum(view["control_scope"] == "selector" for view in views) <= 2
    assert sum(view["control_scope"] == "setup" for view in views) == 1
    assert all(
        view["operation"] == "views.open" and view["outcome"] == "delivered"
        for view in views
    )
    assert any(
        view["control_scope"] == "selector"
        and view["route_count"] == len(routes)
        and view["has_submit"] is True
        for view in views
    )
    assert _BOT_TOKEN not in str(provider_state)
    assert _SIGNING_SECRET not in str(provider_state)


@pytest.mark.runtime_provider
def test_provider_native_channel_work_progress_journey(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    azents_runtime_provider_docker_container: Container,
    slack_provider_fake_url: str,
    openai_proxy_url: str,
) -> None:
    """Render one rich canonical work snapshot through Slack's native Plan."""
    del azents_engine_worker_container, azents_runtime_provider_docker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.delete(
        f"{openai_proxy_url}/v1/_external_channel_progress_requests",
        timeout=5,
    ).raise_for_status()
    root_timestamp = f"{int(time.time()) - 60}.000300"
    message_text = (
        "<@B-E2E> Provider-native Channel Work progress E2E. "
        "Ask <@UREVIEWER> in <#CRELATED>."
    )
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-EXTERNAL",
                        "ts": root_timestamp,
                        "text": message_text,
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    restricted_policy = (
        external_api.external_channel_v1_update_connection_access_policy(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            connection_access_policy_request=ConnectionAccessPolicyRequest(
                open_access_enabled=False,
            ),
            _headers=headers,
        )
    )
    assert restricted_policy.open_access_enabled is False

    def disconnect_connection() -> None:
        external_api.external_channel_v1_disconnect_connection(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    validated = external_api.external_channel_v1_validate_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE

    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }
    event_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _APP_ID,
            "team_id": _TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": _CHANNEL_ID,
                "channel_type": "channel",
                "user": "U-EXTERNAL",
                "text": message_text,
                "ts": root_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    response = requests.post(
        callback_url,
        data=event_body,
        headers=_signed_headers(event_body),
        timeout=5,
    )
    assert response.status_code == 200

    request_id = wait_until(
        lambda: _approval_request_id(slack_provider_fake_url),
        timeout=15,
        interval=0.2,
        message="Channel Work approval control message was not delivered",
    )
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=ExternalChannelDecisionInput(
            decision="allow_agent",
            summary="Provider-native progress E2E approval",
        ),
        _headers=headers,
    )
    assert decided.agent_session_id is None
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    _open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        channel_id=_CHANNEL_ID,
        user_id="U-EXTERNAL",
    )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Approved Channel Work setup did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        user_id="U-EXTERNAL",
        setup_view=setup_view,
    )

    def selected_session_id() -> str | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session.id
        return None

    selected_session = wait_until(
        selected_session_id,
        timeout=15,
        interval=0.2,
        message="Selected Channel Work setup did not create one Session",
    )
    assert isinstance(selected_session, str)
    session_id = selected_session

    def management_projection() -> object | None:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            _headers=headers,
        )
        if len(projection.items) == 1 and projection.items[0].work is not None:
            return projection
        return None

    active_projection = cast(
        Any,
        wait_until(
            management_projection,
            timeout=15,
            interval=0.2,
            message="Approved Channel Work binding was not available",
        ),
    )
    binding_id = active_projection.items[0].id

    wait_until(
        lambda: _matching_progress_request_evidence(
            openai_proxy_url,
            binding_id,
        ),
        timeout=90,
        interval=0.2,
        message="Channel Work model request did not reach the expected proxy stage",
    )

    def completed_channel_action() -> list[dict[str, object]]:
        evidence = _channel_action_tool_evidence(
            azents_public_server_url,
            token,
            session_id,
            call_ids=frozenset({"call_external_channel_progress"}),
        )
        assert any(
            item.get("kind") == "client_tool_call"
            and item.get("call_id") == "call_external_channel_progress"
            for item in evidence
        ), f"Channel Action tool call was not recorded: {evidence!r}"
        assert any(
            item.get("kind") == "client_tool_result"
            and item.get("call_id") == "call_external_channel_progress"
            for item in evidence
        ), f"Channel Action tool result was not recorded: {evidence!r}"
        return evidence

    tool_evidence = wait_until(
        completed_channel_action,
        timeout=90,
        interval=0.2,
        message="Channel Action tool execution did not complete",
    )
    progress_result = next(
        item
        for item in tool_evidence
        if item.get("kind") == "client_tool_result"
        and item.get("call_id") == "call_external_channel_progress"
    )
    assert progress_result.get("status") == "completed", tool_evidence

    def rich_management_projection() -> object | None:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            _headers=headers,
        )
        if (
            len(projection.items) == 1
            and projection.items[0].work is not None
            and projection.items[0].work.title == "Investigating error logs…"
            and len(projection.items[0].work.tasks) == 4
        ):
            return projection
        return None

    projection = cast(
        Any,
        wait_until(
            rich_management_projection,
            timeout=20,
            interval=0.2,
            message="Canonical Channel Work was not updated by the model action",
        ),
    )
    work = projection.items[0].work
    assert work is not None
    assert [task.status for task in work.tasks] == [
        ExternalChannelWorkTaskStatus.IN_PROGRESS,
        ExternalChannelWorkTaskStatus.COMPLETED,
        ExternalChannelWorkTaskStatus.FAILED,
        ExternalChannelWorkTaskStatus.PENDING,
    ]
    assert work.tasks[0].details == "Comparing recent application errors."
    assert work.tasks[0].sources[0].label == "Error log dashboard"
    assert work.tasks[1].output == "Release 2026.07.23 contains the regression."

    provider_state = _provider_state(slack_provider_fake_url)
    request_counts = cast(dict[str, int], provider_state["request_counts"])
    assert request_counts["users.info"] >= 2
    assert request_counts["conversations.info"] >= 2
    assert _BOT_TOKEN not in str(provider_state)
    assert _SIGNING_SECRET not in str(provider_state)

    plan_delivery = cast(
        dict[str, object],
        wait_until(
            lambda: _plan_delivery(slack_provider_fake_url),
            timeout=20,
            interval=0.2,
            message="Slack Plan update was not delivered",
        ),
    )
    expected_fallback = (
        "Investigating error logs…\n"
        "In progress: Inspect recent failures\n"
        "Completed: Verify the affected release\n"
        "Failed: Trace the unavailable dependency\n"
        "Pending: Summarize the incident"
    )
    blocks = cast(list[dict[str, object]], plan_delivery["blocks"])
    assert len(blocks) == 1
    assert plan_delivery["text"] == expected_fallback
    plan = blocks[0]
    assert plan["type"] == "plan"
    assert plan["title"] == "Investigating error logs…"
    assert "plan_id" not in plan
    tasks = cast(list[dict[str, object]], plan["tasks"])
    assert [task["task_id"] for task in tasks] == [
        "inspect",
        "verify",
        "trace",
        "summarize",
    ]
    assert [task["status"] for task in tasks] == [
        "in_progress",
        "complete",
        "error",
        "pending",
    ]
    assert all("type" not in task for task in tasks)
    assert tasks[0]["details"] == {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [
                    {
                        "type": "text",
                        "text": "Comparing recent application errors.",
                    }
                ],
            }
        ],
    }
    assert tasks[0]["sources"] == [
        {
            "type": "url",
            "url": "https://example.com/logs",
            "text": "Error log dashboard",
        }
    ]
    assert tasks[1]["output"] == {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [
                    {
                        "type": "text",
                        "text": "Release 2026.07.23 contains the regression.",
                    }
                ],
            }
        ],
    }

    provider_state = _provider_state(slack_provider_fake_url)
    assert _BOT_TOKEN not in str(provider_state)
    assert _SIGNING_SECRET not in str(provider_state)


@pytest.mark.runtime_provider
def test_external_channel_file_transfer_journey(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    azents_runtime_provider_docker_container: Container,
    slack_provider_fake_url: str,
    openai_proxy_url: str,
) -> None:
    """Transfer one 6 MiB Slack file through Runtime and publish two results."""
    del azents_engine_worker_container, azents_runtime_provider_docker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.delete(
        f"{openai_proxy_url}/v1/_external_channel_file_requests",
        timeout=5,
    ).raise_for_status()
    root_timestamp = f"{int(time.time()) - 60}.000400"
    message_text = (
        "<@B-E2E> External Channel file transfer E2E. "
        "Process only the first attached file and return two results."
    )
    selected_content_pattern = b"runtime-transfer-large-file\n"
    selected_content = (
        selected_content_pattern
        * ((_EXTERNAL_CHANNEL_LARGE_FILE_BYTES // len(selected_content_pattern)) + 1)
    )[:_EXTERNAL_CHANNEL_LARGE_FILE_BYTES]
    ignored_content = b"unused input"
    expected_uploads = (
        b"summary:" + selected_content,
        b"details:" + selected_content[:64].upper(),
    )
    assert len(selected_content) == _EXTERNAL_CHANNEL_LARGE_FILE_BYTES
    event_files = [
        {
            "id": "F-IN-SELECTED",
            "name": "selected-input.txt",
            "title": "Selected input",
            "mimetype": "text/plain",
            "size": len(selected_content),
            "mode": "hosted",
            "is_external": False,
            "file_access": "visible",
        },
        {
            "id": "F-IN-IGNORED",
            "name": "ignored-input.txt",
            "title": "Ignored input",
            "mimetype": "text/plain",
            "size": len(ignored_content),
            "mode": "hosted",
            "is_external": False,
            "file_access": "visible",
        },
    ]
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "files": [
                {
                    **event_files[0],
                    "content_base64": base64.b64encode(selected_content).decode(),
                },
                {
                    **event_files[1],
                    "content_base64": base64.b64encode(ignored_content).decode(),
                },
            ],
            "history_pages": [
                [
                    {
                        "user": "U-FILES",
                        "ts": root_timestamp,
                        "text": message_text,
                        "files": event_files,
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id="system-docker",
        shell_enabled=True,
    )
    _wait_for_runtime_runner_ready(
        public_api_client,
        token=token,
        workspace_handle=handle,
        agent_id=agent_id,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    restricted_policy = (
        external_api.external_channel_v1_update_connection_access_policy(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            connection_access_policy_request=ConnectionAccessPolicyRequest(
                open_access_enabled=False,
            ),
            _headers=headers,
        )
    )
    assert restricted_policy.open_access_enabled is False

    def disconnect_connection() -> None:
        external_api.external_channel_v1_disconnect_connection(
            agent_id=agent_id,
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    validated = external_api.external_channel_v1_validate_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE
    assert validated.capabilities is not None
    assert validated.capabilities.download_files is True
    assert validated.capabilities.upload_files is True

    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }
    event_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _APP_ID,
            "team_id": _TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": _CHANNEL_ID,
                "channel_type": "channel",
                "user": "U-FILES",
                "text": message_text,
                "ts": root_timestamp,
                "files": event_files,
            },
        },
        separators=(",", ":"),
    ).encode()
    response = requests.post(
        callback_url,
        data=event_body,
        headers=_signed_headers(event_body),
        timeout=5,
    )
    assert response.status_code == 200

    request_id = wait_until(
        lambda: _approval_request_id(slack_provider_fake_url),
        timeout=15,
        interval=0.2,
        message="File-transfer approval control message was not delivered",
    )
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=ExternalChannelDecisionInput(
            decision="allow_agent",
            summary="External Channel file transfer E2E approval",
        ),
        _headers=headers,
    )
    assert decided.agent_session_id is None
    _assert_no_pending_slack_participation_lifecycle(
        chat_api=chat_api,
        external_api=external_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        baseline_session_ids=baseline_session_ids,
    )
    _open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        channel_id=_CHANNEL_ID,
        user_id="U-FILES",
    )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Approved file-transfer setup did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_APP_ID,
        team_id=_TEAM_ID,
        user_id="U-FILES",
        setup_view=setup_view,
    )

    def selected_session_id() -> str | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session.id
        return None

    selected_session = wait_until(
        selected_session_id,
        timeout=20,
        interval=0.2,
        message="Selected file-transfer setup did not create one Session",
    )
    assert isinstance(selected_session, str)
    session_id = selected_session

    def binding_id_projection() -> str:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            _headers=headers,
        )
        if len(projection.items) == 1:
            return projection.items[0].id
        return ""

    binding_id = wait_until(
        binding_id_projection,
        timeout=20,
        interval=0.2,
        message="Approved file-transfer binding was not available",
    )

    def initial_file_model_request() -> list[dict[str, object]]:
        evidence = _file_request_evidence(openai_proxy_url)
        assert any(
            item.get("binding") == binding_id
            and item.get("marker_present") is True
            and item.get("locator_count") == 2
            and item.get("search_tool_available") is False
            and item.get("download_tool_available") is True
            and item.get("process_tool_available") is True
            and item.get("channel_action_tool_available") is True
            and item.get("stage") == "initial"
            for item in evidence
        ), evidence
        return evidence

    wait_until(
        initial_file_model_request,
        timeout=90,
        interval=0.2,
        message="File-transfer model request did not expose the expected tools",
    )

    def completed_file_model_stages() -> list[dict[str, object]]:
        evidence = [
            item
            for item in _file_request_evidence(openai_proxy_url)
            if item.get("binding") == binding_id
        ]
        stages = [item.get("stage") for item in evidence]
        expected_stages = [
            "initial",
            "after_download",
            "after_process",
        ]
        previous_index = -1
        for stage in expected_stages:
            assert stage in stages, evidence
            index = stages.index(stage)
            assert index > previous_index, evidence
            previous_index = index
        initial = evidence[stages.index("initial")]
        assert initial.get("search_tool_available") is False, evidence
        assert initial.get("download_tool_available") is True, evidence
        assert initial.get("process_tool_available") is True, evidence
        assert initial.get("channel_action_tool_available") is True, evidence
        for item in evidence:
            tool_outputs = cast(
                dict[str, dict[str, object]],
                item.get("tool_outputs", {}),
            )
            assert all(
                output.get("error") is None for output in tool_outputs.values()
            ), evidence
        return evidence

    completed_evidence = wait_until(
        completed_file_model_stages,
        timeout=120,
        interval=0.2,
        message="File-transfer model stages did not complete",
    )
    tool_outputs = cast(
        dict[str, dict[str, object]], completed_evidence[-1]["tool_outputs"]
    )
    for call_id in (
        "call_external_channel_file_download",
        "call_external_channel_file_process",
    ):
        output = tool_outputs.get(call_id)
        assert output is not None, completed_evidence
        assert output.get("error") is None, completed_evidence

    def completed_file_finish_action() -> list[dict[str, object]]:
        evidence = _channel_action_tool_evidence(
            azents_public_server_url,
            token,
            session_id,
            call_ids=frozenset({"call_external_channel_file_finish"}),
        )
        assert any(
            item.get("kind") == "client_tool_call"
            and item.get("call_id") == "call_external_channel_file_finish"
            for item in evidence
        ), f"Final Channel Action tool call was not recorded: {evidence!r}"
        assert any(
            item.get("kind") == "client_tool_result"
            and item.get("call_id") == "call_external_channel_file_finish"
            and item.get("status") == "completed"
            for item in evidence
        ), f"Final Channel Action tool result did not complete: {evidence!r}"
        return evidence

    wait_until(
        completed_file_finish_action,
        timeout=30,
        interval=0.2,
        message="Final Channel Action tool execution did not complete",
    )

    def completed_file_response() -> list[dict[str, object]]:
        evidence = [
            item
            for item in _file_request_evidence(openai_proxy_url)
            if item.get("binding") == binding_id
        ]
        assert sum(item.get("stage") == "after_finish" for item in evidence) == 1, (
            evidence
        )
        return evidence

    wait_until(
        completed_file_response,
        timeout=30,
        interval=0.2,
        message="Final Channel Action result did not reach the model",
    )
    time.sleep(2)
    completed_file_response()

    def file_completion_delivery() -> dict[str, object]:
        deliveries = _provider_state(slack_provider_fake_url).get("deliveries")
        if not isinstance(deliveries, list):
            return {}
        for raw_delivery in reversed(cast(list[object], deliveries)):
            if not isinstance(raw_delivery, dict):
                continue
            delivery = cast(dict[str, object], raw_delivery)
            if delivery.get("operation") == "files.completeUploadExternal":
                return delivery
        return {}

    completion = wait_until(
        file_completion_delivery,
        timeout=30,
        interval=0.2,
        message="Slack file completion was not delivered",
    )
    assert completion["channel"] == _CHANNEL_ID
    assert completion["thread_ts"] == root_timestamp
    assert completion["file_count"] == 2
    assert completion["total_bytes"] == sum(len(body) for body in expected_uploads)
    assert completion["has_initial_comment"] is True

    provider_state = _provider_state(slack_provider_fake_url)
    request_counts = cast(dict[str, int], provider_state["request_counts"])
    assert request_counts["files.info"] == 2
    assert request_counts["file.download"] == 1
    assert request_counts["files.getUploadURLExternal"] == 2
    assert request_counts["file.upload"] == 2
    assert request_counts["files.completeUploadExternal"] == 1
    upload_requests = [
        cast(dict[str, object], item)
        for item in cast(list[object], provider_state["requests"])
        if isinstance(item, dict)
        and cast(dict[str, object], item).get("operation") == "file.upload"
    ]
    assert [
        (
            item.get("received_length"),
            item.get("content_sha256"),
        )
        for item in upload_requests
    ] == [(len(body), hashlib.sha256(body).hexdigest()) for body in expected_uploads]
    file_requests = [
        cast(dict[str, object], item)
        for item in cast(list[object], provider_state["requests"])
        if isinstance(item, dict)
        and cast(dict[str, object], item).get("operation")
        in {"files.info", "file.download"}
    ]
    assert [item.get("file") for item in file_requests] == [
        "F-IN-SELECTED",
        "F-IN-SELECTED",
        "F-IN-SELECTED",
    ]
    rendered_provider_state = str(provider_state)
    assert _BOT_TOKEN not in rendered_provider_state
    assert _SIGNING_SECRET not in rendered_provider_state
    assert selected_content_pattern.decode().strip() not in rendered_provider_state
    assert ignored_content.decode() not in rendered_provider_state
    assert "selected-input.txt" not in rendered_provider_state


def test_socket_mode_recovers_then_acknowledges_and_preserves_route(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[Container]
    ],
    slack_provider_fake_url: str,
) -> None:
    """Exercise SDK reconnect, durable ACK, and route-preserving terminal health."""
    del azents_engine_worker_container
    installation_suffix = unique()
    socket_app_id = f"A-SOCKET-{installation_suffix}"
    socket_team_id = f"T-SOCKET-{installation_suffix}"
    envelope_id = f"Env-{unique()}"
    root_timestamp = f"{int(time.time()) - 60}.000200"
    socket_payload = {
        "type": "event_callback",
        "event_id": f"Ev-{unique()}",
        "event_time": int(time.time()),
        "api_app_id": socket_app_id,
        "team_id": socket_team_id,
        "event": {
            "type": "app_mention",
            "channel": _CHANNEL_ID,
            "channel_type": "channel",
            "user": "U-SOCKET",
            "text": "<@B-E2E> socket request",
            "ts": root_timestamp,
        },
    }
    socket_sessions: list[dict[str, object]] = [
        {
            "envelopes": [],
            "disconnect_reason": "refresh_requested",
        },
        {
            "envelopes": [
                {
                    "envelope_id": envelope_id,
                    "type": "events_api",
                    "payload": socket_payload,
                }
            ],
            "disconnect_reason": "link_disabled",
        },
    ]
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "provider_app_id": socket_app_id,
            "provider_team_id": socket_team_id,
            "history_pages": [
                [
                    {
                        "user": "U-SOCKET",
                        "ts": root_timestamp,
                        "text": "<@B-E2E> socket request",
                    }
                ]
            ],
            "socket_sessions": socket_sessions,
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=socket_app_id,
            transport=ExternalChannelTransport.SOCKET,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token="xapp-e2e-private",
            ),
        ),
        _headers=headers,
    )
    validated = external_api.external_channel_v1_validate_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE
    assert set(validated.credentials.configured_fields) == {
        "app_token",
        "bot_token",
        "signing_secret",
    }
    external_api.external_channel_v1_update_connection_access_policy(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        connection_access_policy_request=ConnectionAccessPolicyRequest(
            open_access_enabled=True,
        ),
        _headers=headers,
    )
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }

    def socket_binding() -> tuple[Any, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if len(projection.items) == 1:
                return session, projection.items[0]
        return None

    def socket_evidence_contains(field: str) -> bool:
        socket_state = _provider_state(slack_provider_fake_url).get("socket")
        if not isinstance(socket_state, dict):
            return False
        values = cast(dict[str, object], socket_state).get(field)
        return isinstance(values, list) and envelope_id in cast(
            list[object],
            values,
        )

    with azents_external_channel_gateway_factory():
        wait_until(
            lambda: socket_evidence_contains("envelope_ids"),
            timeout=45,
            interval=0.2,
            message="Socket Mode provider fake did not deliver the envelope",
        )
        wait_until(
            lambda: socket_evidence_contains("acknowledgements"),
            timeout=45,
            interval=0.2,
            message="Socket Mode envelope was not acknowledged after admission",
        )
        _assert_no_pending_slack_participation_lifecycle(
            chat_api=chat_api,
            external_api=external_api,
            agent_id=agent_id,
            handle=handle,
            headers=headers,
            baseline_session_ids=baseline_session_ids,
        )

        def reconnect_required_connection() -> object | None:
            connections = external_api.external_channel_v1_list_connections(
                agent_id=agent_id,
                handle=handle,
                _headers=headers,
            )
            if (
                len(connections.items) == 1
                and connections.items[0].status
                is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
            ):
                return connections.items[0]
            return None

        reconnect_required = wait_until(
            reconnect_required_connection,
            timeout=15,
            interval=0.2,
            message="Socket link_disabled did not require reconnection",
        )
        reconnect_payload = cast(Any, reconnect_required)
        assert reconnect_payload.socket_gap_reason == "link_disabled"
        provider_state = _provider_state(slack_provider_fake_url)
        socket_state = provider_state["socket"]
        assert isinstance(socket_state, dict)
        assert socket_state["connections"] == 2
        assert socket_state["configured_sessions"] == 2
        assert "xapp-e2e-private" not in str(provider_state)

    recovered = external_api.external_channel_v1_update_slack_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=socket_app_id,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    assert recovered.status is ExternalChannelConnectionStatus.ACTIVE
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    _open_slack_setup_modal(
        callback_url=callback_url,
        app_id=socket_app_id,
        team_id=socket_team_id,
        channel_id=_CHANNEL_ID,
        user_id="U-SOCKET",
    )
    setup_view = cast(
        dict[str, object],
        wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Recovered Socket Mode setup did not open a location modal",
        ),
    )
    _submit_slack_setup_location(
        callback_url=callback_url,
        app_id=socket_app_id,
        team_id=socket_team_id,
        user_id="U-SOCKET",
        setup_view=setup_view,
    )
    socket_session, socket_channel = cast(
        tuple[Any, Any],
        wait_until(
            socket_binding,
            timeout=15,
            interval=0.2,
            message=(
                "Recovered Socket Mode invocation did not retain one Session binding"
            ),
        ),
    )
    assert socket_session.agent_id == agent_id
    assert socket_channel.provider.value == "slack"
    detail = chat_api.chat_v1_get_agent_session(
        agent_id=agent_id,
        session_id=socket_session.id,
        _headers=headers,
    )
    assert detail.id == socket_session.id
    input_evidence = _external_channel_input_evidence(
        public_server_url=azents_public_server_url,
        token=token,
        session_id=socket_session.id,
    )
    assert len(input_evidence) == 1
    assert input_evidence[0]["provider"] == "slack"
    expected_session_path = (
        f"/w/{handle}/agents/{agent_id}/sessions/{socket_session.id}"
    )
    presence_state = cast(
        dict[str, object],
        wait_until(
            lambda: (
                state
                if expected_session_path
                in _successful_session_paths(
                    state := _provider_state(slack_provider_fake_url)
                )
                and "joined" in _successful_session_presence_states(state)
                else None
            ),
            timeout=10,
            interval=0.2,
            message="Recovered Socket Mode joined presence was not delivered",
        ),
    )
    assert expected_session_path in _successful_session_paths(presence_state)


@pytest.mark.web_surface
def test_connection_management_web_surface_uses_redacted_operational_state(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Render and validate one real connection without exposing credentials."""
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    token, email, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    _login_main_web(
        browser_driver,
        main_web_url=azents_main_web_url,
        email=email,
    )
    browser_driver.set_window_size(390, 844)  # pyright: ignore[reportUnknownMemberType] # Selenium stub leaves window dimensions untyped
    browser_driver.get(
        f"{azents_main_web_url}/w/{handle}/agents/{agent_id}/settings/channels"
    )
    wait = WebDriverWait(browser_driver, 30)
    connection = wait.until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                f'[data-testid="external-connection-{setup.connection.id}"]',
            )
        )
    )
    cast(Any, browser_driver).execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        connection,
    )
    connection_text = connection.text
    assert "Slack" in connection_text
    assert "ACTIVE" in connection_text
    assert "HTTP" in connection_text
    assert _TEAM_ID in connection_text
    assert _APP_ID in connection_text
    assert "CREDENTIALS CONFIGURED" in connection_text
    assert _BOT_TOKEN not in browser_driver.page_source
    assert _SIGNING_SECRET not in browser_driver.page_source

    default_mode = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-default-response-mode"]')
        )
    )
    mention_only = default_mode.find_element(
        By.CSS_SELECTOR,
        'input[value="mention_only"]',
    )
    mention_only.click()
    default_mode.find_element(
        By.CSS_SELECTOR,
        '[data-testid="save-external-default-response-mode"]',
    ).click()

    def default_mode_saved(_: WebDriver) -> bool:
        settings = external_api.external_channel_v1_list_connections(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        )
        return (
            settings.default_response_mode is ExternalChannelResponseMode.MENTION_ONLY
        )

    wait.until(default_mode_saved)
    browser_driver.refresh()
    reloaded_default_mode = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-default-response-mode"]')
        )
    )
    assert reloaded_default_mode.find_element(
        By.CSS_SELECTOR,
        'input[value="mention_only"]',
    ).is_selected()
    connection = wait.until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                f'[data-testid="external-connection-{setup.connection.id}"]',
            )
        )
    )

    validate_button = connection.find_element(
        By.XPATH,
        ".//button[normalize-space()='Validate']",
    )
    validate_button.click()

    def validation_reached_provider(_: WebDriver) -> bool:
        counts = _provider_state(slack_provider_fake_url).get("request_counts")
        return (
            isinstance(counts, dict)
            and cast(dict[str, object], counts).get("auth.test") == 2
        )

    wait.until(validation_reached_provider)
    assert connection.is_displayed()


def test_discord_single_activation_and_interaction_journey(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
) -> None:
    """Exercise Discord activation and signed interaction ingress."""
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
                    "name": "Ask an Azents Agent",
                    "type": 3,
                },
                {
                    "id": "500000000000000103",
                    "name": "Azents settings",
                    "type": 1,
                    "description": "Stale description.",
                },
                {
                    "id": "500000000000000104",
                    "name": "Private customer command",
                    "type": 2,
                },
            ],
            "root_messages": [
                {
                    "id": "700000000000000002",
                    "channel_id": _DISCORD_CHANNEL_ID,
                    "content": "Private Discord interaction invocation",
                    "timestamp": "2026-07-26T00:00:00.000000+00:00",
                    "author": {"id": "600000000000000001"},
                    "mentions": [{"id": _DISCORD_BOT_USER_ID}],
                    "guild_id": _DISCORD_GUILD_ID,
                }
            ],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_discord_connection(
        agent_id=agent_id,
        handle=handle,
        discord_connection_setup_request=DiscordConnectionSetupRequest(
            app_id=_DISCORD_APPLICATION_ID,
            configuration=DiscordConnectionConfiguration(
                target_guild_id=_DISCORD_GUILD_ID
            ),
            credentials=DiscordConnectionCredentials(bot_token=_DISCORD_BOT_TOKEN),
        ),
        _headers=headers,
    )
    assert setup.connection.status is ExternalChannelConnectionStatus.ACTIVE
    assert setup.connection.credentials_configured is True
    assert setup.connection.provider_tenant_id == _DISCORD_GUILD_ID
    assert _DISCORD_BOT_TOKEN not in setup.model_dump_json(by_alias=True)

    activation_state = _discord_provider_state(discord_provider_fake_url)
    assert activation_state["interaction_configurations"] == [
        {"application_id": _DISCORD_APPLICATION_ID}
    ]
    assert activation_state["guild_commands"] == [
        {"role": "azents_settings", "type": 1},
        {"role": "conversation_settings", "type": 3},
        {"role": "message_action", "type": 3},
        {"role": "unrelated", "type": 2},
    ]
    activation_request_counts = cast(
        dict[str, int],
        activation_state["request_counts"],
    )
    assert activation_request_counts["list_guild_commands"] == 1
    assert activation_request_counts["create_guild_command"] == 1
    assert activation_request_counts["update_guild_command"] == 1
    assert activation_request_counts["delete_guild_command"] == 1
    command_ids = {
        role: cast(
            str,
            wait_until(
                lambda role=role: _discord_command_id(
                    discord_provider_fake_url,
                    role=role,
                ),
                timeout=15,
                interval=0.2,
                message=f"Discord {role} command ID was not reconciled",
            ),
        )
        for role in _DISCORD_COMMAND_CONTRACTS
    }
    assert len(set(command_ids.values())) == len(_DISCORD_COMMAND_CONTRACTS)
    ping = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000001",
            "type": 1,
            "application_id": _DISCORD_APPLICATION_ID,
        },
        timeout=10,
    )
    ping.raise_for_status()
    assert ping.json() == {"status": 200, "response_type": 1}
    _open_discord_settings(
        discord_provider_fake_url=discord_provider_fake_url,
        interaction_id="700000000000000002",
        application_id=_DISCORD_APPLICATION_ID,
        guild_id=_DISCORD_GUILD_ID,
        channel_id=_DISCORD_CHANNEL_ID,
        user_id="600000000000000001",
    )

    state = _discord_provider_state(discord_provider_fake_url)
    assert state["interactions"] == [
        {
            "interaction_id": "700000000000000001",
            "interaction_type": 1,
            "response_status": 200,
            "response_type": 1,
        },
        {
            "interaction_id": "700000000000000002",
            "interaction_type": 2,
            "response_status": 200,
            "response_type": 4,
            "component_count": 0,
            "has_content": True,
        },
    ]
    rendered_state = str(state)
    assert _DISCORD_BOT_TOKEN not in rendered_state
    assert "Private Discord interaction invocation" not in rendered_state
    assert "Private customer command" not in rendered_state
    assert "X-Signature-Ed25519" not in rendered_state
    assert all(command_id not in rendered_state for command_id in command_ids.values())


def test_discord_gateway_message_waits_for_location_then_binds(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
    azents_engine_worker_container: Container,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[Container]
    ],
) -> None:
    """Gate one Gateway mention until a signed Discord location selection."""
    del azents_engine_worker_container
    application_id = "100000000000000004"
    guild_id = "200000000000000004"
    bot_user_id = "300000000000000004"
    channel_id = "400000000000000004"
    message_id = "500000000000000004"
    participant_id = "600000000000000004"
    source_text = "Private Discord Gateway invocation"
    timestamp = "2026-07-29T00:00:00.000000+00:00"
    author: dict[str, object] = {
        "id": participant_id,
        "username": "participant",
        "discriminator": "0",
        "avatar": None,
    }
    bot: dict[str, object] = {
        "id": bot_user_id,
        "username": "Azents",
        "discriminator": "0",
        "avatar": None,
        "bot": True,
    }
    provider_message: dict[str, object] = {
        "id": message_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "content": source_text,
        "timestamp": timestamp,
        "edited_timestamp": None,
        "author": author,
        "mentions": [bot],
        "mention_roles": [],
        "attachments": [],
        "embeds": [],
        "components": [],
        "type": 0,
        "pinned": False,
        "mention_everyone": False,
        "tts": False,
    }
    guild_create: dict[str, object] = {
        "id": guild_id,
        "name": "Gateway E2E",
        "unavailable": False,
        "owner_id": participant_id,
        "roles": [],
        "emojis": [],
        "stickers": [],
        "features": [],
        "channels": [
            {
                "id": channel_id,
                "guild_id": guild_id,
                "type": 0,
                "name": "gateway-e2e",
                "position": 0,
                "permission_overwrites": [],
            }
        ],
        "threads": [],
        "members": [
            {
                "user": bot,
                "roles": [],
                "joined_at": timestamp,
                "deaf": False,
                "mute": False,
                "flags": 0,
            }
        ],
        "presences": [],
        "voice_states": [],
        "stage_instances": [],
        "guild_scheduled_events": [],
        "member_count": 1,
    }
    requests.post(
        f"{discord_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{discord_provider_fake_url}/__testenv/configure",
        json={
            "application_id": application_id,
            "guild_id": guild_id,
            "bot_user_id": bot_user_id,
            "root_messages": [provider_message],
            "gateway_dispatches": [
                {
                    "sequence": 2,
                    "event_type": "GUILD_CREATE",
                    "payload": guild_create,
                },
                {
                    "sequence": 3,
                    "event_type": "MESSAGE_CREATE",
                    "payload": provider_message,
                },
            ],
            "gateway_scenarios": ["reconnect", "open"],
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    saved_default = external_api.external_channel_v1_update_default_response_mode(
        agent_id=agent_id,
        handle=handle,
        response_mode_request=ResponseModeRequest(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
        _headers=headers,
    )
    assert saved_default.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    setup = external_api.external_channel_v1_setup_discord_connection(
        agent_id=agent_id,
        handle=handle,
        discord_connection_setup_request=DiscordConnectionSetupRequest(
            app_id=application_id,
            configuration=DiscordConnectionConfiguration(target_guild_id=guild_id),
            credentials=DiscordConnectionCredentials(bot_token=_DISCORD_BOT_TOKEN),
        ),
        _headers=headers,
    )
    external_api.external_channel_v1_update_connection_access_policy(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        connection_access_policy_request=ConnectionAccessPolicyRequest(
            open_access_enabled=True,
        ),
        _headers=headers,
    )
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids = {
        session.id
        for session in chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        ).items
    }

    def gateway_binding() -> tuple[Any, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_id,
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_id,
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if (
                len(projection.items) == 1
                and projection.items[0].provider.value == "discord"
            ):
                return session, projection.items[0]
        return None

    with azents_external_channel_gateway_factory():
        wait_until(
            lambda: (
                6
                in cast(
                    list[object],
                    cast(
                        dict[str, object],
                        _discord_provider_state(discord_provider_fake_url)["gateway"],
                    )["initial_opcodes"],
                )
            ),
            timeout=45,
            interval=0.2,
            message=(
                "External Channel Gateway did not resume Discord with the provider fake"
            ),
        )
        wait_until(
            lambda: (
                cast(
                    dict[str, int],
                    _discord_provider_state(discord_provider_fake_url)[
                        "request_counts"
                    ],
                ).get("get_message", 0)
                >= 1
            ),
            timeout=30,
            interval=0.2,
            message="Discord Gateway mention did not reach setup admission",
        )
        _assert_no_pending_slack_participation_lifecycle(
            chat_api=chat_api,
            external_api=external_api,
            agent_id=agent_id,
            handle=handle,
            headers=headers,
            baseline_session_ids=baseline_session_ids,
        )
        setup_gate_state = _discord_provider_state(discord_provider_fake_url)
        setup_gate_counts = cast(
            dict[str, int],
            setup_gate_state["request_counts"],
        )
        assert setup_gate_counts.get("create_thread", 0) == 0
        assert setup_gate_counts.get("create_message", 0) == 0
        _open_discord_settings(
            discord_provider_fake_url=discord_provider_fake_url,
            interaction_id="700000000000000004",
            application_id=application_id,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=participant_id,
        )
        setup_threads_custom_id = cast(
            str,
            wait_until(
                lambda: _discord_settings_component_id(
                    discord_provider_fake_url,
                    action_code="st",
                ),
                timeout=30,
                interval=0.2,
                message="Discord Gateway setup control was not delivered",
            ),
        )
        _select_discord_setup_location(
            discord_provider_fake_url=discord_provider_fake_url,
            interaction_id="700000000000000005",
            application_id=application_id,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=participant_id,
            custom_id=setup_threads_custom_id,
        )
        session, binding = cast(
            tuple[Any, Any],
            wait_until(
                gateway_binding,
                timeout=30,
                interval=0.2,
                message="Discord setup selection did not activate one Session binding",
            ),
        )
        expected_session_path = f"/w/{handle}/agents/{agent_id}/sessions/{session.id}"
        wait_until(
            lambda: (
                expected_session_path
                in _successful_session_paths(
                    _discord_provider_state(discord_provider_fake_url)
                )
            ),
            timeout=30,
            interval=0.2,
            message="Discord joined-presence provider control was not delivered",
        )

    assert session.agent_id == agent_id
    assert binding.provider.value == "discord"
    assert binding.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    detail = chat_api.chat_v1_get_agent_session(
        agent_id=agent_id,
        session_id=session.id,
        _headers=headers,
    )
    assert detail.id == session.id
    input_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=token,
                        session_id=session.id,
                        include_pending=False,
                    )
                )
                == 1
                else None
            ),
            timeout=30,
            interval=0.2,
            message="Discord Gateway input was not promoted into Session history",
        ),
    )
    assert len(input_evidence) == 1
    logical_input = input_evidence[0]
    assert logical_input["provider"] == "discord"
    assert logical_input["external_message_id"]
    assert logical_input["authorization"] == "authorized_invocation"
    assert logical_input["body"] == source_text
    assert logical_input["original_url"] == (
        f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    )
    state = _discord_provider_state(discord_provider_fake_url)
    assert _successful_session_paths(state) == [
        expected_session_path,
        expected_session_path,
    ]
    assert _successful_session_presence_states(state) == ["joined"]
    request_counts = cast(dict[str, int], state["request_counts"])
    assert request_counts["create_thread"] >= 1
    # Thread reconciliation runs before create; canonical history runs after create.
    assert request_counts["get_message"] >= 2
    gateway = cast(dict[str, object], state["gateway"])
    assert cast(int, gateway["connections"]) >= 2
    initial_opcodes = cast(list[object], gateway["initial_opcodes"])
    resume_index = initial_opcodes.index(6)
    assert 2 in initial_opcodes[:resume_index]
    dispatches = cast(list[object], gateway["dispatches"])
    assert {"event_type": "GUILD_CREATE", "sequence": 2} in dispatches
    assert {"event_type": "MESSAGE_CREATE", "sequence": 3} in dispatches
    rendered = str(state)
    assert source_text not in rendered
    assert _DISCORD_BOT_TOKEN not in rendered
    assert setup_threads_custom_id not in rendered

    disconnected = external_api.external_channel_v1_disconnect_connection(
        agent_id=agent_id,
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert disconnected.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert disconnected.credentials_configured is False
    terminal_state = cast(
        dict[str, object],
        wait_until(
            lambda: (
                provider_state
                if _successful_session_presence_states(
                    provider_state := _discord_provider_state(discord_provider_fake_url)
                )
                == ["joined", "left"]
                else None
            ),
            timeout=15,
            interval=0.2,
            message=(
                "Discord connection disconnect did not deliver captured leave presence"
            ),
        ),
    )
    assert _successful_session_paths(terminal_state) == [
        expected_session_path,
        expected_session_path,
        expected_session_path,
    ]
    assert _DISCORD_BOT_TOKEN not in str(terminal_state)


def test_discord_message_command_selector_and_component_journey(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Exercise Message Command source projection and transient selector scope."""
    del azents_engine_worker_container
    source_message_id = "500000000000000002"
    source_content = "Private selected Discord source"
    requests.post(
        f"{discord_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{discord_provider_fake_url}/__testenv/configure",
        json={
            "application_id": _DISCORD_SELECTOR_APPLICATION_ID,
            "root_messages": [
                {
                    "id": source_message_id,
                    "channel_id": _DISCORD_CHANNEL_ID,
                    "content": source_content,
                    "timestamp": "2026-07-28T00:00:00.000000+00:00",
                    "author": {"id": "600000000000000002"},
                }
            ],
            "allow_synthetic_roots": True,
        },
        timeout=5,
    ).raise_for_status()
    owner_token, _, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        agent_count=2,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {owner_token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_multi_discord_connection(
        handle=handle,
        discord_connection_setup_request=DiscordConnectionSetupRequest(
            app_id=_DISCORD_SELECTOR_APPLICATION_ID,
            configuration=DiscordConnectionConfiguration(
                target_guild_id=_DISCORD_GUILD_ID
            ),
            credentials=DiscordConnectionCredentials(bot_token=_DISCORD_BOT_TOKEN),
        ),
        _headers=headers,
    )

    def disconnect_connection() -> None:
        impact = external_api.external_channel_v1_get_multi_discord_connection_impact(
            connection_id=setup.connection.id,
            handle=handle,
            _headers=headers,
        )
        external_api.external_channel_v1_disconnect_multi_discord_connection(
            connection_id=setup.connection.id,
            handle=handle,
            generation_fence_request=GenerationFenceRequest(
                expected_generation=impact.generation
            ),
            _headers=headers,
        )

    request.addfinalizer(disconnect_connection)
    wait_until(
        lambda: bool(
            _discord_provider_state(discord_provider_fake_url).get(
                "interaction_configurations"
            )
        ),
        timeout=15,
        interval=0.2,
        message="Discord interaction callback was not configured",
    )
    routes = [
        external_api.external_channel_v1_add_multi_discord_route(
            connection_id=setup.connection.id,
            handle=handle,
            multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_id),
            _headers=headers,
        )
        for agent_id in agent_ids
    ]
    chat_api = ChatV1Api(public_api_client)
    baseline_session_ids_by_agent = {
        agent_id: {
            session.id
            for session in chat_api.chat_v1_list_agent_sessions(
                agent_id=agent_id,
                _headers=headers,
            ).items
        }
        for agent_id in agent_ids
    }
    message_command_id = cast(
        str,
        wait_until(
            lambda: _discord_command_id(
                discord_provider_fake_url,
                role="message_action",
            ),
            timeout=15,
            interval=0.2,
            message="Discord Message Command ID was not reconciled",
        ),
    )
    interaction = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000003",
            "type": 2,
            "application_id": _DISCORD_SELECTOR_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "channel": {"id": _DISCORD_CHANNEL_ID, "type": 0},
            "member": {"user": {"id": "600000000000000002"}},
            "data": {
                "id": message_command_id,
                "type": 3,
                "name": "Ask an Azents Agent",
                "target_id": source_message_id,
                "resolved": {
                    "messages": {
                        source_message_id: {
                            "id": source_message_id,
                            "channel_id": _DISCORD_CHANNEL_ID,
                            "content": source_content,
                            "timestamp": "2026-07-28T00:00:00.000000+00:00",
                            "author": {"id": "600000000000000002"},
                        }
                    }
                },
            },
        },
        timeout=10,
    )
    interaction.raise_for_status()
    assert interaction.json() == {"status": 200, "response_type": 4}
    selector = wait_until(
        lambda: (
            requests.get(
                f"{discord_provider_fake_url}/__testenv/transient-selector",
                timeout=5,
            )
            .json()
            .get("custom_id")
        ),
        timeout=15,
        interval=0.2,
        message="Discord Message Command selector response was not rendered",
    )
    assert isinstance(selector, str)
    assert selector.startswith("azents-selector:")
    before_component = _discord_provider_state(discord_provider_fake_url)
    before_request_counts = cast(
        dict[str, int],
        before_component["request_counts"],
    )
    before_thread_count = before_request_counts.get("create_thread", 0)
    before_message_count = before_request_counts.get("create_message", 0)
    before_operation_count = len(
        cast(list[dict[str, object]], before_component["operations"])
    )
    before_delivery_count = len(
        cast(list[dict[str, object]], before_component["deliveries"])
    )
    component = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000004",
            "type": 3,
            "application_id": _DISCORD_SELECTOR_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "channel": {"id": _DISCORD_CHANNEL_ID, "type": 0},
            "member": {"user": {"id": "600000000000000002"}},
            "message": {"id": "800000000000000001"},
            "data": {"custom_id": selector, "values": [routes[1].id]},
        },
        timeout=10,
    )
    component.raise_for_status()
    assert component.json() == {"status": 200, "response_type": 7}
    for selected_agent_id in agent_ids:
        _assert_no_pending_slack_participation_lifecycle(
            chat_api=chat_api,
            external_api=external_api,
            agent_id=selected_agent_id,
            handle=handle,
            headers=headers,
            baseline_session_ids=baseline_session_ids_by_agent[selected_agent_id],
        )
    pending_location_state = _discord_provider_state(discord_provider_fake_url)
    pending_location_counts = cast(
        dict[str, int],
        pending_location_state["request_counts"],
    )
    assert pending_location_counts.get("create_thread", 0) == before_thread_count
    assert pending_location_counts.get("create_message", 0) == before_message_count
    _open_discord_settings(
        discord_provider_fake_url=discord_provider_fake_url,
        interaction_id="700000000000000005",
        application_id=_DISCORD_SELECTOR_APPLICATION_ID,
        guild_id=_DISCORD_GUILD_ID,
        channel_id=_DISCORD_CHANNEL_ID,
        user_id="600000000000000002",
    )
    setup_threads_custom_id = cast(
        str,
        wait_until(
            lambda: _discord_settings_component_id(
                discord_provider_fake_url,
                action_code="st",
            ),
            timeout=15,
            interval=0.2,
            message="Selected Discord route did not expose location controls",
        ),
    )
    _select_discord_setup_location(
        discord_provider_fake_url=discord_provider_fake_url,
        interaction_id="700000000000000006",
        application_id=_DISCORD_SELECTOR_APPLICATION_ID,
        guild_id=_DISCORD_GUILD_ID,
        channel_id=_DISCORD_CHANNEL_ID,
        user_id="600000000000000002",
        custom_id=setup_threads_custom_id,
    )
    state = cast(
        dict[str, object],
        wait_until(
            lambda: (
                (
                    provider_state
                    if (
                        isinstance(
                            request_counts := provider_state.get("request_counts"),
                            dict,
                        )
                        and cast(dict[str, int], request_counts).get("create_thread", 0)
                        > before_thread_count
                        and cast(dict[str, int], request_counts).get(
                            "create_message", 0
                        )
                        > before_message_count
                    )
                    else None
                )
                if (
                    provider_state := _discord_provider_state(discord_provider_fake_url)
                )
                else None
            ),
            timeout=15,
            interval=0.2,
            message=(
                "Discord location selection did not provision its thread and "
                "continue the source"
            ),
        ),
    )
    rendered = str(state)
    interactions = cast(list[dict[str, object]], state["interactions"])
    assert [item["response_type"] for item in interactions] == [4, 7, 4, 7]
    operations = cast(list[dict[str, object]], state["operations"])[
        before_operation_count:
    ]
    thread_channel_id = next(
        operation["thread_channel_id"]
        for operation in operations
        if operation.get("event") == "thread_create"
        and operation.get("outcome") == "delivered"
    )
    deliveries = cast(list[dict[str, object]], state["deliveries"])[
        before_delivery_count:
    ]
    assert any(
        delivery.get("operation") == "create_message"
        and delivery.get("outcome") == "created"
        and delivery.get("channel_id") == thread_channel_id
        for delivery in deliveries
    )

    def selected_binding() -> tuple[Any, Any] | None:
        sessions = chat_api.chat_v1_list_agent_sessions(
            agent_id=agent_ids[1],
            _headers=headers,
        )
        for session in sessions.items:
            projection = external_api.external_channel_v1_list_session_channels(
                agent_id=agent_ids[1],
                session_id=session.id,
                handle=handle,
                _headers=headers,
            )
            if (
                len(projection.items) == 1
                and projection.items[0].provider.value == "discord"
            ):
                return session, projection.items[0]
        return None

    selected_session, selected_channel = cast(
        tuple[Any, Any],
        wait_until(
            selected_binding,
            timeout=15,
            interval=0.2,
            message="Discord HTTP selector replay did not retain one Session binding",
        ),
    )
    assert selected_session.agent_id == agent_ids[1]
    assert selected_channel.provider.value == "discord"
    detail = chat_api.chat_v1_get_agent_session(
        agent_id=agent_ids[1],
        session_id=selected_session.id,
        _headers=headers,
    )
    assert detail.id == selected_session.id
    input_evidence = cast(
        list[dict[str, object]],
        wait_until(
            lambda: (
                evidence
                if len(
                    evidence := _external_channel_input_evidence(
                        public_server_url=azents_public_server_url,
                        token=owner_token,
                        session_id=selected_session.id,
                    )
                )
                == 1
                else None
            ),
            timeout=15,
            interval=0.2,
            message="Discord HTTP selector replay did not activate one mailbox input",
        ),
    )
    assert input_evidence[0]["provider"] == "discord"
    assert input_evidence[0]["body"] == source_content
    expected_session_path = (
        f"/w/{handle}/agents/{agent_ids[1]}/sessions/{selected_session.id}"
    )
    activation_state = cast(
        dict[str, object],
        wait_until(
            lambda: (
                provider_state
                if expected_session_path
                in _successful_session_paths(
                    provider_state := _discord_provider_state(discord_provider_fake_url)
                )
                else None
            ),
            timeout=15,
            interval=0.2,
            message="Discord HTTP selector replay did not deliver joined presence",
        ),
    )
    assert _successful_session_paths(activation_state) == [
        expected_session_path,
        expected_session_path,
    ]
    assert _successful_session_presence_states(activation_state) == ["joined"]
    assert source_content not in rendered
    assert _DISCORD_BOT_TOKEN not in rendered
    assert selector not in rendered
    assert setup_threads_custom_id not in rendered
    assert message_command_id not in rendered


def test_discord_multi_management_and_lifecycle_journey(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
) -> None:
    """Exercise provider-neutral Multi management on one active Discord App."""
    requests.post(
        f"{discord_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{discord_provider_fake_url}/__testenv/configure",
        json={"application_id": _DISCORD_MULTI_APPLICATION_ID},
        timeout=5,
    ).raise_for_status()
    owner_token, _, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        agent_count=2,
        runtime_profile_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {owner_token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_multi_discord_connection(
        handle=handle,
        discord_connection_setup_request=DiscordConnectionSetupRequest(
            app_id=_DISCORD_MULTI_APPLICATION_ID,
            configuration=DiscordConnectionConfiguration(
                target_guild_id=_DISCORD_GUILD_ID
            ),
            credentials=DiscordConnectionCredentials(bot_token=_DISCORD_BOT_TOKEN),
        ),
        _headers=headers,
    )
    validation = external_api.external_channel_v1_validate_multi_discord_connection(
        connection_id=setup.connection.id,
        handle=handle,
        _headers=headers,
    )
    assert validation.status is ExternalChannelConnectionStatus.ACTIVE
    connection = setup.connection
    assert connection.app_mode is ExternalChannelAppMode.MULTI
    assert connection.status is ExternalChannelConnectionStatus.ACTIVE
    assert connection.active_agent_count == 0
    assert connection.credentials_configured is True
    assert _DISCORD_BOT_TOKEN not in setup.model_dump_json(by_alias=True)

    first_route = external_api.external_channel_v1_add_multi_discord_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[0]),
        _headers=headers,
    )
    duplicate_route = external_api.external_channel_v1_add_multi_discord_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[0]),
        _headers=headers,
    )
    second_route = external_api.external_channel_v1_add_multi_discord_route(
        connection_id=connection.id,
        handle=handle,
        multi_route_create_request=MultiRouteCreateRequest(agent_id=agent_ids[1]),
        _headers=headers,
    )
    assert duplicate_route.id == first_route.id
    assert second_route.agent_id == agent_ids[1]

    current = external_api.external_channel_v1_get_multi_discord_connection(
        connection_id=connection.id,
        handle=handle,
        _headers=headers,
    )
    default = external_api.external_channel_v1_replace_multi_discord_channel_default(
        connection_id=connection.id,
        provider_channel_id=_DISCORD_CHANNEL_ID,
        handle=handle,
        multi_channel_default_request=MultiChannelDefaultRequest(
            expected_generation=current.generation,
            route_id=first_route.id,
        ),
        _headers=headers,
    )
    assert default.channel_default is not None
    assert default.channel_default.route_id == first_route.id
    assert default.channel_default.status is ExternalChannelChannelDefaultStatus.ACTIVE
    assert default.invalidated_participation_setting_count == 0
    assert default.terminated_setup_claim_count == 0
    assert default.disconnected_parent_binding_count == 0

    impact = external_api.external_channel_v1_get_multi_discord_route_impact(
        connection_id=connection.id,
        route_id=first_route.id,
        handle=handle,
        _headers=headers,
    )
    removed = external_api.external_channel_v1_remove_multi_discord_route(
        connection_id=connection.id,
        route_id=first_route.id,
        handle=handle,
        generation_fence_request=GenerationFenceRequest(
            expected_generation=impact.generation
        ),
        _headers=headers,
    )
    assert removed.active_default_count == 1
    defaults = external_api.external_channel_v1_list_multi_discord_channel_defaults(
        connection_id=connection.id,
        handle=handle,
        _headers=headers,
    )
    assert defaults.items[0].status is ExternalChannelChannelDefaultStatus.INVALIDATED

    connection_impact = (
        external_api.external_channel_v1_get_multi_discord_connection_impact(
            connection_id=connection.id,
            handle=handle,
            _headers=headers,
        )
    )
    disconnected = external_api.external_channel_v1_disconnect_multi_discord_connection(
        connection_id=connection.id,
        handle=handle,
        generation_fence_request=GenerationFenceRequest(
            expected_generation=connection_impact.generation
        ),
        _headers=headers,
    )
    assert disconnected.disconnected_route_count == 1
    historical = external_api.external_channel_v1_get_multi_discord_connection(
        connection_id=connection.id,
        handle=handle,
        _headers=headers,
    )
    assert historical.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert historical.credentials_configured is False
    assert _DISCORD_BOT_TOKEN not in str(
        _discord_provider_state(discord_provider_fake_url)
    )
