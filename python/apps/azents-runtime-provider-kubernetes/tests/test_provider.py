"""Kubernetes Runtime Provider lifecycle tests."""

import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    digest_effective_policy,
)
from azents_runtime_control.provider import (
    RuntimeContainerAuth as ControlRuntimeContainerAuth,
)
from azents_runtime_control.provider import (
    RuntimeIdentity as ControlRuntimeIdentity,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommand as ControlRuntimeLifecycleCommand,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as ControlRuntimeLifecycleCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as ControlRuntimeProviderObservedState,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResources,
    EmptyDirVolume,
    IpBlock,
    KubernetesApi,
    LeaseResource,
    LocalObjectReference,
    NetworkPolicyEgressRule,
    NetworkPolicyPeer,
    NetworkPolicyResource,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimVolume,
    PodResource,
    PodStatus,
    PodWatchEvent,
    Toleration,
)
from azents_runtime_provider_kubernetes.models import (
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
)
from azents_runtime_provider_kubernetes.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    InvalidResetFinalDesiredState,
    InvalidRunnerEnvironment,
    InvalidWorkspacePath,
    KubernetesRuntimeProvider,
    KubernetesRuntimeProviderConfig,
)
from azents_runtime_provider_kubernetes.runtime_control import (
    KubernetesRuntimeControlAdapter,
)


class FakeKubernetesApi(KubernetesApi):
    """In-memory Kubernetes API fake."""

    def __init__(self) -> None:
        self.pods: dict[tuple[str, str], PodResource] = {}
        self.pvcs: dict[tuple[str, str], PersistentVolumeClaimResource] = {}
        self.network_policies: dict[tuple[str, str], NetworkPolicyResource] = {}
        self.deleted_pods: list[str] = []
        self.deleted_pod_grace_periods: list[int | None] = []
        self.deleted_pvcs: list[str] = []
        self.deleted_network_policies: list[str] = []
        self.watch_events: list[PodWatchEvent] = []
        self.fail_pod_deletion = False

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        """Return a Pod by name."""
        return self.pods.get((namespace, name))

    async def apply_pod(self, pod: PodResource) -> None:
        """Apply a Pod."""
        self.pods[(pod.metadata.namespace, pod.metadata.name)] = pod

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period_seconds: int | None = None,
    ) -> None:
        """Delete a Pod when present."""
        self.deleted_pods.append(name)
        self.deleted_pod_grace_periods.append(grace_period_seconds)
        if self.fail_pod_deletion:
            raise RuntimeError("Pod deletion failed")
        self.pods.pop((namespace, name), None)

    async def list_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PodResource]:
        """List Pods matching labels."""
        return tuple(
            pod
            for (pod_namespace, _), pod in self.pods.items()
            if pod_namespace == namespace
            and all(
                pod.metadata.labels.get(key) == value for key, value in labels.items()
            )
        )

    async def watch_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> AsyncIterator[PodWatchEvent]:
        """Watch Pods matching labels."""
        for event in self.watch_events:
            if event.pod.metadata.namespace != namespace:
                continue
            if all(
                event.pod.metadata.labels.get(key) == value
                for key, value in labels.items()
            ):
                yield event

    async def get_pvc(
        self,
        name: str,
        namespace: str,
    ) -> PersistentVolumeClaimResource | None:
        """Return a PVC by name."""
        return self.pvcs.get((namespace, name))

    async def apply_pvc(self, pvc: PersistentVolumeClaimResource) -> None:
        """Apply a PVC."""
        self.pvcs[(pvc.metadata.namespace, pvc.metadata.name)] = pvc

    async def delete_pvc(self, name: str, namespace: str) -> None:
        """Delete a PVC when present."""
        self.deleted_pvcs.append(name)
        self.pvcs.pop((namespace, name), None)

    async def list_pvcs(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PersistentVolumeClaimResource]:
        """List PVCs matching labels."""
        return tuple(
            pvc
            for (pvc_namespace, _), pvc in self.pvcs.items()
            if pvc_namespace == namespace
            and all(
                pvc.metadata.labels.get(key) == value for key, value in labels.items()
            )
        )

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        """Return a NetworkPolicy by name."""
        return self.network_policies.get((namespace, name))

    async def apply_network_policy(
        self,
        network_policy: NetworkPolicyResource,
    ) -> None:
        """Apply a NetworkPolicy."""
        key = (
            network_policy.metadata.namespace,
            network_policy.metadata.name,
        )
        self.network_policies[key] = network_policy

    async def delete_network_policy(self, name: str, namespace: str) -> None:
        """Delete a NetworkPolicy when present."""
        self.deleted_network_policies.append(name)
        self.network_policies.pop((namespace, name), None)

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Unused by provider tests."""
        return None

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Unused by provider tests."""


