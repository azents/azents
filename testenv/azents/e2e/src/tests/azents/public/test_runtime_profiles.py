"""Workspace-owned Runtime Profile integrated E2E journeys."""

from __future__ import annotations

import time
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.runtime_recreation_create_request import (
    RuntimeRecreationCreateRequest,
)
from azentspublicclient.models.runtime_recreation_operation_response import (
    RuntimeRecreationOperationResponse,
)
from azentspublicclient.models.runtime_recreation_operation_status import (
    RuntimeRecreationOperationStatus,
)
from azentspublicclient.models.runtime_summary import RuntimeSummary
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.workspace_runtime_profile_default_replace_request import (  # noqa: E501
    WorkspaceRuntimeProfileDefaultReplaceRequest,
)
from azentspublicclient.models.workspace_runtime_profile_response import (
    WorkspaceRuntimeProfileResponse,
)
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
    wait_until,
)

_RUNTIME_PROVIDER_ID = "system-docker"


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _stop_runtime_provider(container: DockerContainer) -> None:
    """Stop the deterministic Provider without removing its container."""
    wrapped_container = container.get_wrapped_container()
    wrapped_container.stop(timeout=10)
    wrapped_container.reload()
    assert wrapped_container.status == "exited"


def _restart_runtime_provider(container: DockerContainer) -> None:
    """Restart the deterministic Provider and wait for a new registration."""
    marker = "Runtime Provider registered"
    stdout, stderr = container.get_logs()
    prior_registrations = (
        stdout.decode(errors="replace") + stderr.decode(errors="replace")
    ).count(marker)
    wrapped_container = container.get_wrapped_container()
    wrapped_container.start()

    def registered_again() -> bool:
        wrapped_container.reload()
        if wrapped_container.status == "exited":
            raise AssertionError("Runtime Provider exited while restarting")
        current_stdout, current_stderr = container.get_logs()
        registrations = (
            current_stdout.decode(errors="replace")
            + current_stderr.decode(errors="replace")
        ).count(marker)
        return registrations > prior_registrations

    wait_until(
        registered_again,
        timeout=60,
        interval=1,
        message="Runtime Provider did not register after restart",
    )


