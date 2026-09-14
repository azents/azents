"""OAuth-based External Account linking E2E journeys."""

import json
import time
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit, urlunsplit

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import authenticate_user, unique, wait_until
from tests.required.public import external_channel_scenarios as external_scenarios
from tests.required.public.test_security import _elevate_user

_SLACK_APP_ID = "A-E2E"
_SLACK_TEAM_ID = "T-E2E"
_SLACK_CHANNEL_ID = "C-E2E"
_SLACK_BOT_TOKEN = "xoxb-e2e-private"
_SLACK_SIGNING_SECRET = "e2e-signing-private"
_PROVIDER_CLIENT_IDS = {
    "slack": "slack-oauth-client",
    "discord": "100000000000000001",
}
_PROVIDER_CLIENT_SECRETS = {
    "slack": "slack-oauth-secret",
    "discord": "discord-oauth-secret",
}


class _OAuthCallback(NamedTuple):
    """One request-local provider callback handoff."""

    code: str
    state: str


class _LinkedAccount(NamedTuple):
    """One completed global link and its consumed callback."""

    link: dict[str, object]
    callback: _OAuthCallback


class _SlackWorkspace(NamedTuple):
    """One target Workspace with an active Slack connection."""

    token: str
    handle: str
    agent_id: str


class _SessionBinding(NamedTuple):
    """One exact Session and External Channel Binding."""

    session_id: str
    binding_id: str


