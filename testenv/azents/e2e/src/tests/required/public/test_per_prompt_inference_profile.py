"""Representative prepared inference, provider and subagent product journeys.

Invalid speed preference wire shapes are covered by the backend public Chat
``validation_audit_test.py`` admission contracts.
"""

import json
import time
from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentsadminclient.api.model_catalog_v1_api import ModelCatalogV1Api
from azentsadminclient.models.system_catalog_provider import SystemCatalogProvider
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_model_selection import AgentModelSelection
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.model_capabilities import ModelCapabilities
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.model_catalog_entry_response import (
    ModelCatalogEntryResponse,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.selectable_model_option import SelectableModelOption
from azentspublicclient.models.selectable_model_option_response import (
    SelectableModelOptionResponse,
)
from azentspublicclient.models.subagent_tree_node_response import (
    SubagentTreeNodeResponse,
)
from azentspublicclient.models.subagent_tree_response import SubagentTreeResponse
from azentspublicclient.models.workspace_model_settings_response import (
    WorkspaceModelSettingsResponse,
)
from pydantic import BaseModel, TypeAdapter, ValidationError

from support.image_generation_openai_proxy import is_inference_profile_title_request
from support.observations import (
    InputMessageObservation,
    RequestedProfileObservation,
    ToolResultObservation,
    TurnMarkerObservation,
)
from support.profile_observations import (
    CatalogSourceObservation,
    ProfileBarrierObservation,
    ProfileProviderRequestObservation,
    decode_mock_profile_journal,
    decode_profile_history,
    decode_profile_provider_journal,
    profile_history_event_wire,
)
from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import AgentSetup, authenticate_user, unique, wait_until

_JSON_OBJECT = TypeAdapter(dict[str, object])
_LEGACY_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_QUALITY_MESSAGE = "Per prompt quality profile"
_QUALITY_STANDARD_MESSAGE = "Per prompt quality standard profile"
_FAST_RETRY_MESSAGE = "Per prompt Fast retry preserves prepared option"
_FAST_MESSAGE = "Per prompt fast profile"
_SPAWN_OVERRIDE_MESSAGE = "Subagent spawn with Fast override"
_SPAWN_OVERRIDE_TASK = "Subagent Fast override task"
_FOLLOWUP_MESSAGE = "Subagent follow-up after override"
_FOLLOWUP_TASK = "Subagent Fast follow-up task"
_FULL_HISTORY_REJECTION_MESSAGE = "Subagent reject full-history override"
_UNKNOWN_TARGET_REJECTION_MESSAGE = "Subagent reject unknown target override"
_DISABLED_TARGET_REJECTION_MESSAGE = "Subagent reject disabled target override"
_INHERITED_DISABLED_TARGET_MESSAGE = "Subagent inherit disabled parent target"
_INHERITED_DISABLED_TARGET_TASK = "Inherited disabled parent target task"
_EFFORT_ONLY_DISABLED_TARGET_MESSAGE = "Subagent effort-only disabled parent target"
_EFFORT_ONLY_DISABLED_TARGET_TASK = "Effort-only disabled parent target task"


class ProfileAgentSetup(NamedTuple):
    """Prepared Agent identity and its primary Session."""

    token: str
    agent_id: str
    primary_session_id: str


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _object(value: object, *, label: str) -> dict[str, object]:
    """Validate a JSON object."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {value!r}") from exc


def _response_model[Observation: BaseModel](
    response: requests.Response, model: type[Observation]
) -> Observation:
    """Decode a represented API contract at its HTTP ingress boundary."""
    response.raise_for_status()
    return model.model_validate(response.json())


def _create_profile_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    *,
    user_email: str | None,
    workspace_handle: str | None,
    speed_targets: bool,
) -> AgentSetup:
    """Create a workspace and Agent with deterministic Quality/Fast targets."""
    uniq = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=user_email or f"per-prompt-profile-{uniq}@example.com",
    )
    handle = workspace_handle or f"per-prompt-profile-{uniq}"
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
            name="__testenv_model_listing:deterministic-model-settings",
            secrets=Secrets(ApiKeySecrets(api_key="sk-per-prompt-profile-qa")),
        ),
        _headers=_headers(token),
    )
    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-entries"
    )

    def populated_entries() -> list[ModelCatalogEntryResponse] | None:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        entries = _response_model(response, ModelCatalogEntryListResponse).entries
        identifiers = {entry.provider_model_identifier for entry in entries}
        expected_identifiers = {"gpt-5.5", "gpt-5.5-mini"}
        if speed_targets:
            expected_identifiers.update({"gpt-6-astra", "gpt-5.6-sol"})
        if expected_identifiers.issubset(identifiers):
            return entries
        return None

    entries = wait_until(
        populated_entries,
        timeout=10,
        interval=0.2,
        message="Deterministic catalog entries did not become readable",
    )
    assert entries is not None
    by_identifier = {entry.provider_model_identifier: entry for entry in entries}
    assert by_identifier["gpt-5.5"].supported_execution_options == ["fast"]
    assert by_identifier["gpt-5.5-mini"].supported_execution_options == []

    def selection(identifier: str) -> dict[str, str]:
        return {
            "llm_provider_integration_id": integration.id,
            "model_identifier": identifier,
        }

    runtime_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id="system-docker",
    )
    options: list[dict[str, object]] = [
        {
            "label": "Quality",
            "candidates": [
                {
                    "model_selection": selection(
                        by_identifier["gpt-5.5"].provider_model_identifier
                    ),
                    "settings": {
                        "context_window_tokens": 96_000,
                        "max_output_tokens": 12_000,
                        "builtin_tools": [
                            {"name": "web_search"},
                            {"name": "image_generation"},
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
                    "model_selection": selection(
                        by_identifier["gpt-5.5-mini"].provider_model_identifier
                    ),
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
    ]
    if speed_targets:
        for label, identifier in (
            ("Astra", "gpt-6-astra"),
            ("Sol", "gpt-5.6-sol"),
        ):
            assert by_identifier[identifier].supported_execution_options == [
                "fast",
                "ultrafast",
            ]
            options.append(
                {
                    "label": label,
                    "candidates": [
                        {
                            "model_selection": selection(identifier),
                            "settings": {
                                "context_window_tokens": 32_000,
                                "max_output_tokens": 4_000,
                                "builtin_tools": [],
                            },
                        }
                    ],
                    "subagent_enabled": True,
                }
            )
    agent_payload: dict[str, object] = {
        "name": "Per Prompt Profile QA Agent",
        "type": "public",
        "selectable_model_options": options,
        "main_model_label": "Quality",
        "lightweight_model_label": "Fast",
        "runtime_profile_id": runtime_profile_id,
    }
    created = _response_model(
        requests.post(
            f"{server_url}/agent/v1/workspaces/{handle}/agents",
            headers={**_headers(token), "Content-Type": "application/json"},
            json=agent_payload,
            timeout=10,
        ),
        AgentResponse,
    )
    agent_id = created.id
    created_options = {
        option.label: option for option in created.selectable_model_options
    }
    quality_selection = created_options["Quality"].candidates[0].model_selection
    assert quality_selection.supported_execution_options == ["fast"]
    quality_definitions = created_options["Quality"].execution_option_definitions
    assert len(quality_definitions) == 1
    quality_definition = quality_definitions[0]
    assert quality_definition.id == "fast"
    assert quality_definition.control == "boolean"
    assert quality_definition.label
    assert quality_definition.description
    assert quality_definition.cost_hint
    fast_selection = created_options["Fast"].candidates[0].model_selection
    assert fast_selection.supported_execution_options == []
    assert created_options["Fast"].execution_option_definitions == []
    if speed_targets:
        for label in ("Astra", "Sol"):
            definitions = created_options[label].execution_option_definitions
            assert {definition.id for definition in definitions} == {
                "fast",
                "ultrafast",
            }
            for definition in definitions:
                assert definition.exclusive_group == "processing_speed"
                assert definition.cost_hint
    return AgentSetup(
        access_token=token,
        email=email,
        workspace_handle=handle,
        agent_id=agent_id,
    )


def _profile_primary_session(
    server_url: str,
    setup: AgentSetup,
) -> ProfileAgentSetup:
    """Read the Agent's primary Session through the public API."""
    session = _response_model(
        requests.get(
            f"{server_url}/chat/v1/agents/{setup.agent_id}/team-primary-session",
            headers=_headers(setup.access_token),
            timeout=10,
        ),
        AgentSessionResponse,
    )
    return ProfileAgentSetup(setup.access_token, setup.agent_id, session.id)


def setup_profile_api_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    *,
    speed_targets: bool,
) -> ProfileAgentSetup:
    """Prepare configured model targets and a primary Session for profile APIs."""
    setup = _create_profile_agent(
        public_api_client,
        admin_api_client,
        server_url,
        user_email=None,
        workspace_handle=None,
        speed_targets=speed_targets,
    )
    return _profile_primary_session(server_url, setup)


