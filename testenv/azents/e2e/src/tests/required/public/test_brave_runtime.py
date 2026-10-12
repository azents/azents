"""Credential-free Brave Search product-path and image materialization E2E."""

import json

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from pydantic import TypeAdapter
from testcontainers.core.container import DockerContainer

from support.image_watchdog_observations import ImageOutputObservation
from support.observations import ToolCallObservation, ToolResultObservation
from support.runtime_profiles import start_and_wait_for_agent_runtime
from support.utils import (
    single_candidate_model_options,
    unique,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
)
from tests.required.public.test_brave_search import (
    _completed_success_sessions,
    _tool_events,
)
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
)

E2E_PLANNER_FALLBACK_WEIGHT = 30.0
_IMAGE_PARTS = TypeAdapter(list[ImageOutputObservation])


def test_brave_five_tools_with_managed_runtime(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
) -> None:
    """Prove the same five native searches work with a running managed Runtime."""
    del azents_engine_worker_container, openai_proxy_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=True,
    )
    assert workspace.runtime_profile_id is not None
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave managed Runtime E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave managed Runtime E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace.runtime_profile_id,
            tool_search_enabled=True,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability == AgentRuntimeCapability.MANAGED
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=workspace.token,
        workspace_handle=workspace.handle,
        agent_id=agent.id,
    )
    sessions = _completed_success_sessions(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
    )
    for kind, session_id in sessions.items():
        events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        calls = [
            ToolCallObservation.model_validate(event.payload)
            for event in events
            if event.kind == "client_tool_call"
        ]
        results = [
            ToolResultObservation.model_validate(event.payload)
            for event in events
            if event.kind == "client_tool_result"
        ]
        assert [call.name for call in calls] == [
            "tool_search",
            f"brave__search_{kind}",
        ]
        assert len(results) == 2
        result = results[1]
        assert result.call_id == calls[1].call_id
        assert result.status == "completed"
        serialized = json.dumps(
            result.model_dump(mode="json", exclude_unset=True), ensure_ascii=False
        )
        assert (
            "https://example.org/brave/image-page-1"
            if kind == "images"
            else f"https://example.org/brave/{kind}"
        ) in serialized
        if kind == "images":
            output = result.output
            assert isinstance(output, list)
            assert (
                sum(
                    part.type == "attachment"
                    for part in _IMAGE_PARTS.validate_python(output)
                )
                == 2
            )
