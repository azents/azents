"""Workspace-owned Runtime Profile integrated E2E journeys."""

from __future__ import annotations

import time
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.runtime_provider_v1_api import RuntimeProviderV1Api
from azentsadminclient.exceptions import ApiException as AdminApiException
from azentsadminclient.models.docker_container_profile_spec_v1 import (
    DockerContainerProfileSpecV1,
)
from azentsadminclient.models.docker_container_resources import (
    DockerContainerResources,
)
from azentsadminclient.models.runtime_infrastructure_profile_create_request import (
    RuntimeInfrastructureProfileCreateRequest,
)
from azentsadminclient.models.runtime_infrastructure_profile_delete_request import (
    RuntimeInfrastructureProfileDeleteRequest,
)
from azentsadminclient.models.runtime_infrastructure_profile_deletion_impact_response import (  # noqa: E501
    RuntimeInfrastructureProfileDeletionImpactResponse,
)
from azentsadminclient.models.runtime_infrastructure_profile_spec import (
    RuntimeInfrastructureProfileSpec,
)
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
from azentspublicclient.models.workspace_runtime_profile_create_request import (
    WorkspaceRuntimeProfileCreateRequest,
)
from azentspublicclient.models.workspace_runtime_profile_default_replace_request import (  # noqa: E501
    WorkspaceRuntimeProfileDefaultReplaceRequest,
)
from azentspublicclient.models.workspace_runtime_profile_policy import (
    WorkspaceRuntimeProfilePolicy,
)
from azentspublicclient.models.workspace_runtime_profile_policy_v1 import (
    WorkspaceRuntimeProfilePolicyV1,
)
from azentspublicclient.models.workspace_runtime_profile_replace_request import (
    WorkspaceRuntimeProfileReplaceRequest,
)
from azentspublicclient.models.workspace_runtime_profile_response import (
    WorkspaceRuntimeProfileResponse,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
    wait_until,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_SIGNUP_PASSWORD = "TestPass123!"


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _wait(driver: WebDriver) -> WebDriverWait[WebDriver]:
    """Return the bounded browser wait used by this surface."""
    return WebDriverWait(driver, 20)


def _login_main_web(
    driver: WebDriver,
    *,
    base_url: str,
    email: str,
) -> None:
    """Authenticate through the deployed Main Web login flow."""
    driver.delete_all_cookies()
    driver.get(f"{base_url}/login")
    email_input = _wait(driver).until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/login/password"))
    password_input = _wait(driver).until(
        ec.element_to_be_clickable((By.NAME, "password"))
    )
    password_input.send_keys(_SIGNUP_PASSWORD, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))


def _assert_visible_text(driver: WebDriver, text: str) -> None:
    """Wait for exact visible text."""
    _wait(driver).until(
        ec.visibility_of_element_located((By.XPATH, f"//*[normalize-space()={text!r}]"))
    )


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


