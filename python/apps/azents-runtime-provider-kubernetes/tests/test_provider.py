"""Kubernetes Runtime Provider lifecycle tests."""

import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from azents_runtime_control.provider import (
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
)
from azents_runtime_control.runtime_configuration import (
    JsonValue,
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResources,
    EmptyDirVolume,
    IpBlock,
    KubernetesApi,
    LabelSelector,
    LeaseResource,
    LocalObjectReference,
    NetworkPolicyEgressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    NetworkPolicyResource,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimVolume,
    PodResource,
    PodStatus,
    PodWatchEvent,
    Toleration,
)
from azents_runtime_provider_kubernetes.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    InvalidResetFinalDesiredState,
    InvalidRunnerEnvironment,
    InvalidWorkspacePath,
    KubernetesRuntimeProvider,
    KubernetesRuntimeProviderConfig,
    UnsupportedRuntimeConfiguration,
)

_RUNNER_IMAGE = f"repo/runner:phase5@sha256:{'a' * 64}"
_OLD_RUNNER_IMAGE = f"repo/runner:old@sha256:{'b' * 64}"
_NEW_RUNNER_IMAGE = f"repo/runner:new@sha256:{'c' * 64}"
_ENGINE_IMAGE = f"repo/engine:phase5@sha256:{'e' * 64}"


class FakeKubernetesApi(KubernetesApi):
    """In-memory Kubernetes API fake."""

    def __init__(self) -> None:
        self.pods: dict[tuple[str, str], PodResource] = {}
        self.pvcs: dict[tuple[str, str], PersistentVolumeClaimResource] = {}
        self.network_policies: dict[tuple[str, str], NetworkPolicyResource] = {}
        self.applied_pods: list[str] = []
        self.deleted_pods: list[str] = []
        self.deleted_pod_grace_periods: list[int | None] = []
        self.deleted_pvcs: list[str] = []
        self.deleted_network_policies: list[str] = []
        self.watch_events: list[PodWatchEvent] = []
        self.fail_pod_deletion = False
        self.defer_pod_deletion = False

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        """Return a Pod by name."""
        return self.pods.get((namespace, name))

    async def apply_pod(self, pod: PodResource) -> None:
        """Apply a Pod."""
        self.applied_pods.append(pod.metadata.name)
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
        if not self.defer_pod_deletion:
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


def _provider(
    api: FakeKubernetesApi,
    *,
    network_hard_cap_allowed_cidrs: tuple[str, ...] = (),
    network_hard_cap_denied_cidrs: tuple[str, ...] = (),
    network_hard_cap_extra_egress: tuple[NetworkPolicyEgressRule, ...] = (),
) -> KubernetesRuntimeProvider:
    return _provider_with_runner_env(
        api,
        {},
        network_hard_cap_allowed_cidrs=network_hard_cap_allowed_cidrs,
        network_hard_cap_denied_cidrs=network_hard_cap_denied_cidrs,
        network_hard_cap_extra_egress=network_hard_cap_extra_egress,
    )


