"""Kubernetes implementation of the Agent Runtime Provider lifecycle."""

import dataclasses
import ipaddress
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from azents_runtime_control.execution_policy import (
    RuntimeExecutionPolicy,
    RuntimeExecutionPolicyEvidence,
    RuntimeExecutionStorageMode,
    parse_execution_policy_envelope,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResources,
    ContainerSecurityContext,
    ContainerSpec,
    EmptyDirVolume,
    EnvVar,
    ExecAction,
    IpBlock,
    KubernetesApi,
    KubernetesResourceQuantity,
    LabelSelector,
    LocalObjectReference,
    NetworkPolicyEgressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    NetworkPolicyResource,
    NetworkPolicySpec,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimSpec,
    PersistentVolumeClaimVolume,
    PodResource,
    PodSecurityContext,
    PodSpec,
    PodStatus,
    PodVolume,
    PodWatchEvent,
    Probe,
    Toleration,
    VolumeMount,
)
from azents_runtime_provider_kubernetes.models import (
    RuntimeDesiredState,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)

_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_IMMUTABLE_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
_QUANTITY_RE = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?:(?:[eE]([+-]?\d+))|([numkMGTPE]|[KMGTPE]i))?$"
)
_QUANTITY_SUFFIX_MULTIPLIERS = {
    "n": Decimal("1e-9"),
    "u": Decimal("1e-6"),
    "m": Decimal("1e-3"),
    "k": Decimal("1e3"),
    "M": Decimal("1e6"),
    "G": Decimal("1e9"),
    "T": Decimal("1e12"),
    "P": Decimal("1e15"),
    "E": Decimal("1e18"),
    "Ki": Decimal(1024),
    "Mi": Decimal(1024**2),
    "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4),
    "Pi": Decimal(1024**5),
    "Ei": Decimal(1024**6),
}
_IMAGE_GENERATION = "agent-runtime-kubernetes-v1"
_RUNNER_CONTAINER_NAME = "runner"
_ENGINE_CONTAINER_NAME = "container-engine"
_WORKSPACE_VOLUME_NAME = "agent-workspace"
_ENGINE_SOCKET_VOLUME_NAME = "container-engine-socket"
_ENGINE_STORAGE_VOLUME_NAME = "container-engine-storage"
_SHARED_TMP_VOLUME_NAME = "runtime-shared-tmp"
_ENGINE_SOCKET_DIR = "/var/run/azents-engine"
_ENGINE_STORAGE_PATH = "/var/lib/azents-engine"
_ENGINE_SOCKET_PATH = f"{_ENGINE_SOCKET_DIR}/docker.sock"
_SHARED_TMP_PATH = "/tmp"
_RUNNER_UID = 1000
_RUNNER_GID = 1000
_ENGINE_SOCKET_GROUP = "azents-runner"
_FS_GROUP_CHANGE_POLICY = "OnRootMismatch"

_LABEL_MANAGED_BY = "azents/managed-by"
_LABEL_PROVIDER_ID = "azents/runtime-provider-id"
_LABEL_RUNTIME_ID = "azents/runtime-id"
_LABEL_AGENT_ID = "azents/agent-id"
_LABEL_WORKSPACE_ID = "azents/workspace-id"
_LABEL_DESIRED_GENERATION = "azents/desired-generation"
_LABEL_PROVIDER_GENERATION = "azents/provider-generation"
_LABEL_EXECUTION_POLICY_MANAGED = "azents/execution-policy-managed"
_ANNOTATION_WORKSPACE_PATH = "azents/workspace-path"
_ANNOTATION_POLICY_SNAPSHOT_ID = "azents/execution-policy-snapshot-id"
_ANNOTATION_POLICY_DIGEST = "azents/execution-policy-digest"
_ANNOTATION_POLICY_MODULE_VERSIONS = "azents/execution-policy-module-versions"
_ANNOTATION_POLICY_SOURCE_VERSIONS = "azents/execution-policy-source-versions"
_LABEL_IMAGE_GENERATION = "azents/image-generation"

_ENV_CONTROL_ENDPOINT = "AZ_RUNTIME_CONTROL_ENDPOINT"
_ENV_TRANSFER_ENDPOINT = "AZ_RUNTIME_TRANSFER_ENDPOINT"
_ENV_CONTROL_TLS_CA_PEM = "AZ_RUNTIME_CONTROL_TLS_CA_PEM"
_ENV_CONTROL_ALLOW_INSECURE = "AZ_RUNTIME_CONTROL_ALLOW_INSECURE"
_ENV_RUNTIME_ID = "AZ_RUNTIME_ID"
_ENV_AGENT_ID = "AZ_AGENT_ID"
_ENV_WORKSPACE_ID = "AZ_WORKSPACE_ID"
_ENV_PROVIDER_ID = "AZ_RUNTIME_PROVIDER_ID"
_ENV_PROVIDER_GENERATION = "AZ_RUNTIME_PROVIDER_GENERATION"
_ENV_DESIRED_GENERATION = "AZ_RUNTIME_DESIRED_GENERATION"
_ENV_RUNNER_AUTH_TOKEN = "AZ_RUNTIME_RUNNER_AUTH_TOKEN"
_ENV_RUNNER_AUTH_CREDENTIAL_ID = "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"
_ENV_WORKSPACE_PATH = "AZ_AGENT_WORKSPACE_PATH"
_ENV_POLICY_SNAPSHOT_ID = "AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID"
_ENV_POLICY_DIGEST = "AZ_RUNTIME_EXECUTION_POLICY_DIGEST"
_ENV_POLICY_DESIRED_GENERATION = "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION"
_ENV_POLICY_MODULE_VERSIONS = "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS"
_ENV_POLICY_SOURCE_VERSIONS = "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS"
_ENV_DOCKER_HOST = "DOCKER_HOST"
_ENV_TESTCONTAINERS_HOST_OVERRIDE = "TESTCONTAINERS_HOST_OVERRIDE"
_ENV_TESTCONTAINERS_CONNECTION_MODE = "TESTCONTAINERS_CONNECTION_MODE"
_ENV_TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE = "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE"
RUNNER_LIMIT_ENV_NAMES = (
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS",
)
_LOGGER = logging.getLogger(__name__)