def _provider(api: FakeKubernetesApi) -> KubernetesRuntimeProvider:
    return _provider_with_runner_env(api, {})


def _provider_with_runner_env(
    api: FakeKubernetesApi,
    runner_env: Mapping[str, str],
) -> KubernetesRuntimeProvider:
    return KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="provider-k8s",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=ContainerResources(
                requests={"cpu": "500m", "memory": "1Gi"},
                limits={"cpu": "1500m", "memory": "2Gi"},
                claims=None,
            ),
            runner_env=runner_env,
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
        ),
    )


def test_provider_rejects_unmanaged_runner_environment() -> None:
    with pytest.raises(InvalidRunnerEnvironment, match="UNMANAGED"):
        _provider_with_runner_env(FakeKubernetesApi(), {"UNMANAGED": "value"})


def _command(
    command_type: RuntimeLifecycleCommandType,
    *,
    final_desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 1,
    provider_generation: int = 7,
    runner_image: str = "runner:latest",
    runner_auth_token: str = "runner-token-1",
    runner_auth_credential_id: str = "runner-credential-1",
    execution_policy: RuntimeExecutionPolicyEnvelope | None = None,
) -> RuntimeLifecycleCommand:
    return RuntimeLifecycleCommand(
        command_type=command_type,
        identity=RuntimeIdentity(
            runtime_id="runtime-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
        ),
        desired_generation=desired_generation,
        provider_generation=provider_generation,
        runner_image=runner_image,
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token=runner_auth_token,
            runner_auth_credential_id=runner_auth_credential_id,
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=final_desired_state,
        execution_policy=execution_policy
        or _execution_policy(desired_generation=desired_generation),
    )


def _control_command(
    command_type: ControlRuntimeLifecycleCommandType,
) -> ControlRuntimeLifecycleCommand:
    return ControlRuntimeLifecycleCommand(
        command_type=command_type,
        identity=ControlRuntimeIdentity(
            runtime_id="runtime-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
        ),
        desired_generation=1,
        provider_generation=7,
        runner_image="runner:latest",
        auth=ControlRuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token="runner-token-1",
            runner_auth_credential_id="runner-credential-1",
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=None,
        execution_policy=_execution_policy(),
    )


@pytest.mark.asyncio
async def test_start_creates_pvc_and_pod_with_workspace_mount() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    result = await provider.start(_command(RuntimeLifecycleCommandType.START))

    assert result.report.observed_state is RuntimeProviderObservedState.STARTING
    assert result.report.workspace_path == "/workspace/agent"
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    pvc = api.pvcs[("azents-runtime", "azents-runtime-runtime-1-workspace")]
    container = pod.spec.containers[0]
    env = {item.name: item.value for item in container.env}
    assert container.image == "runner:latest"
    assert container.working_dir == "/workspace/agent"
    assert container.resources == ContainerResources(
        requests={"cpu": "500m", "memory": "1Gi"},
        limits={"cpu": "1500m", "memory": "2Gi"},
        claims=None,
    )
    assert env["AZ_AGENT_WORKSPACE_PATH"] == "/workspace/agent"
    assert env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-1"
    assert env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"] == "runner-credential-1"
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert (
        pod.metadata.annotations["azents/execution-policy-snapshot-id"] == "snapshot-1"
    )
    assert pod.spec.service_account_name is None
    assert pod.spec.automount_service_account_token is False
    assert pod.spec.node_selector == {}
    assert pod.spec.tolerations == ()
    assert pod.spec.security_context is not None
    assert pod.spec.security_context.run_as_user is None
    assert pod.spec.security_context.run_as_group is None
    assert pod.spec.security_context.fs_group == 1000
    assert pod.spec.security_context.fs_group_change_policy == "OnRootMismatch"
    workspace_volume = pod.spec.volumes[0]
    assert isinstance(workspace_volume, PersistentVolumeClaimVolume)
    assert workspace_volume.claim_name == pvc.metadata.name
    assert pvc.spec.storage_class_name == "gp3"
    assert "azents/workspace-path" not in pod.metadata.labels
    assert "azents/workspace-path" not in pvc.metadata.labels
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert pvc.metadata.annotations["azents/workspace-path"] == "/workspace/agent"


