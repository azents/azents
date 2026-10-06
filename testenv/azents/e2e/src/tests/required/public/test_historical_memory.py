"""Credential-free Historical Memory preparation and live lookup journey.

The explicit-time sampler prepares summaries and dispatches common Worker work.
Tests poll the accepted current-memory API instead of treating routing counts as
publication proof. Exact ownership/commit interleavings have backend coverage.
"""

import datetime
import json
from pathlib import Path
from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import psycopg
import pytest
import requests
from azentsadminclient.api.system_settings_v1_api import SystemSettingsV1Api
from azentsadminclient.models.historical_memory_execution_patch_request import (
    HistoricalMemoryExecutionPatchRequest,
)
from azentsadminclient.models.session_diagnostic_event_page import (
    SessionDiagnosticEventPage,
)
from azentsadminclient.models.session_diagnostic_file import SessionDiagnosticFile
from azentsadminclient.models.session_diagnostic_metadata import (
    SessionDiagnosticMetadata,
)
from azentsadminclient.models.system_setting_version_conflict_response import (
    SystemSettingVersionConflictResponse,
)
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
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
from azentspublicclient.models.consolidated_memory_response import (
    ConsolidatedMemoryResponse,
)
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.historical_memory_response import (
    HistoricalMemoryResponse,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from testcontainers.postgres import PostgresContainer

from support.observations import (
    ConsolidatedHistoricalSampleObservation,
    ConsolidationProxyJournalObservation,
    ConsolidationProxyRequestObservation,
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
_UNVERIFIED_DELIVERY = "Delivery uncertainty: no external completion is verified."


class _Setup(NamedTuple):
    token: str
    handle: str
    agent_id: str

    def __repr__(self) -> str:
        return (
            f"_Setup(token='<redacted>', handle={self.handle!r}, "
            f"agent_id={self.agent_id!r})"
        )


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
    admin_url: str, setup: _Setup, now: datetime.datetime, *, consolidate: bool
) -> ConsolidatedHistoricalSampleObservation:
    """Advance domain sampling only, never product rows or execution clocks."""
    response = requests.post(
        f"{admin_url}/scheduler/v1/historical-memory/sample",
        json={
            "agent_id": setup.agent_id,
            "now": now.isoformat(),
            "consolidate": consolidate,
        },
        timeout=125,
    )
    response.raise_for_status()
    return ConsolidatedHistoricalSampleObservation.model_validate(response.json())


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


def _current_memory(
    server_url: str, setup: _Setup, scope: str
) -> ConsolidatedMemoryResponse:
    """Read the authoritative accepted document without triggering generation."""
    response = requests.get(
        f"{server_url}/agent/v1/workspaces/{setup.handle}/agents/{setup.agent_id}/consolidated-memory",
        headers=_headers(setup.token),
        params={"scope": scope},
        timeout=10,
    )
    response.raise_for_status()
    return ConsolidatedMemoryResponse.model_validate(response.json())


def _wait_current_memory(
    server_url: str, setup: _Setup, scope: str, marker: str
) -> ConsolidatedMemoryResponse:
    """Wait for actual Worker submission acceptance, never dispatch counters."""

    def accepted() -> ConsolidatedMemoryResponse | None:
        current = _current_memory(server_url, setup, scope)
        if current.markdown is None or marker not in current.markdown:
            return None
        assert current.published_at is not None
        return current

    result = wait_until(
        accepted,
        timeout=120,
        interval=0.2,
        message="Common Worker did not accept the integrated memory",
    )
    assert result is not None
    return result


def _assert_retained_submission_audit(
    admin_url: str,
    server_url: str,
    setup: _Setup,
    admin_client: azentsadminclient.ApiClient,
    postgres: PostgresContainer,
    source_id: str,
    marker: str,
) -> None:
    """Discover metadata read-only, then verify retained files/events via real API."""
    with psycopg.connect(
        host=postgres.get_container_host_ip(),
        port=postgres.get_exposed_port(5432),
        user=postgres.username,
        password=postgres.password,
        dbname=postgres.dbname,
    ) as connection:
        row = connection.execute(
            """
            SELECT execution.session_id, unit.workspace_id
            FROM memory_executions AS execution
            JOIN memory_units AS unit ON unit.id = execution.unit_id
            WHERE unit.agent_id = %s AND lower(unit.scope::text) = 'team'
              AND execution.accepted_at IS NOT NULL
            ORDER BY execution.accepted_at DESC LIMIT 1
            """,
            (setup.agent_id,),
        ).fetchone()
    assert row is not None
    session_id, workspace_id = row
    assert isinstance(session_id, str) and isinstance(workspace_id, str)
    admin_token = admin_client.configuration.access_token
    assert isinstance(admin_token, str)
    url = f"{admin_url}/debug/v1/sessions/{session_id}"

    def archived() -> SessionDiagnosticMetadata | None:
        response = requests.get(
            url,
            headers=_headers(admin_token),
            params={"workspace_id": workspace_id},
            timeout=10,
        )
        response.raise_for_status()
        metadata = SessionDiagnosticMetadata.model_validate(response.json())
        return metadata if metadata.status == "archived" else None

    assert (
        wait_until(
            archived,
            timeout=30,
            interval=0.2,
            message="Accepted internal Session was not archived",
        )
        is not None
    )
    events = []
    after: str | None = None
    while True:
        params: dict[str, str | int] = {"workspace_id": workspace_id, "limit": 100}
        if after is not None:
            params["after"] = after
        response = requests.get(
            url + "/events", headers=_headers(admin_token), params=params, timeout=10
        )
        response.raise_for_status()
        page = SessionDiagnosticEventPage.model_validate(response.json())
        events.extend(page.items)
        if page.next_cursor is None:
            break
        assert page.next_cursor != after
        after = page.next_cursor
    submit_calls = [
        event
        for event in events
        if event.tool_name == "submit_memory" and event.arguments
    ]
    assert len(submit_calls) == 2
    assert any(
        "no explicit submission has been accepted" in (event.text or "")
        for event in events
    )
    assert any("10,000" in (event.text or "") for event in events)
    for path, writable in ((f"inputs/{source_id}.md", False), ("result.md", True)):
        response = requests.get(
            url + "/file",
            headers=_headers(admin_token),
            params={"workspace_id": workspace_id, "path": path},
            timeout=10,
        )
        response.raise_for_status()
        file = SessionDiagnosticFile.model_validate(response.json())
        assert marker in file.content and file.writable == writable
    public = requests.get(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/sessions/{session_id}",
        headers=_headers(setup.token),
        timeout=10,
    )
    assert public.status_code == 404


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
        azents_admin_server_url,
        setup,
        sampled_at + datetime.timedelta(hours=1),
        consolidate=False,
    )
    assert early.admitted == 0
    assert early.attempted == 0
    prepared = _sample(
        azents_admin_server_url,
        setup,
        sampled_at + datetime.timedelta(hours=7),
        consolidate=False,
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
        azents_admin_server_url,
        setup,
        sampled_at + datetime.timedelta(hours=8),
        consolidate=False,
    )
    assert disabled.attempted == 0
    assert "User correction" not in _inspect(
        azents_public_server_url, setup, consumer, operation="read", path=summary_uri
    )