def _provider_with_runner_env(
    api: FakeKubernetesApi,
    runner_env: Mapping[str, str],
    *,
    network_hard_cap_allowed_cidrs: tuple[str, ...] = (),
    network_hard_cap_denied_cidrs: tuple[str, ...] = (),
    network_hard_cap_extra_egress: tuple[NetworkPolicyEgressRule, ...] = (),
) -> KubernetesRuntimeProvider:
    return KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id="provider-k8s",
            namespace="azents-runtime",
            runner_env=runner_env,
            engine_image=_ENGINE_IMAGE,
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            network_hard_cap_allowed_cidrs=network_hard_cap_allowed_cidrs,
            network_hard_cap_denied_cidrs=network_hard_cap_denied_cidrs,
            network_hard_cap_extra_egress=network_hard_cap_extra_egress,
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
    runner_image: str = _RUNNER_IMAGE,
    runner_auth_token: str = "runner-token-1",
    runner_auth_credential_id: str = "runner-credential-1",
    runtime_configuration: RuntimeConfigurationEnvelope | None = None,
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
            transfer_endpoint="runtime-transfer:8030",
            runner_auth_token=runner_auth_token,
            runner_auth_credential_id=runner_auth_credential_id,
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=final_desired_state,
        runtime_configuration=runtime_configuration
        or _runtime_configuration(desired_generation=desired_generation),
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
    assert container.image == _RUNNER_IMAGE
    assert env["AZ_RUNTIME_TRANSFER_ENDPOINT"] == "runtime-transfer:8030"
    assert "AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY" not in env
    assert container.working_dir == "/workspace/agent"
    assert container.resources == ContainerResources(
        requests={"cpu": "500m", "memory": "1073741824"},
        limits={"cpu": "1500m", "memory": "2147483648"},
        claims=None,
    )
    assert env["AZ_AGENT_WORKSPACE_PATH"] == "/workspace/agent"
    assert env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-1"
    assert env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"] == "runner-credential-1"
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert (
        pod.metadata.annotations["azents/runtime-configuration-revision-id"]
        == "revision-1"
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
    assert [volume.name for volume in pod.spec.volumes] == ["agent-workspace"]
    assert len(container.volume_mounts) == 1
    assert container.volume_mounts[0].name == "agent-workspace"
    assert container.volume_mounts[0].mount_path == "/workspace/agent"
    assert container.volume_mounts[0].read_only is False
    assert container.security_context.run_as_non_root is True
    assert container.security_context.run_as_user == 1000
    assert container.security_context.run_as_group == 1000
    assert container.security_context.capabilities_add == ()
    assert container.security_context.capabilities_drop == ("ALL",)
    assert pvc.spec.storage_class_name == "gp3"
    assert pvc.spec.storage_request == "21474836480"
    assert "azents/workspace-path" not in pod.metadata.labels
    assert "azents/workspace-path" not in pvc.metadata.labels
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert pvc.metadata.annotations["azents/workspace-path"] == "/workspace/agent"


@pytest.mark.asyncio
async def test_start_expands_pvc_but_defers_shrink_until_reset() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    pvc_key = ("azents-runtime", "azents-runtime-runtime-1-workspace")

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=1,
            runtime_configuration=_runtime_configuration(
                desired_generation=1,
                persistent_storage_bytes=10_737_418_240,
            ),
        )
    )
    assert api.pvcs[pvc_key].spec.storage_request == "10737418240"

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=2,
            runtime_configuration=_runtime_configuration(
                desired_generation=2,
                persistent_storage_bytes=21_474_836_480,
            ),
        )
    )
    assert api.pvcs[pvc_key].spec.storage_request == "21474836480"

    shrink_policy = _runtime_configuration(
        desired_generation=3,
        persistent_storage_bytes=5_368_709_120,
    )
    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=3,
            runtime_configuration=shrink_policy,
        )
    )
    assert api.pvcs[pvc_key].spec.storage_request == "21474836480"

    await provider.reset(
        _command(
            RuntimeLifecycleCommandType.RESET,
            final_desired_state=RuntimeDesiredState.STOPPED,
            desired_generation=3,
            runtime_configuration=shrink_policy,
        )
    )
    assert api.pvcs[pvc_key].spec.storage_request == "5368709120"


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
    provider = _provider(api)

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(omit_runner_resources=True),
        )
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].resources is None