@pytest.mark.asyncio
async def test_start_applies_configured_runner_limits() -> None:
    api = FakeKubernetesApi()
    runner_env = {
        name: str(index + 1) for index, name in enumerate(RUNNER_LIMIT_ENV_NAMES)
    }
    provider = _provider_with_runner_env(api, runner_env)

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    env = {item.name: item.value for item in pod.spec.containers[0].env}
    assert {name: env[name] for name in RUNNER_LIMIT_ENV_NAMES} == runner_env


@pytest.mark.asyncio
async def test_start_replaces_pod_when_runner_limit_is_removed() -> None:
    api = FakeKubernetesApi()
    limit_name = "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS"
    old_provider = _provider_with_runner_env(api, {limit_name: "12"})
    new_provider = _provider_with_runner_env(api, {})
    await old_provider.start(_command(RuntimeLifecycleCommandType.START))

    await new_provider.start(_command(RuntimeLifecycleCommandType.START))

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    env = {item.name: item.value for item in pod.spec.containers[0].env}
    assert limit_name not in env


@pytest.mark.asyncio
async def test_start_allows_omitted_runner_resources() -> None:
    api = FakeKubernetesApi()
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=None,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].resources is None


@pytest.mark.asyncio
async def test_start_preserves_generic_runner_resource_requirements() -> None:
    api = FakeKubernetesApi()
    resources = ContainerResources(
        requests={
            "cpu": "500m",
            "ephemeral-storage": "1Gi",
        },
        limits={
            "memory": "2Gi",
            "nvidia.com/gpu": 1,
        },
        claims=None,
    )
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=resources,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].resources == resources


@pytest.mark.asyncio
async def test_start_reuses_pod_with_kubernetes_default_tolerations() -> None:
    """Admission-added tolerations do not make an existing Runtime Pod stale."""
    api = FakeKubernetesApi()
    configured_toleration = Toleration(
        key="runtime",
        operator="Equal",
        value="azents",
        effect="NoSchedule",
    )
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=None,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            pod_tolerations=(configured_toleration,),
        ),
    )
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    default_tolerations = (
        Toleration(
            key="node.kubernetes.io/not-ready",
            operator="Exists",
            effect="NoExecute",
        ),
        Toleration(
            key="node.kubernetes.io/unreachable",
            operator="Exists",
            effect="NoExecute",
        ),
    )
    api.pods[pod_key] = dataclasses.replace(
        pod,
        spec=dataclasses.replace(
            pod.spec,
            tolerations=(configured_toleration, *default_tolerations),
        ),
    )

    await provider.start(command)

    assert api.deleted_pods == []
    assert tuple(api.pods[pod_key].spec.tolerations) == (
        configured_toleration,
        *default_tolerations,
    )


@pytest.mark.asyncio
async def test_start_reuses_pod_with_canonicalized_kubernetes_quantities() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(
        RuntimeLifecycleCommandType.START,
        execution_policy=_execution_policy(image_build=True),
    )
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    engine = pod.spec.containers[-1]
    assert engine.resources is not None
    assert engine.resources.limits is not None
    engine_storage = pod.spec.volumes[-1]
    assert isinstance(engine_storage, EmptyDirVolume)
    api.pods[pod_key] = dataclasses.replace(
        pod,
        spec=dataclasses.replace(
            pod.spec,
            containers=(
                *pod.spec.containers[:-1],
                dataclasses.replace(
                    engine,
                    resources=dataclasses.replace(
                        engine.resources,
                        limits={
                            **engine.resources.limits,
                            "cpu": "1000m",
                            "memory": "2Gi",
                            "ephemeral-storage": "10Gi",
                        },
                    ),
                ),
            ),
            volumes=(
                *pod.spec.volumes[:-1],
                dataclasses.replace(
                    engine_storage,
                    size_limit="8Gi",
                ),
            ),
        ),
    )

    await provider.start(command)

    assert api.deleted_pods == []


