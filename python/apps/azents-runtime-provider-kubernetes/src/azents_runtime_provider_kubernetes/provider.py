"""Kubernetes implementation of the Agent Runtime Provider lifecycle."""

import dataclasses
import logging
import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import PurePosixPath

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResources,
    ContainerSpec,
    EnvVar,
    KubernetesApi,
    LocalObjectReference,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimSpec,
    PersistentVolumeClaimVolume,
    PodResource,
    PodSecurityContext,
    PodSpec,
    PodStatus,
    PodWatchEvent,
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
_IMAGE_GENERATION = "agent-runtime-kubernetes-v1"
_RUNNER_CONTAINER_NAME = "runner"
_WORKSPACE_VOLUME_NAME = "agent-workspace"
_RUNNER_UID = 1000
_RUNNER_GID = 1000
_FS_GROUP_CHANGE_POLICY = "OnRootMismatch"

_LABEL_MANAGED_BY = "azents/managed-by"
_LABEL_PROVIDER_ID = "azents/runtime-provider-id"
_LABEL_RUNTIME_ID = "azents/runtime-id"
_LABEL_AGENT_ID = "azents/agent-id"
_LABEL_WORKSPACE_ID = "azents/workspace-id"
_LABEL_DESIRED_GENERATION = "azents/desired-generation"
_LABEL_PROVIDER_GENERATION = "azents/provider-generation"
_ANNOTATION_WORKSPACE_PATH = "azents/workspace-path"
_LABEL_IMAGE_GENERATION = "azents/image-generation"

_ENV_CONTROL_ENDPOINT = "AZ_RUNTIME_CONTROL_ENDPOINT"
_ENV_CONTROL_AUTH_TOKEN = "AZ_RUNTIME_CONTROL_AUTH_TOKEN"
_ENV_RUNTIME_ID = "AZ_RUNTIME_ID"
_ENV_AGENT_ID = "AZ_AGENT_ID"
_ENV_WORKSPACE_ID = "AZ_WORKSPACE_ID"
_ENV_PROVIDER_ID = "AZ_RUNTIME_PROVIDER_ID"
_ENV_PROVIDER_GENERATION = "AZ_RUNTIME_PROVIDER_GENERATION"
_ENV_DESIRED_GENERATION = "AZ_RUNTIME_DESIRED_GENERATION"
_ENV_RUNNER_AUTH_CREDENTIAL_ID = "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"
_ENV_WORKSPACE_PATH = "AZ_AGENT_WORKSPACE_PATH"
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