class InvalidRuntimeId(ValueError):
    """Runtime id cannot be mapped to Kubernetes resource names."""


class InvalidWorkspacePath(ValueError):
    """Provider workspace mount path is missing or not absolute."""


class InvalidRunnerEnvironment(ValueError):
    """Runner environment contains a variable not managed by the Provider."""


class InvalidResetFinalDesiredState(ValueError):
    """Reset command did not provide an explicit final desired state."""


class UnsupportedExecutionPolicy(ValueError):
    """Effective policy cannot be enforced by this Provider phase."""


@dataclasses.dataclass(frozen=True)
class KubernetesRuntimeProviderConfig:
    """Configuration for a Kubernetes Runtime Provider process."""

    provider_id: str
    namespace: str
    storage_class_name: str
    pvc_storage_request: str
    runner_resources: ContainerResources | None
    runner_env: Mapping[str, str]
    engine_image: str
    runtime_control_namespace: str
    runtime_control_labels: Mapping[str, str]
    runtime_control_port: int
    network_hard_cap_allowed_cidrs: tuple[str, ...] = ()
    network_hard_cap_denied_cidrs: tuple[str, ...] = ()
    network_hard_cap_extra_egress: tuple[NetworkPolicyEgressRule, ...] = ()
    image_pull_secrets: tuple[LocalObjectReference, ...] = ()
    pod_annotations: Mapping[str, str] = dataclasses.field(default_factory=dict)
    pod_node_selector: Mapping[str, str] = dataclasses.field(default_factory=dict)
    pod_tolerations: tuple[Toleration, ...] = ()
    workspace_mount_path: str = "/workspace/agent"