@pytest.mark.asyncio
async def test_runtime_control_adapter_reports_provider_workspace_path() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    adapter = KubernetesRuntimeControlAdapter(provider)

    result = await adapter.start(
        _control_command(ControlRuntimeLifecycleCommandType.START)
    )

    assert result.report.observed_state is ControlRuntimeProviderObservedState.STARTING
    assert result.report.workspace_path == "/workspace/agent"
    assert ("azents-runtime", "azents-runtime-runtime-1") in api.pods


@pytest.mark.asyncio
async def test_observe_running_pod_reports_running() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    api.pods[pod_key] = api.pods[pod_key].__class__(
        metadata=api.pods[pod_key].metadata,
        spec=api.pods[pod_key].spec,
        status=PodStatus(phase="Running", ready=True),
    )

    report = await provider.observe(_command(RuntimeLifecycleCommandType.OBSERVE))

    assert report.observed_state is RuntimeProviderObservedState.RUNNING
    assert report.reason == "pod_running"


@pytest.mark.asyncio
async def test_broadened_network_policy_is_not_ready_in_observe_or_failover() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = dataclasses.replace(
        api.pods[pod_key],
        status=PodStatus(phase="Running", ready=True),
    )
    api.pods[pod_key] = pod
    network_policy_key = (
        "azents-runtime",
        "azents-runtime-runtime-1-execution",
    )
    network_policy = api.network_policies[network_policy_key]
    api.network_policies[network_policy_key] = dataclasses.replace(
        network_policy,
        spec=dataclasses.replace(
            network_policy.spec,
            egress=(
                *network_policy.spec.egress,
                NetworkPolicyEgressRule(
                    peers=(
                        NetworkPolicyPeer(
                            namespace_selector=None,
                            pod_selector=None,
                            ip_block=IpBlock(
                                cidr="0.0.0.0/0",
                                except_cidrs=(),
                            ),
                        ),
                    ),
                    ports=(),
                ),
            ),
        ),
    )
    api.watch_events.append(PodWatchEvent(event_type="MODIFIED", pod=pod))

    command_report = await provider.observe(
        _command(RuntimeLifecycleCommandType.OBSERVE)
    )
    failover_reports = await provider.observe_known_runtimes()
    watch_reports = [report async for report in provider.watch_known_runtimes()]

    assert command_report.observed_state is RuntimeProviderObservedState.STARTING
    assert command_report.reason == "network_policy_not_ready"
    assert failover_reports[0].observed_state is RuntimeProviderObservedState.STARTING
    assert failover_reports[0].reason == "network_policy_not_ready"
    assert watch_reports[0].observed_state is RuntimeProviderObservedState.STARTING
    assert watch_reports[0].reason == "network_policy_not_ready"


@pytest.mark.asyncio
async def test_observe_deleting_pod_reports_stopping_before_running() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        metadata=dataclasses.replace(
            pod.metadata,
            deletion_timestamp=datetime(2026, 5, 26, tzinfo=UTC),
        ),
        status=PodStatus(phase="Running", ready=True),
    )

    report = await provider.observe(_command(RuntimeLifecycleCommandType.OBSERVE))

    assert report.observed_state is RuntimeProviderObservedState.STOPPING
    assert report.reason == "pod_deleting"


@pytest.mark.asyncio
async def test_observe_terminal_pod_reports_stopped() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        status=PodStatus(phase="Failed", ready=False),
    )

    report = await provider.observe(_command(RuntimeLifecycleCommandType.OBSERVE))

    assert report.observed_state is RuntimeProviderObservedState.STOPPED
    assert report.reason == "pod_failed"


@pytest.mark.asyncio
async def test_observe_node_not_ready_pod_reports_stopped() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        status=PodStatus(
            phase="Running",
            ready=False,
            ready_reason="NodeNotReady",
        ),
    )

    report = await provider.observe(_command(RuntimeLifecycleCommandType.OBSERVE))

    assert report.observed_state is RuntimeProviderObservedState.STOPPED
    assert report.reason == "pod_nodenotready"


@pytest.mark.asyncio
async def test_observe_container_create_error_reports_failed() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        status=PodStatus(
            phase="Pending",
            ready=False,
            waiting_reason="CreateContainerConfigError",
        ),
    )

    report = await provider.observe(_command(RuntimeLifecycleCommandType.OBSERVE))

    assert report.observed_state is RuntimeProviderObservedState.FAILED
    assert report.reason == "pod_createcontainerconfigerror"