@dataclasses.dataclass(frozen=True)
class KubernetesRuntimeProviderConfig:
    """Configuration for a Kubernetes Runtime Provider process."""

    provider_id: str
    namespace: str
    storage_class_name: str
    pvc_storage_request: str
    runner_resources: ContainerResources | None
    runner_env: Mapping[str, str]
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
        self._api = api
        self._config = config
        self._runner_env = dict(config.runner_env)
        self._workspace_mount_path = _absolute_posix_path(config.workspace_mount_path)

    async def start(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Start or create a Runtime Pod while preserving PVC data."""
        _LOGGER.info(
            "Kubernetes Runtime start requested",
            extra=_log_context(command, self._config),
        )
        await self._ensure_pvc(command)
        await self._ensure_pod(command, replace=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.START,
            report=await self.observe(command),
        )

    async def stop(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete the Runtime Pod while preserving its PVC."""
        _LOGGER.info(
            "Kubernetes Runtime stop requested",
            extra=_log_context(command, self._config),
        )
        await self._api.delete_pod(
            _pod_name(command.identity.runtime_id),
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
        """Recreate the Runtime Pod while preserving its PVC."""
        _LOGGER.info(
            "Kubernetes Runtime restart requested",
            extra=_log_context(command, self._config),
        )
        await self._ensure_pvc(command)
        await self._ensure_pod(command, replace=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESTART,
            report=await self.observe(command),
        )

    async def reset(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete Pod and PVC, then converge to the reset final desired state."""
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
        await self._api.delete_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        await self._ensure_pvc(command)
        if command.reset_final_desired_state is RuntimeDesiredState.RUNNING:
            await self._ensure_pod(command, replace=False)
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

    async def observe(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeProviderReport:
        """Observe one Runtime Pod/PVC resource set."""
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
            seen_runtime_ids.add(runtime_id)
            reports.append(self._report_from_pod(pod))
        for pvc in await self._api.list_pvcs(labels, self._config.namespace):
            runtime_id = pvc.metadata.labels.get(_LABEL_RUNTIME_ID)
            if runtime_id is None or runtime_id in seen_runtime_ids:
                continue
            reports.append(self._report_from_pvc(pvc))
        return tuple(reports)

    async def watch_known_runtimes(self) -> AsyncIterator[RuntimeProviderReport]:
        """Watch labelled Pods and emit Provider reports for every state change."""
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
        }
        async for event in self._api.watch_pods(labels, self._config.namespace):
            report = self._report_from_pod_event(event)
            if report is not None:
                yield report

    async def _ensure_pvc(self, command: RuntimeLifecycleCommand) -> None:
        _LOGGER.info(
            "Kubernetes Runtime ensuring PVC",
            extra={
                **_log_context(command, self._config),
                "pvc_name": _pvc_name(command.identity.runtime_id),
            },
        )
        await self._api.apply_pvc(self._pvc(command))

    async def _ensure_pod(
        self,
        command: RuntimeLifecycleCommand,
        *,
        replace: bool,
    ) -> None:
        pod_name = _pod_name(command.identity.runtime_id)
        pod = await self._api.get_pod(pod_name, self._config.namespace)
        if pod is not None and (replace or not self._pod_reusable(pod, command)):
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
            if command.command_type is RuntimeLifecycleCommandType.START:
                pod = await self._api.get_pod(pod_name, self._config.namespace)
                if pod is not None:
                    return
            else:
                pod = None
        if pod is None:
            _LOGGER.info(
                "Kubernetes Runtime applying Pod",
                extra={
                    **_log_context(command, self._config),
                    "pod_name": pod_name,
                    "runner_image": command.runner_image,
                },
            )
            await self._api.apply_pod(self._pod(command))

    def _pod_reusable(
        self,
        pod: PodResource,
        command: RuntimeLifecycleCommand,
    ) -> bool:
        if _pod_blocks_recreate(pod):
            return False
        labels = dict(pod.metadata.labels)
        for key, value in self._stable_labels(command).items():
            if labels.get(key) != value:
                return False
        if labels.get(_LABEL_IMAGE_GENERATION) != _IMAGE_GENERATION:
            return False
        annotations = dict(pod.metadata.annotations)
        for key, value in self._pod_annotations().items():
            if annotations.get(key) != value:
                return False
        if len(pod.spec.containers) != 1:
            return False
        container = pod.spec.containers[0]
        if container.image != command.runner_image:
            return False
        if container.working_dir != self._workspace_mount_path:
            return False
        if container.resources != self._config.runner_resources:
            return False
        if tuple(pod.spec.image_pull_secrets) != self._config.image_pull_secrets:
            return False
        if pod.spec.security_context != self._pod_security_context():
            return False
        if dict(pod.spec.node_selector) != dict(self._config.pod_node_selector):
            return False
        if not set(self._config.pod_tolerations).issubset(set(pod.spec.tolerations)):
            return False
        env = {item.name: item.value for item in container.env}
        for key, value in self._stable_env(command).items():
            if env.get(key) != value:
                return False
        managed_runner_env = {
            key: value for key, value in env.items() if key in RUNNER_LIMIT_ENV_NAMES
        }
        if managed_runner_env != self._runner_env:
            return False
        expected_mount = VolumeMount(
            name=_WORKSPACE_VOLUME_NAME,
            mount_path=self._workspace_mount_path,
        )
        return expected_mount in set(container.volume_mounts)

    def _pvc(self, command: RuntimeLifecycleCommand) -> PersistentVolumeClaimResource:
        return PersistentVolumeClaimResource(
            metadata=ObjectMeta(
                name=_pvc_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._base_annotations(),
            ),
            spec=PersistentVolumeClaimSpec(
                storage_class_name=self._config.storage_class_name,
                access_modes=("ReadWriteOnce",),
                storage_request=self._config.pvc_storage_request,
            ),
        )

    def _pod(self, command: RuntimeLifecycleCommand) -> PodResource:
        return PodResource(
            metadata=ObjectMeta(
                name=_pod_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._pod_annotations(),
            ),
            spec=PodSpec(
                service_account_name=None,
                automount_service_account_token=False,
                image_pull_secrets=self._config.image_pull_secrets,
                security_context=self._pod_security_context(),
                node_selector=self._config.pod_node_selector,
                tolerations=self._config.pod_tolerations,
                containers=(
                    ContainerSpec(
                        name=_RUNNER_CONTAINER_NAME,
                        image=command.runner_image,
                        working_dir=self._workspace_mount_path,
                        resources=self._config.runner_resources,
                        env=tuple(
                            EnvVar(name=key, value=value)
                            for key, value in self._env(command).items()
                        ),
                        volume_mounts=(
                            VolumeMount(
                                name=_WORKSPACE_VOLUME_NAME,
                                mount_path=self._workspace_mount_path,
                            ),
                        ),
                    ),
                ),
                volumes=(
                    PersistentVolumeClaimVolume(
                        name=_WORKSPACE_VOLUME_NAME,
                        claim_name=_pvc_name(command.identity.runtime_id),
                    ),
                ),
            ),
        )

    def _pod_security_context(self) -> PodSecurityContext:
        return PodSecurityContext(
            run_as_user=_RUNNER_UID,
            run_as_group=_RUNNER_GID,
            fs_group=_RUNNER_GID,
            fs_group_change_policy=_FS_GROUP_CHANGE_POLICY,
        )

    def _labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_labels(command),
            _LABEL_DESIRED_GENERATION: str(command.desired_generation),
            _LABEL_PROVIDER_GENERATION: str(command.provider_generation),
            _LABEL_IMAGE_GENERATION: _IMAGE_GENERATION,
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

    def _pod_annotations(self) -> dict[str, str]:
        return {
            **self._config.pod_annotations,
            **self._base_annotations(),
        }

    def _env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_env(command),
            **self._runner_env,
            _ENV_PROVIDER_GENERATION: str(command.provider_generation),
            _ENV_DESIRED_GENERATION: str(command.desired_generation),
            _ENV_RUNNER_AUTH_CREDENTIAL_ID: command.auth.runner_auth_token,
        }

    def _stable_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        env = {
            _ENV_CONTROL_ENDPOINT: command.auth.control_endpoint,
            _ENV_RUNTIME_ID: identity.runtime_id,
            _ENV_AGENT_ID: identity.agent_id,
            _ENV_WORKSPACE_ID: identity.workspace_id,
            _ENV_PROVIDER_ID: self._config.provider_id,
            _ENV_WORKSPACE_PATH: self._workspace_mount_path,
        }
        if command.auth.control_token is not None:
            env[_ENV_CONTROL_AUTH_TOKEN] = command.auth.control_token
        return env

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
        )


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