def _journal(proxy_url: str) -> list[ConsolidationProxyRequestObservation]:
    response = requests.get(f"{proxy_url}/v1/_image_generation_requests", timeout=10)
    response.raise_for_status()
    return ConsolidationProxyJournalObservation.model_validate(
        {"requests": response.json()}
    ).requests


def _foreground_instructions(proxy_url: str, marker: str) -> str:
    matching = [
        item
        for item in _journal(proxy_url)
        if marker in json.dumps(item.input)
        and item.fixture_consolidation_chain is None
        and item.tools is not None
    ]
    assert matching
    instructions = matching[0].instructions
    assert instructions is not None
    return instructions


def test_agentic_consolidation_isolated_runtime_free_and_scope_only_result(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    openai_proxy_url: str,
    tmp_path: Path,
    postgres_container: PostgresContainer,
) -> None:
    """Common Worker submits independent scope results from supplied summaries."""
    server, admin = azents_public_server_url, azents_admin_server_url
    setup = _setup(public_api_client, admin_api_client, server)
    other_email = f"historical-other-{unique()}@example.com"
    other_auth = authenticate_user(
        public_api_client, admin_api_client, email=other_email
    )
    invitation_api = InvitationV1Api(public_api_client)
    invitation = invitation_api.invitation_v1_create_invitation(
        setup.handle,
        CreateInvitationRequest(email=other_email),
        _headers=_headers(setup.token),
    )
    accepted = invitation_api.invitation_v1_accept_invitation(
        invitation.id, _headers=_headers(other_auth.access_token)
    )
    assert accepted.status == "accepted"
    other = _Setup(other_auth.access_token, setup.handle, setup.agent_id)
    team_marker = f"AGENTIC_TEAM_{unique()}_V1"
    own_marker = f"AGENTIC_PERSONAL_{unique()}_V1"
    peer_marker = f"AGENTIC_PERSONAL_{unique()}_V1"
    team = _create_session(
        server,
        setup,
        scope="team",
        message=(
            f"Historical Memory E2E source: {team_marker}; "
            "corrected blue, rollout unverified."
        ),
    )
    personal = _create_session(
        server,
        setup,
        scope="user",
        message=f"Historical Memory E2E personal: {own_marker}; "
        "private preference 한글.",
    )
    peer = _create_session(
        server,
        other,
        scope="user",
        message=f"Historical Memory E2E personal: {peer_marker}; "
        "private preference 日本語.",
    )
    sample = _sample(
        admin,
        setup,
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7),
        consolidate=True,
    )
    assert sample.prepared == 3 and sample.failed == 0, sample
    assert sample.consolidation_dispatched == 3, sample
    team_result = _wait_current_memory(server, setup, "team", team_marker)
    own_result = _wait_current_memory(server, setup, "user", own_marker)
    peer_result = _wait_current_memory(server, other, "user", peer_marker)
    _assert_retained_submission_audit(
        admin, server, setup, admin_api_client, postgres_container, team, team_marker
    )
    assert own_marker not in (team_result.markdown or "")
    assert peer_marker not in (own_result.markdown or "")
    assert team_marker not in (peer_result.markdown or "")
    journal = _journal(openai_proxy_url)
    (tmp_path / "consolidation-journal.json").write_text(
        ConsolidationProxyJournalObservation(requests=journal).model_dump_json(
            indent=2, exclude_unset=True
        ),
        encoding="utf-8",
    )
    groups: dict[str, list[ConsolidationProxyRequestObservation]] = {}
    for request in journal:
        identifier = request.fixture_consolidation_chain
        if isinstance(identifier, str):
            groups.setdefault(identifier, []).append(request)
    for marker, forbidden in (
        (team_marker, (own_marker, peer_marker)),
        (own_marker, (team_marker, peer_marker)),
        (peer_marker, (team_marker, own_marker)),
    ):
        matching = [
            group
            for group in groups.values()
            if marker in group[-1].model_dump_json(exclude_unset=True)
        ]
        assert len(matching) == 1
        group = matching[0]
        assert len(group) >= 3
        captured = ConsolidationProxyJournalObservation(requests=group).model_dump_json(
            exclude_unset=True
        )
        assert all(value not in captured for value in forbidden)
        assert "20,000" not in captured and "20k" not in captured
        names = {tool.name for request in group for tool in request.tools or []}
        assert {"read", "write", "edit"} <= names
        assert names <= {
            "read",
            "write",
            "edit",
            "glob",
            "grep",
            "delete",
            "apply_patch",
            "submit_memory",
        }
        assert "submit_memory" in names
        assert "coverage.json" not in captured
        assert "inventory/work" not in captured
        assert "azents://memory/sources/" not in captured
        assert "Source-dependent integrated context" not in captured
    owner_turn = f"Historical Memory E2E continue {unique()}"
    owner_consumer = _create_session(server, setup, scope="user", message=owner_turn)
    owner_prompt = _foreground_instructions(openai_proxy_url, owner_turn)
    assert team_marker in owner_prompt and own_marker in owner_prompt
    assert peer_marker not in owner_prompt
    assert owner_prompt.count("HISTORICAL MEMORY DATA BEGINS") == 2
    team_turn = f"Historical Memory E2E continue {unique()}"
    team_consumer = _create_session(server, setup, scope="team", message=team_turn)
    team_prompt = _foreground_instructions(openai_proxy_url, team_turn)
    assert team_marker in team_prompt
    assert own_marker not in team_prompt and peer_marker not in team_prompt
    assert team_prompt.count("HISTORICAL MEMORY DATA BEGINS") == 1
    team_uri = "azents://memory/consolidated/team/summary.md"
    user_uri = "azents://memory/consolidated/user/summary.md"
    live = _inspect(server, setup, owner_consumer, operation="read", path=team_uri)
    assert team_marker in live
    assert "blue" in live and _UNVERIFIED_DELIVERY in live
    assert "CONSOLIDATION_FIXTURE_FINISHED_NOT_THE_PUBLICATION_BODY" not in live
    assert own_marker in _inspect(
        server, setup, owner_consumer, operation="read", path=user_uri
    )
    assert own_marker not in _inspect(
        server, setup, team_consumer, operation="read", path=user_uri
    )
    assert peer_marker not in _inspect(
        server,
        setup,
        owner_consumer,
        operation="read",
        path=f"azents://memory/historical/user/{peer}/summary.md",
    )
    assert "consolidated/team/summary.md" in _inspect(
        server,
        setup,
        owner_consumer,
        operation="glob",
        path="azents://memory/consolidated/*/summary.md",
    )
    assert "blue" in _inspect(
        server,
        setup,
        owner_consumer,
        operation="grep",
        path="azents://memory/consolidated",
    )
    archived = requests.post(
        f"{server}/chat/v1/agents/{setup.agent_id}/sessions/{team}/archive",
        headers=_headers(setup.token),
        timeout=10,
    )
    assert archived.status_code == 204
    # Archive filters future provided inputs, not already accepted aggregates.
    assert team_marker in _inspect(
        server, setup, owner_consumer, operation="read", path=team_uri
    )
    assert own_marker in _inspect(
        server, setup, owner_consumer, operation="read", path=user_uri
    )
    restored = requests.post(
        f"{server}/chat/v1/agents/{setup.agent_id}/sessions/{team}/restore",
        headers=_headers(setup.token),
        timeout=10,
    )
    restored.raise_for_status()
    # Archive filters future provided inputs, not already accepted aggregates.
    assert team_marker in _inspect(
        server, setup, owner_consumer, operation="read", path=team_uri
    )
    assert team_marker in _inspect(
        server,
        setup,
        owner_consumer,
        operation="read",
        path=f"azents://memory/historical/team/{team}/summary.md",
    )
    assert {row.source_session_id for row in _settings(server, setup, "user")} == {
        personal
    }


