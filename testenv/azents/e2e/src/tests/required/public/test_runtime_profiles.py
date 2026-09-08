"""Workspace-owned Runtime Profile integrated E2E journeys."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from typing import Any, Literal, cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    RuntimeRunnerControlStreamClosed,
)
from azents_runtime_control.runner import (
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerRegistration,
    RunnerRegistrationAccepted,
    RunnerStateReport,
    RuntimeRunnerEventType,
    RuntimeRunnerState,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
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
from azentspublicclient.models.agent_workspace_directory_response import (
    AgentWorkspaceDirectoryResponse,
)
from azentspublicclient.models.agent_workspace_mkdir_request import (
    AgentWorkspaceMkdirRequest,
)
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.runtime_provider_connection_state import (
    RuntimeProviderConnectionState,
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
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.workspace_runtime_profile_default_replace_request import (  # noqa: E501
    WorkspaceRuntimeProfileDefaultReplaceRequest,
)
from azentspublicclient.models.workspace_runtime_profile_response import (
    WorkspaceRuntimeProfileResponse,
)
from redis import Redis
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer

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
_RUNTIME_PROVIDER_REGISTERED_MARKER = "Runtime Provider registered"
_RUNTIME_RUNNER_STALE_CLOSE_MARKER = (
    "Runtime Runner stream close ignored for stale generation"
)
_SIGNUP_PASSWORD = "TestPass123!"
type _StaleRunnerAction = Literal["heartbeat", "report", "result", "revoke"]


@dataclasses.dataclass(frozen=True)
class _RunnerProbeSettings:
    """Secret-bearing Runner probe settings retained only inside one E2E process."""

    endpoint: str
    auth_token: str = dataclasses.field(repr=False)
    registration: RunnerRegistration


@dataclasses.dataclass(frozen=True)
class _InflightProbeOperation:
    """One real Public API operation retained by a controlled Runner probe."""

    client: GrpcRunnerControlClient
    accepted: RunnerRegistrationAccepted
    operation: RunnerOperationEnvelope
    response_task: asyncio.Task[requests.Response]
    path: str


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


def _runtime_provider_registration_count(container: DockerContainer) -> int:
    """Count completed Provider registrations in deterministic container logs."""
    stdout, stderr = container.get_logs()
    return (stdout.decode(errors="replace") + stderr.decode(errors="replace")).count(
        _RUNTIME_PROVIDER_REGISTERED_MARKER
    )


def _container_log_marker_count(container: DockerContainer, marker: str) -> int:
    """Count one secret-free marker across a deterministic container's logs."""
    stdout, stderr = container.get_logs()
    return (stdout.decode(errors="replace") + stderr.decode(errors="replace")).count(
        marker
    )


def _runner_probe_settings(
    *,
    runtime_id: str,
    provider_container: DockerContainer,
    runtime_control_container: DockerContainer,
) -> _RunnerProbeSettings:
    """Read one running E2E Runner's generated credential and policy evidence."""
    docker_client = provider_container.get_wrapped_container().client
    if docker_client is None:
        raise AssertionError("Docker Runtime Provider client is unavailable")
    matches = docker_client.containers.list(
        all=True,
        filters={
            "label": [
                "azents/managed-by=azents-runtime-provider-docker",
                f"azents/runtime-id={runtime_id}",
            ]
        },
    )
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one Docker Runtime Runner for {runtime_id}, found {len(matches)}"
        )
    runner = matches[0]
    runner.reload()
    raw_environment = runner.attrs.get("Config", {}).get("Env", [])
    if not isinstance(raw_environment, list) or not all(
        isinstance(item, str) for item in raw_environment
    ):
        raise AssertionError("Docker Runtime Runner environment is unavailable")
    environment = {
        name: value
        for item in raw_environment
        if "=" in item
        for name, value in (item.split("=", 1),)
    }
    required = (
        "AZ_RUNTIME_RUNNER_AUTH_TOKEN",
        "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID",
        "AZ_RUNTIME_CONFIGURATION_SEQUENCE",
        "AZ_RUNTIME_CONFIGURATION_DIGEST",
        "AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION",
        "HOME",
    )
    missing = [name for name in required if not environment.get(name)]
    if missing:
        raise AssertionError(
            "Docker Runtime Runner environment is incomplete: "
            f"{', '.join(sorted(missing))}"
        )
    endpoint = (
        f"{runtime_control_container.get_container_host_ip()}:"
        f"{runtime_control_container.get_exposed_port(8030)}"
    )
    return _RunnerProbeSettings(
        endpoint=endpoint,
        auth_token=environment["AZ_RUNTIME_RUNNER_AUTH_TOKEN"],
        registration=RunnerRegistration(
            runtime_id=runtime_id,
            runner_id=f"stale-probe-{unique()}",
            protocol_version=RUNNER_TRANSFER_PROTOCOL_VERSION,
            capabilities=(RUNNER_TRANSFER_CAPABILITY,),
            health="ready",
            workspace_path=environment["HOME"],
            metadata={},
            auth_credential_id=environment["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"],
            runtime_configuration=RuntimeConfigurationEvidence(
                configuration_sequence=int(
                    environment["AZ_RUNTIME_CONFIGURATION_SEQUENCE"]
                ),
                digest=environment["AZ_RUNTIME_CONFIGURATION_DIGEST"],
                desired_generation=int(
                    environment["AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION"]
                ),
            ),
        ),
    )


