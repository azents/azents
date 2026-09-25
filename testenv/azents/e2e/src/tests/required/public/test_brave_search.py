"""Credential-free Brave Search product-path and image materialization E2E."""

import json

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
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
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.toolkit_config_update_request import (
    ToolkitConfigUpdateRequest,
)
from testcontainers.core.container import DockerContainer

from support.utils import (
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
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