def test_successive_consolidation_starts_publish_current_work(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    openai_proxy_url: str,
) -> None:
    """Each new source runs through a fresh host and reaches live publication."""
    server, admin = azents_public_server_url, azents_admin_server_url
    setup = _setup(public_api_client, admin_api_client, server)
    markers: list[str] = []
    for _ in range(2):
        marker = f"AGENTIC_TEAM_{unique()}_V1"
        markers.append(marker)
        source = _create_session(
            server,
            setup,
            scope="team",
            message=f"Historical Memory E2E source: {marker}; current evidence.",
        )
        sampled = _sample(
            admin,
            setup,
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7),
            consolidate=True,
        )
        assert sampled.prepared == 1 and sampled.failed == 0, sampled
        assert sampled.consolidation_dispatched == 1, sampled
        current = _wait_current_memory(server, setup, "team", marker)
        if len(markers) == 1:
            archived = requests.post(
                f"{server}/chat/v1/agents/{setup.agent_id}/sessions/{source}/archive",
                headers=_headers(setup.token),
                timeout=10,
            )
            assert archived.status_code == 204
        else:
            # Fresh authoring cannot inherit an archived source through the old result.
            assert markers[0] not in (current.markdown or "")
            groups: dict[str, list[ConsolidationProxyRequestObservation]] = {}
            for item in _journal(openai_proxy_url):
                if item.fixture_consolidation_chain is not None:
                    groups.setdefault(item.fixture_consolidation_chain, []).append(item)
            matching = [
                group
                for group in groups.values()
                if marker in group[-1].model_dump_json(exclude_unset=True)
            ]
            assert len(matching) == 1
            assert markers[0] not in ConsolidationProxyJournalObservation(
                requests=matching[0]
            ).model_dump_json(exclude_unset=True)
    consumer_marker = f"Historical Memory E2E continue {unique()}"
    consumer = _create_session(server, setup, scope="team", message=consumer_marker)
    assert markers[-1] in _foreground_instructions(openai_proxy_url, consumer_marker)
    assert markers[-1] in _inspect(
        server,
        setup,
        consumer,
        operation="read",
        path="azents://memory/consolidated/team/summary.md",
    )