async def _wait_for_runner_generation_above(
    runtime_api: AgentRuntimeV1Api,
    *,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    generation: int,
) -> AgentRuntimeResponse:
    """Wait for the real Runner to replace one probe generation."""
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        current = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        )
        if (
            current.runtime is not None
            and current.runtime.runner_generation is not None
            and current.lifecycle is not None
            and int(current.runtime.runner_generation) > generation
            and current.lifecycle.availability == "ready"
            and current.actions.use_runner
        ):
            return current
        await asyncio.sleep(0.5)
    raise AssertionError("Real Runner did not replace the stale E2E probe")


async def _start_inflight_probe_operation(
    *,
    settings: _RunnerProbeSettings,
    public_server_url: str,
    token: str,
    runtime_api: AgentRuntimeV1Api,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    path: str,
) -> _InflightProbeOperation:
    """Start one real Workspace operation and hold its final Runner result."""
    operation_received = asyncio.Event()
    operations: list[RunnerOperationEnvelope] = []

    async def capture_operation(operation: RunnerOperationEnvelope) -> None:
        operations.append(operation)
        operation_received.set()

    client = GrpcRunnerControlClient.from_endpoint(
        settings.endpoint,
        runner_auth_token=settings.auth_token,
        tls=None,
        allow_insecure=True,
    )
    client.set_operation_handler(capture_operation)
    accepted = await client.register_runner(
        settings.registration,
        connection_id=f"inflight-probe-{unique()}",
        registered_at=datetime.now(UTC),
    )
    await client.report_runner_state(
        RunnerStateReport(
            runtime_id=accepted.runtime_id,
            runner_id=accepted.runner_id,
            runner_generation=accepted.generation,
            runner_state=RuntimeRunnerState.READY,
            capabilities=settings.registration.capabilities,
            active_operation_ids=(),
            health="ready",
            diagnostic={"source": "inflight-probe"},
            workspace_path=settings.registration.workspace_path,
            reported_at=datetime.now(UTC),
            runtime_configuration=settings.registration.runtime_configuration,
        )
    )
    projection_deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < projection_deadline:
        projected = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        )
        if (
            projected.runtime is not None
            and projected.runtime.runner_generation == str(accepted.generation)
            and projected.runtime.runner_state.value == "ready"
        ):
            break
        await asyncio.sleep(0.2)
    else:
        await client.close()
        raise AssertionError("Runner probe generation was not durably projected")
    response_task = asyncio.create_task(
        asyncio.to_thread(
            requests.post,
            f"{public_server_url}/chat/v1/agents/{agent_id}/workspace/directories",
            headers=_headers(token),
            json={"path": path, "parents": False},
            timeout=150,
        )
    )
    try:
        await asyncio.wait_for(operation_received.wait(), timeout=10)
        operation = operations[0]
        assert operation.operation_type == "file.mkdir"
        assert operation.payload["path"] == path
        assert await client.start_runner_operation(operation)
    except asyncio.CancelledError:
        await client.close()
        if not response_task.done():
            response_task.cancel()
        raise
    except Exception:
        await client.close()
        if not response_task.done():
            response_task.cancel()
        raise
    return _InflightProbeOperation(
        client=client,
        accepted=accepted,
        operation=operation,
        response_task=response_task,
        path=path,
    )