@pytest.mark.asyncio
async def test_start_force_replaces_deleting_pod() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        metadata=dataclasses.replace(
            pod.metadata,
            deletion_timestamp=datetime(2026, 5, 26, tzinfo=UTC),
        ),
        status=PodStatus(phase="Running", ready=True),
    )

    result = await provider.start(_command(RuntimeLifecycleCommandType.START))

    assert api.deleted_pod_grace_periods == [0]
    assert result.report.observed_state is RuntimeProviderObservedState.STARTING
    assert ("azents-runtime", "azents-runtime-runtime-1") in api.pods


@pytest.mark.asyncio
async def test_start_applies_configured_pod_annotations() -> None:
    api = FakeKubernetesApi()
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=ContainerResources(
                requests={"cpu": "500m", "memory": "1Gi"},
                limits={"cpu": "1500m", "memory": "2Gi"},
                claims=None,
            ),
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            pod_annotations={"descheduler/no-evict": "true"},
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.metadata.annotations["descheduler/no-evict"] == "true"
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert (
        pod.metadata.annotations["azents/execution-policy-snapshot-id"] == "snapshot-1"
    )


@pytest.mark.asyncio
async def test_start_applies_configured_runtime_pod_scheduling() -> None:
    api = FakeKubernetesApi()
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=ContainerResources(
                requests={"cpu": "500m", "memory": "1Gi"},
                limits={"cpu": "1500m", "memory": "2Gi"},
                claims=None,
            ),
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            pod_node_selector={"azents.azents.io/runtime-isolation": "true"},
            pod_tolerations=(
                Toleration(
                    key="azents.azents.io/runtime-isolation",
                    operator="Equal",
                    value="true",
                    effect="NoSchedule",
                ),
            ),
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.node_selector == {"azents.azents.io/runtime-isolation": "true"}
    assert pod.spec.tolerations == (
        Toleration(
            key="azents.azents.io/runtime-isolation",
            operator="Equal",
            value="true",
            effect="NoSchedule",
        ),
    )


@pytest.mark.asyncio
async def test_start_applies_configured_runtime_pod_image_pull_secrets() -> None:
    api = FakeKubernetesApi()
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=None,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            image_pull_secrets=(LocalObjectReference(name="ecr-pull-secret"),),
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.image_pull_secrets == (
        LocalObjectReference(name="ecr-pull-secret"),
    )


@pytest.mark.asyncio
async def test_start_replaces_pod_when_image_pull_secrets_change() -> None:
    api = FakeKubernetesApi()
    old_provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=None,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
        ),
    )
    new_provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="system-kubernetes",
            namespace="azents-runtime",
            storage_class_name="gp3",
            pvc_storage_request="20Gi",
            runner_resources=None,
            runner_env={},
            gateway_image="gateway@sha256:test",
            engine_image="engine@sha256:test",
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            image_pull_secrets=(LocalObjectReference(name="ecr-pull-secret"),),
        ),
    )
    await old_provider.start(_command(RuntimeLifecycleCommandType.START))

    await new_provider.start(_command(RuntimeLifecycleCommandType.START))

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.image_pull_secrets == (
        LocalObjectReference(name="ecr-pull-secret"),
    )


@pytest.mark.asyncio
async def test_stop_preserves_pvc() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    result = await provider.stop(_command(RuntimeLifecycleCommandType.STOP))

    assert result.report.observed_state is RuntimeProviderObservedState.STOPPED
    assert ("azents-runtime", "azents-runtime-runtime-1") not in api.pods
    assert ("azents-runtime", "azents-runtime-runtime-1-workspace") in api.pvcs


@pytest.mark.asyncio
async def test_restart_preserves_pvc_and_replaces_pod() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    result = await provider.restart(_command(RuntimeLifecycleCommandType.RESTART))

    assert result.report.observed_state is RuntimeProviderObservedState.STARTING
    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert ("azents-runtime", "azents-runtime-runtime-1-workspace") in api.pvcs
    assert ("azents-runtime", "azents-runtime-runtime-1") in api.pods


@pytest.mark.asyncio
async def test_reset_running_deletes_and_recreates_pvc_and_pod() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    result = await provider.reset(
        _command(
            RuntimeLifecycleCommandType.RESET,
            final_desired_state=RuntimeDesiredState.RUNNING,
        )
    )

    assert result.report.observed_state is RuntimeProviderObservedState.STARTING
    assert api.deleted_pvcs == ["azents-runtime-runtime-1-workspace"]
    assert ("azents-runtime", "azents-runtime-runtime-1-workspace") in api.pvcs
    assert ("azents-runtime", "azents-runtime-runtime-1") in api.pods


