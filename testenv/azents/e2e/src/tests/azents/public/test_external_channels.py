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
_EXTERNAL_CHANNEL_LARGE_FILE_BYTES = 6 * 1024 * 1024


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
    *,
    runtime_provider_id: str | None,
    shell_enabled: bool,
) -> tuple[str, str, str, str]:
    """Create an authenticated workspace administrator and one active Agent."""
    token, email, handle, agent_ids = _create_workspace_agents(
        public_api_client,
        admin_api_client,
        public_server_url,
        agent_count=1,
        runtime_provider_id=runtime_provider_id,
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
    runtime_provider_id: str | None,
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
    agent_api = AgentV1Api(public_api_client)
    agent_ids = [
        agent_api.agent_v1_create_agent(
            handle=handle,
            agent_create_request=AgentCreateRequest(
                name=f"External Channel Agent {index + 1} {suffix}",
                model_selection=model_selection,
                lightweight_model_selection=model_selection,
                type=AgentType.PUBLIC,
                runtime_provider_id=runtime_provider_id,
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


def _external_channel_input_evidence(
    *,
    public_server_url: str,
    token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """Read logical External Channel input through public live and history APIs."""
    live_response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/live",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    live_response.raise_for_status()
    history_response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    history_response.raise_for_status()

    candidates: list[dict[str, object]] = []
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
                    presentation = cast(dict[str, object], raw_item).get("presentation")
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
    """Return the latest sanitized selector view evidence."""
    views = _provider_state(slack_provider_fake_url).get("views")
    if not isinstance(views, list):
        return None
    for raw_view in reversed(cast(list[object], views)):
        if not isinstance(raw_view, dict):
            continue
        view = cast(dict[str, object], raw_view)
        if view.get("callback_id") == "azents_agent_selector":
            return view
    return None


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
        runtime_provider_id=None,
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

    decision = ExternalChannelDecisionInput(
        decision="allow_agent",
        summary="Deterministic E2E approval",
    )
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=decision,
        _headers=headers,
    )
    repeated = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=decision,
        _headers=headers,
    )
    assert decided.status is ExternalChannelAccessRequestStatus.ALLOWED
    assert repeated.status is ExternalChannelAccessRequestStatus.ALLOWED
    assert decided.agent_session_id

    def binding_projection() -> object | None:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=cast(str, decided.agent_session_id),
            handle=handle,
            _headers=headers,
        )
        if len(projection.items) == 1:
            return projection
        return None

    bindings = cast(
        Any,
        wait_until(
            binding_projection,
            timeout=10,
            interval=0.2,
            message="Approved External Channel binding was not available",
        ),
    )
    assert len(bindings.items) == 1
    assert bindings.grants == []
    agent_access = external_api.external_channel_v1_list_agent_access(
        agent_id=agent_id,
        handle=handle,
        _headers=headers,
    )
    assert len(agent_access.grants) == 1
    assert agent_access.grants[0].scope is ExternalChannelAccessGrantScope.AGENT
    assert agent_access.grants[0].agent_session_id is None
    input_evidence = _external_channel_input_evidence(
        public_server_url=azents_public_server_url,
        token=token,
        session_id=decided.agent_session_id,
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
        if typed.get("chat.postMessage") == 2 and typed.get("chat.delete") == 1:
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
    # The initial callback, duplicate delivery, and access replay each revalidate
    # the canonical provider-history boundary before converging on one binding.
    assert typed_counts["conversations.history"] == 3
    assert typed_counts["chat.getPermalink"] == 3
    # One access-review control is deleted after approval, while durable acceptance
    # creates the initial provider-native work progress through the Worker drain.
    assert typed_counts["chat.postMessage"] == 2
    assert typed_counts["chat.delete"] == 1
    rendered_state = str(provider_state)
    assert _BOT_TOKEN not in rendered_state
    assert _SIGNING_SECRET not in rendered_state

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
        runtime_provider_id=None,
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
        runtime_provider_id=None,
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
    assert channel_default.route_id == first_route.id
    assert channel_default.agent_id == agent_ids[0]
    assert channel_default.status is ExternalChannelChannelDefaultStatus.ACTIVE

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
        runtime_provider_id=None,
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
        runtime_provider_id=None,
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
    assert selector_view["has_submit"] is True
    metadata = selector_view.get("private_metadata")
    assert isinstance(metadata, str)
    assert metadata

    submission_payload = {
        "type": "view_submission",
        "api_app_id": app_id,
        "team": {"id": team_id},
        "user": {"id": "U-SELECTOR"},
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
    for _ in range(2):
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

    chat_api = ChatV1Api(public_api_client)

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
    assert _approval_request_id(slack_provider_fake_url) == ""
    provider_state = _provider_state(slack_provider_fake_url)
    request_counts = cast(dict[str, int], provider_state["request_counts"])
    assert request_counts["views.open"] == 1
    assert provider_state["views"] == [selector_view]
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
        runtime_provider_id=None,
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
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=ExternalChannelDecisionInput(
            decision="allow_agent",
            summary="Provider-native progress E2E approval",
        ),
        _headers=headers,
    )
    assert decided.agent_session_id is not None
    session_id = decided.agent_session_id

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
    request_counts = cast(dict[str, int], provider_state["request_counts"])
    assert request_counts["users.info"] >= 2
    assert request_counts["conversations.info"] >= 2
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
        runtime_provider_id="system-docker",
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
        f"{azents_public_server_url}/external-channel/v1/slack/events",
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
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=ExternalChannelDecisionInput(
            decision="allow_agent",
            summary="External Channel file transfer E2E approval",
        ),
        _headers=headers,
    )
    assert decided.agent_session_id is not None
    session_id = decided.agent_session_id

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
            and item.get("search_tool_available") is True
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
            "after_search",
            "after_download",
            "after_process",
        ]
        previous_index = -1
        for stage in expected_stages:
            assert stage in stages, evidence
            index = stages.index(stage)
            assert index > previous_index, evidence
            previous_index = index
        after_search = evidence[stages.index("after_search")]
        assert after_search.get("download_tool_available") is True, evidence
        assert after_search.get("process_tool_available") is True, evidence
        assert after_search.get("channel_action_tool_available") is True, evidence
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


def test_socket_mode_acknowledges_and_preserves_route_for_disabled_link(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    slack_provider_fake_url: str,
) -> None:
    """Exercise durable ACK and reconnect health without removing Agent routing."""
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
            "socket_envelopes": [
                {
                    "envelope_id": envelope_id,
                    "type": "events_api",
                    "payload": socket_payload,
                }
            ],
            "socket_disconnect_reason": "link_disabled",
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=None,
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

    def socket_acknowledged() -> bool:
        socket_state = _provider_state(slack_provider_fake_url).get("socket")
        if not isinstance(socket_state, dict):
            return False
        acknowledgements = cast(dict[str, object], socket_state).get("acknowledgements")
        return isinstance(acknowledgements, list) and envelope_id in cast(
            list[object],
            acknowledgements,
        )

    wait_until(
        socket_acknowledged,
        timeout=20,
        interval=0.2,
        message="Socket Mode envelope was not acknowledged after admission",
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
    assert socket_state["connections"] == 1
    assert "xapp-e2e-private" not in str(provider_state)


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
        runtime_provider_id=None,
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
    connection_text = connection.text
    assert "Slack" in connection_text
    assert "ACTIVE" in connection_text
    assert "HTTP" in connection_text
    assert _TEAM_ID in connection_text
    assert _APP_ID in connection_text
    assert "CREDENTIALS CONFIGURED" in connection_text
    assert _BOT_TOKEN not in browser_driver.page_source
    assert _SIGNING_SECRET not in browser_driver.page_source

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
        runtime_provider_id=None,
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
    command = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000002",
            "type": 2,
            "application_id": _DISCORD_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "member": {"user": {"id": "600000000000000001"}},
        },
        timeout=10,
    )
    command.raise_for_status()
    assert command.json() == {"status": 200, "response_type": 5}

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
            "response_type": 5,
        },
    ]
    rendered_state = str(state)
    assert _DISCORD_BOT_TOKEN not in rendered_state
    assert "Private Discord interaction invocation" not in rendered_state
    assert "X-Signature-Ed25519" not in rendered_state