def test_historical_execution_policy_roundtrip_and_custom_consolidation(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    openai_proxy_url: str,
    request: pytest.FixtureRequest,
) -> None:
    """Custom system policy permits file rounds and retains null/version semantics."""
    settings_api = SystemSettingsV1Api(admin_api_client)
    initial = settings_api.system_settings_v1_get_historical_memory_execution_setting()
    assert initial.section == "historical_memory_execution"
    assert initial.schema_version == 1

    def restore_policy() -> None:
        current = (
            settings_api.system_settings_v1_get_historical_memory_execution_setting()
        )
        restored = (
            settings_api.system_settings_v1_patch_historical_memory_execution_setting(
                HistoricalMemoryExecutionPatchRequest(
                    expected_version=current.admin_version,
                    max_turns=initial.max_turns,
                    timeout_seconds=initial.timeout_seconds,
                )
            )
        )
        assert restored.max_turns == initial.max_turns
        assert restored.timeout_seconds == initial.timeout_seconds

    request.addfinalizer(restore_policy)
    configured = (
        settings_api.system_settings_v1_patch_historical_memory_execution_setting(
            HistoricalMemoryExecutionPatchRequest(
                expected_version=initial.admin_version,
                max_turns=50,
                timeout_seconds=900,
            )
        )
    )
    assert configured.admin_version == initial.admin_version + 1
    assert configured.max_turns == 50
    assert configured.timeout_seconds == 900
    assert (
        settings_api.system_settings_v1_get_historical_memory_execution_setting()
        == configured
    )

    token = admin_api_client.configuration.access_token
    assert isinstance(token, str)
    stale_response = requests.patch(
        f"{azents_admin_server_url}/system-setting/v1/sections/historical-memory-execution",
        headers=_headers(token),
        json={"expected_version": initial.admin_version, "max_turns": 2},
        timeout=10,
    )
    assert stale_response.status_code == 409
    stale = SystemSettingVersionConflictResponse.model_validate(stale_response.json())
    assert stale.detail.code == "stale_system_setting_version"
    assert stale.detail.current_version == configured.admin_version
    assert (
        settings_api.system_settings_v1_get_historical_memory_execution_setting()
        == configured
    )

    setup = _setup(public_api_client, admin_api_client, azents_public_server_url)
    marker = f"AGENTIC_TEAM_{unique()}_V1"
    _create_session(
        azents_public_server_url,
        setup,
        scope="team",
        message=(
            f"Historical Memory E2E source: {marker}; "
            "corrected blue, rollout unverified."
        ),
    )
    sampled = _sample(
        azents_admin_server_url,
        setup,
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=7),
        consolidate=True,
    )
    assert sampled.prepared == 1 and sampled.failed == 0, sampled
    assert sampled.consolidation_dispatched == 1, sampled
    accepted_memory = _wait_current_memory(
        azents_public_server_url, setup, "team", marker
    )
    assert "blue" in (accepted_memory.markdown or "")
    assert _UNVERIFIED_DELIVERY in (accepted_memory.markdown or "")
    groups: dict[str, list[ConsolidationProxyRequestObservation]] = {}
    for item in _journal(openai_proxy_url):
        if item.fixture_consolidation_chain is not None:
            groups.setdefault(item.fixture_consolidation_chain, []).append(item)
    matching = [
        group
        for group in groups.values()
        if marker in group[-1].model_dump_json(exclude_unset=True)
    ]
    assert len(matching) == 1
    # This journey proves a finite custom policy accepts ordinary multi-round work.
    # Exact turn exhaustion and deadline enforcement have narrower backend coverage.
    assert 3 <= len(matching[0]) <= 50
    consumer = _create_session(
        azents_public_server_url,
        setup,
        scope="team",
        message=f"Historical Memory E2E continue {unique()}",
    )
    assert marker in _inspect(
        azents_public_server_url,
        setup,
        consumer,
        operation="read",
        path="azents://memory/consolidated/team/summary.md",
    )

    cleared = settings_api.system_settings_v1_patch_historical_memory_execution_setting(
        HistoricalMemoryExecutionPatchRequest(
            expected_version=configured.admin_version,
            max_turns=None,
        )
    )
    assert cleared.admin_version == configured.admin_version + 1
    assert cleared.max_turns is None
    assert cleared.timeout_seconds == 900
    assert (
        settings_api.system_settings_v1_get_historical_memory_execution_setting()
        == cleared
    )
    timeout_only = (
        settings_api.system_settings_v1_patch_historical_memory_execution_setting(
            HistoricalMemoryExecutionPatchRequest(
                expected_version=cleared.admin_version,
                timeout_seconds=901,
            )
        )
    )
    assert timeout_only.admin_version == cleared.admin_version + 1
    assert timeout_only.max_turns is None
    assert timeout_only.timeout_seconds == 901
    assert (
        settings_api.system_settings_v1_get_historical_memory_execution_setting()
        == timeout_only
    )