@pytest.mark.asyncio
async def test_reset_stopped_recreates_only_pvc() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    result = await provider.reset(
        _command(
            RuntimeLifecycleCommandType.RESET,
            final_desired_state=RuntimeDesiredState.STOPPED,
        )
    )

    assert result.report.observed_state is RuntimeProviderObservedState.STOPPED
    assert ("azents-runtime", "azents-runtime-runtime-1-workspace") in api.pvcs
    assert ("azents-runtime", "azents-runtime-runtime-1") not in api.pods


@pytest.mark.asyncio
async def test_terminal_delete_removes_pod_and_pvc_idempotently() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    first = await provider.terminal_delete(
        _command(RuntimeLifecycleCommandType.TERMINAL_DELETE)
    )
    second = await provider.terminal_delete(
        _command(RuntimeLifecycleCommandType.TERMINAL_DELETE)
    )

    assert first.report.terminal_delete_acknowledged is True
    assert first.report.workspace_path == ""
    assert second.report.terminal_delete_acknowledged is True
    assert ("azents-runtime", "azents-runtime-runtime-1") not in api.pods
    assert ("azents-runtime", "azents-runtime-runtime-1-workspace") not in api.pvcs


@pytest.mark.asyncio
async def test_start_replaces_pod_for_new_runner_credential_and_preserves_pvc() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pvc_key = ("azents-runtime", "azents-runtime-runtime-1-workspace")
    pvc_name = api.pvcs[pvc_key].metadata.name

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=2,
            provider_generation=8,
            runner_auth_token="runner-token-2",
            runner_auth_credential_id="runner-credential-2",
        )
    )

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert api.deleted_pvcs == []
    assert api.pvcs[pvc_key].metadata.name == pvc_name
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    env = {item.name: item.value for item in pod.spec.containers[0].env}
    assert pod.metadata.labels["azents/desired-generation"] == "2"
    assert env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-2"
    assert env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"] == "runner-credential-2"
    workspace_volume = pod.spec.volumes[0]
    assert isinstance(workspace_volume, PersistentVolumeClaimVolume)
    assert workspace_volume.claim_name == pvc_name


@pytest.mark.asyncio
async def test_start_replaces_stale_runner_image_and_preserves_pvc() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:old")
    )
    pvc_key = ("azents-runtime", "azents-runtime-runtime-1-workspace")
    pvc = api.pvcs[pvc_key]

    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:new")
    )

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert api.deleted_pvcs == []
    assert api.pvcs[pvc_key] == pvc
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].image == "runner:new"


@pytest.mark.asyncio
async def test_start_reuses_pod_when_runner_image_and_config_are_unchanged() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]

    await provider.start(command)

    assert api.deleted_pods == []
    assert api.deleted_pvcs == []
    assert api.pods[pod_key] == pod


@pytest.mark.asyncio
async def test_observe_known_runtimes_reports_pod_and_pvc() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    command_2 = RuntimeLifecycleCommand(
        command_type=RuntimeLifecycleCommandType.START,
        identity=RuntimeIdentity(
            runtime_id="runtime-2",
            agent_id="agent-2",
            workspace_id="workspace-1",
        ),
        desired_generation=1,
        provider_generation=7,
        runner_image="runner:latest",
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token="runner-token-2",
            runner_auth_credential_id="runner-credential-2",
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=None,
        execution_policy=_execution_policy(),
    )
    await provider.start(command_2)
    await api.delete_pod("azents-runtime-runtime-2", "azents-runtime")

    reports = await provider.observe_known_runtimes()

    by_runtime = {report.runtime_id: report for report in reports}
    assert (
        by_runtime["runtime-1"].observed_state is RuntimeProviderObservedState.STARTING
    )
    assert (
        by_runtime["runtime-2"].observed_state is RuntimeProviderObservedState.STOPPED
    )
    assert by_runtime["runtime-2"].reason == "pvc_present_without_pod"


