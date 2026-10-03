"""Credential-free Historical Memory preparation and live lookup journey.

The explicit-time testenv sampler executes ordinary admission, provider summary,
and publication services. Scheduler/Job Runtime dispatch and exact interleavings
have separate production integration coverage; the sampler does not prove them.
"""

import datetime
import json
from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.historical_memory_response import (
    HistoricalMemoryResponse,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets

from support.observations import (
    HistoricalSampleObservation,
    decode_chat_write,
    decode_historical_memories,
    decode_historical_memory,
    decode_history_page,
    decode_proxy_journal,
    decode_session,
)
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
    wait_until,
)

_COMPLETED = "HISTORICAL_MEMORY_E2E_TURN_COMPLETED"


class _Setup(NamedTuple):
    token: str
    handle: str
    agent_id: str


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup(
    public_client: azentspublicclient.ApiClient,
    admin_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _Setup:
    """Create a Runtime-free Agent and model integration through product APIs."""
    suffix = unique()
    token = authenticate_user(public_client, admin_client).access_token
    handle = f"historical-memory-{suffix}"
    WorkspaceV1Api(public_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name="Historical Memory E2E",
            workspace_handle=handle,
            owner_name="Owner",
        ),
        _headers=_headers(token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-historical-memory-fixture")),
        ),
        _headers=_headers(token),
    )
    selection = model_selection_from_first_candidate(
        server_url, token, handle, integration.id
    )
    agent = AgentV1Api(public_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name="Historical Memory E2E",
            type=AgentType.PUBLIC,
            selectable_model_options=single_candidate_model_options(selection),
            main_model_label="default",
            lightweight_model_label="default",
            runtime_profile_id=None,
            tool_search_enabled=False,
        ),
        _headers=_headers(token),
    )
    assert agent.runtime_capability.value == "none"
    return _Setup(token, handle, agent.id)


def _history(
    server_url: str, setup: _Setup, session_id: str
) -> list[ChatEventResponse]:
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(setup.token),
        params={"limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    return decode_history_page(response.json()).items


def _wait_idle(server_url: str, setup: _Setup, session_id: str) -> AgentSessionResponse:
    """Observe durable assistant output and authoritative idle Session state."""

    def finished() -> AgentSessionResponse | None:
        response = requests.get(
            f"{server_url}/chat/v1/agents/{setup.agent_id}/sessions/{session_id}",
            headers=_headers(setup.token),
            timeout=10,
        )
        response.raise_for_status()
        session = decode_session(response.json())
        if session.run_state != "idle":
            return None
        if not any(
            event.kind == "assistant_message" and _COMPLETED in event.model_dump_json()
            for event in _history(server_url, setup, session_id)
        ):
            return None
        return session

    result = wait_until(
        finished,
        timeout=120,
        interval=0.2,
        message="Historical Memory foreground turn did not complete",
    )
    assert result is not None
    return result


def _create_session(server_url: str, setup: _Setup, *, scope: str, message: str) -> str:
    """Create source/consumer lifecycle through the ordinary first input route."""
    kind = "user-sessions" if scope == "user" else "sessions"
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/{kind}/messages",
        headers=_headers(setup.token),
        json={
            "client_request_id": f"historical-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            "existing_project_paths": [],
            "setup_actions": [],
        },
        timeout=15,
    )
    response.raise_for_status()
    session_id = decode_chat_write(response.json()).session_id
    _wait_idle(server_url, setup, session_id)
    return session_id


def _sample(
    admin_url: str, setup: _Setup, now: datetime.datetime
) -> HistoricalSampleObservation:
    """Advance domain sampling only, never product rows or execution clocks."""
    response = requests.post(
        f"{admin_url}/scheduler/v1/historical-memory/sample",
        json={"agent_id": setup.agent_id, "now": now.isoformat()},
        timeout=125,
    )
    response.raise_for_status()
    return HistoricalSampleObservation.model_validate(response.json())


def _settings(
    server_url: str, setup: _Setup, scope: str
) -> list[HistoricalMemoryResponse]:
    response = requests.get(
        f"{server_url}/agent/v1/workspaces/{setup.handle}/agents/{setup.agent_id}/historical-memories",
        headers=_headers(setup.token),
        params={"scope": scope},
        timeout=10,
    )
    response.raise_for_status()
    return decode_historical_memories(response.json()).items


def _inspect(
    server_url: str, setup: _Setup, session_id: str, *, operation: str, path: str
) -> str:
    """Exercise actual model-selected generic read/glob/grep tools."""
    before = {event.id for event in _history(server_url, setup, session_id)}
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers=_headers(setup.token),
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"historical-{unique()}",
            "message": "Historical Memory E2E inspect "
            + json.dumps({"operation": operation, "path": path, "nonce": unique()}),
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    decode_chat_write(response.json())

    def result() -> str | None:
        events = [
            event
            for event in _history(server_url, setup, session_id)
            if event.id not in before
        ]
        if any(
            event.kind == "assistant_message" and _COMPLETED in event.model_dump_json()
            for event in events
        ):
            outputs = [
                event.model_dump_json()
                for event in events
                if event.kind == "client_tool_result"
            ]
            if outputs:
                return "\n".join(outputs)
        return None

    output = wait_until(
        result,
        timeout=120,
        interval=0.2,
        message="Historical VFS Tool result was not persisted",
    )
    assert output is not None
    _wait_idle(server_url, setup, session_id)
    return output