async def _assert_inflight_request_did_not_succeed(
    inflight: _InflightProbeOperation,
) -> None:
    """Require one lost or stale operation to avoid an HTTP success response."""
    response = await inflight.response_task
    assert response.status_code == 400


def _assert_workspace_path_missing(
    workspace_api: ChatV1Api,
    *,
    agent_id: str,
    path: str,
    headers: dict[str, str],
) -> None:
    """Require that a rejected synthetic result created no Runtime path."""
    with pytest.raises(ApiException) as error:
        workspace_api.chat_v1_read_agent_workspace_path(
            agent_id=agent_id,
            path=path,
            _headers=headers,
        )
    assert cast(Any, error.value).status == 404


async def _wait_for_empty_store_recovery(
    runtime_api: AgentRuntimeV1Api,
    *,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    minimum_generation: int,
    provider_container: DockerContainer,
    prior_provider_registrations: int,
) -> AgentRuntimeResponse:
    """Wait for both Provider and Runner to recover after empty-store reset."""
    deadline = asyncio.get_running_loop().time() + 120
    while asyncio.get_running_loop().time() < deadline:
        current = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=handle,
            _headers=headers,
        )
        if (
            current.runtime is not None
            and current.runtime.runner_generation is not None
            and current.lifecycle is not None
            and _runtime_provider_registration_count(provider_container)
            > prior_provider_registrations
            and int(current.runtime.runner_generation) > minimum_generation
            and current.lifecycle.availability == "ready"
            and current.actions.use_runner
        ):
            return current
        await asyncio.sleep(0.5)
    raise AssertionError("Runtime did not recover with higher authority after reset")


async def _reset_with_inflight_operation(
    *,
    settings: _RunnerProbeSettings,
    public_server_url: str,
    token: str,
    runtime_api: AgentRuntimeV1Api,
    workspace_api: ChatV1Api,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    path: str,
    previous_generation: int,
    provider_container: DockerContainer,
    previous_provider_registrations: int,
    valkey_container: DockerContainer,
) -> AgentRuntimeResponse:
    """Clear Valkey with an active operation and require fail-closed recovery."""
    inflight = await _start_inflight_probe_operation(
        settings=settings,
        public_server_url=public_server_url,
        token=token,
        runtime_api=runtime_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        path=path,
    )
    redis = Redis(
        host=valkey_container.get_container_host_ip(),
        port=int(valkey_container.get_exposed_port(6379)),
        decode_responses=True,
    )
    try:
        await asyncio.to_thread(redis.flushall)
        recovered = await _wait_for_empty_store_recovery(
            runtime_api,
            agent_id=agent_id,
            handle=handle,
            headers=headers,
            minimum_generation=max(
                previous_generation,
                inflight.accepted.generation,
            ),
            provider_container=provider_container,
            prior_provider_registrations=previous_provider_registrations,
        )
        await _assert_inflight_request_did_not_succeed(inflight)
        _assert_workspace_path_missing(
            workspace_api,
            agent_id=agent_id,
            path=inflight.path,
            headers=headers,
        )
        return recovered
    finally:
        redis.close()
        await inflight.client.close()