@pytest.mark.asyncio
async def test_legacy_resources_are_skipped_until_command_replaces_them() -> None:
    """Legacy Pod/PVC evidence stays untrusted while command processing continues."""
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    pvc = api.pvcs[("azents-runtime", "azents-runtime-runtime-1-workspace")]
    for resource in (pod, pvc):
        annotations = cast(dict[str, str], resource.metadata.annotations)
        for key in (
            "azents/execution-policy-snapshot-id",
            "azents/execution-policy-digest",
            "azents/execution-policy-module-versions",
            "azents/execution-policy-source-versions",
        ):
            annotations.pop(key)
    api.watch_events.append(PodWatchEvent(event_type="MODIFIED", pod=pod))

    assert await provider.observe_known_runtimes() == ()
    assert [report async for report in provider.watch_known_runtimes()] == []

    result = await provider.start(command)

    assert result.report.execution_policy == command.execution_policy.evidence
    replaced = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert (
        replaced.metadata.annotations["azents/execution-policy-snapshot-id"]
        == "snapshot-1"
    )


@pytest.mark.asyncio
async def test_watch_deleted_pod_reports_stopped() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    api.watch_events.append(PodWatchEvent(event_type="DELETED", pod=pod))

    reports = [report async for report in provider.watch_known_runtimes()]

    report = reports[0]
    assert report is not None
    assert report.observed_state is RuntimeProviderObservedState.STOPPED
    assert report.reason == "pod_deleted"
    assert report.provider_runtime_id is None


def test_invalid_workspace_path_is_rejected() -> None:
    api = FakeKubernetesApi()

    with pytest.raises(InvalidWorkspacePath):
        KubernetesRuntimeProvider(
            api,
            KubernetesRuntimeProviderConfig(
                provider_id="provider-k8s",
                namespace="azents-runtime",
                storage_class_name="gp3",
                pvc_storage_request="20Gi",
                runner_resources=ContainerResources(
                    requests={"cpu": "500m", "memory": "1Gi"},
                    limits={"cpu": "1500m", "memory": "2Gi"},
                    claims=None,
                ),
                runner_env={},
                gateway_image="gateway@sha256:test",
                engine_image="engine@sha256:test",
                runtime_control_namespace="azents",
                runtime_control_labels={
                    "app.kubernetes.io/component": "runtime-control",
                },
                runtime_control_port=8030,
                workspace_mount_path="relative/path",
            ),
        )


@pytest.mark.asyncio
async def test_reset_requires_explicit_final_desired_state() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(InvalidResetFinalDesiredState):
        await provider.reset(_command(RuntimeLifecycleCommandType.RESET))


@pytest.mark.asyncio
async def test_standard_policy_evidence_is_persisted_and_reported() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    policy = _execution_policy()

    result = await provider.start(
        _command(RuntimeLifecycleCommandType.START, execution_policy=policy)
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert (
        pod.metadata.annotations["azents/execution-policy-snapshot-id"] == "snapshot-1"
    )
    assert result.report.execution_policy == policy.evidence


@pytest.mark.asyncio
async def test_container_execution_policy_creates_fixed_isolated_topology() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    execution_policy = _execution_policy(
        image_build=True,
        network_mode="restricted",
        allowed_destinations=("203.0.113.0/24",),
        denied_destinations=("203.0.113.128/25",),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            execution_policy=execution_policy,
        )
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    runner, gateway, engine = pod.spec.containers
    assert [container.name for container in pod.spec.containers] == [
        "runner",
        "container-policy-gateway",
        "container-engine",
    ]
    assert runner.security_context.privileged is False
    assert gateway.security_context.privileged is False
    assert engine.security_context.privileged is True
    assert engine.security_context.run_as_user == 0
    assert pod.spec.service_account_name is None
    assert pod.spec.automount_service_account_token is False
    assert {mount.name for mount in runner.volume_mounts} == {
        "agent-workspace",
        "container-gateway-socket",
    }
    runner_env = {item.name: item.value for item in runner.env}
    assert runner_env["DOCKER_HOST"] == ("unix:///var/run/azents-gateway/docker.sock")
    assert {mount.name for mount in gateway.volume_mounts} == {
        "container-gateway-socket",
        "container-engine-socket",
    }
    assert {mount.name for mount in engine.volume_mounts} == {
        "container-engine-socket",
        "container-engine-storage",
    }
    engine_storage = pod.spec.volumes[-1]
    assert isinstance(engine_storage, EmptyDirVolume)
    assert engine_storage.size_limit == "8589934592"
    assert len(api.pvcs) == 1

    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    assert (
        network_policy.spec.pod_selector.match_labels["azents/execution-policy-managed"]
        == "true"
    )
    assert network_policy.spec.pod_selector.match_labels[
        "azents/desired-generation"
    ] == str(1)
    assert network_policy.spec.pod_selector.match_labels[
        "azents/provider-generation"
    ] == str(7)
    restricted_peer = network_policy.spec.egress[-1].peers[0]
    assert restricted_peer.ip_block is not None
    assert restricted_peer.ip_block.cidr == "203.0.113.0/24"
    assert restricted_peer.ip_block.except_cidrs == ("203.0.113.128/25",)


@pytest.mark.asyncio
async def test_new_network_policy_does_not_select_old_pod_when_replacement_fails() -> (
    None
):
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    old_pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    api.fail_pod_deletion = True

    with pytest.raises(RuntimeError, match="Pod deletion failed"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                desired_generation=2,
                provider_generation=8,
                execution_policy=_execution_policy(
                    desired_generation=2,
                    network_mode="direct",
                ),
            )
        )

    assert api.pods[("azents-runtime", "azents-runtime-runtime-1")] is old_pod
    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    selector = network_policy.spec.pod_selector.match_labels
    assert selector["azents/desired-generation"] == "2"
    assert selector["azents/provider-generation"] == "8"
    assert old_pod.metadata.labels["azents/desired-generation"] == "1"
    assert old_pod.metadata.labels["azents/provider-generation"] == "7"
    assert any(
        selector[key] != old_pod.metadata.labels.get(key)
        for key in (
            "azents/desired-generation",
            "azents/provider-generation",
        )
    )


