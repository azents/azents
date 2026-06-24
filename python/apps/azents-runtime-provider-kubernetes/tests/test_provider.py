"""Kubernetes Runtime Provider lifecycle tests."""

import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime

import pytest
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
    KubernetesApi,
    LeaseResource,
    LocalObjectReference,
    PersistentVolumeClaimResource,
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
    InvalidResetFinalDesiredState,
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
        self.deleted_pods: list[str] = []
        self.deleted_pod_grace_periods: list[int | None] = []
        self.deleted_pvcs: list[str] = []
        self.watch_events: list[PodWatchEvent] = []

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

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Unused by provider tests."""
        return None

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Unused by provider tests."""


def _provider(api: FakeKubernetesApi) -> KubernetesRuntimeProvider:
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
        ),
    )


def _command(
    command_type: RuntimeLifecycleCommandType,
    *,
    final_desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 1,
    provider_generation: int = 7,
    runner_image: str = "runner:latest",
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
            runner_auth_token="runner-token",
        ),
        reset_final_desired_state=final_desired_state,
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
            runner_auth_token="runner-token",
        ),
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
    assert env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"] == "runner-token"
    assert "AZ_RUNTIME_RUNNER_AUTH_TOKEN" not in env
    assert pod.metadata.annotations == {
        "azents/workspace-path": "/workspace/agent",
    }
    assert pod.spec.service_account_name is None
    assert pod.spec.automount_service_account_token is False
    assert pod.spec.node_selector == {}
    assert pod.spec.tolerations == ()
    assert pod.spec.security_context is not None
    assert pod.spec.security_context.run_as_user == 1000
    assert pod.spec.security_context.run_as_group == 1000
    assert pod.spec.security_context.fs_group == 1000
    assert pod.spec.security_context.fs_group_change_policy == "OnRootMismatch"
    assert pod.spec.volumes[0].claim_name == pvc.metadata.name
    assert pvc.spec.storage_class_name == "gp3"
    assert "azents/workspace-path" not in pod.metadata.labels
    assert "azents/workspace-path" not in pvc.metadata.labels
    assert pod.metadata.annotations["azents/workspace-path"] == "/workspace/agent"
    assert pvc.metadata.annotations["azents/workspace-path"] == "/workspace/agent"


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
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].resources == resources


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
            pod_annotations={"descheduler/no-evict": "true"},
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.metadata.annotations == {
        "descheduler/no-evict": "true",
        "azents/workspace-path": "/workspace/agent",
    }


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
async def test_start_reuses_current_pod_across_generation_changes() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=2,
            provider_generation=8,
        )
    )

    assert api.deleted_pods == []
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.metadata.labels["azents/desired-generation"] == "1"


@pytest.mark.asyncio
async def test_start_deletes_stale_pod_before_later_recreate() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)
    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:old")
    )

    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:new")
    )

    assert api.deleted_pods == ["azents-runtime-runtime-1"]
    pod = api.pods[("azents-runtime", "azents-runtime-runtime-1")]
    assert pod.spec.containers[0].image == "runner:new"


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
            runner_auth_token="runner-token",
        ),
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
                workspace_mount_path="relative/path",
            ),
        )


@pytest.mark.asyncio
async def test_reset_requires_explicit_final_desired_state() -> None:
    api = FakeKubernetesApi()
    provider = _provider(api)

    with pytest.raises(InvalidResetFinalDesiredState):
        await provider.reset(_command(RuntimeLifecycleCommandType.RESET))
