"""External Channel deterministic provider and management E2E journeys."""

import hashlib
import hmac
import json
import time
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.external_channel_access_grant_scope import (
    ExternalChannelAccessGrantScope,
)
from azentspublicclient.models.external_channel_access_request_status import (
    ExternalChannelAccessRequestStatus,
)
from azentspublicclient.models.external_channel_binding_activation_status import (
    ExternalChannelBindingActivationStatus,
)
from azentspublicclient.models.external_channel_connection_status import (
    ExternalChannelConnectionStatus,
)
from azentspublicclient.models.external_channel_decision_input import (
    ExternalChannelDecisionInput,
)
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.external_channel_work_task_status import (
    ExternalChannelWorkTaskStatus,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
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


def _create_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
) -> tuple[str, str, str, str]:
    """Create an authenticated workspace administrator and one active Agent."""
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
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"External Channel Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
        ),
        _headers=headers,
    )
    return token, email, handle, agent.id


def _signed_headers(body: bytes) -> dict[str, str]:
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
        "Content-Type": "application/json",
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
            and blocks
            and isinstance(blocks[0], dict)
            and cast(dict[str, object], blocks[0]).get("type") == "plan"
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


def _channel_action_tool_evidence(
    public_server_url: str,
    token: str,
    session_id: str,
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
        if (
            event_payload.get("name") != "channel_action"
            and event_payload.get("call_id") != "call_external_channel_progress"
        ):
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
    """Return request evidence after the exact progress stage is observed."""
    expected = {
        "binding": binding_id,
        "marker_present": True,
        "resolved_user_reference": True,
        "resolved_channel_reference": True,
        "progress_tool_available": True,
        "path": "/v1/responses",
        "matched": True,
        "stage": "initial",
    }
    evidence = _progress_request_evidence(openai_proxy_url)
    assert any(
        all(item.get(key) == value for key, value in expected.items())
        for item in evidence
    ), evidence
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
    assert setup.connection.credentials_configured is True
    setup_json = setup.model_dump_json(by_alias=True)
    assert _BOT_TOKEN not in setup_json
    assert _SIGNING_SECRET not in setup_json

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

    def hydrated_approval() -> object | None:
        current = external_api.external_channel_v1_get_approval_request(
            access_request_id=request_id,
            _headers=headers,
        )
        return current if current.original_url is not None else None

    approval = cast(
        Any,
        wait_until(
            hydrated_approval,
            timeout=15,
            interval=0.2,
            message="Slack history and permalink hydration did not complete",
        ),
    )
    assert approval.status is ExternalChannelAccessRequestStatus.PENDING
    assert approval.agent_id == agent_id
    assert approval.source_text == "<@B-E2E> investigate"
    assert approval.original_url is not None

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

    def active_binding_projection() -> object | None:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=cast(str, decided.agent_session_id),
            handle=handle,
            _headers=headers,
        )
        if (
            len(projection.items) == 1
            and projection.items[0].activation_status
            is ExternalChannelBindingActivationStatus.ACTIVE
        ):
            return projection
        return None

    bindings = cast(
        Any,
        wait_until(
            active_binding_projection,
            timeout=10,
            interval=0.2,
            message="Approved External Channel binding was not activated",
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
    provider_state = _provider_state(slack_provider_fake_url)
    request_counts = provider_state.get("request_counts")
    assert isinstance(request_counts, dict)
    typed_counts = cast(dict[str, Any], request_counts)
    assert typed_counts["conversations.info"] == 1
    assert typed_counts["conversations.replies"] == 1
    assert typed_counts["chat.getPermalink"] == 1
    assert typed_counts["chat.postMessage"] == 3
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


def test_provider_native_channel_work_progress_journey(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    slack_provider_fake_url: str,
    openai_proxy_url: str,
) -> None:
    """Render one rich canonical work snapshot through Slack's native Plan."""
    del azents_engine_worker_container
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

    def active_management_projection() -> object | None:
        projection = external_api.external_channel_v1_list_session_channels(
            agent_id=agent_id,
            session_id=session_id,
            handle=handle,
            _headers=headers,
        )
        if (
            len(projection.items) == 1
            and projection.items[0].activation_status
            is ExternalChannelBindingActivationStatus.ACTIVE
            and projection.items[0].work is not None
        ):
            return projection
        return None

    active_projection = cast(
        Any,
        wait_until(
            active_management_projection,
            timeout=15,
            interval=0.2,
            message="Approved Channel Work binding was not activated",
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

    plan_delivery = cast(
        dict[str, object],
        wait_until(
            lambda: _plan_delivery(slack_provider_fake_url),
            timeout=20,
            interval=0.2,
            message="Slack Plan update was not delivered",
        ),
    )
    assert plan_delivery["text"] == (
        "Investigating error logs…\n"
        "In progress: Inspect recent failures\n"
        "Completed: Verify the affected release\n"
        "Failed: Trace the unavailable dependency\n"
        "Pending: Summarize the incident"
    )
    blocks = cast(list[dict[str, object]], plan_delivery["blocks"])
    assert len(blocks) == 1
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
    assert request_counts["users.info"] >= 4
    assert request_counts["conversations.info"] >= 3
    assert _BOT_TOKEN not in str(provider_state)
    assert _SIGNING_SECRET not in str(provider_state)


def test_socket_mode_acknowledges_and_preserves_route_for_disabled_link(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
    slack_provider_fake_url: str,
) -> None:
    """Exercise durable ACK and reconnect health without removing Agent routing."""
    del azents_engine_worker_container
    envelope_id = f"Env-{unique()}"
    root_timestamp = f"{int(time.time()) - 60}.000200"
    socket_payload = {
        "type": "event_callback",
        "event_id": f"Ev-{unique()}",
        "event_time": int(time.time()),
        "api_app_id": _APP_ID,
        "team_id": _TEAM_ID,
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
    )
    headers = {"Authorization": f"Bearer {token}"}
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent_id,
        handle=handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
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