def _setup_profile_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    *,
    user_email: str | None = None,
    workspace_handle: str | None = None,
    speed_targets: bool = False,
) -> ProfileAgentSetup:
    """Prepare model targets, a ready managed Runtime, and a primary Session."""
    setup = _create_profile_agent(
        public_api_client,
        admin_api_client,
        server_url,
        user_email=user_email,
        workspace_handle=workspace_handle,
        speed_targets=speed_targets,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=setup.access_token,
        workspace_handle=setup.workspace_handle,
        agent_id=setup.agent_id,
    )
    return _profile_primary_session(server_url, setup)


def _create_profile_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create one independent non-primary Session for a profile test."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    return _response_model(response, AgentSessionResponse).id


def _write_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
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
                "enabled_execution_options": enabled_execution_options,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _write_invalid_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    expected_detail: str,
) -> None:
    """Assert deterministic admission rejection for one invalid profile."""
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
                "enabled_execution_options": enabled_execution_options,
            },
        },
        timeout=10,
    )
    assert response.status_code == 422, response.text
    assert _object(response.json(), label="invalid profile response") == {
        "detail": expected_detail
    }


def _wait_for_session_idle(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    timeout: float = 120,
) -> AgentSessionResponse:
    """Wait for idle and return the authoritative session projection."""
    deadline = time.monotonic() + timeout
    last_state: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
        payload = _response_model(response, AgentSessionResponse)
        last_state = payload.run_state
        if last_state == "idle":
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Session did not become idle: {last_state!r}")


def _typed_wait_for_session_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    timeout: float = 120,
) -> AgentSessionResponse:
    """Wait for the authoritative session projection to persist a profile."""
    deadline = time.monotonic() + timeout
    last_profile: tuple[object, object, object] = (None, None, None)
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
        payload = _response_model(response, AgentSessionResponse)
        last_profile = (
            payload.current_model_target_label,
            payload.current_reasoning_effort,
            payload.current_enabled_execution_options,
        )
        if last_profile == (target, effort, enabled_execution_options):
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Session did not persist profile: {last_profile!r}")


def _typed_history(
    server_url: str, token: str, session_id: str
) -> list[ChatEventResponse]:
    """Fetch the current history page."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return decode_profile_history(response.json()).items


def _serialized_history(events: list[ChatEventResponse]) -> str:
    """Serialize opaque event content for product-output evidence."""
    return json.dumps([profile_history_event_wire(event) for event in events])


def _requested_profile(event: ChatEventResponse) -> RequestedProfileObservation:
    """Require the prepared input profile consumed by the journey."""
    profile = InputMessageObservation.model_validate(
        event.payload
    ).requested_inference_profile
    assert profile is not None
    return profile


def _wait_for_tool_result(
    *,
    server_url: str,
    token: str,
    session_id: str,
    call_id: str,
    timeout: float = 120,
) -> ToolResultObservation:
    """Wait until a tool call has produced a persisted result."""
    deadline = time.monotonic() + timeout
    last_kinds: list[object] = []
    while time.monotonic() < deadline:
        events = _typed_history(server_url, token, session_id)
        last_kinds = [event.kind for event in events]
        for event in events:
            if event.kind != "client_tool_result":
                continue
            payload = ToolResultObservation.model_validate(event.payload)
            if payload.call_id == call_id:
                return payload
        time.sleep(0.5)
    raise TimeoutError(f"Tool result was not observed: {call_id}, {last_kinds!r}")


def _input_event(
    events: list[ChatEventResponse], message: str
) -> ChatEventResponse | None:
    """Find a user or agent input event by content."""
    for event in events:
        if event.kind not in {"user_message", "agent_message"}:
            continue
        payload = InputMessageObservation.model_validate(event.payload)
        if payload.content == message:
            return event
    return None


def _typed_wait_for_input_event(
    *,
    server_url: str,
    token: str,
    session_id: str,
    message: str,
    timeout: float = 120,
) -> ChatEventResponse:
    """Wait for a durable input event without event-level run provenance."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = _input_event(_typed_history(server_url, token, session_id), message)
        if event is not None:
            assert "inference_run_summary" not in event.additional_properties
            return event
        time.sleep(0.5)
    raise TimeoutError(f"Input event was not observed: {message!r}")