@pytest.mark.runtime_provider
def test_admin_deletes_unreferenced_infrastructure_profile_without_runtime_disruption(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
    container_network: Network,
) -> None:
    """Delete applied-only infrastructure authority and retain the Runtime."""
    del azents_runtime_provider_docker_container, azents_engine_worker_container
    suffix = unique()
    admin_profiles = RuntimeProviderV1Api(admin_api_client)
    existing_profiles = admin_profiles.runtime_provider_v1_list_container_profiles(
        provider_id=_RUNTIME_PROVIDER_ID,
        include_disabled=True,
    )
    replacement_infrastructure = next(
        profile for profile in existing_profiles.items if profile.compatible
    )
    display_name = f"Deletion E2E {suffix}"
    container_spec = DockerContainerProfileSpecV1(
        profile_kind="docker_container",
        contract_family="docker.container-profile",
        schema_version=1,
        runner_resources=DockerContainerResources(
            cpu_reservation_millicores=None,
            cpu_limit_millicores=None,
            memory_reservation_bytes=None,
            memory_limit_bytes=None,
        ),
        network_name=container_network.name,
    )
    infrastructure = admin_profiles.runtime_provider_v1_create_container_profile(
        provider_id=_RUNTIME_PROVIDER_ID,
        runtime_infrastructure_profile_create_request=(
            RuntimeInfrastructureProfileCreateRequest(
                display_name=display_name,
                description="Temporary infrastructure deletion E2E Profile.",
                spec=RuntimeInfrastructureProfileSpec(container_spec),
            )
        ),
    )

    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"infrastructure-profile-delete-{suffix}@example.com",
    )
    handle = f"infrastructure-profile-delete-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Infrastructure Profile Delete {suffix}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-infrastructure-profile-delete")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        azents_public_server_url,
        token,
        handle,
        integration.id,
    )
    profile_api = RuntimeProfileV1Api(public_api_client)
    workspace_profile = profile_api.runtime_profile_v1_create_workspace_runtime_profile(
        handle=handle,
        workspace_runtime_profile_create_request=(
            WorkspaceRuntimeProfileCreateRequest(
                infrastructure_profile_id=infrastructure.id,
                display_name=f"Deletion Target {suffix}",
                description="Current reference for infrastructure deletion E2E.",
                policy=WorkspaceRuntimeProfilePolicy(
                    WorkspaceRuntimeProfilePolicyV1(
                        schema_version=1,
                        network_restriction=None,
                    )
                ),
            )
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Infrastructure Delete Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=workspace_profile.id,
        ),
        _headers=headers,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=token,
        workspace_handle=handle,
        agent_id=agent.id,
    )
    runtime_api = AgentRuntimeV1Api(public_api_client)
    runtime_before = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert runtime_before.runtime is not None
    assert runtime_before.runtime.workspace_path
    assert runtime_before.state is not None
    assert runtime_before.state.summary == RuntimeSummary.RUNNING
    assert runtime_before.configuration is not None
    assert runtime_before.configuration.applied is not None
    assert (
        runtime_before.configuration.applied.infrastructure_profile_id
        == infrastructure.id
    )
    prior_runtime_id = runtime_before.runtime.id
    prior_workspace_path = runtime_before.runtime.workspace_path
    prior_applied_sequence = runtime_before.configuration.applied.sequence
    prior_applied_digest = runtime_before.configuration.applied.digest

    blocked_impact = (
        admin_profiles.runtime_provider_v1_get_container_profile_deletion_impact(
            provider_id=_RUNTIME_PROVIDER_ID,
            profile_id=infrastructure.id,
            offset=0,
            limit=50,
        )
    )
    assert blocked_impact.blocking_reference_count == 1
    assert blocked_impact.applied_only_running_runtime_count == 0
    assert len(blocked_impact.references) == 1
    reference = blocked_impact.references[0]
    assert reference.workspace_handle == handle
    assert reference.workspace_runtime_profile_id == workspace_profile.id
    assert reference.selected_agent_count == 1
    assert reference.running_runtime_count == 1
    detail = admin_profiles.runtime_provider_v1_get_workspace_profile_admin_detail(
        handle=handle,
        profile_id=workspace_profile.id,
    )
    assert detail.infrastructure_profile_id == infrastructure.id
    assert detail.selected_agent_count == 1
    assert detail.running_runtime_count == 1

    with pytest.raises(AdminApiException) as blocked_delete:
        admin_profiles.runtime_provider_v1_delete_container_profile(
            provider_id=_RUNTIME_PROVIDER_ID,
            profile_id=infrastructure.id,
            runtime_infrastructure_profile_delete_request=(
                RuntimeInfrastructureProfileDeleteRequest(
                    expected_version=infrastructure.version,
                )
            ),
        )
    assert cast(Any, blocked_delete.value).status == 409

    replaced_profile = profile_api.runtime_profile_v1_replace_workspace_runtime_profile(
        profile_id=workspace_profile.id,
        handle=handle,
        workspace_runtime_profile_replace_request=(
            WorkspaceRuntimeProfileReplaceRequest(
                expected_version=workspace_profile.version,
                infrastructure_profile_id=replacement_infrastructure.id,
                display_name=workspace_profile.display_name,
                description=workspace_profile.description,
                lifecycle=workspace_profile.lifecycle,
                policy=workspace_profile.policy,
            )
        ),
        _headers=headers,
    )
    assert replaced_profile.infrastructure_profile_id == replacement_infrastructure.id

    ready_impact: RuntimeInfrastructureProfileDeletionImpactResponse | None = None

    def deletion_ready() -> bool:
        nonlocal ready_impact
        ready_impact = (
            admin_profiles.runtime_provider_v1_get_container_profile_deletion_impact(
                provider_id=_RUNTIME_PROVIDER_ID,
                profile_id=infrastructure.id,
                offset=0,
                limit=50,
            )
        )
        return (
            ready_impact.blocking_reference_count == 0
            and ready_impact.applied_only_running_runtime_count == 1
        )

    wait_until(
        deletion_ready,
        timeout=60,
        interval=1,
        message="Infrastructure Profile deletion impact did not become applied-only",
    )
    deletion = admin_profiles.runtime_provider_v1_delete_container_profile(
        provider_id=_RUNTIME_PROVIDER_ID,
        profile_id=infrastructure.id,
        runtime_infrastructure_profile_delete_request=(
            RuntimeInfrastructureProfileDeleteRequest(
                expected_version=infrastructure.version,
            )
        ),
    )
    assert deletion.profile_id == infrastructure.id

    runtime_after = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert runtime_after.runtime is not None
    assert runtime_after.runtime.id == prior_runtime_id
    assert runtime_after.runtime.workspace_path == prior_workspace_path
    assert runtime_after.state is not None
    assert runtime_after.state.summary == RuntimeSummary.RUNNING
    assert runtime_after.configuration is not None
    assert runtime_after.configuration.applied is not None
    assert runtime_after.configuration.applied.sequence == prior_applied_sequence
    assert runtime_after.configuration.applied.digest == prior_applied_digest
    assert (
        runtime_after.configuration.applied.infrastructure_profile_id
        == infrastructure.id
    )
    detail_after = (
        admin_profiles.runtime_provider_v1_get_workspace_profile_admin_detail(
            handle=handle,
            profile_id=workspace_profile.id,
        )
    )
    assert detail_after.infrastructure_profile_id == replacement_infrastructure.id

    with pytest.raises(AdminApiException) as absent_profile:
        admin_profiles.runtime_provider_v1_get_container_profile(
            provider_id=_RUNTIME_PROVIDER_ID,
            profile_id=infrastructure.id,
        )
    assert cast(Any, absent_profile.value).status == 404
    recreated = admin_profiles.runtime_provider_v1_create_container_profile(
        provider_id=_RUNTIME_PROVIDER_ID,
        runtime_infrastructure_profile_create_request=(
            RuntimeInfrastructureProfileCreateRequest(
                display_name=display_name,
                description="Recreated infrastructure deletion E2E Profile.",
                spec=RuntimeInfrastructureProfileSpec(container_spec),
            )
        ),
    )
    assert recreated.id != infrastructure.id
    assert recreated.display_name == display_name