async def _assert_stale_runner_action_is_fenced(
    action: _StaleRunnerAction,
    *,
    settings: _RunnerProbeSettings,
    public_server_url: str,
    token: str,
    runtime_api: AgentRuntimeV1Api,
    workspace_api: ChatV1Api,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    runtime_control_container: DockerContainer,
    valkey_container: DockerContainer,
) -> None:
    """Replace one probe, submit one stale action, and preserve current state."""
    inflight: _InflightProbeOperation | None = None
    if action == "result":
        inflight = await _start_inflight_probe_operation(
            settings=settings,
            public_server_url=public_server_url,
            token=token,
            runtime_api=runtime_api,
            agent_id=agent_id,
            handle=handle,
            headers=headers,
            path=f"{settings.registration.workspace_path}/stale-result-{unique()}",
        )
        client = inflight.client
        accepted = inflight.accepted
    else:
        client = GrpcRunnerControlClient.from_endpoint(
            settings.endpoint,
            runner_auth_token=settings.auth_token,
            tls=None,
            allow_insecure=True,
        )
        accepted = await client.register_runner(
            settings.registration,
            connection_id=f"stale-probe-{action}-{unique()}",
            registered_at=datetime.now(UTC),
        )
    current = await _wait_for_runner_generation_above(
        runtime_api,
        agent_id=agent_id,
        handle=handle,
        headers=headers,
        generation=accepted.generation,
    )
    assert current.runtime is not None
    assert current.runtime.runner_generation is not None
    current_generation = current.runtime.runner_generation
    current_runner_state = current.runtime.runner_state
    stale_close_count = _container_log_marker_count(
        runtime_control_container,
        _RUNTIME_RUNNER_STALE_CLOSE_MARKER,
    )
    try:
        if action == "heartbeat":
            with pytest.raises(RuntimeRunnerControlStreamClosed):
                await client.heartbeat_runner(
                    runtime_id=accepted.runtime_id,
                    generation=accepted.generation,
                    heartbeat_at=datetime.now(UTC),
                )
        elif action == "report":
            await client.report_runner_state(
                RunnerStateReport(
                    runtime_id=accepted.runtime_id,
                    runner_id=accepted.runner_id,
                    runner_generation=accepted.generation,
                    runner_state=RuntimeRunnerState.FAILED,
                    capabilities=settings.registration.capabilities,
                    active_operation_ids=(),
                    health="stale-probe",
                    diagnostic={"source": "stale-probe"},
                    workspace_path=settings.registration.workspace_path,
                    reported_at=datetime.now(UTC),
                    runtime_configuration=settings.registration.runtime_configuration,
                )
            )
            with pytest.raises(RuntimeRunnerControlStreamClosed):
                await client.heartbeat_runner(
                    runtime_id=accepted.runtime_id,
                    generation=accepted.generation,
                    heartbeat_at=datetime.now(UTC),
                )
        elif action == "result":
            assert inflight is not None
            redis = Redis(
                host=valkey_container.get_container_host_ip(),
                port=int(valkey_container.get_exposed_port(6379)),
                decode_responses=True,
            )
            operation_key = (
                "azents:agent-runtime:coordination:v2:operation:"
                f"operation:{inflight.operation.request_id}"
            )
            try:
                before_operation = redis.get(operation_key)
            finally:
                redis.close()
            assert isinstance(before_operation, str)
            operation_state = json.loads(before_operation)
            assert operation_state["status"] == "running"
            assert operation_state["final_event_cursor"] is None
            await client.append_runner_event(
                RunnerOperationEvent(
                    request_id=inflight.operation.request_id,
                    runtime_id=accepted.runtime_id,
                    generation=accepted.generation,
                    event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
                    payload={"created_path": inflight.path},
                    created_at=datetime.now(UTC),
                    final=True,
                )
            )
            with pytest.raises(RuntimeRunnerControlStreamClosed):
                await client.heartbeat_runner(
                    runtime_id=accepted.runtime_id,
                    generation=accepted.generation,
                    heartbeat_at=datetime.now(UTC),
                )
            redis = Redis(
                host=valkey_container.get_container_host_ip(),
                port=int(valkey_container.get_exposed_port(6379)),
                decode_responses=True,
            )
            try:
                assert redis.get(operation_key) == before_operation
            finally:
                redis.close()
            await _assert_inflight_request_did_not_succeed(inflight)
            _assert_workspace_path_missing(
                workspace_api,
                agent_id=agent_id,
                path=inflight.path,
                headers=headers,
            )
        else:
            await client.close()
            wait_until(
                lambda: (
                    _container_log_marker_count(
                        runtime_control_container,
                        _RUNTIME_RUNNER_STALE_CLOSE_MARKER,
                    )
                    > stale_close_count
                ),
                timeout=15,
                interval=0.2,
                message="Runtime Control did not ignore the stale Runner revoke",
            )
    finally:
        await client.close()

    after = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id,
        handle=handle,
        _headers=headers,
    )
    assert after.runtime is not None
    assert after.runtime.runner_generation == current_generation
    assert after.runtime.runner_state == current_runner_state