def test_historical_preparation_snapshot_runtime_free_vfs_and_lifecycle(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    openai_proxy_url: str,
) -> None:
    """Prepared sources keep settings/lookup without automatic source packing."""
    setup = _setup(public_api_client, admin_api_client, azents_public_server_url)
    source = _create_session(
        azents_public_server_url,
        setup,
        scope="team",
        message=(
            "Historical Memory E2E source: user corrected red proposal to blue. "
            "Local check passed; rollout unfinished; delivery unverified."
        ),
    )
    personal = _create_session(
        azents_public_server_url,
        setup,
        scope="user",
        message="Historical Memory E2E personal: preserve my private blue preference.",
    )
    sampled_at = datetime.datetime.now(datetime.UTC)
    early = _sample(
        azents_admin_server_url, setup, sampled_at + datetime.timedelta(hours=1)
    )
    assert early.admitted == 0
    assert early.attempted == 0
    prepared = _sample(
        azents_admin_server_url, setup, sampled_at + datetime.timedelta(hours=7)
    )
    # Agent creation also creates one empty Team-primary root through product APIs.
    assert prepared.admitted == 3
    assert prepared.prepared == 2
    assert prepared.failed == 0
    team_rows = _settings(azents_public_server_url, setup, "team")
    personal_rows = _settings(azents_public_server_url, setup, "user")
    assert {row.source_session_id for row in team_rows} == {source}
    assert {row.source_session_id for row in personal_rows} == {personal}
    assert "User correction" in team_rows[0].summary
    assert "not a production deployment" in team_rows[0].summary
    detail_response = requests.get(
        f"{azents_public_server_url}/agent/v1/workspaces/{setup.handle}/agents/{setup.agent_id}/historical-memories/{source}",
        headers=_headers(setup.token),
        timeout=10,
    )
    detail_response.raise_for_status()
    detail = decode_historical_memory(detail_response.json())
    assert source in detail.source_path
    consumer_marker = f"Historical Memory E2E continue {unique()}"
    consumer = _create_session(
        azents_public_server_url, setup, scope="team", message=consumer_marker
    )
    journal = decode_proxy_journal(
        requests.get(
            f"{openai_proxy_url}/v1/_image_generation_requests", timeout=10
        ).json()
    )
    foreground = [
        request
        for request in journal
        if consumer_marker in json.dumps(request.input) and request.tools is not None
    ]
    assert foreground
    captured = foreground[-1].model_dump_json(exclude_unset=True)
    # Stage 1 settings/inventory remain available, but no unit overview has been
    # authored by this fixture. A boundary must not pack raw source summaries.
    assert f"azents://memory/historical/team/{source}/summary.md" not in captured
    assert f"azents://memory/historical/user/{personal}/summary.md" not in captured
    tools = foreground[-1].tools
    assert tools is not None
    assert all(
        name not in {tool.name for tool in tools}
        for name in (
            "get_memory",
            "list_memories",
            "search_memories",
            "search_sessions",
            "read_session_history",
            "read_session_tool_result",
        )
    )
    summary_uri = f"azents://memory/historical/team/{source}/summary.md"
    assert "blue" in _inspect(
        azents_public_server_url, setup, consumer, operation="read", path=summary_uri
    )
    assert source in _inspect(
        azents_public_server_url,
        setup,
        consumer,
        operation="glob",
        path="azents://memory/historical/team/*/summary.md",
    )
    assert "blue" in _inspect(
        azents_public_server_url,
        setup,
        consumer,
        operation="grep",
        path="azents://memory/historical/team",
    )
    denied = _inspect(
        azents_public_server_url,
        setup,
        consumer,
        operation="read",
        path=f"azents://memory/historical/user/{personal}/summary.md",
    )
    assert "User correction" not in denied
    runtime_denied = _inspect(
        azents_public_server_url,
        setup,
        consumer,
        operation="read",
        path="/tmp/historical-unavailable.txt",
    )
    assert "runtime_capability_denied" in runtime_denied
    archived = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}/sessions/{source}/archive",
        headers=_headers(setup.token),
        timeout=10,
    )
    assert archived.status_code == 204
    assert _settings(azents_public_server_url, setup, "team") == []
    assert "User correction" not in _inspect(
        azents_public_server_url, setup, consumer, operation="read", path=summary_uri
    )
    restored = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}/sessions/{source}/restore",
        headers=_headers(setup.token),
        timeout=10,
    )
    restored.raise_for_status()
    decode_session(restored.json())
    assert (
        _settings(azents_public_server_url, setup, "team")[0].source_session_id
        == source
    )
    assert "User correction" in _inspect(
        azents_public_server_url, setup, consumer, operation="read", path=summary_uri
    )
    updated = requests.patch(
        f"{azents_public_server_url}/agent/v1/workspaces/{setup.handle}/agents/{setup.agent_id}",
        headers=_headers(setup.token),
        json={"memory_enabled": False},
        timeout=10,
    )
    updated.raise_for_status()
    AgentResponse.model_validate(updated.json())
    assert (
        _settings(azents_public_server_url, setup, "team")[0].source_session_id
        == source
    )
    disabled = _sample(
        azents_admin_server_url, setup, sampled_at + datetime.timedelta(hours=8)
    )
    assert disabled.attempted == 0
    assert "User correction" not in _inspect(
        azents_public_server_url, setup, consumer, operation="read", path=summary_uri
    )