def test_discord_gateway_message_create_provisions_and_binds_synchronously(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    discord_provider_fake_url: str,
    azents_discord_gateway_worker_factory: Callable[
        [], AbstractContextManager[Container]
    ],
) -> None:
    """Ingest one real Gateway message only after thread and Session acceptance."""
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
        },
        timeout=5,
    ).raise_for_status()
    token, _, handle, agent_id = _create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=None,
        shell_enabled=False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
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

    with azents_discord_gateway_worker_factory():
        wait_until(
            lambda: (
                cast(
                    int,
                    cast(
                        dict[str, object],
                        _discord_provider_state(discord_provider_fake_url)["gateway"],
                    )["connections"],
                )
                >= 1
            ),
            timeout=45,
            interval=0.2,
            message="Discord Gateway Worker did not connect to the provider fake",
        )
        session, binding = cast(
            tuple[Any, Any],
            wait_until(
                gateway_binding,
                timeout=30,
                interval=0.2,
                message="Discord Gateway create did not activate one Session binding",
            ),
        )

    assert session.agent_id == agent_id
    assert binding.provider.value == "discord"
    input_evidence = _external_channel_input_evidence(
        public_server_url=azents_public_server_url,
        token=token,
        session_id=session.id,
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
    request_counts = cast(dict[str, int], state["request_counts"])
    assert request_counts["create_thread"] >= 1
    # Thread reconciliation runs before create; canonical history runs after create.
    assert request_counts["get_message"] >= 2
    gateway = cast(dict[str, object], state["gateway"])
    assert cast(int, gateway["connections"]) >= 1
    initial_opcodes = cast(list[object], gateway["initial_opcodes"])
    assert initial_opcodes
    assert set(initial_opcodes) == {2}
    dispatches = cast(list[object], gateway["dispatches"])
    assert {"event_type": "GUILD_CREATE", "sequence": 2} in dispatches
    assert {"event_type": "MESSAGE_CREATE", "sequence": 3} in dispatches
    rendered = str(state)
    assert source_text not in rendered
    assert _DISCORD_BOT_TOKEN not in rendered


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
        runtime_provider_id=None,
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
    interaction = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000003",
            "type": 2,
            "application_id": _DISCORD_SELECTOR_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "member": {"user": {"id": "600000000000000002"}},
            "data": {
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
    component = requests.post(
        f"{discord_provider_fake_url}/__testenv/interactions",
        json={
            "id": "700000000000000004",
            "type": 3,
            "application_id": _DISCORD_SELECTOR_APPLICATION_ID,
            "guild_id": _DISCORD_GUILD_ID,
            "channel_id": _DISCORD_CHANNEL_ID,
            "member": {"user": {"id": "600000000000000002"}},
            "message": {"id": "800000000000000001"},
            "data": {"custom_id": selector, "values": [routes[1].id]},
        },
        timeout=10,
    )
    component.raise_for_status()
    assert component.json() == {"status": 200, "response_type": 7}
    state = _discord_provider_state(discord_provider_fake_url)
    rendered = str(state)
    interactions = cast(list[dict[str, object]], state["interactions"])
    assert [item["response_type"] for item in interactions] == [4, 7]
    assert source_content not in rendered
    assert _DISCORD_BOT_TOKEN not in rendered
    assert selector not in rendered


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
        runtime_provider_id=None,
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
    assert default.route_id == first_route.id
    assert default.status is ExternalChannelChannelDefaultStatus.ACTIVE

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
