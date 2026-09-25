"""Credential-free Brave Search product-path and image materialization E2E."""

import json
import os
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import azentsadminclient
import azentspublicclient
import boto3
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_toolkit_config_create_request import (
    AgentToolkitConfigCreateRequest,
)
from azentspublicclient.models.agent_toolkit_config_update_request import (
    AgentToolkitConfigUpdateRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
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
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.toolkit_config_update_request import (
    ToolkitConfigUpdateRequest,
)
from botocore.exceptions import ClientError
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import start_and_wait_for_agent_runtime
from support.utils import (
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
    wait_until,
)
from tests.required.public.external_channel_scenarios import (
    _APP_ID,
    _BOT_TOKEN,
    _CHANNEL_ID,
    _SIGNING_SECRET,
    _TEAM_ID,
    _latest_setup_view,
    _open_slack_setup_modal,
    _provider_state,
    _signed_headers,
    _submit_slack_setup_location,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import (
    _create_profile_session,
)
from tests.required.public.test_provider_image_generation import (
    _count_typed_items,
    _wait_for_idle,
)
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
)
from tests.required.public.test_runtime_profiles import _login_main_web

_KINDS = ("web", "context", "news", "images", "videos")


def _submit(
    *, server_url: str, token: str, agent_id: str, session_id: str, kind: str
) -> None:
    """Send one deterministic request through the public conversation API."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"brave-search-{unique()}",
            "message": f"Brave Search E2E {kind}",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _tool_events(
    *, server_url: str, token: str, session_id: str
) -> list[dict[str, object]]:
    """Read durable tool events rather than inferring success from model text."""
    history = list_history(server_url=server_url, token=token, session_id=session_id)
    return history_events(history)


def _request_journal(proxy_url: str) -> list[dict[str, object]]:
    """Read model requests to scope assertions to one new execution."""
    response = requests.get(f"{proxy_url}/v1/_image_generation_requests", timeout=10)
    response.raise_for_status()
    return json_object_list_payload(response.json(), label="Brave request journal")


def test_brave_five_tools_and_one_call_multi_image_without_runtime(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    azents_main_web_url: str,
    browser_driver: WebDriver,
    openai_proxy_url: str,
) -> None:
    """Exercise five endpoints through a Runtime-free Agent and worker."""
    del azents_engine_worker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave Search E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
            always_expose_tools=False,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave Runtime-free E2E {unique()}",
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
    assert agent.runtime_capability == AgentRuntimeCapability.NONE
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    for path in (
        f"/toolkit/v1/workspaces/{workspace.handle}/toolkit-configs/test-connection",
        f"/toolkit/v1/workspaces/{workspace.handle}/agents/"
        f"{agent.id}/toolkit-configs/test-connection",
    ):
        connection = requests.post(
            f"{azents_public_server_url}{path}",
            headers=headers,
            json={
                "toolkit_type": "brave_search",
                "config": {"country": "ALL"},
                "credentials": {"api_key": "brave-e2e-valid"},
                "toolkit_config_id": None,
            },
            timeout=10,
        )
        connection.raise_for_status()
        assert (
            json_object_payload(connection.json(), label="Brave connection test").get(
                "success"
            )
            is True
        )
    for key, expected in (
        ("brave-e2e-revoked", "key is invalid"),
        ("brave-e2e-limited", "rate or quota limit"),
    ):
        connection = requests.post(
            f"{azents_public_server_url}/toolkit/v1/workspaces/"
            f"{workspace.handle}/toolkit-configs/test-connection",
            headers=headers,
            json={
                "toolkit_type": "brave_search",
                "config": {},
                "credentials": {"api_key": key},
                "toolkit_config_id": None,
            },
            timeout=10,
        )
        connection.raise_for_status()
        result = json_object_payload(connection.json(), label="Brave failure test")
        assert result.get("success") is False
        assert expected in str(result.get("message"))
        assert key not in str(result)
    saved_connection = requests.post(
        f"{azents_public_server_url}/toolkit/v1/workspaces/"
        f"{workspace.handle}/toolkit-configs/test-connection",
        headers=headers,
        json={
            "toolkit_type": "brave_search",
            "config": {},
            "credentials": None,
            "toolkit_config_id": toolkit.id,
        },
        timeout=10,
    )
    saved_connection.raise_for_status()
    assert (
        json_object_payload(
            saved_connection.json(), label="Brave saved-key connection"
        ).get("success")
        is True
    )

    # Agent-owned credentials use a separate management authority and may be
    # tested with the saved key without sending it back to the browser.
    api = ToolkitV1Api(public_api_client)
    private = api.toolkit_v1_create_agent_toolkit_config(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_config_create_request=AgentToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="private_brave",
            name="Private Brave E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    assert "brave-e2e-valid" not in private.model_dump_json()
    private_read = api.toolkit_v1_get_agent_toolkit_config(
        handle=workspace.handle,
        agent_id=agent.id,
        toolkit_config_id=private.id,
        _headers=headers,
    )
    assert "brave-e2e-valid" not in private_read.model_dump_json()
    agent_connection_url = (
        f"{azents_public_server_url}/toolkit/v1/workspaces/"
        f"{workspace.handle}/agents/{agent.id}/toolkit-configs/test-connection"
    )

    def test_saved_private_key() -> dict[str, object]:
        response = requests.post(
            agent_connection_url,
            headers=headers,
            json={
                "toolkit_type": "brave_search",
                "config": {},
                "credentials": None,
                "toolkit_config_id": private.id,
            },
            timeout=10,
        )
        response.raise_for_status()
        result = json_object_payload(response.json(), label="Agent-owned Brave key")
        assert "brave-e2e-valid" not in str(result)
        assert "brave-e2e-revoked" not in str(result)
        return result

    assert test_saved_private_key().get("success") is True
    replaced = api.toolkit_v1_update_agent_toolkit_config(
        handle=workspace.handle,
        agent_id=agent.id,
        toolkit_config_id=private.id,
        agent_toolkit_config_update_request=AgentToolkitConfigUpdateRequest(
            credentials={"api_key": "brave-e2e-revoked"}
        ),
        _headers=headers,
    )
    assert "brave-e2e-revoked" not in replaced.model_dump_json()
    assert test_saved_private_key().get("success") is False
    api.toolkit_v1_update_agent_toolkit_config(
        handle=workspace.handle,
        agent_id=agent.id,
        toolkit_config_id=private.id,
        agent_toolkit_config_update_request=AgentToolkitConfigUpdateRequest(
            credentials={"api_key": "brave-e2e-valid"}, enabled=False
        ),
        _headers=headers,
    )
    disabled_private = api.toolkit_v1_get_agent_toolkit_config(
        handle=workspace.handle,
        agent_id=agent.id,
        toolkit_config_id=private.id,
        _headers=headers,
    )
    assert disabled_private.enabled is False

    disabled_session = _create_profile_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
    )
    _submit(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=disabled_session,
        kind="disabled",
    )
    _wait_for_idle(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=disabled_session,
    )
    disabled_events = _tool_events(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=disabled_session,
    )
    disabled_calls = [
        json_object_payload(event.get("payload"), label="Disabled Brave call")
        for event in disabled_events
        if event.get("kind") == "client_tool_call"
    ]
    assert [call.get("name") for call in disabled_calls] == ["tool_search"]
    disabled_search = next(
        json_object_payload(event.get("payload"), label="Disabled Brave search")
        for event in disabled_events
        if event.get("kind") == "client_tool_result"
    )
    assert "private_brave__" not in json.dumps(disabled_search)

    image_session_id: str | None = None
    vision_journal_start: int | None = None
    for kind in _KINDS:
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        if kind == "images":
            vision_journal_start = len(_request_journal(openai_proxy_url))
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
            kind=kind,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
        )
        events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        calls = [event for event in events if event.get("kind") == "client_tool_call"]
        results = [
            event for event in events if event.get("kind") == "client_tool_result"
        ]
        assert len(calls) == len(results) == 2, events
        search_call = json_object_payload(
            calls[0].get("payload"), label="Tool Search call"
        )
        assert search_call.get("name") == "tool_search"
        call = json_object_payload(calls[1].get("payload"), label="Brave call")
        result = json_object_payload(results[1].get("payload"), label="Brave result")
        assert call.get("name") == f"brave__search_{kind}"
        assert result.get("call_id") == call.get("call_id")
        assistant_text = [
            json_object_payload(event.get("payload"), label="Brave assistant").get(
                "content"
            )
            for event in events
            if event.get("kind") == "assistant_message"
        ]
        assert f"BRAVE_SEARCH_E2E_COMPLETED_{kind}" in assistant_text
        serialized = json.dumps(result, ensure_ascii=False)
        assert f"https://example.org/brave/{kind}" in serialized or (
            kind == "images" and "https://example.org/brave/image-page-1" in serialized
        )
        assert "data:image" not in serialized
        if kind != "images":
            continue
        image_session_id = session_id
        assert "https://example.org/brave/original-1.png" in serialized
        assert "https://example.org/brave/original-2.png" in serialized
        assert "https://example.org/brave/original-3.png" in serialized
        assert "Thumbnail was unavailable or unsafe." in serialized
        output = result.get("output")
        assert isinstance(output, list), result
        parts = json_object_list_payload(output, label="Brave image output")
        assert sum(part.get("type") == "attachment" for part in parts) == 2
        assert sum(part.get("kind") == "image" for part in parts) == 2
        attachments = [part for part in parts if part.get("type") == "attachment"]
        for attachment in attachments:
            assert attachment.get("availability") == "available"
            uri = attachment.get("uri")
            assert isinstance(uri, str)
            assert uri.startswith("exchange://")
            attachment_id = attachment.get("attachment_id")
            assert isinstance(attachment_id, str)
            downloaded = requests.get(
                f"{azents_public_server_url}/chat/v1/exchange-files/"
                f"{attachment_id}/download",
                headers=headers,
                timeout=10,
            )
            downloaded.raise_for_status()
            assert downloaded.content.startswith(b"\x89PNG\r\n\x1a\n")

    assert image_session_id is not None
    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=workspace.email,
    )
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/agents/"
        f"{agent.id}/sessions/{image_session_id}"
    )
    gallery = WebDriverWait(browser_driver, 20).until(
        lambda driver: [
            image
            for image in driver.find_elements(
                By.CSS_SELECTOR, 'img[src*="/api/chat/exchange-files/"]'
            )
            if image.is_displayed()
            and driver.execute_script(
                "return arguments[0].complete && arguments[0].naturalWidth > 0",
                image,
            )
        ]
    )
    assert len(gallery) == 2
    artifact_root = Path(os.environ.get("AZENTS_E2E_ARTIFACT_DIR", "/tmp"))
    artifact_root.mkdir(parents=True, exist_ok=True)
    screenshot_path = artifact_root / "brave-search-image-gallery.png"
    assert browser_driver.save_screenshot(str(screenshot_path))
    assert screenshot_path.stat().st_size > 0

    assert vision_journal_start is not None
    requests_ = _request_journal(openai_proxy_url)[vision_journal_start:]
    image_continuations = [
        request
        for request in requests_
        if "call_brave_e2e_images" in json.dumps(request)
        and "function_call_output" in json.dumps(request)
    ]
    assert image_continuations, "Image result was not fed back to the model."
    assert any(
        _count_typed_items(request.get("input"), "input_image") == 2
        for request in image_continuations
    ), "The two generated FileParts must reach the vision-capable model."

    text_integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=workspace.handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-brave-text-only",
            secrets=Secrets(ApiKeySecrets(api_key="sk-brave-text-only-e2e")),
        ),
        _headers=headers,
    )
    text_agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave text-only E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                model_selection_from_first_candidate(
                    azents_public_server_url,
                    workspace.token,
                    workspace.handle,
                    text_integration.id,
                )
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=True,
        ),
        _headers=headers,
    )
    assert text_agent.runtime_capability == AgentRuntimeCapability.NONE
    api.toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=text_agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    text_session = _create_profile_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=text_agent.id,
    )
    text_journal_start = len(_request_journal(openai_proxy_url))
    _submit(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=text_agent.id,
        session_id=text_session,
        kind="images",
    )
    _wait_for_idle(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=text_agent.id,
        session_id=text_session,
    )
    text_events = _tool_events(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=text_session,
    )
    text_image_result = next(
        json_object_payload(event.get("payload"), label="Text-only image result")
        for event in text_events
        if event.get("kind") == "client_tool_result"
        and json_object_payload(
            event.get("payload"), label="Text-only image result"
        ).get("name")
        == "brave__search_images"
    )
    assert "text-only model has NOT visually inspected" in json.dumps(text_image_result)
    assert "https://example.org/brave/image-page-1" in json.dumps(text_image_result)
    continuations = [
        request
        for request in _request_journal(openai_proxy_url)[text_journal_start:]
        if "call_brave_e2e_images" in json.dumps(request)
        and "function_call_output" in json.dumps(request)
    ]
    assert any(
        _count_typed_items(request.get("input"), "input_image") == 0
        and "model does not support this file input" in json.dumps(request)
        and "https://example.org/brave/image-page-1" in json.dumps(request)
        and "https://example.org/brave/original-1.png" in json.dumps(request)
        for request in continuations
    ), "The text-only model must receive bounded placeholders and source links."

    for key, safe_failure in (
        ("brave-e2e-revoked", "invalid"),
        ("brave-e2e-limited", "quota"),
        ("brave-e2e-no-entitlement", "lacks access"),
        ("brave-e2e-timeout", "unreachable"),
    ):
        updated = api.toolkit_v1_update_toolkit_config(
            handle=workspace.handle,
            toolkit_config_id=toolkit.id,
            toolkit_config_update_request=ToolkitConfigUpdateRequest(
                credentials={"api_key": key}
            ),
            _headers=headers,
        )
        assert key not in updated.model_dump_json()
        failed_session = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
            kind="web",
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
        )
        failed_events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=failed_session,
        )
        failures = [
            event
            for event in failed_events
            if event.get("kind") == "client_tool_result"
            and json_object_payload(
                event.get("payload"), label="Brave failure result"
            ).get("name")
            == "brave__search_web"
        ]
        assert len(failures) == 1, failed_events
        failure = json.dumps(failures[0], ensure_ascii=False)
        assert safe_failure in failure
        assert key not in failure
        assert "attachment" not in failure


def test_brave_five_tools_with_managed_runtime(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
) -> None:
    """Prove the same five native searches work with a running managed Runtime."""
    del azents_engine_worker_container, openai_proxy_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=True,
    )
    assert workspace.runtime_profile_id is not None
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave managed Runtime E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave managed Runtime E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace.runtime_profile_id,
            tool_search_enabled=True,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability == AgentRuntimeCapability.MANAGED
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=workspace.token,
        workspace_handle=workspace.handle,
        agent_id=agent.id,
    )
    for kind in _KINDS:
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
            kind=kind,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
        )
        events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        calls = [
            json_object_payload(event.get("payload"), label="Managed Brave call")
            for event in events
            if event.get("kind") == "client_tool_call"
        ]
        results = [
            json_object_payload(event.get("payload"), label="Managed Brave result")
            for event in events
            if event.get("kind") == "client_tool_result"
        ]
        assert [call.get("name") for call in calls] == [
            "tool_search",
            f"brave__search_{kind}",
        ]
        assert len(results) == 2
        result = results[1]
        assert result.get("call_id") == calls[1].get("call_id")
        assert result.get("status") == "completed"
        serialized = json.dumps(result, ensure_ascii=False)
        assert (
            "https://example.org/brave/image-page-1"
            if kind == "images"
            else f"https://example.org/brave/{kind}"
        ) in serialized
        if kind == "images":
            output = result.get("output")
            assert isinstance(output, list)
            assert (
                sum(
                    isinstance(part, dict) and part.get("type") == "attachment"
                    for part in output
                )
                == 2
            )


def test_brave_external_channel_reuses_one_search(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
    slack_provider_fake_url: str,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[DockerContainer]
    ],
) -> None:
    """Publish search URLs through explicit Channel Action after one Brave call."""
    del azents_engine_worker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset", timeout=5
    ).raise_for_status()
    root_timestamp = f"{int(time.time()) - 60}.000103"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-BRAVE",
                        "ts": root_timestamp,
                        "text": "Brave Search E2E external_channel",
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave Channel E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave Channel E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=False,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability == AgentRuntimeCapability.NONE
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent.id,
        handle=workspace.handle,
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
    request.addfinalizer(
        lambda: external_api.external_channel_v1_disconnect_connection(
            agent_id=agent.id,
            connection_id=setup.connection.id,
            handle=workspace.handle,
            _headers=headers,
        )
    )
    external_api.external_channel_v1_validate_connection(
        agent_id=agent.id,
        connection_id=setup.connection.id,
        handle=workspace.handle,
        _headers=headers,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    with azents_external_channel_gateway_factory():
        channel_journal_start = len(_request_journal(openai_proxy_url))
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
                    "user": "U-BRAVE",
                    "text": "<@B-E2E> Brave Search E2E external_channel",
                    "ts": root_timestamp,
                },
            },
            separators=(",", ":"),
        ).encode()
        admitted = requests.post(
            callback_url,
            data=event_body,
            headers=_signed_headers(event_body),
            timeout=5,
        )
        assert admitted.status_code == 200
        _open_slack_setup_modal(
            callback_url=callback_url,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            user_id="U-BRAVE",
        )
        setup_view = wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Brave Channel setup view was not available",
        )
        assert setup_view is not None
        _submit_slack_setup_location(
            callback_url=callback_url,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            user_id="U-BRAVE",
            setup_view=setup_view,
        )
        chat_api = ChatV1Api(public_api_client)

        def bound_session() -> str | None:
            sessions = chat_api.chat_v1_list_agent_sessions(
                agent_id=agent.id, _headers=headers
            )
            for session in sessions.items:
                bindings = external_api.external_channel_v1_list_session_channels(
                    agent_id=agent.id,
                    session_id=session.id,
                    handle=workspace.handle,
                    _headers=headers,
                )
                if len(bindings.items) == 1 and bindings.items[0].work is not None:
                    return session.id
            return None

        session_id = wait_until(
            bound_session,
            timeout=30,
            interval=0.2,
            message="Brave Channel Session binding was not created",
        )
        assert session_id is not None

        def channel_result() -> list[dict[str, object]] | None:
            events = _tool_events(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
            )
            matches = [
                event
                for event in events
                if event.get("kind") == "client_tool_result"
                and json_object_payload(
                    event.get("payload"), label="Brave Channel result"
                ).get("name")
                == "channel_action"
            ]
            return events if len(matches) == 1 else None

        events = wait_until(
            channel_result,
            timeout=90,
            interval=0.2,
            message="Brave Channel publication did not complete",
        )
        assert events is not None
        calls = [
            json_object_payload(event.get("payload"), label="Brave Channel call")
            for event in events
            if event.get("kind") == "client_tool_call"
        ]
        assert [call.get("name") for call in calls] == [
            "brave__search_images",
            "channel_action",
        ]
        search_result = next(
            json_object_payload(event.get("payload"), label="Brave search result")
            for event in events
            if event.get("kind") == "client_tool_result"
            and json_object_payload(
                event.get("payload"), label="Brave search result"
            ).get("name")
            == "brave__search_images"
        )
        serialized = json.dumps(search_result)
        assert "https://example.org/brave/original-1.png" in serialized
        assert "https://example.org/brave/image-page-1" in serialized
        continuations = [
            model_request
            for model_request in _request_journal(openai_proxy_url)[
                channel_journal_start:
            ]
            if "call_brave_e2e_channel_images" in json.dumps(model_request)
            and "function_call_output" in json.dumps(model_request)
        ]
        assert any(
            "https://example.org/brave/original-1.png" in json.dumps(model_request)
            and "https://example.org/brave/image-page-1" in json.dumps(model_request)
            for model_request in continuations
        ), "Both URLs must reach the model before explicit Channel Action."
        channel_call = json.dumps(calls[1])
        assert "https://example.org/brave/original-1.png" in channel_call
        assert "https://example.org/brave/image-page-1" in channel_call
        finished = next(
            json_object_payload(event.get("payload"), label="Channel Action result")
            for event in events
            if event.get("kind") == "client_tool_result"
            and json_object_payload(
                event.get("payload"), label="Channel Action result"
            ).get("name")
            == "channel_action"
        )
        assert finished.get("status") == "completed"
        output = finished.get("output")
        assert isinstance(output, str)
        assert '"status": "delivered"' in output
        assert "brave-e2e-valid" not in json.dumps(events)
        delivery = _provider_state(slack_provider_fake_url)
        raw_deliveries = delivery.get("deliveries")
        assert isinstance(raw_deliveries, list)
        assert any(
            isinstance(item, dict)
            and item.get("operation") in {"chat.postMessage", "chat.update"}
            and item.get("outcome") == "delivered"
            for item in raw_deliveries
        )


def test_brave_storage_failure_cleans_partial_images_and_recovers(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
) -> None:
    """Deny model-file writes after Exchange uploads, then prove clean retry."""
    del azents_engine_worker_container, openai_proxy_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave storage failure E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave storage failure E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=False,
        ),
        _headers=headers,
    )
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    host = rustfs_container.get_container_host_ip()
    port = rustfs_container.get_exposed_port(9000)
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{host}:{port}",
        aws_access_key_id=rustfs_access_key,
        aws_secret_access_key=rustfs_secret_key,
        region_name="us-east-1",
    )
    workspace_id = toolkit.workspace_id
    denied_prefix = f"model-files/{workspace_id}/"
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyBraveModelFileUploadForE2E",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{s3_bucket_name}/{denied_prefix}*",
            }
        ],
    }

    def workspace_objects() -> list[str]:
        """List only this test's Exchange and ModelFile object prefixes."""
        keys: list[str] = []
        for prefix in (
            f"exchange/{workspace_id}/",
            denied_prefix,
        ):
            response = s3.list_objects_v2(Bucket=s3_bucket_name, Prefix=prefix)
            keys.extend(
                item["Key"]
                for item in response.get("Contents", [])
                if isinstance(item.get("Key"), str)
            )
        return keys

    applied = False
    try:
        s3.put_bucket_policy(Bucket=s3_bucket_name, Policy=json.dumps(policy))
        applied = True
        with pytest.raises(ClientError) as denied:
            s3.put_object(
                Bucket=s3_bucket_name,
                Key=f"{denied_prefix}policy-probe",
                Body=b"probe",
            )
        assert denied.value.response["Error"]["Code"] in {
            "AccessDenied",
            "Forbidden",
        }
        failed_session = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
            kind="images",
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
        )
        failed_events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=failed_session,
        )
        assert any(
            json_object_payload(event.get("payload"), label="Failed Brave call").get(
                "name"
            )
            == "brave__search_images"
            for event in failed_events
            if event.get("kind") == "client_tool_call"
        )
        failed_results = [
            json_object_payload(event.get("payload"), label="Failed Brave result")
            for event in failed_events
            if event.get("kind") == "client_tool_result"
            and json_object_payload(
                event.get("payload"), label="Failed Brave result"
            ).get("name")
            == "brave__search_images"
        ]
        assert len(failed_results) == 1
        failed_result = failed_results[0]
        assert failed_result.get("status") == "failed"
        assert failed_result.get("output") == [
            {"type": "text", "text": "Generated image output could not be stored."}
        ]
        assert workspace_objects() == []
    finally:
        try:
            if applied:
                s3.delete_bucket_policy(Bucket=s3_bucket_name)
        finally:
            s3.close()

    recovered_session = _create_profile_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
    )
    _submit(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=recovered_session,
        kind="images",
    )
    _wait_for_idle(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=recovered_session,
    )
    recovered = _tool_events(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=recovered_session,
    )
    results = [
        json_object_payload(event.get("payload"), label="Recovered Brave result")
        for event in recovered
        if event.get("kind") == "client_tool_result"
        and json_object_payload(
            event.get("payload"), label="Recovered Brave result"
        ).get("name")
        == "brave__search_images"
    ]
    assert len(results) == 1
    output = results[0].get("output")
    assert isinstance(output, list)
    attachments = [
        part
        for part in output
        if isinstance(part, dict) and part.get("type") == "attachment"
    ]
    assert len(attachments) == 2