def _typed_wait_for_turn_provenance(
    *,
    server_url: str,
    token: str,
    session_id: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    display_name: str,
    effective_context_window_tokens: int,
    timeout: float = 120,
) -> TurnMarkerObservation:
    """Wait for a durable turn marker with the exact public provenance."""
    deadline = time.monotonic() + timeout
    last_profiles: list[object] = []
    while time.monotonic() < deadline:
        last_profiles = []
        for event in _typed_history(server_url, token, session_id):
            if event.kind != "turn_marker":
                continue
            payload = TurnMarkerObservation.model_validate(event.payload)
            profile = payload.applied_inference_profile
            if profile is None:
                last_profiles.append(None)
                continue
            last_profiles.append(profile)
            if (
                profile.model_target_label != target
                or profile.reasoning_effort != effort
                or profile.enabled_execution_options != enabled_execution_options
            ):
                continue
            assert profile.model_display_name == display_name
            assert (
                payload.effective_context_window_tokens
                == effective_context_window_tokens
            )
            assert payload.effective_auto_compaction_threshold_tokens == int(
                effective_context_window_tokens * 0.9
            )
            assert "provider" not in (payload.model_extra or {})
            assert "model_selection" not in (payload.model_extra or {})
            assert "credential_kwargs" not in (payload.model_extra or {})
            return payload
        time.sleep(0.5)
    raise TimeoutError(
        f"Turn provenance was not observed: {(target, effort)!r}, {last_profiles!r}"
    )


def _wait_for_mock_models(mock_openai_url: str, *model_ids: str) -> str:
    """Wait until the mock provider journal contains every expected model."""

    def complete_journal() -> str | None:
        response = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
        response.raise_for_status()
        requests_seen = decode_mock_profile_journal(response.json())
        identifiers = {request.body.model for request in requests_seen}
        if all(model_id in identifiers for model_id in model_ids):
            return json.dumps(
                [
                    request.model_dump(mode="json", exclude_unset=True)
                    for request in requests_seen
                ]
            )
        return None

    journal = wait_until(
        complete_journal,
        timeout=120,
        interval=0.5,
        message="Expected model requests were not observed",
    )
    assert journal is not None
    return journal


def _wait_for_mock_model_output_cap(
    *,
    mock_openai_url: str,
    model_id: str,
    max_output_tokens: int,
    timeout: float = 120,
) -> None:
    """Wait until a mock request carries the selected model output cap."""
    deadline = time.monotonic() + timeout
    last_payload: object = None
    while time.monotonic() < deadline:
        response = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
        response.raise_for_status()
        last_payload = response.json()
        for item in decode_mock_profile_journal(last_payload):
            body = item.body
            if body.model != model_id:
                continue
            if body.max_tokens == max_output_tokens:
                return
        time.sleep(0.5)
    raise TimeoutError(
        "Selected model output cap was not observed: "
        f"{(model_id, max_output_tokens)!r}, {last_payload!r}"
    )


def _wait_for_proxy_service_tier(
    *,
    openai_proxy_url: str,
    message: str,
    model_id: str,
    expected_tier: str | None,
    timeout: float = 120,
) -> None:
    """Wait for the matching raw provider request and assert its service tier."""
    deadline = time.monotonic() + timeout
    last_payload: object = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
        )
        response.raise_for_status()
        last_payload = response.json()
        for body in decode_profile_provider_journal(last_payload):
            if body.model != model_id:
                continue
            if message not in body.serialized():
                continue
            if expected_tier is None:
                assert "service_tier" not in body.model_fields_set
            else:
                assert body.service_tier == expected_tier
            return
        time.sleep(0.5)
    raise TimeoutError(
        "Provider request service tier was not observed: "
        f"{(message, model_id, expected_tier)!r}, {last_payload!r}"
    )


def _wait_for_matching_proxy_requests(
    *,
    openai_proxy_url: str,
    message: str,
    model_id: str,
    minimum_count: int,
) -> list[ProfileProviderRequestObservation]:
    """Wait for an authoritative number of matching raw provider requests."""

    def matching_requests() -> list[ProfileProviderRequestObservation] | None:
        response = requests.get(
            f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
        )
        response.raise_for_status()
        matches = [
            body
            for body in decode_profile_provider_journal(response.json())
            if body.model == model_id and message in body.serialized()
        ]
        return matches if len(matches) >= minimum_count else None

    matches = wait_until(
        matching_requests,
        timeout=120,
        interval=0.5,
        message=f"Expected {minimum_count} matching provider requests",
    )
    assert matches is not None
    return matches


def _subagent_tree(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> SubagentTreeResponse:
    """Fetch the public Subagent Tree projection."""
    return _response_model(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}/subagents/tree",
            headers=_headers(token),
            timeout=10,
        ),
        SubagentTreeResponse,
    )


def _find_tree_node(
    nodes: list[SubagentTreeNodeResponse],
    name: str,
) -> SubagentTreeNodeResponse | None:
    """Find a named node in the recursive public Subagent Tree."""
    for node in nodes:
        if node.name == name:
            return node
        child = _find_tree_node(
            node.children or [],
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
) -> SubagentTreeNodeResponse:
    """Wait for a named Subagent Tree node."""
    deadline = time.monotonic() + timeout
    last_tree: SubagentTreeResponse | None = None
    while time.monotonic() < deadline:
        last_tree = _subagent_tree(
            server_url=server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
        )
        node = _find_tree_node(
            last_tree.nodes,
            name,
        )
        if node is not None and node.status == "completed":
            return node
        time.sleep(0.5)
    raise TimeoutError(f"Subagent Tree node did not complete: {name}, {last_tree!r}")


def _tree_names(tree: SubagentTreeResponse) -> set[str]:
    """Collect declared names in a public Subagent Tree."""
    names: set[str] = set()

    def collect(nodes: list[SubagentTreeNodeResponse]) -> None:
        for node in nodes:
            names.add(node.name)
            collect(node.children or [])

    collect(tree.nodes)
    return names