@pytest.mark.asyncio
async def test_start_uses_profile_runner_resources() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].resources == ContainerResources(
        requests={"cpu": "500m", "memory": "1073741824"},
        limits={"cpu": "1500m", "memory": "2147483648"},
        claims=None,
    )


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
    provider = _provider(api)
    command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(configured_scheduling=True),
    )
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
async def test_start_reuses_pod_with_kubernetes_default_service_account() -> None:
    """The API-server default is safe when token automount remains disabled."""
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        spec=dataclasses.replace(
            pod.spec,
            service_account_name="default",
        ),
    )

    await provider.start(command)

    assert api.deleted_pods == []
    assert api.pods[pod_key].spec.service_account_name == "default"
    assert api.pods[pod_key].spec.automount_service_account_token is False


@pytest.mark.asyncio
async def test_start_replaces_pod_with_non_default_service_account() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    api.pods[pod_key] = dataclasses.replace(
        pod,
        spec=dataclasses.replace(
            pod.spec,
            service_account_name="privileged-runtime",
        ),
    )

    await provider.start(command)

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert api.pods[pod_key].spec.service_account_name is None


@pytest.mark.asyncio
async def test_start_reuses_pod_with_canonicalized_kubernetes_quantities() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(
            docker_enabled=True,
            cpu_request_millicores=500,
            memory_request_bytes=1_073_741_824,
        ),
    )
    await provider.start(command)
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pod = api.pods[pod_key]
    engine = pod.spec.containers[-1]
    assert engine.resources is not None
    assert engine.resources.limits is not None
    shared_tmp = pod.spec.volumes[-2]
    assert isinstance(shared_tmp, EmptyDirVolume)
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
                            "cpu": "1",
                            "memory": "2Gi",
                        },
                    ),
                ),
            ),
            volumes=(
                *pod.spec.volumes[:-2],
                dataclasses.replace(
                    shared_tmp,
                    size_limit="10Gi",
                ),
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
            runner_env={},
            engine_image=_ENGINE_IMAGE,
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            pod_annotations={"descheduler/no-evict": "true"},
        ),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(
                provider_logical_id="system-kubernetes",
            ),
        )
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.metadata.annotations["descheduler/no-evict"] == "true"
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert (
        pod.metadata.annotations["azents/runtime-configuration-revision-id"]
        == "revision-1"
    )


