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
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import start_and_wait_for_agent_runtime
from support.utils import (
    single_candidate_model_options,
    unique,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    json_object_payload,
)
from tests.required.public.test_brave_search import _submit, _tool_events
from tests.required.public.test_per_prompt_inference_profile import (
    _create_profile_session,
)
from tests.required.public.test_provider_image_generation import (
    _wait_for_idle,
)
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
)

_KINDS = ("web", "context", "news", "images", "videos")
E2E_PLANNER_FALLBACK_WEIGHT = 30.0


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
    for kind in _KINDS:
        session_id = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
            kind=kind,
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=session_id,
        )
        events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        )
        calls = [
            json_object_payload(event.get("payload"), label="Managed Brave call")
            for event in events
            if event.get("kind") == "client_tool_call"
        ]
        results = [
            json_object_payload(event.get("payload"), label="Managed Brave result")
            for event in events
            if event.get("kind") == "client_tool_result"
        ]
        assert [call.get("name") for call in calls] == [
            "tool_search",
            f"brave__search_{kind}",
        ]
        assert len(results) == 2
        result = results[1]
        assert result.get("call_id") == calls[1].get("call_id")
        assert result.get("status") == "completed"
        serialized = json.dumps(result, ensure_ascii=False)
        assert (
            "https://example.org/brave/image-page-1"
            if kind == "images"
            else f"https://example.org/brave/{kind}"
        ) in serialized
        if kind == "images":
            output = result.get("output")
            assert isinstance(output, list)
            assert (
                sum(
                    isinstance(part, dict) and part.get("type") == "attachment"
                    for part in output
                )
                == 2
            )
