"""Provider-hosted tool semantic transcript E2E coverage."""

import json
import time
from typing import cast

import azentsadminclient
import azentspublicclient
import requests

from support.utils import unique
from tests.azents.public.test_agent_execution_persistence import (
    auth_headers,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
)
from tests.azents.public.test_per_prompt_inference_profile import setup_profile_agent

_PROMPT = "Provider semantic web search handoff"
_SAME_NATIVE_PROMPT = "Provider semantic same-native follow-up"
_CROSS_NATIVE_PROMPT = "Provider semantic cross-native follow-up"
_POST_COMPACTION_PROMPT = "Provider semantic post-compaction follow-up"
_QUERY = "Azents provider semantic transcript"
_SOURCE_URL = "https://example.com/provider-semantic-transcript"
_INITIAL_RESPONSE = "PROVIDER_SEMANTIC_WEB_SEARCH_COMPLETED"
_SAME_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_SAME_NATIVE_COMPLETED"
_CROSS_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_CROSS_NATIVE_COMPLETED"
_POST_COMPACTION_RESPONSE = "PROVIDER_SEMANTIC_POST_COMPACTION_COMPLETED"
_NATIVE_ITEM_ID = "search_provider_semantic"
_PROXY_JOURNAL_PATH = "/v1/_image_generation_requests"
_COMPACTION_SYSTEM_PREFIX = (
    "You are a context compaction engine for a long-running coding agent."
)


def _submit(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    model_target_label: str,
) -> None:
    """Submit one explicit model-target turn through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"provider-semantic-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": model_target_label,
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _wait_for_turn(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    expected_response: str,
    timeout: float = 120,
) -> None:
    """Wait until the assistant response is durable and the session is idle."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    latest_history: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest_history = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        response_observed = False
        for event in history_events(latest_history):
            if event.get("kind") != "assistant_message":
                continue
            payload = json_object_payload(
                event.get("payload"),
                label="assistant payload",
            )
            if payload.get("content") == expected_response:
                response_observed = True
                break
        session_response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=auth_headers(token),
            timeout=10,
        )
        session_response.raise_for_status()
        session = json_object_payload(
            session_response.json(),
            label="session response",
        )
        last_state = session.get("run_state")
        if response_observed and last_state == "idle":
            return
        time.sleep(0.2)
    raise TimeoutError(
        "provider semantic turn did not complete: "
        f"response={expected_response!r}, state={last_state!r}, "
        f"history={latest_history!r}"
    )


