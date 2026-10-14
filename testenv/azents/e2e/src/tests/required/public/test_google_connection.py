"""Assembled Google OAuth, review/publication and Worker capability product flows."""

import json
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import azentsadminclient
import azentspublicclient
import requests
from azentsadminclient.api.system_settings_v1_api import SystemSettingsV1Api
from azentsadminclient.models.google_application_patch_request import (
    GoogleApplicationPatchRequest,
)
from azentsadminclient.models.system_setting_secret_action_request import (
    SystemSettingSecretActionRequest,
)
from azentsadminclient.models.system_setting_secret_action_type import (
    SystemSettingSecretActionType,
)
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.google_cancel_output import GoogleCancelOutput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.models.google_review import GoogleReview
from pydantic import BaseModel, ConfigDict

from support.google_provider_fake import CLIENT_ID, CLIENT_SECRET
from support.google_provider_fixture import GoogleProviderFixture
from support.observations import ToolResultObservation
from support.utils import single_candidate_model_options, unique
from tests.required.admin.test_03_system_settings import _replace_secret
from tests.required.public.test_brave_search import (
    _tool_events,
    _wait_for_terminal_session,
)
from tests.required.public.test_per_prompt_inference_profile import (
    _create_profile_session,
)
from tests.required.public.test_runtime_optional_capability import _create_workspace

E2E_PLANNER_FALLBACK_WEIGHT = 35.0


class ProviderState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str
    exchanges: int
    refreshes: int
    calls: list[str]


class Callback(NamedTuple):
    code: str
    state: str


def saved_status(base: str, token: str, toolkit_id: str) -> GoogleConnectionOutput:
    result = GoogleConnectionOutput.from_json(
        response(
            base, token, "GET", "/toolkit-configs/" + toolkit_id + "/google/connection"
        ).text
    )
    assert result is not None
    return result


def fixture_ready(fixture: GoogleProviderFixture | None) -> GoogleProviderFixture:
    if fixture is None:
        raise AssertionError("Google product fixture was not prepared for this lane.")
    return fixture


def scenario(fixture: GoogleProviderFixture, name: str) -> None:
    response = requests.post(
        fixture.control_url + "/__testenv/scenario", json={"scenario": name}, timeout=5
    )
    response.raise_for_status()


def prepare_operator(admin: azentsadminclient.ApiClient) -> None:
    settings = SystemSettingsV1Api(admin)
    before = settings.system_settings_v1_get_google_oauth_setting()
    configured = settings.system_settings_v1_patch_google_oauth_setting(
        GoogleApplicationPatchRequest(
            expected_version=before.admin_version,
            client_id=CLIENT_ID,
            client_secret=_replace_secret(CLIENT_SECRET),
        )
    )
    assert configured.status == "configured_unverified"
    assert (
        configured.preview_verified is False
        and configured.service_access_verified is False
    )
    assert CLIENT_SECRET not in configured.to_json()


def response(
    base: str, token: str, method: str, path: str, body: object | None = None
) -> requests.Response:
    result = requests.request(
        method,
        base + path,
        headers={"Authorization": "Bearer " + token},
        json=body,
        timeout=20,
    )
    result.raise_for_status()
    return result


def authorize(fixture: GoogleProviderFixture, url: str) -> Callback:
    parsed = urlsplit(url)
    assert parsed.hostname == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["prompt"] == ["consent"]
    redirected = requests.get(
        fixture.control_url + parsed.path + "?" + parsed.query,
        timeout=5,
        allow_redirects=False,
    )
    assert redirected.status_code == 302
    callback = parse_qs(urlsplit(redirected.headers["Location"]).query)
    assert callback["state"] == query["state"]
    return Callback(callback["code"][0], callback["state"][0])