def _object(value: object) -> dict[str, object]:
    """Validate one JSON object with string keys."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AssertionError("Expected a JSON object with string keys.")
    return value


def _list(value: object) -> list[object]:
    """Validate one JSON list."""
    if not isinstance(value, list):
        raise AssertionError("Expected a JSON list.")
    return value


def _json(response: requests.Response) -> dict[str, object]:
    """Require one successful JSON object response."""
    response.raise_for_status()
    return _object(response.json())


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _public_url(server_url: str, path: str) -> str:
    return f"{server_url}/external-channel/v1/{path.lstrip('/')}"


def _error_code(response: requests.Response) -> str | None:
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        return None
    code = detail.get("code")
    return code if isinstance(code, str) else None


def _require_sanitized_evidence(rendered: str, secrets: tuple[str, ...]) -> None:
    """Fail without echoing transient OAuth material."""
    if any(secret and secret in rendered for secret in secrets):
        raise AssertionError(
            "Sanitized provider evidence exposed OAuth secret material."
        )


def _request_count(fake_url: str, operation: str) -> int:
    """Return one sanitized provider request count."""
    state = _json(requests.get(f"{fake_url}/__testenv/state", timeout=5))
    counts = state.get("request_counts")
    if not isinstance(counts, dict):
        return 0
    value = counts.get(operation)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _admin_token(admin_api_client: azentsadminclient.ApiClient) -> str:
    token = admin_api_client.configuration.access_token
    if not isinstance(token, str) or not token:
        raise AssertionError("Admin API client is not authenticated.")
    return token


def _configure_provider_oauth(
    *,
    admin_api_client: azentsadminclient.ApiClient,
    admin_server_url: str,
    public_server_url: str,
    user_token: str,
    fake_url: str,
    provider: str,
    identity: dict[str, object] | None = None,
) -> str:
    """Configure one Admin-owned provider Section and matching fake identity."""
    section_url = (
        f"{admin_server_url}/system-setting/v1/sections/"
        f"external-account-oauth/{provider}"
    )
    headers = _auth(_admin_token(admin_api_client))
    current = _json(requests.get(section_url, headers=headers, timeout=10))
    version = current.get("admin_version")
    assert isinstance(version, int)
    identifier_field = "client_id" if provider == "slack" else "application_id"
    configured = _json(
        requests.patch(
            section_url,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "expected_version": version,
                identifier_field: _PROVIDER_CLIENT_IDS[provider],
                "client_secret": {
                    "action": "replace",
                    "value": _PROVIDER_CLIENT_SECRETS[provider],
                },
            },
            timeout=10,
        )
    )
    callback_url = configured.get("callback_url")
    assert isinstance(callback_url, str) and callback_url
    fake_configuration = {
        "client_id": _PROVIDER_CLIENT_IDS[provider],
        "client_secret": _PROVIDER_CLIENT_SECRETS[provider],
        "redirect_uri": callback_url,
        **(identity or {}),
    }
    requests.post(
        f"{fake_url}/__testenv/configure",
        json={"oauth": fake_configuration},
        timeout=5,
    ).raise_for_status()
    providers = _json(
        requests.get(
            _public_url(public_server_url, "account-links/providers"),
            headers=_auth(user_token),
            timeout=10,
        )
    )
    matching = [
        item
        for item in _list(providers["items"])
        if isinstance(item, dict) and item.get("provider") == provider
    ]
    assert len(matching) == 1
    assert matching[0].get("available") is True
    return callback_url


def _host_authorization_url(authorization_url: str, fake_url: str) -> str:
    """Route an internal fake authorization URL through its host-visible port."""
    authorization = urlsplit(authorization_url)
    fake = urlsplit(fake_url)
    return urlunsplit(
        (fake.scheme, fake.netloc, authorization.path, authorization.query, "")
    )


def _start_oauth(*, server_url: str, token: str, provider: str) -> str:
    result = _json(
        requests.post(
            _public_url(server_url, f"account-links/oauth/{provider}/start"),
            headers=_auth(token),
            timeout=10,
        )
    )
    authorization_url = result.get("authorization_url")
    assert isinstance(authorization_url, str) and authorization_url
    return authorization_url


def _authorize(authorization_url: str, fake_url: str) -> _OAuthCallback:
    response = requests.get(
        _host_authorization_url(authorization_url, fake_url),
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    code = query.get("code")
    state = query.get("state")
    assert isinstance(code, list) and len(code) == 1
    assert isinstance(state, list) and len(state) == 1
    return _OAuthCallback(code=code[0], state=state[0])


def _exchange(
    *,
    server_url: str,
    token: str,
    provider: str,
    callback: _OAuthCallback,
) -> requests.Response:
    return requests.post(
        _public_url(server_url, f"account-links/oauth/{provider}/exchange"),
        headers={**_auth(token), "Content-Type": "application/json"},
        json={"code": callback.code, "state": callback.state},
        timeout=10,
    )


def _complete_oauth(
    *, server_url: str, token: str, provider: str, fake_url: str
) -> _LinkedAccount:
    callback = _authorize(
        _start_oauth(server_url=server_url, token=token, provider=provider),
        fake_url,
    )
    return _LinkedAccount(
        link=_json(
            _exchange(
                server_url=server_url,
                token=token,
                provider=provider,
                callback=callback,
            )
        ),
        callback=callback,
    )


def _list_links(server_url: str, token: str) -> list[dict[str, object]]:
    payload = _json(
        requests.get(
            _public_url(server_url, "account-links"),
            headers=_auth(token),
            timeout=10,
        )
    )
    return [item for item in _list(payload["items"]) if isinstance(item, dict)]


def _setup_slack_workspace(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
) -> _SlackWorkspace:
    """Create one target Workspace and Slack connection through public APIs."""
    created = external_scenarios._create_agent(
        public_api_client,
        admin_api_client,
        public_server_url,
        runtime_profile_provider_id=None,
    )
    api = ExternalChannelV1Api(public_api_client)
    setup = api.external_channel_v1_setup_slack_connection(
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
        lambda: api.external_channel_v1_disconnect_connection(
            agent_id=created.agent_id,
            connection_id=setup.connection.id,
            handle=created.handle,
            _headers=_auth(created.token),
        )
    )
    validated = api.external_channel_v1_validate_connection(
        agent_id=created.agent_id,
        connection_id=setup.connection.id,
        handle=created.handle,
        _headers=_auth(created.token),
    )
    assert validated.status is ExternalChannelConnectionStatus.ACTIVE
    return _SlackWorkspace(created.token, created.handle, created.agent_id)


def _transient_slack_view(
    fake_url: str, *, scope: str, after_hash: str | None = None
) -> dict[str, object] | None:
    payload = _json(
        requests.get(
            f"{fake_url}/__testenv/transient-view",
            params={"scope": scope},
            timeout=5,
        )
    )
    view_hash = payload.get("view_hash")
    if not isinstance(view_hash, str) or view_hash == after_hash:
        return None
    return payload


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
            return _SessionBinding(session.id, projection.items[0].id)
    return None


def _seed_connected_slack_channel(
    *,
    public_api_client: azentspublicclient.ApiClient,
    server_url: str,
    fake_url: str,
    workspace: _SlackWorkspace,
    user_id: str,
) -> _SessionBinding:
    """Create one exact guest Session/Binding through signed Slack callbacks."""
    callback_url = f"{server_url}/external-channel/v1/slack/events"
    root_timestamp = f"{int(time.time()) - 60}.000100"
    requests.post(
        f"{fake_url}/__testenv/configure",
        json={
            "provider_team_id": _SLACK_TEAM_ID,
            "history_pages": [
                [
                    {
                        "user": user_id,
                        "ts": root_timestamp,
                        "text": "Start deterministic global-link target setup.",
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-global-link-{unique()}",
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
        data=body,
        headers=external_scenarios._signed_headers(body),
        timeout=10,
    )
    assert response.status_code == 200
    wait_until(
        lambda: _request_count(fake_url, "chat.postMessage") >= 1,
        timeout=15,
        interval=0.2,
        message="Slack guest setup control was not delivered",
    )
    external_scenarios._open_slack_setup_modal(
        callback_url=callback_url,
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        channel_id=_SLACK_CHANNEL_ID,
        user_id=user_id,
    )
    setup_view = _object(
        wait_until(
            lambda: _transient_slack_view(fake_url, scope="setup"),
            timeout=15,
            interval=0.2,
            message="Slack setup modal was not rendered",
        )
    )
    external_scenarios._submit_slack_setup_location(
        callback_url=callback_url,
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        user_id=user_id,
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
        message="Slack setup did not create a Session Binding",
    )
    assert isinstance(binding, _SessionBinding)
    return binding


def _open_slack_settings(
    *, server_url: str, fake_url: str, user_id: str
) -> dict[str, object]:
    """Open one current private settings view for the target channel."""
    previous = _transient_slack_view(fake_url, scope="settings")
    previous_hash = previous.get("view_hash") if previous is not None else None
    assert previous_hash is None or isinstance(previous_hash, str)
    external_scenarios._open_slack_setup_modal(
        callback_url=f"{server_url}/external-channel/v1/slack/events",
        app_id=_SLACK_APP_ID,
        team_id=_SLACK_TEAM_ID,
        channel_id=_SLACK_CHANNEL_ID,
        user_id=user_id,
    )
    return _object(
        wait_until(
            lambda: _transient_slack_view(
                fake_url,
                scope="settings",
                after_hash=previous_hash,
            ),
            timeout=15,
            interval=0.2,
            message="Slack settings view was not rendered",
        )
    )


def test_slack_web_oauth_global_reuse_unlink_and_target_fence(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    slack_provider_fake_url: str,
) -> None:
    """Reuse one global Slack identity without bypassing target membership."""
    linked_token, _, linked_email = authenticate_user(
        public_api_client, admin_api_client
    )
    _configure_provider_oauth(
        admin_api_client=admin_api_client,
        admin_server_url=azents_admin_server_url,
        public_server_url=azents_public_server_url,
        user_token=linked_token,
        fake_url=slack_provider_fake_url,
        provider="slack",
        identity={
            "user_id": "U-GLOBAL-LINK",
            "user_label": "Global Slack User",
            "team_id": _SLACK_TEAM_ID,
            "team_label": "Global Slack Team",
        },
    )
    linked = _complete_oauth(
        server_url=azents_public_server_url,
        token=linked_token,
        provider="slack",
        fake_url=slack_provider_fake_url,
    )
    assert linked.link["identity_scope"] == _SLACK_TEAM_ID
    assert linked.link["provider_user_id"] == "U-GLOBAL-LINK"

    target = _setup_slack_workspace(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    _seed_connected_slack_channel(
        public_api_client=public_api_client,
        server_url=azents_public_server_url,
        fake_url=slack_provider_fake_url,
        workspace=target,
        user_id="U-GLOBAL-LINK",
    )
    settings = _open_slack_settings(
        server_url=azents_public_server_url,
        fake_url=slack_provider_fake_url,
        user_id="U-GLOBAL-LINK",
    )
    action_ids = settings.get("action_ids")
    assert isinstance(action_ids, list)
    assert "azents_model_open" not in action_ids
    link_paths = settings.get("link_paths")
    assert isinstance(link_paths, list)
    assert "/account/external-accounts" in link_paths
    assert "/account/external-accounts/connect/slack" not in link_paths

    elevated = _elevate_user(
        public_api_client,
        admin_api_client,
        linked_token,
        linked_email,
    )
    unlinked = _json(
        requests.delete(
            _public_url(
                azents_public_server_url,
                f"account-links/{linked.link['id']}",
            ),
            headers=_auth(elevated),
            timeout=10,
        )
    )
    assert unlinked["state"] == "revoked"
    reopened = _open_slack_settings(
        server_url=azents_public_server_url,
        fake_url=slack_provider_fake_url,
        user_id="U-GLOBAL-LINK",
    )
    reopened_paths = reopened.get("link_paths")
    assert isinstance(reopened_paths, list)
    assert "/account/external-accounts/connect/slack" in reopened_paths
    reopened_actions = reopened.get("action_ids")
    assert isinstance(reopened_actions, list)
    assert "azents_conversation_response_mode" in reopened_actions


def test_discord_web_oauth_global_link_replay_and_unlink(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    discord_provider_fake_url: str,
) -> None:
    """Create one Discord global link, reject replay, and unlink globally."""
    token, _, email = authenticate_user(public_api_client, admin_api_client)
    _configure_provider_oauth(
        admin_api_client=admin_api_client,
        admin_server_url=azents_admin_server_url,
        public_server_url=azents_public_server_url,
        user_token=token,
        fake_url=discord_provider_fake_url,
        provider="discord",
        identity={
            "user_id": "730000000000000001",
            "username": "global-discord-user",
            "global_name": "Global Discord User",
        },
    )
    linked = _complete_oauth(
        server_url=azents_public_server_url,
        token=token,
        provider="discord",
        fake_url=discord_provider_fake_url,
    )
    assert linked.link["identity_scope"] == "global"
    assert linked.link["provider_user_id"] == "730000000000000001"
    assert _list_links(azents_public_server_url, token) == [linked.link]
    replay = _exchange(
        server_url=azents_public_server_url,
        token=token,
        provider="discord",
        callback=linked.callback,
    )
    assert replay.status_code == 409
    assert _error_code(replay) == "already_consumed"
    elevated = _elevate_user(public_api_client, admin_api_client, token, email)
    unlinked = _json(
        requests.delete(
            _public_url(
                azents_public_server_url,
                f"account-links/{linked.link['id']}",
            ),
            headers=_auth(elevated),
            timeout=10,
        )
    )
    assert unlinked["state"] == "revoked"
    assert _list_links(azents_public_server_url, token) == []


def test_oauth_auth_session_provider_and_conflict_fences(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    slack_provider_fake_url: str,
    discord_provider_fake_url: str,
) -> None:
    """Reject substituted Sessions, provider mismatch, tamper, and conflict."""
    owner_token, _, owner_email = authenticate_user(public_api_client, admin_api_client)
    contender_token, _, contender_email = authenticate_user(
        public_api_client, admin_api_client
    )
    _configure_provider_oauth(
        admin_api_client=admin_api_client,
        admin_server_url=azents_admin_server_url,
        public_server_url=azents_public_server_url,
        user_token=owner_token,
        fake_url=slack_provider_fake_url,
        provider="slack",
        identity={"user_id": "U-CONFLICT", "team_id": _SLACK_TEAM_ID},
    )
    _configure_provider_oauth(
        admin_api_client=admin_api_client,
        admin_server_url=azents_admin_server_url,
        public_server_url=azents_public_server_url,
        user_token=owner_token,
        fake_url=discord_provider_fake_url,
        provider="discord",
    )
    callback = _authorize(
        _start_oauth(
            server_url=azents_public_server_url,
            token=owner_token,
            provider="slack",
        ),
        slack_provider_fake_url,
    )
    replacement_session, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=owner_email,
    )
    substituted = _exchange(
        server_url=azents_public_server_url,
        token=replacement_session,
        provider="slack",
        callback=callback,
    )
    assert substituted.status_code == 409
    assert _error_code(substituted) == "auth_session_mismatch"
    mismatch = _exchange(
        server_url=azents_public_server_url,
        token=owner_token,
        provider="discord",
        callback=callback,
    )
    assert mismatch.status_code == 400
    assert _error_code(mismatch) == "provider_mismatch"
    tampered = _exchange(
        server_url=azents_public_server_url,
        token=owner_token,
        provider="slack",
        callback=_OAuthCallback(callback.code, callback.state + "tampered"),
    )
    assert tampered.status_code == 400
    assert _error_code(tampered) == "invalid_attempt"
    _json(
        _exchange(
            server_url=azents_public_server_url,
            token=owner_token,
            provider="slack",
            callback=callback,
        )
    )
    contender_callback = _authorize(
        _start_oauth(
            server_url=azents_public_server_url,
            token=contender_token,
            provider="slack",
        ),
        slack_provider_fake_url,
    )
    conflict = _exchange(
        server_url=azents_public_server_url,
        token=contender_token,
        provider="slack",
        callback=contender_callback,
    )
    assert conflict.status_code == 409
    assert _error_code(conflict) == "conflict"
    assert owner_email not in conflict.text
    assert contender_email not in conflict.text


def _browser_password_elevation(driver: WebDriver) -> None:
    """Complete password elevation without exposing authentication material."""
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


def run_web_external_account_oauth_management(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Verify protected Web OAuth, global list, mobile layout, and unlink."""
    created = external_scenarios._create_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_profile_provider_id=None,
    )
    _configure_provider_oauth(
        admin_api_client=admin_api_client,
        admin_server_url=azents_admin_server_url,
        public_server_url=azents_public_server_url,
        user_token=created.token,
        fake_url=slack_provider_fake_url,
        provider="slack",
        identity={
            "user_id": "U-WEB-OAUTH",
            "user_label": "Web OAuth User",
            "team_id": _SLACK_TEAM_ID,
            "team_label": "Web OAuth Team",
        },
    )
    external_scenarios._login_main_web(
        browser_driver,
        main_web_url=azents_main_web_url,
        email=created.email,
    )
    browser_driver.get(f"{azents_main_web_url}/account/external-accounts/connect/slack")
    wait = WebDriverWait(browser_driver, 30)
    result = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-account-oauth-result"]')
        )
    )
    assert "Slack account connected" in result.text
    browser_driver.set_window_size(390, 844)
    browser_driver.get(f"{azents_main_web_url}/account/external-accounts")
    root = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="external-account-links"]')
        )
    )
    assert "Web OAuth User" in root.text
    links = _list_links(azents_public_server_url, created.token)
    assert len(links) == 1
    link_id = links[0]["id"]
    assert isinstance(link_id, str)
    row_selector = f'[data-testid="external-account-link-{link_id}"]'
    row = wait.until(ec.visibility_of_element_located((By.CSS_SELECTOR, row_selector)))
    assert "Connected" in row.text
    overflow = browser_driver.execute_script(
        "return document.documentElement.scrollWidth > "
        "document.documentElement.clientWidth;"
    )
    assert overflow is False
    row.find_element(By.XPATH, ".//button[normalize-space()='Disconnect']").click()
    wait.until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Disconnect account']")
        )
    ).click()
    _browser_password_elevation(browser_driver)
    wait.until(ec.invisibility_of_element_located((By.CSS_SELECTOR, row_selector)))
    wait_until(
        lambda: _list_links(azents_public_server_url, created.token) == [],
        timeout=15,
        interval=0.2,
        message="Web disconnect did not remove the global link",
    )
    browser_driver.set_window_size(1280, 844)