async def _assert_stale_runner_actions_are_fenced(
    *,
    settings: _RunnerProbeSettings,
    public_server_url: str,
    token: str,
    runtime_api: AgentRuntimeV1Api,
    workspace_api: ChatV1Api,
    agent_id: str,
    handle: str,
    headers: dict[str, str],
    runtime_control_container: DockerContainer,
    valkey_container: DockerContainer,
) -> None:
    """Exercise stale heartbeat, report, result, and revoke through real gRPC."""
    for action in ("heartbeat", "report", "result", "revoke"):
        await _assert_stale_runner_action_is_fenced(
            action,
            settings=settings,
            public_server_url=public_server_url,
            token=token,
            runtime_api=runtime_api,
            workspace_api=workspace_api,
            agent_id=agent_id,
            handle=handle,
            headers=headers,
            runtime_control_container=runtime_control_container,
            valkey_container=valkey_container,
        )


def _restart_runtime_provider(container: DockerContainer) -> None:
    """Restart the deterministic Provider and wait for a new registration."""
    prior_registrations = _runtime_provider_registration_count(container)
    wrapped_container = container.get_wrapped_container()
    wrapped_container.start()

    def registered_again() -> bool:
        wrapped_container.reload()
        if wrapped_container.status == "exited":
            raise AssertionError("Runtime Provider exited while restarting")
        return _runtime_provider_registration_count(container) > prior_registrations

    wait_until(
        registered_again,
        timeout=60,
        interval=1,
        message="Runtime Provider did not register after restart",
    )


