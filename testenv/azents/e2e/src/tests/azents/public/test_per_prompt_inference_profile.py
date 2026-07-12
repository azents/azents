"""Per-prompt inference profile product E2E tests."""

import json
import time
from typing import cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import TypeAdapter, ValidationError

from support.utils import authenticate_user, unique, wait_until

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_QUALITY_MESSAGE = "Per prompt quality profile"
_FAST_MESSAGE = "Per prompt fast profile"
_SPAWN_OVERRIDE_MESSAGE = "Subagent spawn with Fast override"
_SPAWN_OVERRIDE_TASK = "Subagent Fast override task"
_FOLLOWUP_MESSAGE = "Subagent follow-up after override"
_FOLLOWUP_TASK = "Subagent Fast follow-up task"
_FULL_HISTORY_REJECTION_MESSAGE = "Subagent reject full-history override"
_UNKNOWN_TARGET_REJECTION_MESSAGE = "Subagent reject unknown target override"


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _object(value: object, *, label: str) -> dict[str, object]:
    """Validate a JSON object."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {value!r}") from exc


def _objects(value: object, *, label: str) -> list[dict[str, object]]:
    """Validate a JSON object list."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {value!r}") from exc


def _response_object(response: requests.Response) -> dict[str, object]:
    """Validate an HTTP JSON object response."""
    response.raise_for_status()
    return _object(response.json(), label="HTTP response")


