"""Provider-hosted image generation product-path E2E coverage."""

import base64
import hashlib
import json
import time
from collections.abc import Callable

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from pydantic import TypeAdapter

from support.consts import REPOSITORY_ROOT
from support.utils import unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import setup_profile_agent

_PROMPT = "Provider image generation handoff"
_FOLLOW_UP_PROMPT = "Provider image generation follow-up"
_FOLLOW_UP_RESPONSE = "PROVIDER_IMAGE_GENERATION_FOLLOW_UP_COMPLETED"
_PROXY_JOURNAL_PATH = "/v1/_image_generation_requests"
_IMAGE_PATH = (
    REPOSITORY_ROOT
    / "testenv/azents/e2e/src/support/fixtures/provider-image-generation.png"
)
_IMAGE_BYTES = _IMAGE_PATH.read_bytes()
_IMAGE_BASE64 = base64.b64encode(_IMAGE_BYTES).decode()
_IMAGE_SHA256 = hashlib.sha256(_IMAGE_BYTES).hexdigest()
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


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
        payload = json_object_payload(response.json(), label="session response")
        last_state = payload.get("run_state")
        if last_state == "idle":
            return
        time.sleep(0.2)
    raise TimeoutError(f"image generation session did not become idle: {last_state!r}")


def _provider_call(
    events: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the completed image-generation provider call."""
    for event in events:
        if event.get("kind") != "provider_tool_call":
            continue
        payload = json_object_payload(event.get("payload"), label="provider call")
        if (
            payload.get("name") == "image_generation"
            and payload.get("status") == "completed"
        ):
            return event
    return None


def _assistant_content(event: dict[str, object]) -> str | None:
    """Return plain assistant content from one history event."""
    if event.get("kind") != "assistant_message":
        return None
    payload = json_object_payload(event.get("payload"), label="assistant payload")
    content = payload.get("content")
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


def _proxy_journal(openai_proxy_url: str) -> list[dict[str, object]]:
    """Return raw Responses requests captured by the deterministic proxy."""
    response = requests.get(
        f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
        timeout=10,
    )
    response.raise_for_status()
    return _JSON_OBJECT_LIST.validate_python(response.json())


def _last_user_text(request: dict[str, object]) -> str | None:
    """Return the last user input text from one raw Responses request."""
    input_value = request.get("input")
    if isinstance(input_value, str):
        return input_value
    if not isinstance(input_value, list):
        return None
    for raw_item in reversed(input_value):
        if not isinstance(raw_item, dict):
            continue
        item = json_object_payload(raw_item, label="Responses input item")
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        text_parts: list[str] = []
        for raw_part in content:
            if not isinstance(raw_part, dict):
                continue
            part = json_object_payload(raw_part, label="Responses input content")
            text = part.get("text")
            if part.get("type") == "input_text" and isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)
    return None


def _request_for_prompt(
    requests_: list[dict[str, object]],
    prompt: str,
) -> dict[str, object]:
    """Return the captured request whose last user input matches the prompt."""
    for request in requests_:
        if _last_user_text(request) == prompt:
            return request
    raise AssertionError(f"proxy request was not captured for prompt: {prompt!r}")


def _image_tool(request: dict[str, object]) -> dict[str, object]:
    """Return the exact image-generation tool from one provider request."""
    tools = json_object_list_payload(
        request.get("tools"),
        label="provider request tools",
    )
    image_tools = [tool for tool in tools if tool.get("type") == "image_generation"]
    assert len(image_tools) == 1, tools
    return image_tools[0]


def _profile_workspace_and_integration(
    *,
    public_api_client: azentspublicclient.ApiClient,
    token: str,
) -> tuple[str, str]:
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
    return handle, integrations.items[0].id


def _wait_for_image_catalog(
    *,
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> dict[str, object]:
    """Wait for the initial exact-registry image catalog projection."""
    catalog_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration_id}/"
        "image-generation-model-catalog"
    )

    def current_catalog() -> dict[str, object] | None:
        response = requests.get(
            catalog_url,
            headers=auth_headers(token),
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = json_object_payload(
            response.json(),
            label="image generation catalog",
        )
        entries = json_object_list_payload(
            payload.get("entries"),
            label="image generation catalog entries",
        )
        identifiers = [entry.get("provider_model_identifier") for entry in entries]
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
    current = 1 if value.get("type") == item_type else 0
    return current + sum(_count_typed_items(item, item_type) for item in value.values())


class TestProviderImageGeneration:
    """Validate hosted image output, storage, replay, and payload hygiene."""

    def test_default_omission_and_explicit_pin_reach_provider_request(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Stored catalog selection controls the exact hosted tool payload."""
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
        assert catalog.get("default_available") is True
        assert catalog.get("explicit_selection_supported") is True
        assert catalog.get("generation_current") is True
        assert catalog.get("total") == 2

        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
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
        assert _image_tool(default_request) == {"type": "image_generation"}

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
        updated_agent = json_object_payload(
            update.json(),
            label="updated explicit image model Agent",
        )
        quality_option = next(
            option
            for option in json_object_list_payload(
                updated_agent.get("selectable_model_options"),
                label="updated selectable model options",
            )
            if option.get("label") == "Quality"
        )
        quality_candidates = json_object_list_payload(
            quality_option.get("candidates"),
            label="updated Quality candidates",
        )
        quality_settings = json_object_payload(
            quality_candidates[0].get("settings"),
            label="updated Quality settings",
        )
        assert json_object_list_payload(
            quality_settings.get("builtin_tools"),
            label="updated Quality built-in tools",
        )[1] == {
            "name": "image_generation",
            "config": {
                "model": "gpt-image-2.5-flare",
                "quality": "high",
            },
        }

        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
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
        explicit_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        assert _image_tool(explicit_request) == {
            "type": "image_generation",
            "model": "gpt-image-2.5-flare",
            "quality": "high",
        }

    def test_materializes_downloads_and_replays_generated_image(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """One generated image becomes one durable dual-resource result."""
        del azents_engine_worker_container
        requests.delete(
            f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
            timeout=10,
        ).raise_for_status()
        token, agent_id, session_id = setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        observed_statuses: set[str] = set()
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
                action = json_object_payload(
                    json.loads(raw_text),
                    label="WebSocket action",
                )
                action_type = action.get("type")
                observed_action_types.append(action_type)
                if action_type == "live_event_upserted":
                    event = json_object_payload(
                        action.get("event"),
                        label="provider live event",
                    )
                    if event.get("kind") == "provider_tool_call":
                        payload = json_object_payload(
                            event.get("payload"),
                            label="provider live payload",
                        )
                        if payload.get("name") == "image_generation":
                            status = payload.get("status")
                            if isinstance(status, str):
                                observed_statuses.add(status)
                elif action_type == "live_run_cleared":
                    run_cleared = True
                if run_cleared and observed_statuses >= {
                    "running",
                    "completed",
                }:
                    break
            if not run_cleared or not observed_statuses >= {
                "running",
                "completed",
            }:
                raise TimeoutError(
                    "image-generation live handoff did not complete: "
                    f"statuses={observed_statuses!r}, "
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
            if _provider_call([event]) is not None
        ]
        assert len(results) == 1, serialized_history
        result_payload = json_object_payload(
            results[0].get("payload"),
            label="durable provider result payload",
        )
        assert "output" not in result_payload
        semantic = json_object_payload(
            result_payload.get("semantic"),
            label="provider result semantic content",
        )
        output = json_object_list_payload(
            semantic.get("output"),
            label="provider result semantic output",
        )
        assert "attachments" not in result_payload
        assert len(output) == 2
        assert isinstance(output[0].get("model_file_id"), str)
        assert output[0].get("kind") == "image"
        assert output[0].get("media_type") == "image/jpeg"
        attachment = output[1]
        assert attachment.get("type") == "attachment"
        assert attachment.get("availability") == "available"
        assert attachment.get("media_type") == "image/png"
        assert attachment.get("size") == len(_IMAGE_BYTES)
        attachment_uri = attachment.get("uri")
        assert isinstance(attachment_uri, str)
        assert attachment_uri.startswith("exchange://")
        attachment_id = attachment.get("attachment_id")
        assert isinstance(attachment_id, str)

        download = requests.get(
            f"{azents_public_server_url}/chat/v1/exchange-files/{attachment_id}/download",
            headers=auth_headers(token),
            timeout=10,
        )
        download.raise_for_status()
        assert hashlib.sha256(download.content).hexdigest() == _IMAGE_SHA256
        assert download.content == _IMAGE_BYTES

        initial_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        tools = json_object_list_payload(
            initial_request.get("tools"),
            label="initial provider tools",
        )
        assert {tool.get("type") for tool in tools} >= {"image_generation"}

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
        input_items = json_object_list_payload(
            follow_up_request.get("input"),
            label="follow-up input",
        )
        image_items = [
            item for item in input_items if item.get("type") == "image_generation_call"
        ]
        assert len(image_items) == 1
        assert _count_string_occurrences(input_items, attachment_uri) == 1
        assert _count_typed_items(input_items, "input_image") == 0
        replayed_result = image_items[0].get("result")
        assert isinstance(replayed_result, str)
        replayed_image = base64.b64decode(replayed_result, validate=True)
        assert replayed_result != _IMAGE_BASE64
        assert replayed_image.startswith(b"\xff\xd8\xff")
        assert replayed_image.endswith(b"\xff\xd9")

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
                    if _provider_call([event]) is not None
                ]
            )
            == 1
        )