@pytest.mark.asyncio
async def test_invalid_container_execution_policy_fails_before_resource_mutation() -> (
    None
):
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(ValueError, match="bounded resources"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                execution_policy=_execution_policy(
                    image_build=True,
                    bounded=False,
                ),
            )
        )

    assert api.pods == {}
    assert api.pvcs == {}
    assert api.network_policies == {}


@pytest.mark.asyncio
async def test_direct_network_policy_can_deny_an_entire_ip_family() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            execution_policy=_execution_policy(
                network_mode="direct",
                denied_destinations=("0.0.0.0/0",),
            ),
        )
    )

    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    optional_rules = network_policy.spec.egress[2:]
    assert len(optional_rules) == 1
    assert optional_rules[0].peers[0].ip_block is not None
    assert optional_rules[0].peers[0].ip_block.cidr == "::/0"


def _execution_policy(
    *,
    image_build: bool = False,
    desired_generation: int = 1,
    bounded: bool = True,
    network_mode: str = "none",
    allowed_destinations: tuple[str, ...] = (),
    denied_destinations: tuple[str, ...] = (),
) -> RuntimeExecutionPolicyEnvelope:
    engine_enabled = image_build and bounded
    policy: dict[str, JsonValue] = {
        "schema_version": 1,
        "image_build": {
            "module_id": "container.image_build",
            "version": 1,
            "enabled": image_build,
        },
        "container_run": {
            "module_id": "container.run",
            "version": 1,
            "enabled": False,
        },
        "compose": {
            "module_id": "container.compose",
            "version": 1,
            "enabled": False,
        },
        "resources": {
            "module_id": "container.resources",
            "version": 1,
            "cpu_millicores": 1000 if engine_enabled else None,
            "memory_bytes": 2_147_483_648 if engine_enabled else None,
            "pids": 256 if engine_enabled else None,
            "container_count": 8 if engine_enabled else None,
            "ephemeral_storage_bytes": 10_737_418_240 if engine_enabled else None,
        },
        "engine_storage": {
            "module_id": "engine.storage",
            "version": 1,
            "mode": "ephemeral" if engine_enabled else "none",
            "capacity_bytes": 8_589_934_592 if engine_enabled else None,
        },
        "network_egress": {
            "module_id": "network.egress",
            "version": 1,
            "mode": network_mode,
            "allowed_destinations": list(allowed_destinations),
            "denied_destinations": list(denied_destinations),
        },
    }
    return RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id="snapshot-1",
            digest=digest_effective_policy(policy),
            desired_generation=desired_generation,
            module_versions={
                "container.image_build": 1,
                "container.run": 1,
                "container.compose": 1,
                "container.resources": 1,
                "engine.storage": 1,
                "network.egress": 1,
            },
            source_versions={
                "platform": 1,
                "profile": 1,
                "workspace": 1,
                "agent": 1,
            },
        ),
        effective_policy=policy,
    )