def connect(
    fixture: GoogleProviderFixture, base: str, token: str, toolkit_id: str | None = None
) -> GoogleReview:
    path = (
        "/google/connect"
        if toolkit_id is None
        else "/toolkit-configs/" + toolkit_id + "/google/reconnect"
    )
    prepared = GoogleConnectOutput.from_json(
        response(
            base,
            token,
            "POST",
            path,
            {"tasks": ["calendar_read", "calendar_edit", "gmail_read"], "timeout": 30},
        ).text
    )
    assert prepared is not None
    code, state = authorize(fixture, prepared.authorization_url)
    reviewed = GoogleReview.from_json(
        response(
            base, token, "POST", "/google/exchange", {"code": code, "state": state}
        ).text
    )
    assert reviewed is not None and reviewed.attempt_id == prepared.attempt_id
    assert reviewed.grant_result == "partial" and reviewed.renewable
    assert (
        reviewed.identity.email == "connected-account@example.invalid"
        or reviewed.identity.email == "replacement-account@example.invalid"
    )
    assert "access_token" not in reviewed.model_dump_json()
    assert (
        next(
            item for item in reviewed.tasks if item.task.value == "calendar_edit"
        ).status
        == "not_granted"
    )
    return reviewed


def final_settings(slug: str) -> dict[str, object]:
    return {
        "name": "Google product fixture",
        "slug": slug,
        "description": None,
        "prompt": None,
        "enabled": True,
        "always_expose_tools": True,
        "tasks": ["calendar_read"],
        "timeout": 30,
        "security_risk_acknowledged": True,
    }


