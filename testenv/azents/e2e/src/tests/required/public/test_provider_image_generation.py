"""Client-executed OpenAI image generation product-path E2E coverage."""

import base64
import hashlib
import json
import time
from collections.abc import Callable
from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.image_generation_model_catalog_response import (
    ImageGenerationModelCatalogResponse,
)

from support.consts import REPOSITORY_ROOT
from support.exchange_download import download_fixture_exchange_file
from support.image_watchdog_observations import (
    AssistantContentObservation,
    ImageRequestObservation,
    ImageResultObservation,
    RequestNodeObservation,
    RequestToolObservation,
    WatchdogActionObservation,
    decode_image_requests,
)
from support.observations import HistoryEventObservation, ToolResultObservation
from support.utils import unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    history_events,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import setup_profile_agent


class _ProfileWorkspaceIntegration(NamedTuple):
    """Field-named result for ``_profile_workspace_and_integration``."""

    workspace_handle: str
    integration_id: str


_PROMPT = "Provider image generation handoff"
_EXPLICIT_IMAGE_PROMPT = "Provider image generation explicit pin handoff"
_FOLLOW_UP_PROMPT = "Provider image generation follow-up"
_FOLLOW_UP_RESPONSE = "PROVIDER_IMAGE_GENERATION_FOLLOW_UP_COMPLETED"
_PROXY_JOURNAL_PATH = "/v1/_image_generation_requests"
_IMAGE_API_JOURNAL_PATH = "/v1/_openai_images_requests"
_IMAGE_PATH = (
    REPOSITORY_ROOT
    / "testenv/azents/e2e/src/support/fixtures/provider-image-generation.png"
)
_IMAGE_BYTES = _IMAGE_PATH.read_bytes()
_IMAGE_BASE64 = base64.b64encode(_IMAGE_BYTES).decode()
_IMAGE_SHA256 = hashlib.sha256(_IMAGE_BYTES).hexdigest()


def _submit(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    reasoning_effort: str | None,
) -> None:
    """Submit one Quality-profile turn through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"provider-image-generation-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": reasoning_effort,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _wait_for_idle(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> None:
    """Wait for the submitted turn to leave the running state."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=auth_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        payload = AgentSessionResponse.model_validate(response.json())
        last_state = payload.run_state
        if last_state == "idle":
            return
        time.sleep(0.2)
    raise TimeoutError(f"image generation session did not become idle: {last_state!r}")


def _client_result(events: list[dict[str, object]]) -> dict[str, object] | None:
    """Select a validated image-result event, preserving legacy egress shape."""
    for raw in events:
        event = HistoryEventObservation.model_validate(raw)
        if event.kind != "client_tool_result":
            continue
        payload = ToolResultObservation.model_validate(event.payload)
        if payload.name == "image_generation" and payload.status == "completed":
            ImageResultObservation.model_validate(event.payload)
            return raw
    return None


def _assistant_content(raw: dict[str, object]) -> str | None:
    """Return selected typed assistant text while preserving opaque other events."""
    event = HistoryEventObservation.model_validate(raw)
    if event.kind != "assistant_message":
        return None
    content = AssistantContentObservation.model_validate(event.payload).content
    return content if isinstance(content, str) else None


def _wait_for_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
    predicate: Callable[[dict[str, object]], bool],
    timeout: float = 120,
) -> dict[str, object]:
    """Poll history until the supplied event predicate succeeds."""
    deadline = time.monotonic() + timeout
    latest: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        for event in history_events(latest):
            if predicate(event):
                return event
        time.sleep(0.2)
    raise TimeoutError(
        f"expected image-generation history was not observed: {latest!r}"
    )


def _proxy_journal(openai_proxy_url: str) -> list[ImageRequestObservation]:
    """Decode provider request decision fields before journal selection."""
    response = requests.get(f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}", timeout=10)
    response.raise_for_status()
    return decode_image_requests(response.json())


