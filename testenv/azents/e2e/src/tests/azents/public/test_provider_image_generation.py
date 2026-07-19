"""Provider-hosted image generation product-path E2E coverage."""

import base64
import hashlib
import json
import time
from collections.abc import Callable
from typing import cast

import azentsadminclient
import azentspublicclient
import requests
from pydantic import TypeAdapter

from support.consts import REPOSITORY_ROOT
from support.utils import unique
from tests.azents.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
)
from tests.azents.public.test_per_prompt_inference_profile import setup_profile_agent

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
    for raw_item in reversed(cast(list[object], input_value)):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, object], raw_item)
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        text_parts: list[str] = []
        for raw_part in cast(list[object], content):
            if not isinstance(raw_part, dict):
                continue
            part = cast(dict[str, object], raw_part)
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


class TestProviderImageGeneration:
    """Validate hosted image output, storage, replay, and payload hygiene."""

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
        attachments = json_object_list_payload(
            result_payload.get("attachments"),
            label="provider call attachments",
        )
        assert len(output) == 2
        assert isinstance(output[0].get("model_file_id"), str)
        assert output[0].get("kind") == "image"
        assert output[0].get("media_type") == "image/jpeg"
        assert attachments == []
        attachment = output[1]
        assert attachment.get("type") == "attachment"
        assert attachment.get("availability") == "available"
        assert attachment.get("media_type") == "image/png"
        assert attachment.get("size") == len(_IMAGE_BYTES)
        assert isinstance(attachment.get("uri"), str)
        assert cast(str, attachment["uri"]).startswith("exchange://")
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