def test_google_catalog_follows_operator_configuration(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    settings = SystemSettingsV1Api(admin_api_client)
    catalog = ToolkitV1Api(public_api_client)
    before = settings.system_settings_v1_get_google_oauth_setting()
    cleared = settings.system_settings_v1_patch_google_oauth_setting(
        GoogleApplicationPatchRequest(
            expected_version=before.admin_version,
            client_id=None,
            client_secret=SystemSettingSecretActionRequest(
                action=SystemSettingSecretActionType.CLEAR
            ),
        )
    )
    assert cleared.status == "not_configured"
    hidden = catalog.toolkit_v1_list_toolkits()
    hidden_slugs = [item.slug for item in hidden.items]
    assert "google" not in hidden_slugs and "brave_search" in hidden_slugs
    prepare_operator(admin_api_client)
    visible = catalog.toolkit_v1_list_toolkits()
    assert [item.slug for item in visible.items if item.slug != "google"] == (
        hidden_slugs
    )
    assert any(item.slug == "google" for item in visible.items)
    assert CLIENT_SECRET not in visible.to_json()
    current = settings.system_settings_v1_get_google_oauth_setting()
    settings.system_settings_v1_patch_google_oauth_setting(
        GoogleApplicationPatchRequest(
            expected_version=current.admin_version,
            client_secret=SystemSettingSecretActionRequest(
                action=SystemSettingSecretActionType.CLEAR
            ),
        )
    )
    assert not any(
        item.slug == "google" for item in catalog.toolkit_v1_list_toolkits().items
    )


def test_google_review_publication_reconnect_and_exact_outcome(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    google_provider_fixture: GoogleProviderFixture | None,
) -> None:
    fixture = fixture_ready(google_provider_fixture)
    scenario(fixture, "partial")
    prepare_operator(admin_api_client)
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    base = f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
    before = ToolkitV1Api(public_api_client).toolkit_v1_list_toolkit_configs(
        workspace.handle, _headers={"Authorization": "Bearer " + workspace.token}
    )
    review = connect(fixture, base, workspace.token)
    staged = ToolkitV1Api(public_api_client).toolkit_v1_list_toolkit_configs(
        workspace.handle, _headers={"Authorization": "Bearer " + workspace.token}
    )
    assert len(before.items) == len(staged.items)
    body = {"settings": final_settings("google_product")}
    path = "/google/attempts/" + review.attempt_id + "/confirm"
    denied = requests.post(
        base + path,
        headers={"Authorization": "Bearer " + workspace.token},
        json={
            "settings": {
                **final_settings("google_product"),
                "security_risk_acknowledged": False,
            }
        },
        timeout=10,
    )
    assert denied.status_code == 422
    published = GooglePublishedOutput.from_json(
        response(base, workspace.token, "POST", path, body).text
    )
    assert published is not None and published.current
    duplicate = GooglePublishedOutput.from_json(
        response(base, workspace.token, "POST", path, body).text
    )
    assert duplicate == published
    candidate = connect(fixture, base, workspace.token, published.toolkit_id)
    discarded = response(
        base, workspace.token, "DELETE", "/google/attempts/" + candidate.attempt_id
    )
    discarded_state = GoogleCancelOutput.from_json(discarded.text)
    assert discarded_state is not None and discarded_state.cancelled
    current = saved_status(base, workspace.token, published.toolkit_id)
    assert current.identity is not None
    assert current.identity.email == "connected-account@example.invalid"
    scenario(fixture, "changed_account")
    replacement = connect(fixture, base, workspace.token, published.toolkit_id)
    changed = GooglePublishedOutput.from_json(
        response(
            base,
            workspace.token,
            "POST",
            "/google/attempts/" + replacement.attempt_id + "/reconnect-confirm",
            {
                "settings": {
                    "tasks": ["calendar_read"],
                    "timeout": 12,
                    "security_risk_acknowledged": True,
                }
            },
        ).text
    )
    assert changed is not None and changed.connection_id != published.connection_id
    historical = GooglePublishedOutput.from_json(
        response(
            base,
            workspace.token,
            "GET",
            "/google/attempts/" + review.attempt_id + "/outcome",
        ).text
    )
    assert historical is not None and not historical.current
    response(
        base,
        workspace.token,
        "DELETE",
        "/toolkit-configs/" + published.toolkit_id + "/google/connection",
    )
    assert (
        saved_status(base, workspace.token, published.toolkit_id).status
        == "not_connected"
    )


def test_google_verified_partial_grant_reaches_worker_and_blocks_write(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    google_provider_fixture: GoogleProviderFixture | None,
) -> None:
    fixture = fixture_ready(google_provider_fixture)
    scenario(fixture, "expiring")
    prepare_operator(admin_api_client)
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": "Bearer " + workspace.token}
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        workspace.handle,
        AgentCreateRequest(
            name="Google execution E2E",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=True,
        ),
        _headers=headers,
    )
    base = f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
    review = connect(fixture, base, workspace.token)
    worker_settings = {
        **final_settings("google_product"),
        "tasks": ["calendar_read", "calendar_edit"],
    }
    published = GooglePublishedOutput.from_json(
        response(
            base,
            workspace.token,
            "POST",
            "/google/attempts/" + review.attempt_id + "/confirm",
            {"settings": worker_settings},
        ).text
    )
    assert published is not None
    current = saved_status(base, workspace.token, published.toolkit_id)
    edit = next(item for item in current.tasks if item.task.value == "calendar_edit")
    assert edit.status == "not_granted"
    saved = ToolkitV1Api(public_api_client).toolkit_v1_get_toolkit_config(
        handle=workspace.handle,
        toolkit_config_id=published.toolkit_id,
        _headers=headers,
    )
    assert "calendar_edit" in saved.config["tasks"]
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(
            toolkit_id=published.toolkit_id
        ),
        _headers=headers,
    )
    session = _create_profile_session(
        server_url=azents_public_server_url, token=workspace.token, agent_id=agent.id
    )
    sent = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session}/inputs",
        headers=headers,
        json={
            "agent_id": agent.id,
            "client_request_id": "google-product-" + unique(),
            "message": "Google Connection E2E partial",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=15,
    )
    sent.raise_for_status()
    _wait_for_terminal_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=session,
    )
    events = _tool_events(
        server_url=azents_public_server_url, token=workspace.token, session_id=session
    )
    results = [
        ToolResultObservation.model_validate(event.payload)
        for event in events
        if event.kind == "client_tool_result"
    ]
    allowed = next(
        item for item in results if item.call_id == "call_google_product_read"
    )
    assert (
        allowed.status == "completed"
        and "GOOGLE_E2E_READ_OK" in allowed.model_dump_json()
    )
    denied = next(
        item for item in results if item.call_id == "call_google_product_write"
    )
    assert denied.status == "failed"
    assert "Tool not found: google_product__calendar_create_event" in (
        denied.model_dump_json()
    )
    assert "GOOGLE_E2E_READ_OK" not in denied.model_dump_json()
    observed = requests.get(fixture.control_url + "/__testenv/state", timeout=5)
    observed.raise_for_status()
    state = ProviderState.model_validate_json(observed.text)
    assert state.refreshes >= 1
    assert (
        "calendar.list_events" in state.calls
        and "calendar.create_event" not in state.calls
    )
    assert CLIENT_SECRET not in json.dumps(
        [item.model_dump(mode="json") for item in results]
    )