class KubernetesRuntimeProvider:
    """Lifecycle-only Runtime Provider backed by Kubernetes Pod/PVC resources."""

    def __init__(
        self,
        api: KubernetesApi,
        config: KubernetesRuntimeProviderConfig,
    ) -> None:
        """Initialize the Kubernetes Provider."""
        unknown_runner_env = set(config.runner_env).difference(RUNNER_LIMIT_ENV_NAMES)
        if unknown_runner_env:
            raise InvalidRunnerEnvironment(
                f"unsupported Runner environment variables: "
                f"{', '.join(sorted(unknown_runner_env))}"
            )
        if not config.runtime_control_labels:
            raise ValueError("Runtime Control NetworkPolicy labels are required.")
        if not 1 <= config.runtime_control_port <= 65_535:
            raise ValueError("Runtime Control NetworkPolicy port is invalid.")
        for cidr in (
            *config.network_hard_cap_allowed_cidrs,
            *config.network_hard_cap_denied_cidrs,
        ):
            _ip_network(cidr)
        _immutable_image_reference(config.engine_image, "engine image")
        self._api = api
        self._config = config
        self._runner_env = dict(config.runner_env)
        self._workspace_mount_path = _absolute_posix_path(config.workspace_mount_path)

    async def start(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Start or create a Runtime Pod while preserving PVC data."""
        policy = self._validate_command(command)
        _LOGGER.info(
            "Kubernetes Runtime start requested",
            extra=_log_context(command, self._config),
        )
        await self._ensure_pvc(command, policy)
        await self._ensure_network_policy(command)
        await self._ensure_pod(command, policy, replace=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.START,
            report=await self.observe(command),
        )

    async def stop(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete the Runtime Pod and policy while preserving its PVC."""
        self._validate_command(command)
        _LOGGER.info(
            "Kubernetes Runtime stop requested",
            extra=_log_context(command, self._config),
        )
        await self._api.delete_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._api.delete_network_policy(
            _network_policy_name(command.identity.runtime_id),
            self._config.namespace,
        )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.STOP,
            report=await self.observe(command),
        )

    async def restart(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Recreate the Runtime Pod and policy while preserving its PVC."""
        policy = self._validate_command(command)
        _LOGGER.info(
            "Kubernetes Runtime restart requested",
            extra=_log_context(command, self._config),
        )
        await self._ensure_pvc(command, policy)
        await self._ensure_network_policy(command)
        await self._ensure_pod(command, policy, replace=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESTART,
            report=await self.observe(command),
        )

    async def reset(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete Pod, policy, and PVC, then converge to the reset target."""
        policy = self._validate_command(command)
        _LOGGER.info(
            "Kubernetes Runtime reset requested",
            extra={
                **_log_context(command, self._config),
                "final_desired_state": (
                    command.reset_final_desired_state.value
                    if command.reset_final_desired_state is not None
                    else None
                ),
            },
        )
        if command.reset_final_desired_state is None:
            raise InvalidResetFinalDesiredState("reset final desired state is required")
        await self._api.delete_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._api.delete_network_policy(
            _network_policy_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._api.delete_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._ensure_pvc(command, policy)
        if command.reset_final_desired_state is RuntimeDesiredState.RUNNING:
            await self._ensure_network_policy(command)
            await self._ensure_pod(command, policy, replace=False)
            report = await self.observe(command)
        else:
            report = self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="reset_pvc_recreated",
                provider_runtime_id=None,
            )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESET,
            report=report,
        )

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete the Runtime Pod, policy, and PVC without recreating them."""
        self._validate_command(command)
        _LOGGER.info(
            "Kubernetes Runtime terminal deletion requested",
            extra=_log_context(command, self._config),
        )
        await self._api.delete_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._api.delete_network_policy(
            _network_policy_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._api.delete_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.TERMINAL_DELETE,
            report=dataclasses.replace(
                self._report(
                    command,
                    observed_state=RuntimeProviderObservedState.STOPPED,
                    reason="terminal_resources_absent",
                    provider_runtime_id=None,
                ),
                workspace_path="",
                terminal_delete_acknowledged=True,
            ),
        )

    async def observe(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeProviderReport:
        """Observe one Runtime Pod/PVC/NetworkPolicy resource set."""
        self._validate_command(command)
        pod = await self._api.get_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        if pod is None:
            pvc = await self._api.get_pvc(
                _pvc_name(command.identity.runtime_id),
                self._config.namespace,
            )
            reason = (
                "pvc_present_without_pod" if pvc is not None else "resources_absent"
            )
            return self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason=reason,
                provider_runtime_id=None,
            )
        network_policy = await self._api.get_network_policy(
            _network_policy_name(command.identity.runtime_id),
            self._config.namespace,
        )
        if network_policy is None or network_policy != self._network_policy(command):
            return self._report(
                command,
                observed_state=RuntimeProviderObservedState.STARTING,
                reason="network_policy_not_ready",
                provider_runtime_id=pod.metadata.name,
            )
        observed_state, reason = _observed_state(pod)
        return self._report(
            command,
            observed_state=observed_state,
            reason=reason,
            provider_runtime_id=pod.metadata.name,
        )

    async def observe_known_runtimes(self) -> tuple[RuntimeProviderReport, ...]:
        """Scan labelled Pods/PVCs after Provider leader failover."""
        reports: list[RuntimeProviderReport] = []
        seen_runtime_ids: set[str] = set()
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
        }
        for pod in await self._api.list_pods(labels, self._config.namespace):
            runtime_id = pod.metadata.labels.get(_LABEL_RUNTIME_ID)
            if runtime_id is None:
                continue
            try:
                report = self._report_from_pod(pod)
            except ValueError:
                _LOGGER.warning(
                    "Kubernetes Runtime Pod observation skipped without trusted "
                    "policy evidence",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "pod_name": pod.metadata.name,
                    },
                )
                continue
            report = _fail_closed_without_command_policy(report)
            seen_runtime_ids.add(runtime_id)
            reports.append(report)
        for pvc in await self._api.list_pvcs(labels, self._config.namespace):
            runtime_id = pvc.metadata.labels.get(_LABEL_RUNTIME_ID)
            if runtime_id is None or runtime_id in seen_runtime_ids:
                continue
            try:
                reports.append(self._report_from_pvc(pvc))
            except ValueError:
                _LOGGER.warning(
                    "Kubernetes Runtime PVC observation skipped without trusted "
                    "policy evidence",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "pvc_name": pvc.metadata.name,
                    },
                )
        return tuple(reports)

    async def watch_known_runtimes(self) -> AsyncIterator[RuntimeProviderReport]:
        """Watch labelled Pods and emit Provider reports for every state change."""
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
        }
        async for event in self._api.watch_pods(labels, self._config.namespace):
            try:
                report = self._report_from_pod_event(event)
            except ValueError:
                runtime_id = event.pod.metadata.labels.get(_LABEL_RUNTIME_ID)
                _LOGGER.warning(
                    "Kubernetes Runtime watch event skipped without trusted policy "
                    "evidence",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "pod_name": event.pod.metadata.name,
                        "event_type": event.event_type,
                    },
                )
                continue
            if report is not None:
                if event.event_type != "DELETED":
                    report = _fail_closed_without_command_policy(report)
                yield report

    async def _ensure_pvc(
        self,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
    ) -> None:
        desired = self._pvc(command, policy)
        existing = await self._api.get_pvc(
            desired.metadata.name,
            desired.metadata.namespace,
        )
        if existing is not None:
            existing_size = _quantity_value(existing.spec.storage_request)
            desired_size = _quantity_value(desired.spec.storage_request)
            if (
                existing_size is not None
                and desired_size is not None
                and existing_size > desired_size
            ):
                desired = dataclasses.replace(
                    desired,
                    spec=dataclasses.replace(
                        desired.spec,
                        storage_request=existing.spec.storage_request,
                    ),
                )
        _LOGGER.info(
            "Kubernetes Runtime ensuring PVC",
            extra={
                **_log_context(command, self._config),
                "pvc_name": _pvc_name(command.identity.runtime_id),
                "storage_request": desired.spec.storage_request,
            },
        )
        await self._api.apply_pvc(desired)

    async def _ensure_network_policy(
        self,
        command: RuntimeLifecycleCommand,
    ) -> None:
        network_policy = self._network_policy(command)
        _LOGGER.info(
            "Kubernetes Runtime ensuring NetworkPolicy",
            extra={
                **_log_context(command, self._config),
                "network_policy_name": network_policy.metadata.name,
            },
        )
        await self._api.apply_network_policy(network_policy)

    async def _ensure_pod(
        self,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
        *,
        replace: bool,
    ) -> None:
        pod_name = _pod_name(command.identity.runtime_id)
        pod = await self._api.get_pod(pod_name, self._config.namespace)
        if pod is not None and (
            replace or not self._pod_reusable(pod, command, policy)
        ):
            grace_period_seconds = 0 if _pod_blocks_recreate(pod) else None
            _LOGGER.info(
                "Kubernetes Runtime replacing Pod",
                extra={
                    **_log_context(command, self._config),
                    "pod_name": pod_name,
                    "grace_period_seconds": grace_period_seconds,
                },
            )
            await self._api.delete_pod(
                pod_name,
                self._config.namespace,
                grace_period_seconds=grace_period_seconds,
            )
            # Kubernetes Pod deletion is asynchronous. Never server-side apply a
            # replacement while the old object still owns the name: that becomes an
            # immutable Pod PATCH and fails with 422. A later idempotent lifecycle
            # retry creates the replacement after deletion is observable.
            pod = await self._api.get_pod(pod_name, self._config.namespace)
            if pod is not None:
                return
        if pod is None:
            _LOGGER.info(
                "Kubernetes Runtime applying Pod",
                extra={
                    **_log_context(command, self._config),
                    "pod_name": pod_name,
                    "runner_image": command.runner_image,
                },
            )
            await self._api.apply_pod(self._pod(command, policy))

    def _pod_reusable(
        self,
        pod: PodResource,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
    ) -> bool:
        if _pod_blocks_recreate(pod):
            return False
        expected = self._pod(command, policy)
        labels = dict(pod.metadata.labels)
        for key, value in expected.metadata.labels.items():
            if labels.get(key) != value:
                return False
        annotations = dict(pod.metadata.annotations)
        for key, value in expected.metadata.annotations.items():
            if annotations.get(key) != value:
                return False
        if not _container_specs_equal(
            pod.spec.containers,
            expected.spec.containers,
        ):
            return False
        if not _pod_volumes_equal(pod.spec.volumes, expected.spec.volumes):
            return False
        if pod.spec.image_pull_secrets != expected.spec.image_pull_secrets:
            return False
        if pod.spec.security_context != expected.spec.security_context:
            return False
        if pod.spec.service_account_name not in {None, "default"}:
            return False
        if pod.spec.automount_service_account_token:
            return False
        if dict(pod.spec.node_selector) != dict(expected.spec.node_selector):
            return False
        if not set(self._config.pod_tolerations).issubset(set(pod.spec.tolerations)):
            return False
        return True

    def _pvc(
        self,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
    ) -> PersistentVolumeClaimResource:
        persistent_storage_bytes = policy.resources.persistent_storage_bytes
        return PersistentVolumeClaimResource(
            metadata=ObjectMeta(
                name=_pvc_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations={
                    **self._base_annotations(),
                    **self._policy_annotations(command),
                },
            ),
            spec=PersistentVolumeClaimSpec(
                storage_class_name=self._config.storage_class_name,
                access_modes=("ReadWriteOnce",),
                storage_request=(
                    str(persistent_storage_bytes)
                    if persistent_storage_bytes is not None
                    else self._config.pvc_storage_request
                ),
            ),
        )

    def _pod(
        self,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
    ) -> PodResource:
        docker_enabled = policy.docker.enabled
        docker_storage_capacity = policy.docker.storage_capacity_bytes
        runtime_ephemeral_storage = policy.resources.ephemeral_storage_bytes
        if docker_enabled and docker_storage_capacity is None:
            raise AssertionError("Docker storage capacity is required")
        if docker_enabled and runtime_ephemeral_storage is None:
            raise AssertionError("Runtime ephemeral storage is required")
        return PodResource(
            metadata=ObjectMeta(
                name=_pod_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._pod_annotations(command),
            ),
            spec=PodSpec(
                service_account_name=None,
                automount_service_account_token=False,
                image_pull_secrets=self._config.image_pull_secrets,
                security_context=self._pod_security_context(),
                node_selector=self._config.pod_node_selector,
                tolerations=self._config.pod_tolerations,
                containers=self._containers(command, policy),
                volumes=(
                    PersistentVolumeClaimVolume(
                        name=_WORKSPACE_VOLUME_NAME,
                        claim_name=_pvc_name(command.identity.runtime_id),
                    ),
                    *(
                        (
                            EmptyDirVolume(
                                name=_ENGINE_SOCKET_VOLUME_NAME,
                                medium="Memory",
                                size_limit="16Mi",
                            ),
                            EmptyDirVolume(
                                name=_SHARED_TMP_VOLUME_NAME,
                                medium=None,
                                size_limit=str(runtime_ephemeral_storage),
                            ),
                            EmptyDirVolume(
                                name=_ENGINE_STORAGE_VOLUME_NAME,
                                medium=None,
                                size_limit=str(docker_storage_capacity),
                            ),
                        )
                        if docker_enabled
                        else ()
                    ),
                ),
            ),
        )

    def _containers(
        self,
        command: RuntimeLifecycleCommand,
        policy: RuntimeExecutionPolicy,
    ) -> tuple[ContainerSpec, ...]:
        runner_mounts = [
            VolumeMount(
                name=_WORKSPACE_VOLUME_NAME,
                mount_path=self._workspace_mount_path,
                read_only=False,
            )
        ]
        docker_enabled = policy.docker.enabled
        runner_env = self._env(command)
        docker_resources = _docker_resources(policy) if docker_enabled else None
        if docker_enabled:
            runner_mounts.append(
                VolumeMount(
                    name=_ENGINE_SOCKET_VOLUME_NAME,
                    mount_path=_ENGINE_SOCKET_DIR,
                    read_only=True,
                )
            )
            runner_mounts.append(
                VolumeMount(
                    name=_SHARED_TMP_VOLUME_NAME,
                    mount_path=_SHARED_TMP_PATH,
                    read_only=False,
                )
            )
            runner_env[_ENV_DOCKER_HOST] = f"unix://{_ENGINE_SOCKET_PATH}"
            runner_env[_ENV_TESTCONTAINERS_HOST_OVERRIDE] = "127.0.0.1"
            runner_env[_ENV_TESTCONTAINERS_CONNECTION_MODE] = "docker_host"
            runner_env[_ENV_TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE] = _ENGINE_SOCKET_PATH
        runner = ContainerSpec(
            name=_RUNNER_CONTAINER_NAME,
            image=command.runner_image,
            command=None,
            args=(),
            working_dir=self._workspace_mount_path,
            resources=self._config.runner_resources,
            security_context=_unprivileged_security_context(
                uid=_RUNNER_UID,
                gid=_RUNNER_GID,
            ),
            readiness_probe=None,
            env=tuple(
                EnvVar(name=key, value=value) for key, value in runner_env.items()
            ),
            volume_mounts=tuple(runner_mounts),
        )
        if not docker_enabled:
            return (runner,)
        if docker_resources is None:
            raise AssertionError("Docker resources are required")
        engine = ContainerSpec(
            name=_ENGINE_CONTAINER_NAME,
            image=self._config.engine_image,
            command=("dockerd",),
            args=(
                f"--host=unix://{_ENGINE_SOCKET_PATH}",
                f"--data-root={_ENGINE_STORAGE_PATH}",
                f"--group={_ENGINE_SOCKET_GROUP}",
            ),
            working_dir="/",
            resources=docker_resources,
            security_context=_engine_security_context(),
            readiness_probe=_engine_probe(),
            env=(),
            volume_mounts=(
                VolumeMount(
                    name=_WORKSPACE_VOLUME_NAME,
                    mount_path=self._workspace_mount_path,
                    read_only=False,
                ),
                VolumeMount(
                    name=_ENGINE_SOCKET_VOLUME_NAME,
                    mount_path=_ENGINE_SOCKET_DIR,
                    read_only=False,
                ),
                VolumeMount(
                    name=_SHARED_TMP_VOLUME_NAME,
                    mount_path=_SHARED_TMP_PATH,
                    read_only=False,
                ),
                VolumeMount(
                    name=_ENGINE_STORAGE_VOLUME_NAME,
                    mount_path=_ENGINE_STORAGE_PATH,
                    read_only=False,
                ),
            ),
        )
        return (runner, engine)

    def _network_policy(
        self,
        command: RuntimeLifecycleCommand,
    ) -> NetworkPolicyResource:
        return NetworkPolicyResource(
            metadata=ObjectMeta(
                name=_network_policy_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._policy_annotations(command),
            ),
            spec=NetworkPolicySpec(
                pod_selector=LabelSelector(
                    match_labels={
                        _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
                        _LABEL_RUNTIME_ID: command.identity.runtime_id,
                        _LABEL_DESIRED_GENERATION: str(command.desired_generation),
                        _LABEL_PROVIDER_GENERATION: str(command.provider_generation),
                        _LABEL_EXECUTION_POLICY_MANAGED: "true",
                    }
                ),
                policy_types=("Ingress", "Egress"),
                ingress=(),
                egress=(
                    _dns_egress_rule(),
                    _runtime_control_egress_rule(self._config),
                    *_permitted_egress_rules(self._config),
                ),
            ),
        )

    def _pod_security_context(self) -> PodSecurityContext:
        return PodSecurityContext(
            run_as_user=None,
            run_as_group=None,
            fs_group=_RUNNER_GID,
            fs_group_change_policy=_FS_GROUP_CHANGE_POLICY,
        )

    def _labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_labels(command),
            _LABEL_DESIRED_GENERATION: str(command.desired_generation),
            _LABEL_PROVIDER_GENERATION: str(command.provider_generation),
            _LABEL_IMAGE_GENERATION: _IMAGE_GENERATION,
            _LABEL_EXECUTION_POLICY_MANAGED: "true",
        }

    def _stable_labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        return {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: identity.runtime_id,
            _LABEL_AGENT_ID: identity.agent_id,
            _LABEL_WORKSPACE_ID: identity.workspace_id,
        }

    def _base_annotations(self) -> dict[str, str]:
        return {_ANNOTATION_WORKSPACE_PATH: self._workspace_mount_path}

    def _pod_annotations(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._config.pod_annotations,
            **self._base_annotations(),
            **self._policy_annotations(command),
        }

    def _env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_env(command),
            **self._runner_env,
            **self._runner_auth_env(command),
            **self._policy_env(command),
            _ENV_PROVIDER_GENERATION: str(command.provider_generation),
        }

    def _runner_auth_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            _ENV_DESIRED_GENERATION: str(command.desired_generation),
            _ENV_RUNNER_AUTH_TOKEN: command.auth.runner_auth_token,
            _ENV_RUNNER_AUTH_CREDENTIAL_ID: command.auth.runner_auth_credential_id,
        }

    def _stable_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        env = {
            _ENV_CONTROL_ENDPOINT: command.auth.control_endpoint,
            _ENV_TRANSFER_ENDPOINT: command.auth.transfer_endpoint,
            _ENV_RUNTIME_ID: identity.runtime_id,
            _ENV_AGENT_ID: identity.agent_id,
            _ENV_WORKSPACE_ID: identity.workspace_id,
            _ENV_PROVIDER_ID: self._config.provider_id,
            _ENV_WORKSPACE_PATH: self._workspace_mount_path,
        }
        if command.auth.control_tls_ca_pem is not None:
            env[_ENV_CONTROL_TLS_CA_PEM] = command.auth.control_tls_ca_pem
        env[_ENV_CONTROL_ALLOW_INSECURE] = str(
            command.auth.allow_insecure_control
        ).lower()
        return env

    def _policy_annotations(
        self,
        command: RuntimeLifecycleCommand,
    ) -> dict[str, str]:
        evidence = command.execution_policy.evidence
        return {
            _ANNOTATION_POLICY_SNAPSHOT_ID: evidence.snapshot_id,
            _ANNOTATION_POLICY_DIGEST: evidence.digest,
            _ANNOTATION_POLICY_MODULE_VERSIONS: _canonical_mapping(
                evidence.module_versions
            ),
            _ANNOTATION_POLICY_SOURCE_VERSIONS: _canonical_mapping(
                evidence.source_versions
            ),
        }

    def _policy_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        evidence = command.execution_policy.evidence
        return {
            _ENV_POLICY_SNAPSHOT_ID: evidence.snapshot_id,
            _ENV_POLICY_DIGEST: evidence.digest,
            _ENV_POLICY_DESIRED_GENERATION: str(evidence.desired_generation),
            _ENV_POLICY_MODULE_VERSIONS: _canonical_mapping(evidence.module_versions),
            _ENV_POLICY_SOURCE_VERSIONS: _canonical_mapping(evidence.source_versions),
        }

    def _report(
        self,
        command: RuntimeLifecycleCommand,
        *,
        observed_state: RuntimeProviderObservedState,
        reason: str,
        provider_runtime_id: str | None,
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=command.identity.runtime_id,
            provider_id=self._config.provider_id,
            provider_generation=command.provider_generation,
            observed_state=observed_state,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id=provider_runtime_id,
            workspace_path=self._workspace_mount_path,
            reason=reason,
            diagnostic={},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            execution_policy=command.execution_policy.evidence,
        )

    def _report_from_pod(self, pod: PodResource) -> RuntimeProviderReport:
        observed_state, reason = _observed_state(pod)
        return RuntimeProviderReport(
            runtime_id=pod.metadata.labels[_LABEL_RUNTIME_ID],
            provider_id=self._config.provider_id,
            provider_generation=_int_label(
                pod.metadata.labels, _LABEL_PROVIDER_GENERATION
            ),
            observed_state=observed_state,
            observed_desired_generation=_int_label(
                pod.metadata.labels,
                _LABEL_DESIRED_GENERATION,
            ),
            provider_runtime_id=pod.metadata.name,
            workspace_path=pod.metadata.annotations.get(
                _ANNOTATION_WORKSPACE_PATH,
                self._workspace_mount_path,
            ),
            reason=reason,
            diagnostic={"source": "pod"},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            execution_policy=_policy_evidence_from_metadata(
                pod.metadata.annotations,
                desired_generation=_int_label(
                    pod.metadata.labels,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
        )

    def _report_from_pod_event(
        self,
        event: PodWatchEvent,
    ) -> RuntimeProviderReport | None:
        runtime_id = event.pod.metadata.labels.get(_LABEL_RUNTIME_ID)
        if runtime_id is None:
            return None
        if event.event_type == "DELETED":
            return RuntimeProviderReport(
                runtime_id=runtime_id,
                provider_id=self._config.provider_id,
                provider_generation=_int_label(
                    event.pod.metadata.labels, _LABEL_PROVIDER_GENERATION
                ),
                observed_state=RuntimeProviderObservedState.STOPPED,
                observed_desired_generation=_int_label(
                    event.pod.metadata.labels,
                    _LABEL_DESIRED_GENERATION,
                ),
                provider_runtime_id=None,
                workspace_path=event.pod.metadata.annotations.get(
                    _ANNOTATION_WORKSPACE_PATH,
                    self._workspace_mount_path,
                ),
                reason="pod_deleted",
                diagnostic={"source": "pod_watch", "event_type": event.event_type},
                reported_at=datetime.now(UTC),
                terminal_delete_acknowledged=False,
                execution_policy=_policy_evidence_from_metadata(
                    event.pod.metadata.annotations,
                    desired_generation=_int_label(
                        event.pod.metadata.labels,
                        _LABEL_DESIRED_GENERATION,
                    ),
                ),
            )
        report = self._report_from_pod(event.pod)
        return dataclasses.replace(
            report,
            diagnostic={"source": "pod_watch", "event_type": event.event_type},
        )

    def _report_from_pvc(
        self, pvc: PersistentVolumeClaimResource
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=pvc.metadata.labels[_LABEL_RUNTIME_ID],
            provider_id=self._config.provider_id,
            provider_generation=_int_label(
                pvc.metadata.labels, _LABEL_PROVIDER_GENERATION
            ),
            observed_state=RuntimeProviderObservedState.STOPPED,
            observed_desired_generation=_int_label(
                pvc.metadata.labels,
                _LABEL_DESIRED_GENERATION,
            ),
            provider_runtime_id=None,
            workspace_path=pvc.metadata.annotations.get(
                _ANNOTATION_WORKSPACE_PATH,
                self._workspace_mount_path,
            ),
            reason="pvc_present_without_pod",
            diagnostic={"source": "pvc"},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            execution_policy=_policy_evidence_from_metadata(
                pvc.metadata.annotations,
                desired_generation=_int_label(
                    pvc.metadata.labels,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
        )

    def _validate_command(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeExecutionPolicy:
        policy = parse_execution_policy_envelope(
            command.execution_policy,
            desired_generation=command.desired_generation,
        )
        if policy.docker.enabled:
            _immutable_image_reference(command.runner_image, "Runner image")
            _docker_resources(policy)
            if policy.docker.storage_mode is not RuntimeExecutionStorageMode.EPHEMERAL:
                raise UnsupportedExecutionPolicy(
                    "Kubernetes Runtime Provider supports ephemeral Docker "
                    "storage only."
                )
        elif policy.docker.storage_mode is not RuntimeExecutionStorageMode.NONE:
            raise UnsupportedExecutionPolicy(
                "Docker storage requires Docker to be enabled."
            )
        return policy


def _engine_security_context() -> ContainerSecurityContext:
    return ContainerSecurityContext(
        privileged=True,
        allow_privilege_escalation=True,
        read_only_root_filesystem=False,
        run_as_non_root=False,
        run_as_user=0,
        run_as_group=0,
        capabilities_add=(),
        capabilities_drop=(),
    )


def _unprivileged_security_context(
    *,
    uid: int,
    gid: int,
    read_only_root_filesystem: bool = False,
) -> ContainerSecurityContext:
    return ContainerSecurityContext(
        privileged=False,
        allow_privilege_escalation=False,
        read_only_root_filesystem=read_only_root_filesystem,
        run_as_non_root=True,
        run_as_user=uid,
        run_as_group=gid,
        capabilities_add=(),
        capabilities_drop=("ALL",),
    )


def _engine_probe() -> Probe:
    return Probe(
        exec_action=ExecAction(
            command=(
                "sh",
                "-ec",
                (
                    'test "$(docker --host '
                    f"unix://{_ENGINE_SOCKET_PATH} version "
                    "--format '{{.Server.Version}}/{{.Server.APIVersion}}')\" "
                    "= '28.5.2/1.51'"
                ),
            )
        ),
        initial_delay_seconds=1,
        period_seconds=2,
        timeout_seconds=1,
        failure_threshold=30,
    )


def _immutable_image_reference(value: str, name: str) -> str:
    if not _IMMUTABLE_IMAGE_RE.fullmatch(value):
        raise UnsupportedExecutionPolicy(
            f"{name} must use an immutable sha256 digest reference."
        )
    return value


def _docker_resources(
    policy: RuntimeExecutionPolicy,
) -> ContainerResources:
    resources = policy.resources
    cpu_request_millicores = resources.cpu_request_millicores
    cpu_limit_millicores = resources.cpu_limit_millicores
    memory_request_bytes = resources.memory_request_bytes
    memory_limit_bytes = resources.memory_limit_bytes
    ephemeral_storage_bytes = resources.ephemeral_storage_bytes
    if ephemeral_storage_bytes is None:
        raise AssertionError("execution ephemeral storage is required")
    requests = _kubernetes_resource_values(
        cpu_millicores=cpu_request_millicores,
        memory_bytes=memory_request_bytes,
        ephemeral_storage_bytes=ephemeral_storage_bytes,
    )
    limits = _kubernetes_resource_values(
        cpu_millicores=cpu_limit_millicores,
        memory_bytes=memory_limit_bytes,
        ephemeral_storage_bytes=ephemeral_storage_bytes,
    )
    return ContainerResources(
        requests=requests,
        limits=limits,
        claims=None,
    )


def _kubernetes_resource_values(
    *,
    cpu_millicores: int | None,
    memory_bytes: int | None,
    ephemeral_storage_bytes: int,
) -> dict[str, str]:
    values = {"ephemeral-storage": str(ephemeral_storage_bytes)}
    if cpu_millicores is not None and cpu_millicores > 0:
        values["cpu"] = _canonical_millicores(cpu_millicores)
    if memory_bytes is not None and memory_bytes > 0:
        values["memory"] = str(memory_bytes)
    return values


def _dns_egress_rule() -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={"kubernetes.io/metadata.name": "kube-system"}
                ),
                pod_selector=LabelSelector(match_labels={"k8s-app": "kube-dns"}),
                ip_block=None,
            ),
        ),
        ports=(
            NetworkPolicyPort(protocol="UDP", port=53),
            NetworkPolicyPort(protocol="TCP", port=53),
        ),
    )


def _runtime_control_egress_rule(
    config: KubernetesRuntimeProviderConfig,
) -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={
                        "kubernetes.io/metadata.name": (
                            config.runtime_control_namespace
                        )
                    }
                ),
                pod_selector=LabelSelector(match_labels=config.runtime_control_labels),
                ip_block=None,
            ),
        ),
        ports=(
            NetworkPolicyPort(
                protocol="TCP",
                port=config.runtime_control_port,
            ),
        ),
    )


def _permitted_egress_rules(
    config: KubernetesRuntimeProviderConfig,
) -> tuple[NetworkPolicyEgressRule, ...]:
    hard_cap_denied = tuple(
        _ip_network(value) for value in config.network_hard_cap_denied_cidrs
    )
    hard_cap_allowed = tuple(
        _ip_network(value) for value in config.network_hard_cap_allowed_cidrs
    )
    rules: list[NetworkPolicyEgressRule] = []
    for internet in (
        ipaddress.ip_network("0.0.0.0/0"),
        ipaddress.ip_network("::/0"),
    ):
        rule = _bounded_ip_block_rule(internet, denied=hard_cap_denied)
        if rule is not None:
            rules.append(rule)
    for allowed in hard_cap_allowed:
        rule = _bounded_ip_block_rule(allowed, denied=())
        if rule is not None:
            rules.append(rule)
    return (*rules, *config.network_hard_cap_extra_egress)


def _bounded_ip_block_rule(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
    *,
    denied: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> NetworkPolicyEgressRule | None:
    if any(
        _subnet_of_same_family(network, denied_network) for denied_network in denied
    ):
        return None
    return _ip_block_rule(network, denied=denied)


def _ip_block_rule(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
    *,
    denied: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> NetworkPolicyEgressRule:
    except_cidrs = tuple(
        str(denied_network)
        for denied_network in denied
        if _subnet_of_same_family(denied_network, network) and denied_network != network
    )
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=None,
                pod_selector=None,
                ip_block=IpBlock(
                    cidr=str(network),
                    except_cidrs=except_cidrs,
                ),
            ),
        ),
        ports=(),
    )


def _ip_network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as error:
        raise UnsupportedExecutionPolicy(
            "Kubernetes NetworkPolicy destinations must be IP CIDRs."
        ) from error


def _subnet_of_same_family(
    candidate: ipaddress.IPv4Network | ipaddress.IPv6Network,
    container: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    if isinstance(candidate, ipaddress.IPv4Network) and isinstance(
        container,
        ipaddress.IPv4Network,
    ):
        return candidate.subnet_of(container)
    if isinstance(candidate, ipaddress.IPv6Network) and isinstance(
        container,
        ipaddress.IPv6Network,
    ):
        return candidate.subnet_of(container)
    return False


def _fail_closed_without_command_policy(
    report: RuntimeProviderReport,
) -> RuntimeProviderReport:
    if report.observed_state not in {
        RuntimeProviderObservedState.STARTING,
        RuntimeProviderObservedState.RUNNING,
    }:
        return report
    return dataclasses.replace(
        report,
        observed_state=RuntimeProviderObservedState.STARTING,
        reason="network_policy_not_ready",
    )


def _container_specs_equal(
    actual: Sequence[ContainerSpec],
    expected: Sequence[ContainerSpec],
) -> bool:
    if len(actual) != len(expected):
        return False
    return all(
        dataclasses.replace(actual_container, resources=None)
        == dataclasses.replace(expected_container, resources=None)
        and _container_resources_equal(
            actual_container.resources,
            expected_container.resources,
        )
        for actual_container, expected_container in zip(
            actual,
            expected,
            strict=True,
        )
    )


def _container_resources_equal(
    actual: ContainerResources | None,
    expected: ContainerResources | None,
) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return (
        _resource_quantity_maps_equal(actual.requests, expected.requests)
        and _resource_quantity_maps_equal(actual.limits, expected.limits)
        and tuple(actual.claims or ()) == tuple(expected.claims or ())
    )


def _resource_quantity_maps_equal(
    actual: Mapping[str, KubernetesResourceQuantity] | None,
    expected: Mapping[str, KubernetesResourceQuantity] | None,
) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if set(actual) != set(expected):
        return False
    return all(_quantities_equal(actual[key], expected[key]) for key in actual)


def _pod_volumes_equal(
    actual: Sequence[PodVolume],
    expected: Sequence[PodVolume],
) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_volume, expected_volume in zip(actual, expected, strict=True):
        if isinstance(actual_volume, PersistentVolumeClaimVolume) or isinstance(
            expected_volume,
            PersistentVolumeClaimVolume,
        ):
            if actual_volume != expected_volume:
                return False
            continue
        if (
            actual_volume.name != expected_volume.name
            or actual_volume.medium != expected_volume.medium
        ):
            return False
        if actual_volume.size_limit is None or expected_volume.size_limit is None:
            if actual_volume.size_limit is not expected_volume.size_limit:
                return False
        elif not _quantities_equal(
            actual_volume.size_limit,
            expected_volume.size_limit,
        ):
            return False
    return True


def _canonical_millicores(value: int) -> str:
    if value % 1000 == 0:
        return str(value // 1000)
    return f"{value}m"


def _quantities_equal(
    actual: KubernetesResourceQuantity,
    expected: KubernetesResourceQuantity,
) -> bool:
    actual_value = _quantity_value(actual)
    expected_value = _quantity_value(expected)
    if actual_value is None or expected_value is None:
        return str(actual) == str(expected)
    return actual_value == expected_value


def _quantity_value(value: KubernetesResourceQuantity) -> Decimal | None:
    match = _QUANTITY_RE.fullmatch(str(value))
    if match is None:
        return None
    try:
        quantity = Decimal(match.group(1))
        exponent = match.group(2)
        if exponent is not None:
            return quantity.scaleb(int(exponent))
        suffix = match.group(3)
        if suffix is None:
            return quantity
        return quantity * _QUANTITY_SUFFIX_MULTIPLIERS[suffix]
    except InvalidOperation, ValueError:
        return None


def _absolute_posix_path(raw_path: str) -> str:
    path = PurePosixPath(raw_path.strip())
    if not raw_path.strip() or not path.is_absolute():
        raise InvalidWorkspacePath(raw_path)
    return str(path)


def _log_context(
    command: RuntimeLifecycleCommand,
    config: KubernetesRuntimeProviderConfig,
) -> dict[str, str | int]:
    return {
        "runtime_id": command.identity.runtime_id,
        "agent_id": command.identity.agent_id,
        "workspace_id": command.identity.workspace_id,
        "provider_id": config.provider_id,
        "desired_generation": command.desired_generation,
        "provider_generation": command.provider_generation,
        "namespace": config.namespace,
    }


def _pod_name(runtime_id: str) -> str:
    return f"azents-runtime-{_safe_runtime_id(runtime_id)}"


def _pvc_name(runtime_id: str) -> str:
    return f"azents-runtime-{_safe_runtime_id(runtime_id)}-workspace"


def _network_policy_name(runtime_id: str) -> str:
    return f"azents-runtime-{_safe_runtime_id(runtime_id)}-execution"


def _safe_runtime_id(runtime_id: str) -> str:
    if not _RUNTIME_ID_RE.fullmatch(runtime_id):
        raise InvalidRuntimeId(runtime_id)
    return runtime_id


def _observed_state(pod: PodResource) -> tuple[RuntimeProviderObservedState, str]:
    if pod.metadata.deletion_timestamp is not None:
        return RuntimeProviderObservedState.STOPPING, "pod_deleting"
    if pod.status is None:
        return RuntimeProviderObservedState.STARTING, "pod_created"
    if pod.status.phase == "Running" and pod.status.ready:
        return RuntimeProviderObservedState.RUNNING, "pod_running"
    if pod.status.phase in {"Failed", "Unknown"}:
        return RuntimeProviderObservedState.STOPPED, f"pod_{pod.status.phase.lower()}"
    if pod.status.ready_reason in {"NodeLost", "NodeNotReady"}:
        return RuntimeProviderObservedState.STOPPED, _pod_reason(pod.status)
    if pod.status.waiting_reason in {
        "CreateContainerConfigError",
        "CreateContainerError",
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "RunContainerError",
    }:
        return RuntimeProviderObservedState.FAILED, _pod_reason(pod.status)
    return RuntimeProviderObservedState.STARTING, "pod_not_ready"


def _pod_reason(status: PodStatus) -> str:
    reason = status.ready_reason or status.waiting_reason or status.phase or "unknown"
    return f"pod_{reason.lower()}"


def _pod_blocks_recreate(pod: PodResource) -> bool:
    if pod.metadata.deletion_timestamp is not None:
        return True
    if pod.status is None:
        return False
    return pod.status.phase in {"Failed", "Unknown"}


def _int_label(labels: Mapping[str, str], key: str) -> int:
    value = labels.get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _canonical_mapping(values: Mapping[str, int]) -> str:
    return json.dumps(dict(values), sort_keys=True, separators=(",", ":"))


def _policy_evidence_from_metadata(
    values: Mapping[str, str],
    *,
    desired_generation: int,
) -> RuntimeExecutionPolicyEvidence:
    snapshot_id = values.get(_ANNOTATION_POLICY_SNAPSHOT_ID)
    digest = values.get(_ANNOTATION_POLICY_DIGEST)
    module_versions = values.get(_ANNOTATION_POLICY_MODULE_VERSIONS)
    source_versions = values.get(_ANNOTATION_POLICY_SOURCE_VERSIONS)
    if (
        snapshot_id is None
        or digest is None
        or module_versions is None
        or source_versions is None
    ):
        raise ValueError("Runtime execution-policy metadata is incomplete.")
    try:
        parsed_modules = json.loads(module_versions)
        parsed_sources = json.loads(source_versions)
        if not isinstance(parsed_modules, dict) or not isinstance(parsed_sources, dict):
            raise ValueError("Runtime execution-policy metadata is invalid.")
        return RuntimeExecutionPolicyEvidence(
            snapshot_id=str(snapshot_id),
            digest=str(digest),
            desired_generation=desired_generation,
            module_versions={
                str(key): int(value) for key, value in parsed_modules.items()
            },
            source_versions={
                str(key): int(value) for key, value in parsed_sources.items()
            },
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Runtime execution-policy metadata is invalid.") from error