@pytest.mark.asyncio
async def test_start_applies_profile_runtime_pod_scheduling() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(isolated_scheduling=True),
        )
    )

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
            runner_env={},
            engine_image=_ENGINE_IMAGE,
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            image_pull_secrets=(LocalObjectReference(name="ecr-pull-secret"),),
        ),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(
                provider_logical_id="system-kubernetes",
            ),
        )
    )

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
            runner_env={},
            engine_image=_ENGINE_IMAGE,
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
            runner_env={},
            engine_image=_ENGINE_IMAGE,
            runtime_control_namespace="azents",
            runtime_control_labels={
                "app.kubernetes.io/component": "runtime-control",
            },
            runtime_control_port=8030,
            image_pull_secrets=(LocalObjectReference(name="ecr-pull-secret"),),
        ),
    )
    command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(
            provider_logical_id="system-kubernetes",
        ),
    )
    await old_provider.start(command)
    await new_provider.start(command)

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
async def test_restart_waits_for_asynchronous_pod_deletion_before_recreate() -> None:
    """Restart never patches immutable fields on a terminating Pod."""
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    api.defer_pod_deletion = True

    result = await provider.restart(_command(RuntimeLifecycleCommandType.RESTART))

    assert result.report.observed_state is RuntimeProviderObservedState.STARTING
    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert api.applied_pods == ["azents-runtime-runtime-1"]

    api.pods.pop(("azents-runtime", "azents-runtime-runtime-1"))
    api.defer_pod_deletion = False
    await provider.restart(_command(RuntimeLifecycleCommandType.RESTART))

    assert api.applied_pods == [
        "azents-runtime-runtime-1",
        "azents-runtime-runtime-1",
    ]


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
        _command(RuntimeLifecycleCommandType.START, runner_image=_OLD_RUNNER_IMAGE)
    )
    pvc_key = ("azents-runtime", "azents-runtime-runtime-1-workspace")
    pvc = api.pvcs[pvc_key]

    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image=_NEW_RUNNER_IMAGE)
    )

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    assert api.deleted_pvcs == []
    assert api.pvcs[pvc_key] == pvc
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].image == _NEW_RUNNER_IMAGE


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
        runner_image=_RUNNER_IMAGE,
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            transfer_endpoint="runtime-transfer:8030",
            runner_auth_token="runner-token-2",
            runner_auth_credential_id="runner-credential-2",
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=None,
        runtime_configuration=_runtime_configuration(),
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
            "azents/runtime-configuration-revision-id",
            "azents/runtime-configuration-digest",
        ):
            annotations.pop(key)
    api.watch_events.append(PodWatchEvent(event_type="MODIFIED", pod=pod))

    assert await provider.observe_known_runtimes() == ()
    assert [report async for report in provider.watch_known_runtimes()] == []

    result = await provider.start(command)

    assert result.report.runtime_configuration == command.runtime_configuration.evidence
    replaced = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert (
        replaced.metadata.annotations["azents/runtime-configuration-revision-id"]
        == "revision-1"
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
                runner_env={},
                engine_image=_ENGINE_IMAGE,
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
async def test_runtime_configuration_evidence_is_persisted_and_reported() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    configuration = _runtime_configuration()

    result = await provider.start(
        _command(RuntimeLifecycleCommandType.START, runtime_configuration=configuration)
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert (
        pod.metadata.annotations["azents/runtime-configuration-revision-id"]
        == "revision-1"
    )
    assert result.report.runtime_configuration == configuration.evidence


@pytest.mark.asyncio
async def test_dind_profile_exposes_private_engine_socket_directly() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    runtime_configuration = _runtime_configuration(
        docker_enabled=True,
        cpu_request_millicores=500,
        memory_request_bytes=1_073_741_824,
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=runtime_configuration,
        )
    )

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    runner, engine = pod.spec.containers
    assert [container.name for container in pod.spec.containers] == [
        "runner",
        "container-engine",
    ]
    assert runner.security_context.privileged is False
    assert runner.security_context.run_as_non_root is True
    assert runner.security_context.run_as_user == 1000
    assert runner.security_context.run_as_group == 1000
    assert runner.security_context.capabilities_add == ()
    assert runner.security_context.capabilities_drop == ("ALL",)
    assert engine.resources == ContainerResources(
        requests={
            "cpu": "500m",
            "memory": "1073741824",
        },
        limits={
            "cpu": "1",
            "memory": "2147483648",
        },
        claims=None,
    )
    assert engine.security_context.privileged is True
    assert engine.security_context.run_as_user == 0
    assert runner.image == _RUNNER_IMAGE
    assert engine.image == _ENGINE_IMAGE
    assert pod.spec.service_account_name is None
    assert pod.spec.automount_service_account_token is False
    assert {mount.name for mount in runner.volume_mounts} == {
        "agent-workspace",
        "container-engine-socket",
        "runtime-shared-tmp",
    }
    runner_engine_mount = next(
        mount
        for mount in runner.volume_mounts
        if mount.name == "container-engine-socket"
    )
    assert runner_engine_mount.mount_path == "/var/run/azents-engine"
    assert runner_engine_mount.read_only is True
    runner_env = {item.name: item.value for item in runner.env}
    assert runner_env["DOCKER_HOST"] == "unix:///var/run/azents-engine/docker.sock"
    assert runner_env["TESTCONTAINERS_HOST_OVERRIDE"] == "127.0.0.1"
    assert runner_env["TESTCONTAINERS_CONNECTION_MODE"] == "docker_host"
    assert runner_env["TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE"] == (
        "/var/run/azents-engine/docker.sock"
    )
    assert {mount.name for mount in engine.volume_mounts} == {
        "agent-workspace",
        "container-engine-socket",
        "container-engine-storage",
        "runtime-shared-tmp",
    }
    runner_mounts = {mount.mount_path: mount for mount in runner.volume_mounts}
    engine_mounts = {mount.name: mount for mount in engine.volume_mounts}
    assert runner_mounts["/workspace/agent"].name == "agent-workspace"
    assert engine_mounts["agent-workspace"].mount_path == "/workspace/agent"
    assert runner_mounts["/workspace/agent"].read_only is False
    assert engine_mounts["agent-workspace"].read_only is False
    assert runner_mounts["/tmp"].name == "runtime-shared-tmp"
    assert engine_mounts["runtime-shared-tmp"].mount_path == "/tmp"
    assert runner_mounts["/tmp"].read_only is False
    assert engine_mounts["runtime-shared-tmp"].read_only is False
    assert engine.args[-1] == "--group=azents-runner"
    assert engine.readiness_probe is not None
    engine_probe = engine.readiness_probe.exec_action.command
    assert engine_probe[:2] == ("sh", "-ec")
    assert "28.5.2/1.51" in engine_probe[2]
    engine_storage = pod.spec.volumes[-1]
    assert isinstance(engine_storage, EmptyDirVolume)
    assert engine_storage.size_limit == "8589934592"
    shared_tmp = pod.spec.volumes[-2]
    assert isinstance(shared_tmp, EmptyDirVolume)
    assert shared_tmp.name == "runtime-shared-tmp"
    assert shared_tmp.medium is None
    assert shared_tmp.size_limit == "10737418240"
    assert len(api.pvcs) == 1

    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    assert (
        network_policy.spec.pod_selector.match_labels[
            "azents/runtime-configuration-managed"
        ]
        == "true"
    )
    assert network_policy.spec.pod_selector.match_labels == {
        "azents/managed-by": "azents-runtime-provider-kubernetes",
        "azents/runtime-id": "runtime-1",
        "azents/runtime-configuration-managed": "true",
    }
    assert len(network_policy.spec.egress) == 4


@pytest.mark.asyncio
async def test_direct_network_policy_is_bounded_by_deployment_hard_cap() -> None:
    api = FakeKubernetesApi()
    extra_egress = NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={"kubernetes.io/metadata.name": "ingress"}
                ),
                pod_selector=LabelSelector(
                    match_labels={"app.kubernetes.io/name": "traefik"}
                ),
                ip_block=None,
            ),
        ),
        ports=(NetworkPolicyPort(protocol="TCP", port="websecure"),),
    )
    provider = _provider(
        api,
        network_hard_cap_allowed_cidrs=("10.10.0.0/16",),
        network_hard_cap_denied_cidrs=("10.0.0.0/8",),
        network_hard_cap_extra_egress=(extra_egress,),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(),
        )
    )

    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    optional_rules = network_policy.spec.egress[2:]
    assert optional_rules == (extra_egress,)


