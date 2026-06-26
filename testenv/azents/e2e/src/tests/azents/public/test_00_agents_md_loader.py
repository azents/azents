"""AGENTS.md t E2E test."""

import time
import uuid
from typing import Any, LiteralString, NamedTuple, cast

import azentsadminclient
import azentspublicclient
import psycopg
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from psycopg.types.json import Jsonb
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_MARKER = "ROOT_AGENTS_E2E_MARKER_3542"


class AgentsMdExerciseResult(NamedTuple):
    """AGENTS.md loader exercise result."""

    requests_count: int
    instruction_marker_requests: list[int]
    instruction_snippets: list[str]
    request_summaries: list[str]
    agent_shell_enabled: bool | None


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Generated client t API host stringt t."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _system_message_texts(item: dict[str, object]) -> list[str]:
    """AIMock journal item t instruction/system stringt t."""
    body = item.get("body")
    if not isinstance(body, dict):
        return []
    body_dict = cast("dict[str, object]", body)
    texts: list[str] = []
    instructions = body_dict.get("instructions")
    if isinstance(instructions, str):
        texts.append(instructions)
    messages = body_dict.get("messages")
    if not isinstance(messages, list):
        return texts
    message_items = cast("list[object]", messages)
    for message in message_items:
        if not isinstance(message, dict):
            continue
        message_dict = cast("dict[str, object]", message)
        if message_dict.get("role") != "system":
            continue
        content = message_dict.get("content")
        if isinstance(content, str):
            texts.append(content)
    return texts


def _request_summary(item: dict[str, object]) -> str:
    """AIMock journal item t t request shape t assertion messaget summaryt."""
    body = item.get("body")
    if not isinstance(body, dict):
        return "body=<missing>"
    body_dict = cast("dict[str, object]", body)
    user_messages: list[str] = []
    tool_names: list[str] = []
    tool_results: list[str] = []
    messages = body_dict.get("messages")
    if isinstance(messages, list):
        for message in cast("list[object]", messages):
            if not isinstance(message, dict):
                continue
            message_dict = cast("dict[str, object]", message)
            role = message_dict.get("role")
            content = message_dict.get("content")
            if role == "user" and isinstance(content, str):
                user_messages.append(content[:120])
            if role == "tool":
                tool_call_id = message_dict.get("tool_call_id")
                if isinstance(tool_call_id, str):
                    tool_names.append(f"tool_result:{tool_call_id}")
                if isinstance(content, str):
                    tool_results.append(content[:1200])
    tools = body_dict.get("tools")
    if isinstance(tools, list):
        for tool in cast("list[object]", tools):
            if not isinstance(tool, dict):
                continue
            tool_dict = cast("dict[str, object]", tool)
            function = tool_dict.get("function")
            if isinstance(function, dict):
                name = cast("dict[str, object]", function).get("name")
                if isinstance(name, str):
                    tool_names.append(name)
    system_texts = _system_message_texts(item)
    instruction_prefixes = [text[:80].replace("\n", "\\n") for text in system_texts]
    instruction_flags = [
        {
            "len": len(text),
            "has_marker": _MARKER in text,
            "has_runtime_files": "## Runtime Files" in text,
            "has_root_block": "## Session Workspace Instructions" in text,
        }
        for text in system_texts
    ]
    return (
        f"users={user_messages} tools={tool_names[:20]} "
        f"tool_results={tool_results[:5]} "
        f"instructions={instruction_prefixes} instruction_flags={instruction_flags}"
    )