def _setup_profile_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> tuple[str, str, str]:
    """Create a workspace and Agent with deterministic Quality/Fast targets."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"per-prompt-profile-{uniq}@example.com",
    )
    handle = f"per-prompt-profile-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Per Prompt Profile QA {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-per-prompt-profile-qa")),
        ),
        _headers=_headers(token),
    )
    sync_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-sync"
    )
    sync_response = wait_until(
        lambda: requests.post(sync_url, headers=_headers(token), timeout=10),
        timeout=10,
        interval=0.2,
        message="Catalog sync did not become available",
    )
    sync_response.raise_for_status()

    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-entries"
    )

    def populated_entries() -> list[dict[str, object]] | None:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        response.raise_for_status()
        entries = _objects(
            _response_object(response).get("entries"),
            label="catalog entries",
        )
        identifiers = {entry.get("provider_model_identifier") for entry in entries}
        if {"gpt-5.5", "gpt-5.5-mini"}.issubset(identifiers):
            return entries
        return None

    entries = wait_until(
        populated_entries,
        timeout=10,
        interval=0.2,
        message="Deterministic catalog entries did not become readable",
    )
    assert entries is not None
    by_identifier = {
        cast(str, entry["provider_model_identifier"]): entry for entry in entries
    }

    def selection(identifier: str) -> dict[str, str]:
        return {
            "llm_provider_integration_id": integration.id,
            "model_identifier": identifier,
        }

    created = _response_object(
        requests.post(
            f"{server_url}/agent/v1/workspaces/{handle}/agents",
            headers={**_headers(token), "Content-Type": "application/json"},
            json={
                "name": "Per Prompt Profile QA Agent",
                "type": "public",
                "selectable_model_options": [
                    {
                        "label": "Quality",
                        "model_selection": selection(
                            cast(
                                str,
                                by_identifier["gpt-5.5"]["provider_model_identifier"],
                            )
                        ),
                    },
                    {
                        "label": "Fast",
                        "model_selection": selection(
                            cast(
                                str,
                                by_identifier["gpt-5.5-mini"][
                                    "provider_model_identifier"
                                ],
                            )
                        ),
                    },
                ],
                "main_model_label": "Quality",
                "lightweight_model_label": "Fast",
            },
            timeout=10,
        )
    )
    agent_id = created.get("id")
    if not isinstance(agent_id, str):
        raise AssertionError(f"Agent response did not include id: {created!r}")
    session = _response_object(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        )
    )
    session_id = session.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Session response did not include id: {session!r}")
    return token, agent_id, session_id


def _write_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    target: str,
    effort: str | None,
) -> None:
    """Submit one explicit per-prompt profile."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"per-prompt-profile-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": target,
                "reasoning_effort": effort,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _wait_for_session_idle(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for idle and return the authoritative session projection."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
        payload = _response_object(response)
        last_state = payload.get("run_state")
        if last_state == "idle":
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Session did not become idle: {last_state!r}")


def _wait_for_session_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    target: str,
    effort: str | None,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for the authoritative session projection to persist a profile."""
    deadline = time.monotonic() + timeout
    last_profile: tuple[object, object] = (None, None)
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
        payload = _response_object(response)
        last_profile = (
            payload.get("current_model_target_label"),
            payload.get("current_reasoning_effort"),
        )
        if last_profile == (target, effort):
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Session did not persist profile: {last_profile!r}")


def _history(server_url: str, token: str, session_id: str) -> list[dict[str, object]]:
    """Fetch the current history page."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    return _objects(_response_object(response).get("items"), label="history items")


def _wait_for_tool_result(
    *,
    server_url: str,
    token: str,
    session_id: str,
    call_id: str,
    timeout: float = 120,
) -> None:
    """Wait until a tool call has produced a persisted result."""
    deadline = time.monotonic() + timeout
    last_kinds: list[object] = []
    while time.monotonic() < deadline:
        events = _history(server_url, token, session_id)
        last_kinds = [event.get("kind") for event in events]
        for event in events:
            if event.get("kind") != "client_tool_result":
                continue
            payload = _object(event.get("payload"), label="tool result payload")
            if payload.get("call_id") == call_id:
                return
        time.sleep(0.5)
    raise TimeoutError(f"Tool result was not observed: {call_id}, {last_kinds!r}")


def _input_event(
    events: list[dict[str, object]], message: str
) -> dict[str, object] | None:
    """Find a user or agent input event by content."""
    for event in events:
        if event.get("kind") not in {"user_message", "agent_message"}:
            continue
        payload = _object(event.get("payload"), label="input event payload")
        if payload.get("content") == message:
            return event
    return None


def _wait_for_input_event(
    *,
    server_url: str,
    token: str,
    session_id: str,
    message: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for a durable input event without event-level run provenance."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = _input_event(_history(server_url, token, session_id), message)
        if event is not None:
            assert "inference_run_summary" not in event
            return event
        time.sleep(0.5)
    raise TimeoutError(f"Input event was not observed: {message!r}")


def _wait_for_system_error(
    *,
    server_url: str,
    token: str,
    session_id: str,
    content: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for a durable handled preparation failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in _history(server_url, token, session_id):
            if event.get("kind") != "system_error":
                continue
            payload = _object(event.get("payload"), label="system error payload")
            if payload.get("content") == content:
                return event
        time.sleep(0.5)
    raise TimeoutError(f"System error was not observed: {content!r}")


def _wait_for_mock_models(mock_openai_url: str, *model_ids: str) -> str:
    """Wait until the mock provider journal contains every expected model."""

    def complete_journal() -> str | None:
        journal = json.dumps(
            requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
        )
        if all(model_id in journal for model_id in model_ids):
            return journal
        return None

    journal = wait_until(
        complete_journal,
        timeout=120,
        interval=0.5,
        message="Expected model requests were not observed",
    )
    assert journal is not None
    return journal


def _subagent_tree(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch the public Subagent Tree projection."""
    return _response_object(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/subagents/tree",
            headers=_headers(token),
            timeout=10,
        )
    )


def _find_tree_node(
    nodes: list[dict[str, object]],
    name: str,
) -> dict[str, object] | None:
    """Find a named node in a raw Subagent Tree."""
    for node in nodes:
        if node.get("name") == name:
            return node
        child = _find_tree_node(
            _objects(node.get("children"), label="tree children"),
            name,
        )
        if child is not None:
            return child
    return None


def _wait_for_tree_node(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    root_session_id: str,
    name: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for a named Subagent Tree node."""
    deadline = time.monotonic() + timeout
    last_tree: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_tree = _subagent_tree(
            server_url=server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
        )
        node = _find_tree_node(
            _objects(last_tree.get("nodes"), label="tree nodes"),
            name,
        )
        if node is not None and node.get("status") == "completed":
            return node
        time.sleep(0.5)
    raise TimeoutError(f"Subagent Tree node did not complete: {name}, {last_tree!r}")


def _tree_names(tree: dict[str, object]) -> set[str]:
    """Collect all names in a raw Subagent Tree."""
    names: set[str] = set()

    def collect(nodes: list[dict[str, object]]) -> None:
        for node in nodes:
            name = node.get("name")
            if isinstance(name, str):
                names.add(name)
            collect(_objects(node.get("children"), label="tree children"))

    collect(_objects(tree.get("nodes"), label="tree nodes"))
    return names


class TestPerPromptInferenceProfile:
    """Per-prompt routing and provenance E2E coverage."""

    def test_target_effort_resolution_and_safe_failure(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        mock_openai_url: str,
    ) -> None:
        """Resolve distinct targets and expose an unsupported effort safely."""
        del azents_engine_worker_container
        token, agent_id, session_id = _setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        requests.delete(
            f"{mock_openai_url}/v1/_requests", timeout=10
        ).raise_for_status()

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
            target="Quality",
            effort="high",
        )
        _wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_FAST_MESSAGE,
            target="Fast",
            effort=None,
        )
        _wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_FAST_MESSAGE,
        )

        _wait_for_mock_models(mock_openai_url, "gpt-5.5", "gpt-5.5-mini")

        unsupported_message = "Unsupported effort must fail safely"
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=unsupported_message,
            target="Fast",
            effort="high",
        )
        _wait_for_system_error(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            content="The selected reasoning effort is not supported by this model.",
        )
        assert (
            _input_event(
                _history(azents_public_server_url, token, session_id),
                unsupported_message,
            )
            is None
        )
        session = _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        assert session["current_model_target_label"] == "Fast"
        assert session["current_reasoning_effort"] is None

    def test_subagent_spawn_override_continuation(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Persist a spawn override and reuse it for a follow-up run."""
        del azents_engine_worker_container
        token, agent_id, root_session_id = _setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_SPAWN_OVERRIDE_MESSAGE,
            target="Quality",
            effort="high",
        )
        child = _wait_for_tree_node(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            root_session_id=root_session_id,
            name="profile_child",
        )
        child_session_id = child.get("agent_session_id")
        if not isinstance(child_session_id, str):
            raise AssertionError(f"Child node has no AgentSession ID: {child!r}")
        _wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=child_session_id,
            message=_SPAWN_OVERRIDE_TASK,
        )
        _wait_for_session_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=child_session_id,
            target="Fast",
            effort=None,
        )
        _wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=root_session_id,
            message=_SPAWN_OVERRIDE_MESSAGE,
        )
        _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_FOLLOWUP_MESSAGE,
            target="Quality",
            effort="high",
        )
        _wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=child_session_id,
            message=_FOLLOWUP_TASK,
        )
        _wait_for_session_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=child_session_id,
            target="Fast",
            effort=None,
        )

    @pytest.mark.parametrize(
        ("message", "rejected_name", "call_id"),
        [
            (
                _FULL_HISTORY_REJECTION_MESSAGE,
                "invalid_history",
                "call_subagent_reject_full_history",
            ),
            (
                _UNKNOWN_TARGET_REJECTION_MESSAGE,
                "invalid_target",
                "call_subagent_reject_unknown_target",
            ),
        ],
    )
    def test_subagent_spawn_override_rejection_is_atomic(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        message: str,
        rejected_name: str,
        call_id: str,
    ) -> None:
        """Reject an invalid override without creating a child."""
        del azents_engine_worker_container
        token, agent_id, session_id = _setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            target="Quality",
            effort="high",
        )
        _wait_for_tool_result(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            call_id=call_id,
        )
        tree = _subagent_tree(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        assert rejected_name not in _tree_names(tree)