@pytest.mark.asyncio
async def test_platform_extra_ip_egress_is_part_of_provider_boundary() -> None:
    api = FakeKubernetesApi()
    extra_egress = NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=None,
                pod_selector=None,
                ip_block=IpBlock(
                    cidr="192.168.68.144/32",
                    except_cidrs=(),
                ),
            ),
        ),
        ports=(NetworkPolicyPort(protocol="TCP", port=443),),
    )

    provider = _provider(
        api,
        network_hard_cap_denied_cidrs=("192.168.0.0/16",),
        network_hard_cap_extra_egress=(extra_egress,),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(),
        )
    )

    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    assert extra_egress in network_policy.spec.egress


def test_provider_rejects_invalid_extra_ip_egress_exception() -> None:
    extra_egress = NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=None,
                pod_selector=None,
                ip_block=IpBlock(
                    cidr="10.10.0.0/16",
                    except_cidrs=("10.10.0.0/16",),
                ),
            ),
        ),
        ports=(),
    )

    with pytest.raises(
        UnsupportedRuntimeConfiguration,
        match="exceptions must be strict subnets",
    ):
        _provider(
            FakeKubernetesApi(),
            network_hard_cap_extra_egress=(extra_egress,),
        )


def test_provider_rejects_mutable_engine_image() -> None:
    with pytest.raises(UnsupportedRuntimeConfiguration, match="immutable sha256"):
        KubernetesRuntimeProvider(
            FakeKubernetesApi(),
            KubernetesRuntimeProviderConfig(
                provider_id="provider-k8s",
                namespace="azents-runtime",
                runner_env={},
                engine_image="repo/engine:latest",
                runtime_control_namespace="azents",
                runtime_control_labels={
                    "app.kubernetes.io/component": "runtime-control",
                },
                runtime_control_port=8030,
            ),
        )