# Raw compatibility adapters are egress boundaries for adjacent, out-of-scope
# E2E modules. The profile journeys above/below use the typed helpers directly.
def _objects(value: object, *, label: str) -> list[dict[str, object]]:
    """Preserve the legacy adjacent-module JSON-list boundary."""
    try:
        return _LEGACY_OBJECT_LIST.validate_python(value)
    except ValidationError as error:
        raise AssertionError(f"{label} is not an object list: {value!r}") from error


def _response_object(response: requests.Response) -> dict[str, object]:
    """Preserve the legacy adjacent-module raw HTTP observation boundary."""
    response.raise_for_status()
    return _object(response.json(), label="HTTP response")


def _history(server_url: str, token: str, session_id: str) -> list[dict[str, object]]:
    """Serialize typed history for existing adjacent-module wire consumers."""
    return [
        profile_history_event_wire(event)
        for event in _typed_history(server_url, token, session_id)
    ]


def _wait_for_session_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    timeout: float = 120,
) -> dict[str, object]:
    """Serialize authoritative typed Session evidence for legacy callers."""
    return _typed_wait_for_session_profile(
        server_url=server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target=target,
        effort=effort,
        enabled_execution_options=enabled_execution_options,
        timeout=timeout,
    ).model_dump(mode="json", exclude_unset=True)