def _image_api_journal(openai_proxy_url: str) -> list[ImageRequestObservation]:
    """Decode Images API request identities from synthetic journal evidence."""
    response = requests.get(f"{openai_proxy_url}{_IMAGE_API_JOURNAL_PATH}", timeout=10)
    response.raise_for_status()
    return decode_image_requests(response.json())


def _last_user_text(request: ImageRequestObservation) -> str | None:
    """Select the last user text from a validated Responses input projection."""
    input_value = request.input
    if isinstance(input_value, str):
        return input_value
    if input_value is None:
        return None
    for item in reversed(input_value):
        if item.role != "user":
            continue
        content = item.content
        if isinstance(content, str):
            return content
        if content is None:
            return None
        return "".join(
            part.text
            for part in content
            if part.type == "input_text" and part.text is not None
        )
    return None


def _request_for_prompt(
    requests_: list[ImageRequestObservation], prompt: str
) -> ImageRequestObservation:
    """Return the typed request whose last user input matches the prompt."""
    for request in requests_:
        if _last_user_text(request) == prompt:
            return request
    raise AssertionError(f"proxy request was not captured for prompt: {prompt!r}")


def _image_tool(request: ImageRequestObservation) -> RequestToolObservation:
    """Return the client image-generation function in a validated request."""
    tools = request.tools
    assert tools is not None
    image_tools = [
        tool
        for tool in tools
        if tool.type == "function" and tool.name == "image_generation"
    ]
    assert len(image_tools) == 1, tools
    return image_tools[0]


def _profile_workspace_and_integration(
    *,
    public_api_client: azentspublicclient.ApiClient,
    token: str,
) -> _ProfileWorkspaceIntegration:
    """Resolve the unique workspace and OpenAI integration created by setup."""
    headers = auth_headers(token)
    workspaces = WorkspaceV1Api(public_api_client).workspace_v1_list_workspaces(
        _headers=headers,
    )
    assert len(workspaces.items) == 1
    handle = workspaces.items[0].handle
    integrations = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_list_integrations(
        handle=handle,
        _headers=headers,
    )
    assert len(integrations.items) == 1
    return _ProfileWorkspaceIntegration(
        workspace_handle=handle,
        integration_id=integrations.items[0].id,
    )