def _history_events(
    *,
    public_url: str,
    access_token: str,
    session_id: str,
) -> list[dict[str, object]]:
    """REST history event listt fetcht."""
    response = requests.get(
        f"{public_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    raw_body: object = response.json()
    if not isinstance(raw_body, dict):
        raise AssertionError(f"history response is not an object: {raw_body!r}")
    body = cast("dict[str, object]", raw_body)
    items = body.get("items")
    if not isinstance(items, list):
        raise AssertionError(f"history items is not a list: {body!r}")
    return [
        cast("dict[str, object]", item)
        for item in cast("list[object]", items)
        if isinstance(item, dict)
    ]


def _event_content(event: dict[str, object]) -> str:
    """event payload content text t returnt."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    content = cast("dict[str, object]", payload).get("content")
    if isinstance(content, str):
        return content
    return ""


def _run_marker_completed(event: dict[str, object]) -> bool:
    """run_marker completed t returnt."""
    if event.get("kind") != "run_marker":
        return False
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return False
    return cast("dict[str, object]", payload).get("status") == "completed"


def _wait_for_turn_complete(
    *,
    public_url: str,
    access_token: str,
    session_id: str,
    message: str,
    timeout: float = 120,
) -> None:
    """REST write t t turn t durable run_marker t completet t."""
    deadline = time.monotonic() + timeout
    last_events: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        events = _history_events(
            public_url=public_url,
            access_token=access_token,
            session_id=session_id,
        )
        last_events = events
        message_index: int | None = None
        for index, event in enumerate(events):
            if event.get("kind") != "user_message":
                continue
            if _event_content(event) == message:
                message_index = index
        if message_index is not None:
            for event in events[message_index + 1 :]:
                if _run_marker_completed(event):
                    return
        time.sleep(0.5)
    raise TimeoutError(f"turn did not complete: {message}, events={last_events!r}")


def _run_new_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
) -> str:
    """t session t messaget REST write boundary t t session_id t returnt."""
    del public_api_client
    session_response = requests.get(
        f"{public_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    session_response.raise_for_status()
    session_payload = session_response.json()
    session_id = session_payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team primary response did not include id: {session_payload!r}"
        )
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/messages",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "agent_id": agent_id,
            "client_request_id": f"agents-md-create-{unique()}",
            "message": "Create AGENTS.md",
        },
        timeout=10,
    )
    response.raise_for_status()
    _wait_for_turn_complete(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
        message="Create AGENTS.md",
    )
    return session_id


def _run_existing_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """t session messaget REST write boundary t t."""
    del public_api_client
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/messages",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "agent_id": agent_id,
            "client_request_id": f"agents-md-report-{unique()}",
            "message": "Report instructions",
        },
        timeout=10,
    )
    response.raise_for_status()
    _wait_for_turn_complete(
        public_url=public_url,
        access_token=access_token,
        session_id=session_id,
        message="Report instructions",
    )


def _seed_root_agents_state(
    postgres_container: PostgresContainer,
    *,
    agent_id: str,
    session_id: str,
    content: str,
) -> None:
    """Runtime root AGENTS.md Toolkit Statet deterministic E2E DBt seedt."""
    with psycopg.connect(
        host=postgres_container.get_container_host_ip(),
        port=postgres_container.get_exposed_port(5432),
        dbname=postgres_container.dbname,
        user=postgres_container.username,
        password=postgres_container.password,
    ) as conn:
        upsert_state_sql: LiteralString = """
            INSERT INTO toolkit_states (
                id,
                agent_id,
                session_id,
                toolkit_namespace,
                state_name,
                state_json,
                schema_version,
                version
            )
            VALUES (
                %s,
                %s,
                %s,
                'builtin',
                'root_agents_instruction',
                %s,
                1,
                1
            )
            ON CONFLICT ON CONSTRAINT uq_toolkit_states_identity
            DO UPDATE SET
                state_json = EXCLUDED.state_json,
                schema_version = EXCLUDED.schema_version,
                version = toolkit_states.version + 1,
                updated_at = now()
        """
        conn.execute(  # pyright: ignore[reportUnknownMemberType] # psycopg execute overload is partially unknown.
            upsert_state_sql,
            (
                uuid.uuid4().hex,
                agent_id,
                session_id,
                Jsonb({"schema_version": 1, "root_content": content}),
            ),
        )


def _exercise_agents_md_loader(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    postgres_container: PostgresContainer,
    public_url: str,
    mock_openai_url: str,
) -> AgentsMdExerciseResult:
    """AGENTS.md state seed t next turn t mock journal marker t returnt."""
    requests.delete(
        f"{mock_openai_url}/v1/_requests",
        timeout=10,
    ).raise_for_status()
    unique_id = unique()
    access_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"agents-md-{unique_id}@example.com",
    )

    workspace_api = WorkspaceV1Api(public_api_client)
    workspace_handle = f"agents-{unique_id}"
    workspace_api.workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"AGENTS QA {unique_id}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {unique_id}",
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    integration_api = LLMProviderIntegrationV1Api(public_api_client)
    integration = integration_api.llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-dummy")),
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        access_token,
        workspace_handle,
        integration.id,
    )

    agent_api = AgentV1Api(public_api_client)
    agent = agent_api.agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"AGENTS QA Agent {unique_id}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            shell_enabled=True,
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    session_id = _run_new_session(
        public_api_client=public_api_client,
        public_url=public_url,
        access_token=access_token,
        agent_id=agent.id,
    )
    _seed_root_agents_state(
        postgres_container,
        agent_id=agent.id,
        session_id=session_id,
        content=f"Always include {_MARKER} in QA answers.",
    )
    for _ in range(3):
        _run_existing_session(
            public_api_client=public_api_client,
            public_url=public_url,
            access_token=access_token,
            agent_id=agent.id,
            session_id=session_id,
        )
        payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
        instruction_marker_requests = [
            index
            for index, item in enumerate(payload, start=1)
            if any(_MARKER in text for text in _system_message_texts(item))
        ]
        if instruction_marker_requests:
            break
        time.sleep(1.0)

    payload = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
    requests_count = len(payload)
    instruction_marker_requests = [
        index
        for index, item in enumerate(payload, start=1)
        if any(_MARKER in text for text in _system_message_texts(item))
    ]
    instruction_snippets = [
        text[:500]
        for item in payload
        if isinstance(item, dict)
        for text in _system_message_texts(cast("dict[str, object]", item))
    ]
    return AgentsMdExerciseResult(
        requests_count=requests_count,
        instruction_marker_requests=instruction_marker_requests,
        instruction_snippets=instruction_snippets,
        request_summaries=[
            _request_summary(cast("dict[str, object]", item))
            for item in payload
            if isinstance(item, dict)
        ],
        agent_shell_enabled=agent.shell_enabled,
    )


class TestAgentsMdLoader:
    """AGENTS.md t WebSocket E2E."""

    def test_root_agents_md_written_by_tool_is_loaded_into_next_prompt(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: DockerContainer,
        postgres_container: PostgresContainer,
        mock_openai_url: str,
    ) -> None:
        """root AGENTS.md statet next LLM requestt t."""
        del azents_engine_worker_container

        result = _exercise_agents_md_loader(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
            postgres_container=postgres_container,
            public_url=azents_public_server_url,
            mock_openai_url=mock_openai_url,
        )

        assert result.requests_count >= 3
        assert 1 not in result.instruction_marker_requests
        assert result.instruction_marker_requests, result
