"""Real Runtime lifecycle/storage boundaries without browser presentation work."""

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.agent_workspace_directory_response import (
    AgentWorkspaceDirectoryResponse,
)
from azentspublicclient.models.agent_workspace_mkdir_request import (
    AgentWorkspaceMkdirRequest,
)
from azentspublicclient.models.reset_agent_runtime_request import (
    ResetAgentRuntimeRequest,
)
from azentspublicclient.models.runtime_desired_state import RuntimeDesiredState
from azentspublicclient.models.runtime_system_metrics_summary import (
    RuntimeSystemMetricsSummary,
)
from testcontainers.core.container import DockerContainer

from support.utils import single_candidate_model_options, unique, wait_until
from tests.required.public.test_runtime_optional_capability import _create_workspace


def test_runtime_restart_stop_start_preserve_workspace_and_reset_deletes_it(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Relocate storage semantics from the repetitive Web lifecycle journey."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=True,
    )
    headers = {"Authorization": f"Bearer {workspace.token}"}
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime lifecycle storage {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace.runtime_profile_id,
        ),
        _headers=headers,
    )
    api = AgentRuntimeV1Api(public_api_client)
    files = ChatV1Api(public_api_client)

    def snapshot() -> AgentRuntimeResponse:
        return api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent.id, handle=workspace.handle, _headers=headers
        )

    def ready(minimum_generation: int) -> AgentRuntimeResponse:
        def observe() -> AgentRuntimeResponse | None:
            runtime = snapshot()
            state = runtime.lifecycle
            if (
                state is not None
                and state.desired_generation >= minimum_generation
                and state.target == "running"
                and state.convergence == "stable"
                and state.availability == "ready"
                and state.provider.resource == "running"
                and state.runner.state == "ready"
            ):
                return runtime
            return None

        result = wait_until(
            observe,
            timeout=120,
            interval=1,
            message="New Runtime generation did not regain full readiness",
        )
        assert result is not None
        return result

    wait_until(
        lambda: snapshot().actions.start,
        timeout=120,
        interval=1,
        message="Provider did not authorize Runtime start",
    )
    before = snapshot()
    admitted = api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent.id, handle=workspace.handle, _headers=headers
    )
    assert admitted.desired_generation > 0
    if before.lifecycle is not None:
        assert admitted.desired_generation > before.lifecycle.desired_generation
    initial = ready(admitted.desired_generation)
    assert initial.runtime is not None and initial.runtime.workspace_path
    sentinel = f"{initial.runtime.workspace_path}/lifecycle-sentinel-{unique()}"
    files.chat_v1_create_agent_workspace_directory(
        agent_id=agent.id,
        agent_workspace_mkdir_request=AgentWorkspaceMkdirRequest(
            path=sentinel, parents=False
        ),
        _headers=headers,
    )

    def retained() -> None:
        result = files.chat_v1_read_agent_workspace_path(
            agent_id=agent.id, path=sentinel, _headers=headers
        )
        assert isinstance(result.actual_instance, AgentWorkspaceDirectoryResponse)

    retained()
    assert initial.lifecycle is not None
    api.agent_runtime_v1_restart_agent_runtime(
        agent_id=agent.id, handle=workspace.handle, _headers=headers
    )
    restarted = ready(initial.lifecycle.desired_generation + 1)
    retained()
    wait_until(
        lambda: bool(
            api.agent_runtime_v1_get_agent_runtime_system_metrics(
                agent_id=agent.id, handle=workspace.handle, _headers=headers
            ).samples
        ),
        timeout=120,
        interval=1,
        message="Runtime did not publish history before stop",
    )
    api.agent_runtime_v1_stop_agent_runtime(
        agent_id=agent.id, handle=workspace.handle, _headers=headers
    )

    def stopped() -> AgentRuntimeResponse | None:
        runtime = snapshot()
        state = runtime.lifecycle
        if (
            state is not None
            and state.target == "stopped"
            and state.convergence == "stable"
            and state.availability == "stopped"
        ):
            return runtime
        return None

    stopped_runtime = wait_until(
        stopped,
        timeout=120,
        interval=1,
        message="Runtime stop did not converge",
    )
    assert stopped_runtime is not None and stopped_runtime.lifecycle is not None
    assert restarted.lifecycle is not None
    assert (
        stopped_runtime.lifecycle.desired_generation
        > restarted.lifecycle.desired_generation
    )
    stopped_metrics = api.agent_runtime_v1_get_agent_runtime_system_metrics(
        agent_id=agent.id, handle=workspace.handle, _headers=headers
    )
    assert stopped_metrics.summary is RuntimeSystemMetricsSummary.STOPPED
    assert stopped_metrics.scope is not None and stopped_metrics.samples
    api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent.id, handle=workspace.handle, _headers=headers
    )
    started = ready(stopped_runtime.lifecycle.desired_generation + 1)
    retained()
    assert started.lifecycle is not None
    api.agent_runtime_v1_reset_agent_runtime(
        agent_id=agent.id,
        handle=workspace.handle,
        reset_agent_runtime_request=ResetAgentRuntimeRequest(
            final_desired_state=RuntimeDesiredState.RUNNING
        ),
        _headers=headers,
    )
    ready(started.lifecycle.desired_generation + 1)
    with pytest.raises(ApiException) as missing:
        files.chat_v1_read_agent_workspace_path(
            agent_id=agent.id, path=sentinel, _headers=headers
        )
    assert missing.value.status == 404