def _wait_for_image_catalog(
    *,
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> ImageGenerationModelCatalogResponse:
    """Wait for the initial exact-registry image catalog projection."""
    catalog_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration_id}/"
        "image-generation-model-catalog"
    )

    def current_catalog() -> ImageGenerationModelCatalogResponse | None:
        response = requests.get(
            catalog_url,
            headers=auth_headers(token),
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = ImageGenerationModelCatalogResponse.model_validate(response.json())
        identifiers = [entry.provider_model_identifier for entry in payload.entries]
        if identifiers != [
            "gpt-image-2.5-flare",
            "gpt-image-2.5-sunburst",
        ]:
            return None
        return payload

    catalog = wait_until(
        current_catalog,
        timeout=15,
        interval=0.2,
        message="Image generation catalog did not become readable",
    )
    assert catalog is not None
    return catalog


def _count_string_occurrences(value: object, needle: str) -> int:
    """Count a bounded string across nested request values without serializing it."""
    if isinstance(value, str):
        return value.count(needle)
    if isinstance(value, list):
        return sum(_count_string_occurrences(item, needle) for item in value)
    if isinstance(value, dict):
        return sum(_count_string_occurrences(item, needle) for item in value.values())
    return 0


def _count_typed_items(value: object, item_type: str) -> int:
    """Count nested request objects with one exact Responses item type."""
    if isinstance(value, list):
        return sum(_count_typed_items(item, item_type) for item in value)
    if not isinstance(value, dict):
        return 0
    current = 1 if RequestNodeObservation.model_validate(value).type == item_type else 0
    return current + sum(_count_typed_items(item, item_type) for item in value.values())


class TestProviderImageGeneration:
    """Validate client image output, storage, replay, and payload hygiene."""

    def test_default_omission_and_explicit_pin_reach_image_api(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Stored catalog selection controls the exact client Images API model."""
        del azents_engine_worker_container
        token, agent_id, session_id = setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        handle, integration_id = _profile_workspace_and_integration(
            public_api_client=public_api_client,
            token=token,
        )
        catalog = _wait_for_image_catalog(
            server_url=azents_public_server_url,
            token=token,
            handle=handle,
            integration_id=integration_id,
        )
        assert catalog.default_available is True
        assert catalog.explicit_selection_supported is True
        assert catalog.usable is True
        assert catalog.total == 2

        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        requests.delete(
            f"{openai_proxy_url}{_IMAGE_API_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_PROMPT,
            reasoning_effort=None,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        default_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        assert _image_tool(default_request).name == "image_generation"
        assert [request.model for request in _image_api_journal(openai_proxy_url)] == [
            "gpt-image-2"
        ]

        update = requests.patch(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/"
            f"agents/{agent_id}",
            headers={**auth_headers(token), "Content-Type": "application/json"},
            json={
                "selectable_model_options": [
                    {
                        "label": "Quality",
                        "candidates": [
                            {
                                "model_selection": {
                                    "llm_provider_integration_id": integration_id,
                                    "model_identifier": "gpt-5.5",
                                },
                                "settings": {
                                    "context_window_tokens": 96_000,
                                    "max_output_tokens": 12_000,
                                    "builtin_tools": [
                                        {"name": "web_search"},
                                        {
                                            "name": "image_generation",
                                            "config": {
                                                "model": "gpt-image-2.5-flare",
                                                "quality": "high",
                                            },
                                        },
                                    ],
                                },
                            }
                        ],
                        "subagent_enabled": False,
                        "subagent_guidance": "Reserve for complex synthesis.",
                    },
                    {
                        "label": "Fast",
                        "candidates": [
                            {
                                "model_selection": {
                                    "llm_provider_integration_id": integration_id,
                                    "model_identifier": "gpt-5.5-mini",
                                },
                                "settings": {
                                    "context_window_tokens": 32_000,
                                    "max_output_tokens": 4_000,
                                    "builtin_tools": [],
                                },
                            }
                        ],
                        "subagent_enabled": True,
                        "subagent_guidance": "Prefer for bounded investigation.",
                    },
                ],
                "main_model_label": "Quality",
                "lightweight_model_label": "Fast",
            },
            timeout=10,
        )
        update.raise_for_status()
        updated_agent = AgentResponse.model_validate(update.json())
        assert updated_agent.selectable_model_options is not None
        quality_option = next(
            option
            for option in updated_agent.selectable_model_options
            if option.label == "Quality"
        )
        quality_settings = quality_option.candidates[0].settings
        assert (
            quality_settings is not None and quality_settings.builtin_tools is not None
        )
        assert quality_settings.builtin_tools[1].to_dict() == {
            "name": "image_generation",
            "config": {"model": "gpt-image-2.5-flare", "quality": "high"},
        }

        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        requests.delete(
            f"{openai_proxy_url}{_IMAGE_API_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_EXPLICIT_IMAGE_PROMPT,
            reasoning_effort=None,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        explicit_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _EXPLICIT_IMAGE_PROMPT,
        )
        assert _image_tool(explicit_request).name == "image_generation"
        assert [request.model for request in _image_api_journal(openai_proxy_url)] == [
            "gpt-image-2.5-flare"
        ]

    def test_materializes_downloads_and_replays_generated_image(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_browser_s3_endpoint_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """One generated image becomes one durable dual-resource result."""
        del azents_engine_worker_container
        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        requests.delete(
            f"{openai_proxy_url}{_IMAGE_API_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        token, agent_id, session_id = setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        run_cleared = False
        with connect_chat(
            public_api_client=public_api_client,
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        ) as websocket:
            websocket.recv(timeout=10)
            _submit(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
                message=_PROMPT,
                reasoning_effort=None,
            )
            deadline = time.monotonic() + 30
            observed_action_types: list[object] = []
            while time.monotonic() < deadline:
                try:
                    raw = websocket.recv(timeout=max(0.1, deadline - time.monotonic()))
                except TimeoutError:
                    break
                raw_text = raw.decode() if isinstance(raw, bytes) else raw
                assert _IMAGE_BASE64 not in raw_text
                action = WatchdogActionObservation.model_validate_json(raw_text)
                action_type = action.type
                observed_action_types.append(action_type)
                if action_type == "live_run_cleared":
                    run_cleared = True
                if run_cleared:
                    break
            if not run_cleared:
                raise TimeoutError(
                    "image-generation live handoff did not complete: "
                    f"run_cleared={run_cleared!r}, "
                    f"actions={observed_action_types!r}"
                )

        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        history = list_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        serialized_history = json.dumps(history, ensure_ascii=False, sort_keys=True)
        assert _IMAGE_BASE64 not in serialized_history
        assert "data:image" not in serialized_history
        results = [
            event
            for event in history_events(history)
            if _client_result([event]) is not None
        ]
        assert len(results) == 1, serialized_history
        result_payload = ImageResultObservation.model_validate(
            HistoryEventObservation.model_validate(results[0]).payload
        )
        output = result_payload.output
        assert len(output) == 2
        assert isinstance(output[0].model_file_id, str)
        assert output[0].kind == "image"
        assert output[0].media_type == "image/jpeg"
        attachment = output[1]
        assert attachment.type == "attachment"
        assert attachment.availability == "available"
        assert attachment.media_type == "image/png"
        assert attachment.size == len(_IMAGE_BYTES)
        attachment_uri = attachment.uri
        assert isinstance(attachment_uri, str)
        assert attachment_uri.startswith("exchange://")
        attachment_id = attachment.attachment_id
        assert isinstance(attachment_id, str)

        download = download_fixture_exchange_file(
            server_url=azents_public_server_url,
            access_token=token,
            attachment_id=attachment_id,
            storage_endpoint_url=azents_browser_s3_endpoint_url,
        )
        assert hashlib.sha256(download).hexdigest() == _IMAGE_SHA256
        assert download == _IMAGE_BYTES

        initial_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        tools = initial_request.tools
        assert tools is not None
        assert any(
            tool.type == "function" and tool.name == "image_generation"
            for tool in tools
        )
        assert all(tool.type != "image_generation" for tool in tools)
        assert [request.model for request in _image_api_journal(openai_proxy_url)] == [
            "gpt-image-2"
        ]

        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_FOLLOW_UP_PROMPT,
            reasoning_effort="high",
        )
        _wait_for_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            predicate=lambda event: _assistant_content(event) == _FOLLOW_UP_RESPONSE,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )

        follow_up_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _FOLLOW_UP_PROMPT,
        )
        assert isinstance(follow_up_request.input, list)
        input_items = [
            item.model_dump(mode="json", exclude_unset=True)
            for item in follow_up_request.input
        ]
        assert _count_typed_items(input_items, "image_generation_call") == 0
        assert _count_typed_items(input_items, "function_call_output") >= 1
        assert _count_string_occurrences(input_items, attachment_uri) == 1
        assert _IMAGE_BASE64 not in json.dumps(input_items)

        final_history = list_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        final_serialized = json.dumps(
            final_history,
            ensure_ascii=False,
            sort_keys=True,
        )
        assert _IMAGE_BASE64 not in final_serialized
        assert "data:image" not in final_serialized
        assert (
            len(
                [
                    event
                    for event in history_events(final_history)
                    if _client_result([event]) is not None
                ]
            )
            == 1
        )