def _wait_for_input_event(
    *,
    server_url: str,
    token: str,
    session_id: str,
    message: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Serialize a selected typed input event for legacy wire callers."""
    return profile_history_event_wire(
        _typed_wait_for_input_event(
            server_url=server_url,
            token=token,
            session_id=session_id,
            message=message,
            timeout=timeout,
        )
    )


def _wait_for_turn_provenance(
    *,
    server_url: str,
    token: str,
    session_id: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    display_name: str,
    effective_context_window_tokens: int,
    timeout: float = 120,
) -> dict[str, object]:
    """Serialize typed turn evidence for adjacent existing wire assertions."""
    return _typed_wait_for_turn_provenance(
        server_url=server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort=effort,
        enabled_execution_options=enabled_execution_options,
        display_name=display_name,
        effective_context_window_tokens=effective_context_window_tokens,
        timeout=timeout,
    ).model_dump(mode="json", exclude_unset=True)


# Shared public-path helper used by provider-tool lifecycle E2E coverage.
setup_profile_agent = _setup_profile_agent


@pytest.fixture(scope="class")
def profile_agent_setup(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    azents_engine_worker_container: object,
) -> ProfileAgentSetup:
    """Prepare one immutable Agent/runtime shared by independent test Sessions."""
    del azents_engine_worker_container
    public_api_client = azentspublicclient.ApiClient(
        configuration=azentspublicclient.Configuration(host=azents_public_server_url)
    )
    admin_api_client = azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=system_bootstrap_evidence.access_token,
        )
    )
    # Persist real validated-source authority before any priced model call.
    # SDK/install price maps and direct database seeding are not fixture inputs.
    ModelCatalogV1Api(admin_api_client).model_catalog_v1_refresh_system_model_catalog(
        provider=SystemCatalogProvider.OPENAI,
        _request_timeout=20,
    )
    return _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        speed_targets=True,
    )


class TestPerPromptInferenceProfile:
    """Per-prompt routing and provenance E2E coverage."""

    def test_target_effort_resolution_and_safe_failure(
        self,
        azents_public_server_url: str,
        mock_openai_url: str,
        openai_proxy_url: str,
        profile_agent_setup: ProfileAgentSetup,
    ) -> None:
        """Resolve distinct targets and expose an unsupported effort safely."""
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        requests.delete(
            f"{mock_openai_url}/v1/_requests", timeout=10
        ).raise_for_status()
        requests.delete(
            f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
        ).raise_for_status()

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
            target="Quality",
            effort="xhigh",
            enabled_execution_options=["fast"],
        )
        quality_event = _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
        )
        assert _requested_profile(quality_event).model_dump(exclude_unset=True) == {
            "model_target_label": "Quality",
            "reasoning_effort": "xhigh",
            "enabled_execution_options": ["fast"],
        }
        _typed_wait_for_turn_provenance(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            target="Quality",
            effort="xhigh",
            enabled_execution_options=["fast"],
            display_name="GPT 5.5 Deterministic",
            effective_context_window_tokens=32_000,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_QUALITY_STANDARD_MESSAGE,
            target="Quality",
            effort="high",
            enabled_execution_options=[],
        )
        standard_event = _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_QUALITY_STANDARD_MESSAGE,
        )
        assert _requested_profile(standard_event).model_dump(exclude_unset=True) == {
            "model_target_label": "Quality",
            "reasoning_effort": "high",
            "enabled_execution_options": [],
        }
        _typed_wait_for_turn_provenance(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            target="Quality",
            effort="high",
            enabled_execution_options=[],
            display_name="GPT 5.5 Deterministic",
            effective_context_window_tokens=32_000,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_FAST_MESSAGE,
            target="Fast",
            effort=None,
            enabled_execution_options=[],
        )
        fast_event = _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_FAST_MESSAGE,
        )
        assert _requested_profile(fast_event).model_dump(exclude_unset=True) == {
            "model_target_label": "Fast",
            "reasoning_effort": None,
            "enabled_execution_options": [],
        }
        _typed_wait_for_turn_provenance(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            target="Fast",
            effort=None,
            enabled_execution_options=[],
            display_name="GPT 5.5 Mini Deterministic",
            effective_context_window_tokens=32_000,
        )

        _wait_for_mock_models(mock_openai_url, "gpt-5.5", "gpt-5.5-mini")
        _wait_for_mock_model_output_cap(
            mock_openai_url=mock_openai_url,
            model_id="gpt-5.5",
            max_output_tokens=12_000,
        )
        _wait_for_mock_model_output_cap(
            mock_openai_url=mock_openai_url,
            model_id="gpt-5.5-mini",
            max_output_tokens=4_000,
        )
        _wait_for_proxy_service_tier(
            openai_proxy_url=openai_proxy_url,
            message=_QUALITY_MESSAGE,
            model_id="gpt-5.5",
            expected_tier="priority",
        )
        _wait_for_proxy_service_tier(
            openai_proxy_url=openai_proxy_url,
            message=_QUALITY_STANDARD_MESSAGE,
            model_id="gpt-5.5",
            expected_tier="default",
        )
        _wait_for_proxy_service_tier(
            openai_proxy_url=openai_proxy_url,
            message=_FAST_MESSAGE,
            model_id="gpt-5.5-mini",
            expected_tier=None,
        )

        unsupported_message = "Unsupported effort must fail safely"
        _write_invalid_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=unsupported_message,
            target="Fast",
            effort="high",
            enabled_execution_options=[],
            expected_detail="Reasoning effort is not supported by model target",
        )
        assert (
            _input_event(
                _typed_history(azents_public_server_url, token, session_id),
                unsupported_message,
            )
            is None
        )
        unsupported_option_message = "Unsupported execution option must fail safely"
        _write_invalid_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=unsupported_option_message,
            target="Fast",
            effort=None,
            enabled_execution_options=["fast"],
            expected_detail="Enabled execution option is not supported by the model.",
        )
        assert (
            _input_event(
                _typed_history(azents_public_server_url, token, session_id),
                unsupported_option_message,
            )
            is None
        )
        session = _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        assert session.current_model_target_label == "Fast"
        assert session.current_reasoning_effort is None

    def test_retry_preserves_prepared_fast_option(
        self,
        azents_public_server_url: str,
        mock_openai_url: str,
        openai_proxy_url: str,
        profile_agent_setup: ProfileAgentSetup,
    ) -> None:
        """Keep Fast enabled across deterministic provider retry attempts."""
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        requests.delete(
            f"{mock_openai_url}/v1/_requests", timeout=10
        ).raise_for_status()
        requests.delete(
            f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
        ).raise_for_status()

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_FAST_RETRY_MESSAGE,
            target="Quality",
            effort="high",
            enabled_execution_options=["fast"],
        )
        _wait_for_session_idle(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        requests_ = _wait_for_matching_proxy_requests(
            openai_proxy_url=openai_proxy_url,
            message=_FAST_RETRY_MESSAGE,
            model_id="gpt-5.5",
            minimum_count=2,
        )
        assert len(requests_) >= 2
        for body in requests_:
            assert body.model == "gpt-5.5"
            assert body.service_tier == "priority"

    @pytest.mark.parametrize(
        ("target", "model_id", "display_name", "scenario", "options", "tier", "priced"),
        [
            (
                "Astra",
                "gpt-6-astra",
                "GPT 6 Astra Deterministic",
                "served-ultrafast",
                ["ultrafast"],
                "ultrafast",
                False,
            ),
            (
                "Sol",
                "gpt-5.6-sol",
                "GPT 5.6 Sol Deterministic",
                "served-ultrafast",
                ["ultrafast"],
                "ultrafast",
                False,
            ),
            (
                "Astra",
                "gpt-6-astra",
                "GPT 6 Astra Deterministic",
                "missing-tier",
                ["ultrafast"],
                "ultrafast",
                False,
            ),
            (
                "Quality",
                "gpt-5.5",
                "GPT 5.5 Deterministic",
                "served-default",
                [],
                "default",
                True,
            ),
            (
                "Quality",
                "gpt-5.5",
                "GPT 5.5 Deterministic",
                "served-priority",
                ["fast"],
                "priority",
                False,
            ),
        ],
    )
    def test_explicit_speed_submit_preserves_output_and_actual_tier_cost(
        self,
        azents_public_server_url: str,
        openai_proxy_url: str,
        profile_agent_setup: ProfileAgentSetup,
        target: str,
        model_id: str,
        display_name: str,
        scenario: str,
        options: list[str],
        tier: str,
        priced: bool,
    ) -> None:
        """Keep successful output and tokens when actual premium cost is unknown."""
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url, token=token, agent_id=agent_id
        )
        message = f"Ultrafast E2E {scenario} {unique()}"
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            target=target,
            effort="high",
            enabled_execution_options=options,
        )
        event = _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=message,
        )
        assert _requested_profile(event).model_dump(exclude_unset=True) == {
            "model_target_label": target,
            "reasoning_effort": "high",
            "enabled_execution_options": options,
        }
        _wait_for_proxy_service_tier(
            openai_proxy_url=openai_proxy_url,
            message=message,
            model_id=model_id,
            expected_tier=tier,
        )
        marker = _typed_wait_for_turn_provenance(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            target=target,
            effort="high",
            enabled_execution_options=options,
            display_name=display_name,
            effective_context_window_tokens=32_000,
        )
        usage = marker.usage
        assert usage is not None
        assert usage.prompt_tokens == 1
        assert usage.completion_tokens == 1
        if priced:
            assert usage.cost_usd is not None
            assert usage.cost_usd > 0
        else:
            # REST history omits null payload fields; unavailable is not zero.
            assert usage.cost_usd is None
        history = _typed_history(azents_public_server_url, token, session_id)
        assert f"INFERENCE_PROFILE_COMPLETED {scenario}" in _serialized_history(history)
        assert not any(item.kind == "system_error" for item in history)
        if target == "Astra" and scenario == "served-ultrafast":

            def auxiliary_title_request() -> ProfileProviderRequestObservation | None:
                response = requests.get(
                    f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
                )
                response.raise_for_status()
                for body in decode_profile_provider_journal(response.json()):
                    serialized = body.serialized()
                    if (
                        message in serialized
                        and "Create a brief title from the request" in serialized
                    ):
                        return body
                return None

            auxiliary = wait_until(
                auxiliary_title_request,
                timeout=30,
                interval=0.2,
                message="Independent title request was not observed",
            )
            assert auxiliary is not None
            assert auxiliary.service_tier not in {"priority", "ultrafast"}

    @pytest.mark.parametrize("scenario", ["retry", "rejected"])
    def test_ultrafast_provider_errors_never_downgrade(
        self,
        azents_public_server_url: str,
        openai_proxy_url: str,
        profile_agent_setup: ProfileAgentSetup,
        scenario: str,
    ) -> None:
        """Retry transient errors unchanged and expose entitlement rejection."""
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url, token=token, agent_id=agent_id
        )
        message = f"Ultrafast E2E {scenario} {unique()}"
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            target="Astra",
            effort="high",
            enabled_execution_options=["ultrafast"],
        )
        _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=message,
        )
        matches = _wait_for_matching_proxy_requests(
            openai_proxy_url=openai_proxy_url,
            message=message,
            model_id="gpt-6-astra",
            minimum_count=2 if scenario == "retry" else 1,
        )
        for body in matches:
            assert body.service_tier == "ultrafast"
        if scenario == "retry":
            _typed_wait_for_turn_provenance(
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
                target="Astra",
                effort="high",
                enabled_execution_options=["ultrafast"],
                display_name="GPT 6 Astra Deterministic",
                effective_context_window_tokens=32_000,
            )
        else:

            def failed_history() -> list[ChatEventResponse] | None:
                history = _typed_history(azents_public_server_url, token, session_id)
                return (
                    history
                    if any(item.kind == "system_error" for item in history)
                    else None
                )

            history = wait_until(
                failed_history,
                timeout=120,
                interval=0.5,
                message="Provider entitlement rejection did not become visible",
            )
            assert history is not None
            assert "INFERENCE_PROFILE_COMPLETED" not in _serialized_history(history)
        journal = decode_profile_provider_journal(
            requests.get(
                f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
            ).json(),
        )
        matching = [
            body
            for body in journal
            if message in body.serialized()
            and "Create a brief title from the request" not in body.serialized()
        ]
        assert matching
        assert all(body.model == "gpt-6-astra" for body in matching)
        assert all(body.service_tier == "ultrafast" for body in matching)

    def test_prepared_ultrafast_is_immutable_while_standard_input_queues(
        self,
        azents_public_server_url: str,
        openai_proxy_url: str,
        profile_agent_setup: ProfileAgentSetup,
        ordinary_model_stream_worker: object,
    ) -> None:
        """Use an explicit provider barrier instead of racing profile preparation."""
        del ordinary_model_stream_worker
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url, token=token, agent_id=agent_id
        )
        barrier_url = f"{openai_proxy_url}/v1/_inference_profile_barrier"
        requests.post(barrier_url, timeout=10).raise_for_status()
        prepared_message = f"Ultrafast E2E prepared {unique()}"
        queued_message = f"Ultrafast E2E queued {unique()}"
        try:
            _write_profile(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
                message=prepared_message,
                target="Astra",
                effort="high",
                enabled_execution_options=["ultrafast"],
            )
            wait_until(
                lambda: (
                    _response_model(
                        requests.get(barrier_url, timeout=10), ProfileBarrierObservation
                    ).reached
                ),
                timeout=30,
                interval=0.1,
                message="Prepared provider request did not reach the barrier",
            )
            _write_profile(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
                message=queued_message,
                target="Astra",
                effort="high",
                enabled_execution_options=[],
            )
            _wait_for_proxy_service_tier(
                openai_proxy_url=openai_proxy_url,
                message=prepared_message,
                model_id="gpt-6-astra",
                expected_tier="ultrafast",
            )
        finally:
            requests.post(f"{barrier_url}/release", timeout=10).raise_for_status()
        for options in (["ultrafast"], []):
            _typed_wait_for_turn_provenance(
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
                target="Astra",
                effort="high",
                enabled_execution_options=options,
                display_name="GPT 6 Astra Deterministic",
                effective_context_window_tokens=32_000,
            )
        _wait_for_proxy_service_tier(
            openai_proxy_url=openai_proxy_url,
            message=queued_message,
            model_id="gpt-6-astra",
            expected_tier="default",
        )

    def test_subagent_spawn_override_continuation(
        self,
        azents_public_server_url: str,
        profile_agent_setup: ProfileAgentSetup,
    ) -> None:
        """Persist a spawn override and reuse it for a follow-up run."""
        token, agent_id, _ = profile_agent_setup
        root_session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=_SPAWN_OVERRIDE_MESSAGE,
            target="Quality",
            effort="high",
            enabled_execution_options=[],
        )
        child = _wait_for_tree_node(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            root_session_id=root_session_id,
            name="profile_child",
        )
        child_session_id = child.agent_session_id
        if not isinstance(child_session_id, str):
            raise AssertionError(f"Child node has no AgentSession ID: {child!r}")
        _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=child_session_id,
            message=_SPAWN_OVERRIDE_TASK,
        )
        _typed_wait_for_session_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=child_session_id,
            target="Fast",
            effort=None,
            enabled_execution_options=[],
        )
        _typed_wait_for_input_event(
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
            enabled_execution_options=[],
        )
        _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=child_session_id,
            message=_FOLLOWUP_TASK,
        )
        _typed_wait_for_session_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=child_session_id,
            target="Fast",
            effort=None,
            enabled_execution_options=[],
        )

    @pytest.mark.parametrize(
        (
            "message",
            "child_name",
            "task",
            "call_id",
            "expected_effort",
        ),
        [
            (
                _INHERITED_DISABLED_TARGET_MESSAGE,
                "inherited_disabled",
                _INHERITED_DISABLED_TARGET_TASK,
                "call_subagent_inherit_disabled_target",
                "high",
            ),
            (
                _EFFORT_ONLY_DISABLED_TARGET_MESSAGE,
                "effort_only_disabled",
                _EFFORT_ONLY_DISABLED_TARGET_TASK,
                "call_subagent_effort_only_disabled_target",
                "low",
            ),
        ],
    )
    def test_disabled_target_remains_available_through_inheritance(
        self,
        azents_public_server_url: str,
        profile_agent_setup: ProfileAgentSetup,
        message: str,
        child_name: str,
        task: str,
        call_id: str,
        expected_effort: str,
    ) -> None:
        """Inherit a disabled parent target with or without an effort override."""
        token, agent_id, _ = profile_agent_setup
        root_session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=root_session_id,
            message=message,
            target="Quality",
            effort="high",
            enabled_execution_options=[],
        )
        tool_result = _wait_for_tool_result(
            server_url=azents_public_server_url,
            token=token,
            session_id=root_session_id,
            call_id=call_id,
        )
        assert tool_result.status == "completed", tool_result
        child = _wait_for_tree_node(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            root_session_id=root_session_id,
            name=child_name,
        )
        child_session_id = child.agent_session_id
        if not isinstance(child_session_id, str):
            raise AssertionError(f"Child node has no AgentSession ID: {child!r}")
        _typed_wait_for_input_event(
            server_url=azents_public_server_url,
            token=token,
            session_id=child_session_id,
            message=task,
        )
        _typed_wait_for_session_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=child_session_id,
            target="Quality",
            effort=expected_effort,
            enabled_execution_options=[],
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
            (
                _DISABLED_TARGET_REJECTION_MESSAGE,
                "invalid_disabled_target",
                "call_subagent_reject_disabled_target",
            ),
        ],
    )
    def test_subagent_spawn_override_rejection_is_atomic(
        self,
        azents_public_server_url: str,
        profile_agent_setup: ProfileAgentSetup,
        message: str,
        rejected_name: str,
        call_id: str,
    ) -> None:
        """Reject an invalid override without creating a child."""
        token, agent_id, _ = profile_agent_setup
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            target="Quality",
            effort="high",
            enabled_execution_options=[],
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


class TestModelSupportContract:
    """Exercise active support and saved pricing through ordinary product APIs."""

    def test_active_support_refresh_preserves_saved_dispatch_pricing(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        openai_proxy_url: str,
    ) -> None:
        """Recompile support while preserving identity, settings and saved prices."""
        catalog_api = ModelCatalogV1Api(admin_api_client)

        def refresh_source(variant: str) -> None:
            control = requests.post(
                f"{openai_proxy_url}/inference-profile/catalog-source",
                json={"variant": variant},
                timeout=10,
            )
            control.raise_for_status()
            assert _response_model(control, CatalogSourceObservation).variant == variant
            refreshed = catalog_api.model_catalog_v1_refresh_system_model_catalog(
                provider=SystemCatalogProvider.OPENAI,
                _request_timeout=20,
            )
            assert refreshed.last_success_at is not None
            assert refreshed.status == "succeeded"

        def primary_selection(
            options: list[SelectableModelOptionResponse]
            | list[SelectableModelOption]
            | None,
        ) -> AgentModelSelection:
            assert options is not None
            quality = next(option for option in options if option.label == "Quality")
            return quality.candidates[0].model_selection

        def contract(capabilities: ModelCapabilities | None) -> ModelCapabilities:
            assert capabilities is not None
            assert capabilities.capability_schema_version == 3
            return capabilities

        def effort_supported(descriptor: ModelCapabilities, level: str) -> bool:
            reasoning = descriptor.reasoning
            assert reasoning is not None
            return reasoning.supported is True and any(
                item.value == level for item in reasoning.effort_levels or []
            )

        try:
            refresh_source("baseline")
            uniq = unique()
            token, _, _ = authenticate_user(
                public_api_client,
                admin_api_client,
                email=f"model-support-contract-{uniq}@example.com",
            )
            handle = f"model-support-contract-{uniq}"
            WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
                CreateWorkspaceRequest(
                    workspace_name=f"Model Support Contract {uniq}",
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
                    # An ordinary integration exercises the real system projection,
                    # not the historical deterministic-listing snapshot shortcut.
                    name=f"Model support source contract {uniq}",
                    secrets=Secrets(ApiKeySecrets(api_key="sk-model-support-contract")),
                ),
                _headers=_headers(token),
            )
            catalog_url = (
                f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
                f"{handle}/llm-provider-integrations/{integration.id}/catalog-entries"
            )

            def entries() -> dict[str, ModelCatalogEntryResponse]:
                payload = _response_model(
                    requests.get(catalog_url, headers=_headers(token), timeout=10),
                    ModelCatalogEntryListResponse,
                )
                assert payload.catalog_scope == "system"
                return {
                    entry.provider_model_identifier: entry for entry in payload.entries
                }

            baseline_entry = entries()["gpt-5.5"]
            baseline_contract = contract(baseline_entry.normalized_capabilities)
            assert effort_supported(baseline_contract, "max")
            assert effort_supported(baseline_contract, "xhigh")
            selection_input = {
                "llm_provider_integration_id": integration.id,
                "model_identifier": "gpt-5.5",
            }
            option_inputs = [
                {
                    "label": "Quality",
                    "candidates": [
                        {
                            "model_selection": selection_input,
                            "settings": {
                                "context_window_tokens": 32_000,
                                "max_output_tokens": 4_000,
                                "builtin_tools": [],
                            },
                        }
                    ],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                }
            ]
            workspace_url = (
                f"{azents_public_server_url}/workspace-model-settings/v1/"
                f"workspaces/{handle}"
            )
            workspace_settings = _response_model(
                requests.put(
                    workspace_url,
                    headers=_headers(token),
                    json={
                        "default_selectable_model_options": option_inputs,
                        "default_main_model_label": "Quality",
                        "default_lightweight_model_label": "Quality",
                    },
                    timeout=10,
                ),
                WorkspaceModelSettingsResponse,
            )
            workspace_selection = primary_selection(
                workspace_settings.default_selectable_model_options
            )
            assert contract(workspace_selection.normalized_capabilities) == (
                baseline_contract
            )
            runtime_profile_id = create_workspace_runtime_profile(
                public_api_client,
                token=token,
                workspace_handle=handle,
                provider_id="system-docker",
            )
            created = _response_model(
                requests.post(
                    f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
                    headers=_headers(token),
                    # Omitting model options copies the saved Workspace contract.
                    json={
                        "name": "Source-backed support Agent",
                        "type": "public",
                        "runtime_profile_id": runtime_profile_id,
                    },
                    timeout=10,
                ),
                AgentResponse,
            )
            agent_id = created.id
            agent_url = (
                f"{azents_public_server_url}/agent/v1/workspaces/"
                f"{handle}/agents/{agent_id}"
            )
            agent_selection = primary_selection(created.selectable_model_options)
            assert agent_selection.pricing is not None
            assert agent_selection.pricing == workspace_selection.pricing
            assert contract(agent_selection.normalized_capabilities) == (
                baseline_contract
            )
            display_name = agent_selection.model_display_name
            assert display_name is not None
            start_and_wait_for_agent_runtime(
                public_api_client,
                token=token,
                workspace_handle=handle,
                agent_id=agent_id,
            )

            def saved_selections_unchanged(
                expected_capabilities: ModelCapabilities | None,
            ) -> None:
                saved_agent = _response_model(
                    requests.get(agent_url, headers=_headers(token), timeout=10),
                    AgentResponse,
                )
                saved_workspace = _response_model(
                    requests.get(workspace_url, headers=_headers(token), timeout=10),
                    WorkspaceModelSettingsResponse,
                )
                for options, original_options, original_selection in (
                    (
                        saved_agent.selectable_model_options,
                        created.selectable_model_options,
                        agent_selection,
                    ),
                    (
                        saved_workspace.default_selectable_model_options,
                        workspace_settings.default_selectable_model_options,
                        workspace_selection,
                    ),
                ):
                    assert options is not None and original_options is not None
                    assert [option.label for option in options] == [
                        option.label for option in original_options
                    ]
                    assert [
                        candidate.settings
                        for option in options
                        for candidate in option.candidates
                    ] == [
                        candidate.settings
                        for option in original_options
                        for candidate in option.candidates
                    ]
                    selected = primary_selection(options)
                    # Active projection replaces metadata, not the saved selection.
                    metadata_fields = {
                        "normalized_capabilities",
                        "supported_execution_options",
                        "source_metadata",
                    }
                    assert selected.model_dump(exclude=metadata_fields) == (
                        original_selection.model_dump(exclude=metadata_fields)
                    )
                    active = contract(selected.normalized_capabilities)
                    if expected_capabilities is not None:
                        assert active == expected_capabilities
                    else:
                        assert not effort_supported(active, "max")
                        assert not effort_supported(active, "xhigh")

            def dispatch(effort: str, expected_cost: float | None) -> None:
                # Independent Sessions keep provenance polling specific to this turn.
                session_id = _create_profile_session(
                    server_url=azents_public_server_url, token=token, agent_id=agent_id
                )
                message = f"Ultrafast E2E served-default saved-support {unique()}"
                _write_profile(
                    server_url=azents_public_server_url,
                    token=token,
                    agent_id=agent_id,
                    session_id=session_id,
                    message=message,
                    target="Quality",
                    effort=effort,
                    enabled_execution_options=[],
                )

                def matching_main_requests() -> (
                    list[ProfileProviderRequestObservation] | None
                ):
                    response = requests.get(
                        f"{openai_proxy_url}/v1/_image_generation_requests",
                        timeout=10,
                    )
                    response.raise_for_status()
                    matches = [
                        body
                        for body in decode_profile_provider_journal(response.json())
                        if body.model == "gpt-5.5"
                        and message in body.serialized()
                        and not is_inference_profile_title_request(
                            body.model_dump(mode="json", exclude_unset=True)
                        )
                    ]
                    # Count only main calls inside the poll: title may arrive first.
                    return matches if matches else None

                raw_requests = wait_until(
                    matching_main_requests,
                    timeout=120,
                    interval=0.5,
                    message="Saved-contract main provider request was not observed",
                )
                assert raw_requests is not None
                reasoning = raw_requests[0].reasoning
                assert reasoning is not None and reasoning.effort == effort
                assert raw_requests[0].max_output_tokens == 4_000
                marker = _typed_wait_for_turn_provenance(
                    server_url=azents_public_server_url,
                    token=token,
                    session_id=session_id,
                    target="Quality",
                    effort=effort,
                    enabled_execution_options=[],
                    display_name=display_name,
                    effective_context_window_tokens=32_000,
                )
                usage = marker.usage
                assert usage is not None
                assert usage.prompt_tokens == 1
                assert usage.completion_tokens == 1
                if expected_cost is None:
                    # Unknown exact-model cost remains unavailable.
                    assert usage.cost_usd is None
                else:
                    assert usage.cost_usd == pytest.approx(
                        expected_cost, rel=1e-12, abs=1e-12
                    )
                _wait_for_session_idle(
                    server_url=azents_public_server_url,
                    token=token,
                    agent_id=agent_id,
                    session_id=session_id,
                )
                assert (
                    "INFERENCE_PROFILE_COMPLETED served-default"
                    in _serialized_history(
                        _typed_history(azents_public_server_url, token, session_id)
                    )
                )

            def reject_max(expected_detail: str) -> None:
                rejected_session = _create_profile_session(
                    server_url=azents_public_server_url, token=token, agent_id=agent_id
                )
                rejected_message = f"Unsupported current max {unique()}"
                _write_invalid_profile(
                    server_url=azents_public_server_url,
                    token=token,
                    agent_id=agent_id,
                    session_id=rejected_session,
                    message=rejected_message,
                    target="Quality",
                    effort="max",
                    enabled_execution_options=[],
                    expected_detail=expected_detail,
                )
                assert (
                    _input_event(
                        _typed_history(
                            azents_public_server_url, token, rejected_session
                        ),
                        rejected_message,
                    )
                    is None
                )

            dispatch("max", 0.000003)
            refresh_source("refreshed")
            refreshed_contract = contract(entries()["gpt-5.5"].normalized_capabilities)
            assert not effort_supported(refreshed_contract, "max")
            assert effort_supported(refreshed_contract, "xhigh")
            saved_selections_unchanged(refreshed_contract)
            # Normal saves without model selections preserve embedded prices.
            _response_model(
                requests.patch(
                    agent_url,
                    headers=_headers(token),
                    json={"description": "Keep the saved model support contract"},
                    timeout=10,
                ),
                AgentResponse,
            )
            _response_model(
                requests.put(
                    workspace_url,
                    headers=_headers(token),
                    json={"default_main_model_label": "Quality"},
                    timeout=10,
                ),
                WorkspaceModelSettingsResponse,
            )
            saved_selections_unchanged(refreshed_contract)
            reject_max("Reasoning effort is not supported by model target")
            dispatch("xhigh", 0.000003)

            refresh_source("missing-model")
            assert "gpt-5.5" not in entries()
            saved_selections_unchanged(None)
            # Missing current evidence cannot authorize a new dispatch.
            reject_max("Active model metadata is unavailable: exact_entry_unavailable.")

            refresh_source("refreshed")
            reselected_workspace = _response_model(
                requests.put(
                    workspace_url,
                    headers=_headers(token),
                    json={"default_selectable_model_options": option_inputs},
                    timeout=10,
                ),
                WorkspaceModelSettingsResponse,
            )
            reselected_agent = _response_model(
                requests.patch(
                    agent_url,
                    headers=_headers(token),
                    json={"selectable_model_options": option_inputs},
                    timeout=10,
                ),
                AgentResponse,
            )
            for options in (
                reselected_workspace.default_selectable_model_options,
                reselected_agent.selectable_model_options,
            ):
                selected = primary_selection(options)
                assert contract(selected.normalized_capabilities) == refreshed_contract
                assert selected.pricing is not None
                assert selected.pricing != agent_selection.pricing
            reject_max("Reasoning effort is not supported by model target")
            dispatch("xhigh", 0.000007)
        finally:
            # This local source fixture is global to the serial required-suite lane.
            refresh_source("baseline")