@pytest.mark.asyncio
async def test_dind_profile_rejects_mutable_runner_image_before_mutation() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(UnsupportedRuntimeConfiguration, match="Runner image"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runner_image="repo/runner:latest",
                runtime_configuration=_runtime_configuration(docker_enabled=True),
            )
        )

    assert api.pods == {}
    assert api.pvcs == {}
    assert api.network_policies == {}


@pytest.mark.asyncio
async def test_network_policy_keeps_stable_selector_when_replacement_fails() -> None:
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
                runtime_configuration=_runtime_configuration(
                    desired_generation=2,
                ),
            )
        )

    assert api.pods[("azents-runtime", "azents-runtime-runtime-1")] is old_pod
    network_policy = api.network_policies[
        ("azents-runtime", "azents-runtime-runtime-1-execution")
    ]
    selector = network_policy.spec.pod_selector.match_labels
    assert selector == {
        "azents/managed-by": "azents-runtime-provider-kubernetes",
        "azents/runtime-id": "runtime-1",
        "azents/runtime-configuration-managed": "true",
    }
    assert old_pod.metadata.labels["azents/desired-generation"] == "1"
    assert old_pod.metadata.labels["azents/provider-generation"] == "7"
    assert all(
        old_pod.metadata.labels.get(key) == value for key, value in selector.items()
    )


@pytest.mark.asyncio
async def test_configuration_update_changes_only_network_policy() -> None:
    """Network-only adoption preserves the existing Pod and PVC."""
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    pod_key = ("azents-runtime", "azents-runtime-runtime-1")
    pvc_key = ("azents-runtime", "azents-runtime-runtime-1-workspace")
    policy_key = ("azents-runtime", "azents-runtime-runtime-1-execution")
    original_pod = api.pods[pod_key]
    original_pvc = api.pvcs[pvc_key]
    applied_pod_count = len(api.applied_pods)
    updated_configuration = _runtime_configuration(
        allowed_cidrs=["10.20.0.0/16"],
        denied_cidrs=["10.20.1.0/24"],
        revision_id="revision-2",
        digest="e" * 64,
    )

    result = await provider.update_configuration(
        _command(
            RuntimeLifecycleCommandType.UPDATE_CONFIGURATION,
            runtime_configuration=updated_configuration,
        )
    )

    assert api.pods[pod_key] is original_pod
    assert api.pvcs[pvc_key] is original_pvc
    assert len(api.applied_pods) == applied_pod_count
    assert api.deleted_pods == []
    assert api.deleted_pvcs == []
    policy = api.network_policies[policy_key]
    assert policy.metadata.annotations["azents/runtime-configuration-revision-id"] == (
        "revision-2"
    )
    assert result.report.runtime_configuration == updated_configuration.evidence


@pytest.mark.asyncio
async def test_invalid_dind_configuration_fails_before_resource_mutation() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(ValueError, match="docker_storage_bytes"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runtime_configuration=_runtime_configuration(
                    docker_enabled=True,
                    bounded=False,
                ),
            )
        )

    assert api.pods == {}
    assert api.pvcs == {}
    assert api.network_policies == {}