def test_empty_valkey_recovers_runtime_with_higher_generation_and_new_work(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_control_container: DockerContainer,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
    valkey_container: DockerContainer,
) -> None:
    """An empty Valkey instance loses live work but not Runtime authority."""
    del azents_engine_worker_container
    suffix = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-empty-valkey-{suffix}@example.com",
    )
    handle = f"runtime-empty-valkey-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Empty Valkey {suffix}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-empty-valkey")),
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
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Empty Valkey {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=profile_id,
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
    before = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert before.runtime is not None
    assert before.runtime.runner_generation is not None
    assert before.runtime.workspace_path
    previous_generation = int(before.runtime.runner_generation)
    assert previous_generation > 0
    previous_provider_registrations = _runtime_provider_registration_count(
        azents_runtime_provider_docker_container
    )
    workspace_api = ChatV1Api(public_api_client)
    settings = _runner_probe_settings(
        runtime_id=before.runtime.id,
        provider_container=azents_runtime_provider_docker_container,
        runtime_control_container=azents_runtime_control_container,
    )
    recovered = asyncio.run(
        _reset_with_inflight_operation(
            settings=settings,
            public_server_url=azents_public_server_url,
            token=token,
            runtime_api=runtime_api,
            workspace_api=workspace_api,
            agent_id=agent.id,
            handle=handle,
            headers=headers,
            path=(f"{before.runtime.workspace_path}/lost-inflight-reset-{suffix}"),
            previous_generation=previous_generation,
            provider_container=azents_runtime_provider_docker_container,
            previous_provider_registrations=previous_provider_registrations,
            valkey_container=valkey_container,
        )
    )
    assert recovered.runtime is not None
    assert recovered.runtime.workspace_path
    asyncio.run(
        _assert_stale_runner_actions_are_fenced(
            settings=settings,
            public_server_url=azents_public_server_url,
            token=token,
            runtime_api=runtime_api,
            workspace_api=workspace_api,
            agent_id=agent.id,
            handle=handle,
            headers=headers,
            runtime_control_container=azents_runtime_control_container,
            valkey_container=valkey_container,
        )
    )

    directory = f"{recovered.runtime.workspace_path}/empty-valkey-{suffix}"
    workspace_api.chat_v1_create_agent_workspace_directory(
        agent_id=agent.id,
        agent_workspace_mkdir_request=AgentWorkspaceMkdirRequest(
            path=directory,
            parents=False,
        ),
        _headers=headers,
    )
    created = workspace_api.chat_v1_read_agent_workspace_path(
        agent_id=agent.id,
        path=directory,
        _headers=headers,
    )
    assert isinstance(created.actual_instance, AgentWorkspaceDirectoryResponse)


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
    reconciled_runtime: AgentRuntimeResponse | None = None

    def runtime_reconciled_without_compute() -> bool:
        nonlocal reconciled_runtime
        current = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=explicit_agent.id,
            handle=handle,
            _headers=headers,
        )
        runtime = current.runtime
        lifecycle = current.lifecycle
        configuration = current.configuration
        if runtime is None or lifecycle is None or configuration is None:
            return False
        reconciled_runtime = current
        return (
            lifecycle.availability == "stopped"
            and lifecycle.convergence == "stable"
            and configuration.status == "configured_not_created"
            and configuration.desired is not None
            and configuration.applied is None
            and runtime.workspace_path is None
            and runtime.last_lifecycle_command is None
            and lifecycle.provider.connection
            is RuntimeProviderConnectionState.CONNECTED
            and current.actions.start
        )

    wait_until(
        runtime_reconciled_without_compute,
        timeout=30,
        interval=1,
        message=(
            "Runtime Profile reconciliation did not establish a stopped logical Runtime"
        ),
    )
    assert reconciled_runtime is not None
    assert reconciled_runtime.capability == AgentRuntimeCapability.MANAGED
    assert reconciled_runtime.runtime_profile_id == explicit_profile_id
    assert reconciled_runtime.runtime is not None
    assert (
        reconciled_runtime.runtime.runtime_provider_id == explicit_profile.provider_id
    )
    assert reconciled_runtime.lifecycle is not None
    assert reconciled_runtime.lifecycle.availability == "stopped"
    assert reconciled_runtime.lifecycle.convergence == "stable"
    assert reconciled_runtime.configuration is not None
    assert reconciled_runtime.configuration.status == "configured_not_created"
    assert reconciled_runtime.configuration.desired is not None
    assert (
        reconciled_runtime.configuration.desired.workspace_runtime_profile_id
        == explicit_profile_id
    )
    assert reconciled_runtime.configuration.applied is None
    assert reconciled_runtime.actions.add is False
    assert reconciled_runtime.actions.start is True

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
        lifecycle = applied_runtime.lifecycle
        return (
            configuration is not None
            and lifecycle is not None
            and configuration.status == "applied"
            and lifecycle.availability == "ready"
            and lifecycle.convergence == "stable"
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

    assert applied_runtime.runtime is not None
    assert applied_runtime.runtime.workspace_path
    sentinel_path = (
        f"{applied_runtime.runtime.workspace_path}/"
        f".runtime-profile-recreation-sentinel-{unique()}"
    )
    workspace_api = ChatV1Api(public_api_client)
    workspace_api.chat_v1_create_agent_workspace_directory(
        agent_id=explicit_agent.id,
        agent_workspace_mkdir_request=AgentWorkspaceMkdirRequest(
            path=sentinel_path,
            parents=False,
        ),
        _headers=headers,
    )
    sentinel_before_recreation = workspace_api.chat_v1_read_agent_workspace_path(
        agent_id=explicit_agent.id,
        path=sentinel_path,
        _headers=headers,
    )
    assert isinstance(
        sentinel_before_recreation.actual_instance,
        AgentWorkspaceDirectoryResponse,
    )

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
        lifecycle = recreated_runtime.lifecycle
        current_applied = configuration.applied if configuration is not None else None
        return (
            configuration is not None
            and lifecycle is not None
            and configuration.status == "applied"
            and current_applied is not None
            and current_applied.sequence > prior_applied_sequence
            and lifecycle.availability == "ready"
            and lifecycle.convergence == "stable"
        )

    wait_until(
        recreated_runtime_applied,
        timeout=120,
        interval=1,
        message="Recreated Runtime did not apply its replacement state",
    )
    assert recreated_runtime is not None
    assert recreated_runtime.configuration is not None
    assert recreated_runtime.lifecycle is not None
    recreated_desired = recreated_runtime.configuration.desired
    recreated_applied = recreated_runtime.configuration.applied
    assert recreated_desired is not None
    assert recreated_applied is not None
    assert recreated_applied.sequence == recreated_desired.sequence
    assert recreated_applied.sequence > prior_applied_sequence
    assert recreated_applied.target_generation == recreated_desired.target_generation
    assert (
        recreated_desired.target_generation
        == recreated_runtime.lifecycle.desired_generation
    )
    assert recreated_applied.digest == recreated_desired.digest
    assert recreated_desired.provider_reported_digest == recreated_desired.digest
    assert recreated_desired.runner_reported_digest == recreated_desired.digest
    assert recreated_desired.workspace_runtime_profile_id == explicit_profile_id
    assert recreated_applied.workspace_runtime_profile_id == explicit_profile_id
    assert (
        recreated_desired.workspace_runtime_profile_version == explicit_profile.version
    )
    assert (
        recreated_applied.workspace_runtime_profile_version == explicit_profile.version
    )
    assert recreated_desired.provider_id == runtime_provider_resource_id
    assert recreated_applied.provider_id == runtime_provider_resource_id
    assert (
        recreated_desired.provider_capability_revision_id
        == explicit_profile.capability_revision_id
    )
    assert (
        recreated_applied.provider_capability_revision_id
        == explicit_profile.capability_revision_id
    )
    assert (
        recreated_desired.infrastructure_profile_id
        == explicit_profile.infrastructure_profile_id
    )
    assert (
        recreated_applied.infrastructure_profile_id
        == explicit_profile.infrastructure_profile_id
    )
    assert (
        recreated_desired.infrastructure_profile_version
        == explicit_profile.infrastructure_profile_version
    )
    assert (
        recreated_applied.infrastructure_profile_version
        == explicit_profile.infrastructure_profile_version
    )
    assert recreated_desired.provider_acknowledged_at is not None
    assert recreated_desired.runner_observed_at is not None
    assert recreated_applied.applied_at is not None
    sentinel_after_recreation = workspace_api.chat_v1_read_agent_workspace_path(
        agent_id=explicit_agent.id,
        path=sentinel_path,
        _headers=headers,
    )
    assert isinstance(
        sentinel_after_recreation.actual_instance,
        AgentWorkspaceDirectoryResponse,
    )

    _stop_runtime_provider(azents_runtime_provider_docker_container)
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
        retained_runtime: AgentRuntimeResponse | None = None

        def ready_runner_without_host_authority() -> bool:
            nonlocal retained_runtime
            retained_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
                agent_id=explicit_agent.id,
                handle=handle,
                _headers=headers,
            )
            lifecycle = retained_runtime.lifecycle
            actions = retained_runtime.actions
            return (
                lifecycle is not None
                and lifecycle.availability == "ready"
                and lifecycle.convergence == "stable"
                and actions.use_runner
                and not actions.start
                and not actions.stop
                and not actions.restart
                and not actions.reset
            )

        wait_until(
            ready_runner_without_host_authority,
            timeout=30,
            interval=1,
            message=("Ready Runner did not retain data authority after Provider loss"),
        )
        assert retained_runtime is not None
        assert retained_runtime.lifecycle is not None
        assert retained_runtime.lifecycle.availability == "ready"
        assert retained_runtime.lifecycle.convergence == "stable"
        assert retained_runtime.actions.use_runner is True
        assert retained_runtime.actions.start is False
        assert retained_runtime.actions.stop is False
        assert retained_runtime.actions.restart is False
        assert retained_runtime.actions.reset is False
        sentinel_while_provider_disconnected = (
            workspace_api.chat_v1_read_agent_workspace_path(
                agent_id=explicit_agent.id,
                path=sentinel_path,
                _headers=headers,
            )
        )
        assert isinstance(
            sentinel_while_provider_disconnected.actual_instance,
            AgentWorkspaceDirectoryResponse,
        )
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


def run_owner_deletes_runtime_profile_in_web_and_running_runtime_is_retained(
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
    assert runtime_after.lifecycle is not None
    assert runtime_after.lifecycle.availability == "ready"
    assert runtime_after.lifecycle.convergence == "stable"
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
    assert runtime_after.actions.use_runner is True
    assert runtime_after.actions.stop is True
    assert runtime_after.actions.observe is True
