"""Assembled Google OAuth, review/publication and Worker capability product flows."""

import hashlib
import json
from typing import Literal, NamedTuple
from urllib.parse import parse_qs, urlsplit

import azentsadminclient
import azentspublicclient
import pytest
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
from azentspublicclient.models.google_picker_token_output import GooglePickerTokenOutput
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.models.google_review import GoogleReview
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from support.google_provider_fake import CLIENT_ID, CLIENT_SECRET, FILE_BYTES, SCOPE
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
from tests.required.public.test_user_sessions import _write_user_first_message

E2E_PLANNER_FALLBACK_WEIGHT = 35.0


class ProviderState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str
    exchanges: int
    refreshes: int
    calls: list[str]
    effects: list[str]
    downloads: int
    uploaded_bytes: int


class Callback(NamedTuple):
    code: str
    state: str


class CalendarGuestPrivileges(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    modify: bool = Field(alias="guestsCanModify")
    invite: bool = Field(alias="guestsCanInviteOthers")
    see_guests: bool = Field(alias="guestsCanSeeOtherGuests")


class GoogleTextOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["text"]
    text: str


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
    assert configured.service_access_verified is False
    assert configured.picker_status == "not_configured"
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
            {
                "services": ["calendar", "gmail"],
                "oauth_request_scopes": [
                    "openid",
                    "email",
                    "https://www.googleapis.com/auth/calendar.events.readonly",
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/gmail.readonly",
                ],
                "timeout": 30,
            },
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
    calendar = next(
        item for item in reviewed.accesses if item.service.value == "calendar"
    )
    assert "calendar_create_event" not in [
        tool.value for tool in calendar.permitted_tools
    ]
    return reviewed


def final_settings(slug: str) -> dict[str, object]:
    return {
        "name": "Google product fixture",
        "slug": slug,
        "description": None,
        "prompt": None,
        "enabled": True,
        "always_expose_tools": True,
        "services": ["calendar"],
        "oauth_request_scopes": [
            "openid",
            "email",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
        "timeout": 30,
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
                "services": ["drive"],
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
                    "services": ["calendar"],
                    "oauth_request_scopes": [
                        "openid",
                        "email",
                        "https://www.googleapis.com/auth/calendar.events.readonly",
                    ],
                    "timeout": 12,
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
    worker_settings = final_settings("google_product")
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
    calendar = next(
        item for item in current.accesses if item.service.value == "calendar"
    )
    assert "calendar_list_events" in [tool.value for tool in calendar.permitted_tools]
    assert "calendar_create_event" not in [
        tool.value for tool in calendar.permitted_tools
    ]
    saved = ToolkitV1Api(public_api_client).toolkit_v1_get_toolkit_config(
        handle=workspace.handle,
        toolkit_config_id=published.toolkit_id,
        _headers=headers,
    )
    assert saved.config["services"] == ["calendar"]
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
    assert state.effects == []
    assert CLIENT_SECRET not in json.dumps(
        [item.model_dump(mode="json") for item in results]
    )


@pytest.mark.parametrize("personal", [False, True])
def test_google_gmail_drive_runtime_file_roundtrip(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    google_provider_fixture: GoogleProviderFixture | None,
    personal: bool,
) -> None:
    """Prove SDK reads/effects and canonical bytes through a real Runner."""
    fixture = fixture_ready(google_provider_fixture)
    scenario(fixture, "full")
    prepare_operator(admin_api_client)
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=True,
    )
    headers = {"Authorization": "Bearer " + workspace.token}
    base = f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
    setup_path = "/personal/google" if personal else "/google"
    scopes = [
        "openid",
        "email",
        SCOPE + "gmail.readonly",
        SCOPE + "gmail.send",
        SCOPE + "gmail.settings.basic",
        SCOPE + "calendar.events",
        SCOPE + "drive.file",
    ]
    prepared = GoogleConnectOutput.from_json(
        response(
            base,
            workspace.token,
            "POST",
            setup_path + "/connect",
            {
                "services": ["calendar", "gmail", "drive"],
                "oauth_request_scopes": scopes,
                "timeout": 30,
            },
        ).text
    )
    assert prepared is not None
    callback = authorize(fixture, prepared.authorization_url)
    review = GoogleReview.from_json(
        response(
            base,
            workspace.token,
            "POST",
            setup_path + "/exchange",
            {"code": callback.code, "state": callback.state},
        ).text
    )
    assert review is not None and review.grant_result == "full"
    published = GooglePublishedOutput.from_json(
        response(
            base,
            workspace.token,
            "POST",
            setup_path + "/attempts/" + review.attempt_id + "/confirm",
            {
                "settings": {
                    **final_settings("google_product"),
                    "services": ["calendar", "gmail", "drive"],
                    "oauth_request_scopes": scopes,
                }
            },
        ).text
    )
    assert published is not None and published.current
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        workspace.handle,
        AgentCreateRequest(
            name="Google canonical files E2E",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace.runtime_profile_id,
        ),
        _headers=headers,
    )
    if personal:
        session = _write_user_first_message(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            message="Google Direct E2E files",
            client_request_id="google-personal-files-" + unique(),
        ).session_id
    else:
        ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
            handle=workspace.handle,
            agent_id=agent.id,
            agent_toolkit_attach_request=AgentToolkitAttachRequest(
                toolkit_id=published.toolkit_id
            ),
            _headers=headers,
        )
        session = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        submitted = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{session}/inputs",
            headers=headers,
            json={
                "agent_id": agent.id,
                "client_request_id": "google-files-" + unique(),
                "message": "Google Direct E2E files",
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
            timeout=15,
        )
        submitted.raise_for_status()
    _wait_for_terminal_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=session,
    )
    results = {
        item.call_id: item
        for event in _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session,
        )
        if event.kind == "client_tool_result"
        for item in [ToolResultObservation.model_validate(event.payload)]
    }
    for stage in ("calendar", "mail", "send", "filter", "download", "import", "upload"):
        result = results["call_google_direct_" + stage]
        assert result.status == "completed", result.model_dump_json()
    assert results["call_google_direct_denied"].status == "failed"
    calendar_output = TypeAdapter(list[GoogleTextOutput]).validate_python(
        results["call_google_direct_calendar"].output
    )
    assert len(calendar_output) == 1
    privileges = CalendarGuestPrivileges.model_validate_json(calendar_output[0].text)
    assert privileges.modify is False
    assert privileges.invite is True
    assert privileges.see_guests is False
    assert "GOOGLE_E2E_MAIL_OK" in results["call_google_direct_mail"].model_dump_json()
    assert "artifact://" in results["call_google_direct_download"].model_dump_json()
    assert (
        hashlib.sha256(FILE_BYTES).hexdigest()
        in results["call_google_direct_upload"].model_dump_json()
    )
    observed = requests.get(fixture.control_url + "/__testenv/state", timeout=5)
    observed.raise_for_status()
    state = ProviderState.model_validate_json(observed.text)
    assert state.effects == [
        "calendar.create_event",
        "gmail.send_message",
        "gmail.create_filter",
        "drive.create_file",
    ]
    assert state.downloads == len(FILE_BYTES)
    assert state.uploaded_bytes > len(FILE_BYTES)
    assert "gmail.get_message" in state.calls
    assert state.calls.count("drive.get_metadata") == 1
    if personal:
        # Exercise the browser credential boundary without a live Picker/Google
        # session. The access token is consumed only by this manager test client.
        settings_api = SystemSettingsV1Api(admin_api_client)
        operator = settings_api.system_settings_v1_get_google_oauth_setting()
        settings_api.system_settings_v1_patch_google_oauth_setting(
            GoogleApplicationPatchRequest(
                expected_version=operator.admin_version,
                picker_api_key="synthetic-browser-key",
                picker_app_id="123456789",
            )
        )
        target = "/personal-toolkit-configs/" + published.toolkit_id + "/google"
        current = GoogleConnectionOutput.from_json(
            response(base, workspace.token, "GET", target + "/connection").text
        )
        assert current is not None and current.connection_id is not None
        expected = {
            "expected_revision": current.revision,
            "connection_id": current.connection_id,
        }
        issued = response(
            base, workspace.token, "POST", target + "/picker-token", expected
        )
        assert issued.headers["Cache-Control"] == "no-store"
        assert issued.headers["Pragma"] == "no-cache"
        transient = GooglePickerTokenOutput.from_json(issued.text)
        assert transient is not None
        assert transient.app_id == "123456789"
        assert all(
            transient.access_token not in item.model_dump_json()
            for item in results.values()
        )
        switched = GoogleConnectionOutput.from_json(
            response(
                base,
                workspace.token,
                "PATCH",
                target + "/services",
                {
                    "expected_revision": current.revision,
                    "services": [],
                },
            ).text
        )
        assert switched is not None and switched.connection_id == current.connection_id
        assert switched.services == []
        denied_picker = requests.post(
            base + target + "/picker-token",
            headers=headers,
            json=expected,
            timeout=10,
        )
        assert denied_picker.status_code == 409
        assert "access_token" not in denied_picker.text
        retained = response(base, workspace.token, "GET", target + "/connection")
        assert transient.access_token not in retained.text