@pytest.mark.runtime_provider
def test_runtime_profile_precedence_applied_evidence_and_recreation(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
    runtime_provider_resource_id: str,
) -> None:
    """Validate exact selection, application, recreation, and no fallback."""
    del azents_engine_worker_container
    suffix = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-profiles-{suffix}@example.com",
    )
    handle = f"runtime-profiles-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Profiles {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-profiles")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        azents_public_server_url,
        token,
        handle,
        integration.id,
    )
    agent_api = AgentV1Api(public_api_client)
    unconfigured = agent_api.agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Unconfigured {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
        ),
        _headers=headers,
    )
    assert unconfigured.runtime_profile_id is None
    assert unconfigured.runtime_profile_available is False
    assert (
        unconfigured.runtime_profile_availability_reason_code
        == "runtime_profile_unconfigured"
    )

    default_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    explicit_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    profile_api = RuntimeProfileV1Api(public_api_client)
    default_state = (
        profile_api.runtime_profile_v1_get_workspace_runtime_profile_default(
            handle=handle,
            _headers=headers,
        )
    )
    replaced_default = (
        profile_api.runtime_profile_v1_replace_workspace_runtime_profile_default(
            handle=handle,
            workspace_runtime_profile_default_replace_request=(
                WorkspaceRuntimeProfileDefaultReplaceRequest(
                    expected_version=default_state.version,
                    runtime_profile_id=default_profile_id,
                )
            ),
            _headers=headers,
        )
    )
    assert replaced_default.runtime_profile_id == default_profile_id

    omitted_profile_agent = agent_api.agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Omitted Profile {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
        ),
        _headers=headers,
    )
    explicit_agent = agent_api.agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Explicit {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=explicit_profile_id,
        ),
        _headers=headers,
    )
    assert omitted_profile_agent.runtime_profile_id is None
    assert omitted_profile_agent.runtime_profile_available is False
    assert (
        omitted_profile_agent.runtime_profile_availability_reason_code
        == "runtime_profile_unconfigured"
    )
    assert explicit_agent.runtime_profile_id == explicit_profile_id
    assert explicit_agent.runtime_profile_available is True

    explicit_profile = profile_api.runtime_profile_v1_get_workspace_runtime_profile(
        profile_id=explicit_profile_id,
        handle=handle,
        _headers=headers,
    )
    assert explicit_profile.provider_id == _RUNTIME_PROVIDER_ID
    assert explicit_profile.available is True
    assert explicit_profile.capability_revision_id is not None

    runtime_api = AgentRuntimeV1Api(public_api_client)
    read_only_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=explicit_agent.id,
        handle=handle,
        _headers=headers,
    )
    assert read_only_runtime.capability == AgentRuntimeCapability.MANAGED
    assert read_only_runtime.runtime_profile_id == explicit_profile_id
    assert read_only_runtime.runtime is None
    assert read_only_runtime.state is None
    assert read_only_runtime.configuration is None
    assert read_only_runtime.actions.add is False
    assert read_only_runtime.actions.start is True

    initial_runtime = runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=explicit_agent.id,
        handle=handle,
        _headers=headers,
    )
    assert initial_runtime.configuration is not None
    assert initial_runtime.runtime is not None
    assert initial_runtime.configuration.status == "configured_not_created"
    assert initial_runtime.configuration.applied is None
    assert initial_runtime.configuration.desired is not None
    assert (
        initial_runtime.configuration.desired.workspace_runtime_profile_id
        == explicit_profile_id
    )
    assert (
        initial_runtime.configuration.desired.infrastructure_profile_id
        == explicit_profile.infrastructure_profile_id
    )
    assert initial_runtime.runtime.runtime_provider_id == explicit_profile.provider_id
    assert (
        initial_runtime.runtime.runtime_provider_resource_id
        == runtime_provider_resource_id
    )
    assert (
        initial_runtime.configuration.desired.provider_id
        == runtime_provider_resource_id
    )

    applied_runtime: AgentRuntimeResponse | None = None

    def runtime_applied() -> bool:
        nonlocal applied_runtime
        applied_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=explicit_agent.id,
            handle=handle,
            _headers=headers,
        )
        configuration = applied_runtime.configuration
        state = applied_runtime.state
        return (
            configuration is not None
            and state is not None
            and configuration.status == "applied"
            and state.summary == RuntimeSummary.RUNNING
        )

    wait_until(
        runtime_applied,
        timeout=120,
        interval=1,
        message="Runtime Profile did not become applied",
    )
    assert applied_runtime is not None
    assert applied_runtime.configuration is not None
    desired = applied_runtime.configuration.desired
    applied = applied_runtime.configuration.applied
    assert desired is not None
    assert applied is not None
    assert applied.sequence == desired.sequence
    assert applied.digest == desired.digest
    assert desired.provider_reported_digest == desired.digest
    assert desired.runner_reported_digest == desired.digest
    assert desired.provider_acknowledged_at is not None
    assert desired.runner_observed_at is not None
    assert applied.applied_at is not None
    prior_applied_sequence = applied.sequence

    operation = profile_api.runtime_profile_v1_create_profile_recreation(
        profile_id=explicit_profile_id,
        handle=handle,
        runtime_recreation_create_request=RuntimeRecreationCreateRequest(
            expected_version=explicit_profile.version,
            concurrency_limit=1,
        ),
        _headers=headers,
    )
    assert operation.total_count == 1

    completed_operation: RuntimeRecreationOperationResponse | None = None

    def recreation_completed() -> bool:
        nonlocal completed_operation
        completed_operation = (
            profile_api.runtime_profile_v1_get_workspace_runtime_profile_recreation(
                operation_id=operation.id,
                handle=handle,
                _headers=headers,
            )
        )
        return completed_operation.status in {
            RuntimeRecreationOperationStatus.COMPLETED,
            RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES,
            RuntimeRecreationOperationStatus.FAILED,
        }

    wait_until(
        recreation_completed,
        timeout=120,
        interval=1,
        message="Runtime Profile recreation did not complete",
    )
    assert completed_operation is not None
    assert completed_operation.status == RuntimeRecreationOperationStatus.COMPLETED
    assert completed_operation.succeeded_count == 1
    assert completed_operation.skipped_count == 0
    assert completed_operation.failed_count == 0

    recreated_runtime: AgentRuntimeResponse | None = None

    def recreated_runtime_applied() -> bool:
        nonlocal recreated_runtime
        recreated_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=explicit_agent.id,
            handle=handle,
            _headers=headers,
        )
        configuration = recreated_runtime.configuration
        current_applied = configuration.applied if configuration is not None else None
        return (
            configuration is not None
            and configuration.status == "applied"
            and current_applied is not None
            and current_applied.sequence > prior_applied_sequence
        )

    wait_until(
        recreated_runtime_applied,
        timeout=120,
        interval=1,
        message="Recreated Runtime did not apply its replacement state",
    )

    _stop_runtime_provider(azents_runtime_provider_docker_container)
    time.sleep(2)
    try:
        unavailable_profile: WorkspaceRuntimeProfileResponse | None = None

        def profile_unavailable() -> bool:
            nonlocal unavailable_profile
            unavailable_profile = (
                profile_api.runtime_profile_v1_get_workspace_runtime_profile(
                    profile_id=explicit_profile_id,
                    handle=handle,
                    _headers=headers,
                )
            )
            return unavailable_profile.available is False

        wait_until(
            profile_unavailable,
            timeout=30,
            interval=1,
            message="Selected Runtime Profile did not reflect Provider loss",
        )
        retained_agent = agent_api.agent_v1_get_agent(
            agent_id=explicit_agent.id,
            handle=handle,
            _headers=headers,
        )
        assert retained_agent.runtime_profile_id == explicit_profile_id
        assert retained_agent.runtime_profile_available is False
        with pytest.raises(ApiException) as restart_error:
            runtime_api.agent_runtime_v1_restart_agent_runtime(
                agent_id=explicit_agent.id,
                handle=handle,
                _headers=headers,
            )
        assert cast(Any, restart_error.value).status == 409
    finally:
        _restart_runtime_provider(azents_runtime_provider_docker_container)

    wait_until(
        lambda: (
            profile_api.runtime_profile_v1_get_workspace_runtime_profile(
                profile_id=explicit_profile_id,
                handle=handle,
                _headers=headers,
            ).available
        ),
        timeout=60,
        interval=1,
        message="Selected Runtime Profile did not recover with its Provider",
    )