@pytest.mark.asyncio
async def test_configuration_bound_to_another_provider_is_rejected() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(UnsupportedRuntimeConfiguration, match="different Kubernetes"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runtime_configuration=_runtime_configuration(
                    provider_logical_id="provider-k8s-other",
                ),
            )
        )

    assert api.pods == {}
    assert api.pvcs == {}
    assert api.network_policies == {}


def _runtime_configuration(
    *,
    docker_enabled: bool = False,
    desired_generation: int = 1,
    provider_logical_id: str = "provider-k8s",
    bounded: bool = True,
    omit_runner_resources: bool = False,
    configured_scheduling: bool = False,
    isolated_scheduling: bool = False,
    cpu_request_millicores: int | None = None,
    cpu_limit_millicores: int = 1000,
    memory_request_bytes: int | None = None,
    memory_limit_bytes: int = 2_147_483_648,
    ephemeral_storage_bytes: int = 10_737_418_240,
    persistent_storage_bytes: int | None = None,
    allowed_cidrs: list[str] | None = None,
    denied_cidrs: list[str] | None = None,
    revision_id: str = "revision-1",
    digest: str = "d" * 64,
) -> RuntimeConfigurationEnvelope:
    docker_configured = docker_enabled and bounded
    allowed_cidr_values: list[JsonValue] = []
    allowed_cidr_values.extend(allowed_cidrs or [])
    denied_cidr_values: list[JsonValue] = []
    denied_cidr_values.extend(denied_cidrs or [])
    network_policy: dict[str, JsonValue] = {
        "allowed_cidrs": allowed_cidr_values,
        "denied_cidrs": denied_cidr_values,
    }
    effective_profile: dict[str, JsonValue] = {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": None if omit_runner_resources else 500,
            "cpu_limit_millicores": None if omit_runner_resources else 1500,
            "memory_request_bytes": (None if omit_runner_resources else 1_073_741_824),
            "memory_limit_bytes": (None if omit_runner_resources else 2_147_483_648),
        },
        "workspace_volume": {
            "storage_class_name": "gp3",
            "storage_request_bytes": (
                persistent_storage_bytes
                if persistent_storage_bytes is not None
                else 21_474_836_480
            ),
        },
        "network_policy": network_policy,
        "service_account_name": None,
        "scheduling": {
            "node_selector": (
                {"azents.azents.io/runtime-isolation": "true"}
                if isolated_scheduling
                else {}
            ),
            "tolerations": (
                [
                    {
                        "key": "azents.azents.io/runtime-isolation",
                        "operator": "Equal",
                        "value": "true",
                        "effect": "NoSchedule",
                        "toleration_seconds": None,
                    }
                ]
                if isolated_scheduling
                else (
                    [
                        {
                            "key": "runtime",
                            "operator": "Equal",
                            "value": "azents",
                            "effect": "NoSchedule",
                            "toleration_seconds": None,
                        }
                    ]
                    if configured_scheduling
                    else []
                )
            ),
        },
        "dind": (
            {
                "engine_resources": {
                    "cpu_request_millicores": cpu_request_millicores,
                    "cpu_limit_millicores": cpu_limit_millicores,
                    "memory_request_bytes": memory_request_bytes,
                    "memory_limit_bytes": memory_limit_bytes,
                },
                "docker_storage_bytes": (8_589_934_592 if docker_configured else None),
                "shared_temporary_storage_bytes": (
                    ephemeral_storage_bytes if docker_configured else None
                ),
            }
            if docker_enabled
            else None
        ),
    }
    configuration: dict[str, JsonValue] = {
        "schema_version": 1,
        "provider": {
            "id": "provider-resource-1",
            "logical_id": provider_logical_id,
            "kind": "kubernetes",
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            revision_id=revision_id,
            digest=digest,
            desired_generation=desired_generation,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(configuration),
    )
