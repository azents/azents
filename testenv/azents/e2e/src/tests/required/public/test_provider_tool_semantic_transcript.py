"""Provider-hosted tool semantic transcript E2E coverage."""

import json
import time

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.session_context_raw_event_response import (
    SessionContextRawEventResponse,
)
from azentspublicclient.models.session_context_response import SessionContextResponse
from pydantic import JsonValue, StrictStr, TypeAdapter

from support.observations import (
    ExtensionObservation,
    decode_history_page,
)
from support.profile_observations import (
    ProfileProviderRequestObservation,
)
from support.utils import unique
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import setup_profile_agent

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
    "You are a context compaction engine for a long-running agent."
)


class _ContentPart(ExtensionObservation):
    type: StrictStr
    text: StrictStr | None = None


class _TextPayload(ExtensionObservation):
    content: StrictStr | list[dict[str, JsonValue]]


class _InputItem(ExtensionObservation):
    type: StrictStr | None = None
    id: StrictStr | None = None
    role: StrictStr | None = None
    content: StrictStr | list[_ContentPart] | None = None


class _Tool(ExtensionObservation):
    type: StrictStr


class _SemanticRequest(ProfileProviderRequestObservation):
    instructions: StrictStr | None = None
    tools: list[_Tool] | None = None


_REQUESTS = TypeAdapter(list[_SemanticRequest])


class _Reference(ExtensionObservation):
    uri: StrictStr | None


class _Semantic(ExtensionObservation):
    input: StrictStr | None
    references: list[_Reference]


class _ProviderPayload(ExtensionObservation):
    name: StrictStr
    semantic: _Semantic


_ITEMS = TypeAdapter(list[_InputItem])


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
                "enabled_execution_options": [],
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
    latest_history: object = None
    while time.monotonic() < deadline:
        latest_history = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        response_observed = False
        for event in decode_history_page(latest_history).items:
            if event.kind != "assistant_message":
                continue
            payload = _TextPayload.model_validate(event.payload)
            if payload.content == expected_response:
                response_observed = True
                break
        session_response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=auth_headers(token),
            timeout=10,
        )
        session_response.raise_for_status()
        session = AgentSessionResponse.model_validate(session_response.json())
        last_state = session.run_state
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
) -> SessionContextResponse:
    """Fetch the public context-inspector payload."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/context",
        headers=auth_headers(token),
        params={"limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    return SessionContextResponse.model_validate(response.json())


def _proxy_journal(openai_proxy_url: str) -> list[_SemanticRequest]:
    """Return raw Responses requests captured by the deterministic proxy."""
    response = requests.get(
        f"{openai_proxy_url}{_PROXY_JOURNAL_PATH}",
        timeout=10,
    )
    response.raise_for_status()
    return _REQUESTS.validate_python(response.json())


def _last_user_text(request: _SemanticRequest) -> str | None:
    """Interpret known message fields after decoding the Responses input."""
    if isinstance(request.input, str):
        return request.input
    if request.input is None:
        return None
    for item in reversed(_ITEMS.validate_python(request.input)):
        if item.role != "user":
            continue
        if isinstance(item.content, str):
            return item.content
        if item.content is None:
            return None
        return "".join(
            part.text
            for part in item.content
            if part.type == "input_text" and part.text is not None
        )
    return None


def _request_for_prompt(
    requests_: list[_SemanticRequest],
    prompt: str,
) -> _SemanticRequest:
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
    latest_history: object = None
    while time.monotonic() < deadline:
        latest_history = list_history(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        kinds = {event.kind for event in decode_history_page(latest_history).items}
        if {"compaction_marker", "compaction_summary"} <= kinds:
            return
        time.sleep(0.2)
    raise TimeoutError(
        f"provider semantic compaction did not complete: {latest_history!r}"
    )


def _compaction_request(
    requests_: list[_SemanticRequest],
) -> _SemanticRequest:
    """Return the captured context-compaction model request."""
    for request in reversed(requests_):
        instructions = request.instructions
        if isinstance(instructions, str) and instructions.startswith(
            _COMPACTION_SYSTEM_PREFIX
        ):
            return request
    raise AssertionError("proxy did not capture a compaction model request")


def _serialized_input(request: _SemanticRequest) -> str:
    """Serialize model input for deterministic semantic assertions."""
    return json.dumps(request.input, ensure_ascii=False, sort_keys=True)


def _provider_semantic_event(
    context: SessionContextResponse,
) -> SessionContextRawEventResponse:
    """Return the durable provider Web-search context event."""
    for event in context.raw_events:
        if event.kind != "provider_tool_call":
            continue
        payload = _ProviderPayload.model_validate(event.payload)
        if payload.name == "web_search":
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
        payload = _ProviderPayload.model_validate(provider_event.payload)
        semantic = payload.semantic
        assert semantic.input == json.dumps(
            {"query": _QUERY, "type": "search"},
            separators=(",", ":"),
            sort_keys=True,
        )
        assert [reference.uri for reference in semantic.references] == [_SOURCE_URL]
        tool_segments = [
            segment for segment in context.breakdown if segment.key == "tool"
        ]
        assert len(tool_segments) == 1
        tool_tokens = tool_segments[0].tokens
        assert isinstance(tool_tokens, int)
        assert tool_tokens > len(_QUERY)

        initial_request = _request_for_prompt(
            _proxy_journal(openai_proxy_url),
            _PROMPT,
        )
        tools = initial_request.tools
        assert tools is not None
        assert "web_search" in {tool.type for tool in tools}

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
        same_native_input = _ITEMS.validate_python(same_native_request.input)
        replayed_searches = [
            item for item in same_native_input if item.type == "web_search_call"
        ]
        assert len(replayed_searches) == 1
        assert replayed_searches[0].id == _NATIVE_ITEM_ID
        assert _QUERY in replayed_searches[0].model_dump_json(exclude_unset=True)
        assert _SOURCE_URL in replayed_searches[0].model_dump_json(exclude_unset=True)

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
        compacted_events = decode_history_page(compacted_history).items
        summaries = [
            _TextPayload.model_validate(event.payload)
            for event in compacted_events
            if event.kind == "compaction_summary"
        ]
        assert len(summaries) == 1
        summary_content = summaries[0].content
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