@pytest.mark.web_surface
def test_owner_deletes_runtime_profile_in_web_and_running_runtime_is_retained(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
) -> None:
    """Delete a selected/default Profile in Web and verify retained Runtime state."""
    del azents_runtime_provider_docker_container, azents_engine_worker_container
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-profile-delete-web-{suffix}@example.com",
    )
    handle = f"runtime-profile-delete-web-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Profile Delete Web {suffix}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-profile-delete-web")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        azents_public_server_url,
        token,
        handle,
        integration.id,
    )
    profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    profile_api = RuntimeProfileV1Api(public_api_client)
    profile = profile_api.runtime_profile_v1_get_workspace_runtime_profile(
        profile_id=profile_id,
        handle=handle,
        _headers=headers,
    )
    default_state = (
        profile_api.runtime_profile_v1_get_workspace_runtime_profile_default(
            handle=handle,
            _headers=headers,
        )
    )
    profile_api.runtime_profile_v1_replace_workspace_runtime_profile_default(
        handle=handle,
        workspace_runtime_profile_default_replace_request=(
            WorkspaceRuntimeProfileDefaultReplaceRequest(
                expected_version=default_state.version,
                runtime_profile_id=profile.id,
            )
        ),
        _headers=headers,
    )
    agent_api = AgentV1Api(public_api_client)
    agent = agent_api.agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Profile Delete Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=profile.id,
        ),
        _headers=headers,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=token,
        workspace_handle=handle,
        agent_id=agent.id,
    )
    runtime_api = AgentRuntimeV1Api(public_api_client)
    runtime_before = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert runtime_before.runtime is not None
    assert runtime_before.runtime.workspace_path
    assert runtime_before.configuration is not None
    assert runtime_before.configuration.status == "applied"
    assert runtime_before.configuration.applied is not None
    assert (
        runtime_before.configuration.applied.workspace_runtime_profile_id == profile.id
    )
    prior_runtime_id = runtime_before.runtime.id
    prior_workspace_path = runtime_before.runtime.workspace_path
    prior_applied_sequence = runtime_before.configuration.applied.sequence
    prior_applied_digest = runtime_before.configuration.applied.digest

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=email,
    )
    browser_driver.get(f"{azents_main_web_url}/w/{handle}/settings/runtime-profiles")
    _assert_visible_text(browser_driver, "Runtime profiles")
    _assert_visible_text(browser_driver, profile.display_name)
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//button[@aria-label={'Delete ' + profile.display_name!r}]",
            )
        )
    ).click()
    _assert_visible_text(browser_driver, "Permanently delete runtime profile")
    confirmation_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//label[normalize-space()='Runtime profile name']/following::input[1]",
            )
        )
    )
    confirmation_input.send_keys(profile.display_name)
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//*[@role='dialog']//label[contains(normalize-space(), "
                "'I understand that this deletion is permanent')]",
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//button[normalize-space()='Delete profile permanently']",
            )
        )
    ).click()
    _assert_visible_text(
        browser_driver,
        f"{profile.display_name} was permanently deleted",
    )
    _assert_visible_text(browser_driver, "The workspace default was cleared.")
    _assert_visible_text(browser_driver, "1 agent selection was cleared.")
    _assert_visible_text(
        browser_driver,
        "1 running runtime kept its applied configuration and storage.",
    )
    _assert_visible_text(
        browser_driver,
        "No active recreation operations were superseded.",
    )
    _wait(browser_driver).until(
        ec.invisibility_of_element_located(
            (
                By.XPATH,
                f"//tr[.//*[normalize-space()={profile.display_name!r}]]",
            )
        )
    )

    profiles = profile_api.runtime_profile_v1_list_workspace_runtime_profiles(
        handle=handle,
        include_disabled=True,
        _headers=headers,
    )
    assert all(item.id != profile.id for item in profiles.items)
    with pytest.raises(ApiException) as deleted_profile_error:
        profile_api.runtime_profile_v1_get_workspace_runtime_profile(
            profile_id=profile.id,
            handle=handle,
            _headers=headers,
        )
    assert cast(Any, deleted_profile_error.value).status == 404
    default_after = (
        profile_api.runtime_profile_v1_get_workspace_runtime_profile_default(
            handle=handle,
            _headers=headers,
        )
    )
    assert default_after.runtime_profile_id is None
    agent_after = agent_api.agent_v1_get_agent(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert agent_after.runtime_profile_id is None
    assert agent_after.runtime_profile_available is False
    assert (
        agent_after.runtime_profile_availability_reason_code
        == "runtime_profile_unconfigured"
    )

    runtime_after = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert runtime_after.runtime_profile_id is None
    assert runtime_after.runtime_profile_status == "profile_required"
    assert runtime_after.runtime is not None
    assert runtime_after.runtime.id == prior_runtime_id
    assert runtime_after.runtime.workspace_path == prior_workspace_path
    assert runtime_after.state is not None
    assert runtime_after.state.summary == RuntimeSummary.RUNNING
    assert runtime_after.configuration is not None
    assert runtime_after.configuration.status == "profile_required"
    assert runtime_after.configuration.desired is not None
    assert runtime_after.configuration.desired.status == "unconfigured"
    assert runtime_after.configuration.desired.reason_code == "runtime_profile_required"
    assert runtime_after.configuration.applied is not None
    assert runtime_after.configuration.applied.sequence == prior_applied_sequence
    assert runtime_after.configuration.applied.digest == prior_applied_digest
    assert (
        runtime_after.configuration.applied.workspace_runtime_profile_id == profile.id
    )
    assert runtime_after.actions.start is False
    assert runtime_after.actions.restart is False
    assert runtime_after.actions.reset is False
    assert runtime_after.actions.use_runner is False
    assert runtime_after.actions.stop is True
    assert runtime_after.actions.observe is True