def _context(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch the public context-inspector payload."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/context",
        headers=auth_headers(token),
        params={"limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    return json_object_payload(response.json(), label="context response")


def _proxy_journal(openai_proxy_url: str) -> list[dict[str, object]]:
    """Return raw Responses requests captured by the deterministic proxy."""
    response = requests.get(
        f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
        timeout=10,
    )
    response.raise_for_status()
    return json_object_list_payload(response.json(), label="proxy journal")


def _last_user_text(request: dict[str, object]) -> str | None:
    """Return the last user input text from one Responses request."""
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


def _run_compaction(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> None:
    """Run manual compaction through the public command input boundary."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"provider-semantic-compact-{unique()}",
            "message": "",
            "action": {"type": "command", "name": "compact"},
            "inference_profile": None,
        },
        timeout=10,
    )
    response.raise_for_status()
    deadline = time.monotonic() + timeout
    latest_history: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest_history = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        kinds = {event.get("kind") for event in history_events(latest_history)}
        if {"compaction_marker", "compaction_summary"} <= kinds:
            return
        time.sleep(0.2)
    raise TimeoutError(
        f"provider semantic compaction did not complete: {latest_history!r}"
    )


def _compaction_request(requests_: list[dict[str, object]]) -> dict[str, object]:
    """Return the captured context-compaction model request."""
    for request in reversed(requests_):
        instructions = request.get("instructions")
        if isinstance(instructions, str) and instructions.startswith(
            _COMPACTION_SYSTEM_PREFIX
        ):
            return request
    raise AssertionError("proxy did not capture a compaction model request")


def _serialized_input(request: dict[str, object]) -> str:
    """Serialize model input for deterministic semantic assertions."""
    return json.dumps(request.get("input"), ensure_ascii=False, sort_keys=True)


def _provider_semantic_event(context: dict[str, object]) -> dict[str, object]:
    """Return the durable provider Web-search context event."""
    raw_events = json_object_list_payload(
        context.get("raw_events"),
        label="context raw events",
    )
    for event in raw_events:
        if event.get("kind") != "provider_tool_call":
            continue
        payload = json_object_payload(
            event.get("payload"),
            label="provider tool payload",
        )
        if payload.get("name") == "web_search":
            return event
    raise AssertionError("provider Web-search event was not found in context")


class TestProviderToolSemanticTranscript:
    """Validate semantic persistence, replay, lowering, and compaction."""

    def test_preserves_web_search_semantics_across_compaction(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Canonical query and references survive every model-input boundary."""
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

        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_PROMPT,
            model_target_label="Quality",
        )
        _wait_for_turn(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            expected_response=_INITIAL_RESPONSE,
        )

        context = _context(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        provider_event = _provider_semantic_event(context)
        payload = json_object_payload(
            provider_event.get("payload"),
            label="provider tool payload",
        )
        semantic = json_object_payload(
            payload.get("semantic"),
            label="provider tool semantic content",
        )
        assert semantic.get("input") == json.dumps(
            {"query": _QUERY, "type": "search"},
            separators=(",", ":"),
            sort_keys=True,
        )
        references = json_object_list_payload(
            semantic.get("references"),
            label="provider tool references",
        )
        assert [reference.get("uri") for reference in references] == [_SOURCE_URL]
        breakdown = json_object_list_payload(
            context.get("breakdown"),
            label="context breakdown",
        )
        tool_segments = [
            segment for segment in breakdown if segment.get("key") == "tool"
        ]
        assert len(tool_segments) == 1
        tool_tokens = tool_segments[0].get("tokens")
        assert isinstance(tool_tokens, int)
        assert tool_tokens > len(_QUERY)

        initial_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        tools = json_object_list_payload(
            initial_request.get("tools"),
            label="initial provider tools",
        )
        assert "web_search" in {tool.get("type") for tool in tools}

        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_SAME_NATIVE_PROMPT,
            model_target_label="Quality",
        )
        _wait_for_turn(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            expected_response=_SAME_NATIVE_RESPONSE,
        )
        same_native_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _SAME_NATIVE_PROMPT,
        )
        same_native_input = json_object_list_payload(
            same_native_request.get("input"),
            label="same-native input",
        )
        replayed_searches = [
            item for item in same_native_input if item.get("type") == "web_search_call"
        ]
        assert len(replayed_searches) == 1
        assert replayed_searches[0].get("id") == _NATIVE_ITEM_ID
        assert _QUERY in json.dumps(replayed_searches[0], ensure_ascii=False)
        assert _SOURCE_URL in json.dumps(replayed_searches[0], ensure_ascii=False)

        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_CROSS_NATIVE_PROMPT,
            model_target_label="Fast",
        )
        _wait_for_turn(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            expected_response=_CROSS_NATIVE_RESPONSE,
        )
        cross_native_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _CROSS_NATIVE_PROMPT,
        )
        cross_native_input = _serialized_input(cross_native_request)
        assert "[Provider tool call: web_search completed]" in cross_native_input
        assert _QUERY in cross_native_input
        assert _SOURCE_URL in cross_native_input
        assert _INITIAL_RESPONSE in cross_native_input
        assert _NATIVE_ITEM_ID not in cross_native_input

        _run_compaction(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        requests_ = _proxy_journal(openai_proxy_url)
        compaction_input = _serialized_input(_compaction_request(requests_))
        assert "[Provider tool call: web_search completed]" in compaction_input
        assert _QUERY in compaction_input
        assert _SOURCE_URL in compaction_input
        assert _INITIAL_RESPONSE in compaction_input
        assert _NATIVE_ITEM_ID not in compaction_input

        compacted_history = list_history(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        compacted_events = history_events(compacted_history)
        summaries = [
            json_object_payload(event.get("payload"), label="compaction summary")
            for event in compacted_events
            if event.get("kind") == "compaction_summary"
        ]
        assert len(summaries) == 1
        summary_content = summaries[0].get("content")
        assert isinstance(summary_content, str)
        assert _QUERY in summary_content
        assert _SOURCE_URL in summary_content

        _submit(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_POST_COMPACTION_PROMPT,
            model_target_label="Fast",
        )
        _wait_for_turn(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            expected_response=_POST_COMPACTION_RESPONSE,
        )
        post_compaction_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _POST_COMPACTION_PROMPT,
        )
        post_compaction_input = _serialized_input(post_compaction_request)
        assert _QUERY in post_compaction_input
        assert _SOURCE_URL in post_compaction_input
        assert _INITIAL_RESPONSE in post_compaction_input
        assert _NATIVE_ITEM_ID not in post_compaction_input
