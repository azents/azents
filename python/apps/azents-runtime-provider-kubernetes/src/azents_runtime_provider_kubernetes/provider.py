"""Kubernetes implementation of the Agent Runtime Provider lifecycle."""

import dataclasses
import ipaddress
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from azents_runtime_control.provider import (
    RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
    RuntimeDesiredState,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderObservedState,
    RuntimeProviderReconciliationEvidence,
    RuntimeProviderReconciliationObservation,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    KubernetesContainerResources as ResolvedKubernetesContainerResources,
)
from azents_runtime_control.runtime_configuration import (
    KubernetesPodProfileV1,
    KubernetesPodProfileV2,
    KubernetesPodProfileV3,
    RuntimeConfigurationEvidence,
    RuntimeNetworkMode,
    RuntimeNetworkPolicy,
    RuntimeProxyRequiredNetworkAccess,
    parse_configuration_sequence,
    parse_runtime_configuration_envelope,
    serialize_configuration_sequence,
    validate_runtime_configuration_cleanup_envelope,
)

from azents_runtime_provider_kubernetes.interception_ca import (
    CA_COMBINED_SECRET_KEY,
    CA_PUBLIC_SECRET_KEY,
    InvalidRuntimeCa,
    RuntimeCaMaterial,
    generate_runtime_ca,
    validate_runtime_ca,
)
from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
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
    SeccompProfile,
    SecretResource,
    Toleration,
    VolumeMount,
)
from azents_runtime_provider_kubernetes.network_enforcement import (
    InvalidMandatoryService,
    MandatoryServiceReference,
    NetworkEnforcementInputs,
    ObservedMandatoryService,
    RuntimeNetworkInputs,
    build_proxy_network_inputs,
    build_runtime_network_inputs,
    endpoint_from_url,
    observe_mandatory_service,
    validate_endpoint_authority,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    ANNOTATION_CA_FINGERPRINT,
    ANNOTATION_NETWORK_MODE,
    LABEL_RESOURCE_ROLE,
    InvalidOwnedResourceMetadata,
    OwnedResourceIdentity,
    ResourceRole,
    config_map_comparison_view,
    resource_name,
    secret_comparison_view,
    service_comparison_view,
)
from azents_runtime_provider_kubernetes.strict_resources import (
    RUNTIME_CA_MOUNT_PATH,
    RUNTIME_CA_VOLUME,
    RUNTIME_TRUST_MOUNT_PATH,
    RUNTIME_TRUST_VOLUME,
    ProxyResourceInputs,
    ProxyResources,
    build_proxy_resources,
    runtime_ca_volume,
    runtime_proxy_environment,
    runtime_trust_volume,
)

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
_LABEL_CONFIGURATION_MANAGED = "azents/runtime-configuration-managed"
_ANNOTATION_CONFIGURATION_SEQUENCE = "azents/runtime-configuration-sequence"
_ANNOTATION_CONFIGURATION_DIGEST = "azents/runtime-configuration-digest"
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
_ENV_HOME = "HOME"
_ENV_CONFIGURATION_SEQUENCE = "AZ_RUNTIME_CONFIGURATION_SEQUENCE"
_ENV_CONFIGURATION_DIGEST = "AZ_RUNTIME_CONFIGURATION_DIGEST"
_ENV_CONFIGURATION_DESIRED_GENERATION = "AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION"
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
type KubernetesPodProfile = (
    KubernetesPodProfileV1 | KubernetesPodProfileV2 | KubernetesPodProfileV3
)


class InvalidWorkspacePath(ValueError):
    """Provider workspace mount path is missing or not absolute."""


class InvalidRunnerEnvironment(ValueError):
    """Runner environment contains a variable not managed by the Provider."""


class InvalidResetFinalDesiredState(ValueError):
    """Reset command did not provide an explicit final desired state."""


class UnsupportedRuntimeConfiguration(ValueError):
    """Resolved configuration cannot be enforced by this Provider."""


class NetworkRecreationRequired(UnsupportedRuntimeConfiguration):
    """The requested enforcement change requires Runtime recreation."""


class ProxyNotReady(UnsupportedRuntimeConfiguration):
    """The strict proxy bundle is not ready for Runtime acknowledgement."""


@dataclasses.dataclass(frozen=True)
class _V3Bundle:
    """Complete desired resources for one Profile v3 command."""

    identity: OwnedResourceIdentity
    mandatory_services: tuple[ObservedMandatoryService, ...]
    runtime_network: RuntimeNetworkInputs
    runtime_pod: PodResource
    ca: RuntimeCaMaterial | None
    proxy: ProxyResources | None
    proxy_ingress_policy: NetworkPolicyResource | None
    proxy_egress_policy: NetworkPolicyResource | None


@dataclasses.dataclass(frozen=True)
class KubernetesRuntimeProviderConfig:
    """Configuration for a Kubernetes Runtime Provider process."""

    provider_id: str
    namespace: str
    runner_env: Mapping[str, str]
    engine_image: str
    runtime_control_namespace: str
    runtime_control_labels: Mapping[str, str]
    runtime_control_port: int
    mandatory_services: tuple[MandatoryServiceReference, ...]
    proxy_image: str | None
    proxy_addon_digest: str | None
    proxy_port: int
    proxy_readiness_port: int
    workspace_mount_path: str
    network_hard_cap_allowed_cidrs: tuple[str, ...] = ()
    network_hard_cap_denied_cidrs: tuple[str, ...] = ()
    network_hard_cap_extra_egress: tuple[NetworkPolicyEgressRule, ...] = ()
    image_pull_secrets: tuple[LocalObjectReference, ...] = ()
    pod_annotations: Mapping[str, str] = dataclasses.field(default_factory=dict)


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
        if len(config.mandatory_services) != 2 or {
            item.role for item in config.mandatory_services
        } != {"runtime_control", "runtime_transfer"}:
            raise ValueError(
                "Runtime Control and transfer mandatory Service references are "
                "required."
            )
        if not 1 <= config.proxy_port <= 65_535:
            raise ValueError("proxy port is invalid")
        if not 1 <= config.proxy_readiness_port <= 65_535:
            raise ValueError("proxy readiness port is invalid")
        for cidr in (
            *config.network_hard_cap_allowed_cidrs,
            *config.network_hard_cap_denied_cidrs,
        ):
            _ip_network(cidr)
        _validate_extra_egress_ip_blocks(config.network_hard_cap_extra_egress)
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
        if isinstance(policy, KubernetesPodProfileV3):
            await self._start_v3(command, policy, replace_runtime=False)
            return RuntimeLifecycleResult(
                command_type=RuntimeLifecycleCommandType.START,
                report=await self.observe(command),
            )
        await self._ensure_pvc(command, policy, ca_fingerprint=None)
        if await self._delete_strict_runtime_before_direct(command):
            return RuntimeLifecycleResult(
                command_type=RuntimeLifecycleCommandType.START,
                report=await self.observe(command),
            )
        await self._ensure_network_policy(command, policy)
        await self._ensure_pod(command, policy, replace=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.START,
            report=await self.observe(command),
        )

    async def stop(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete execution resources while preserving the PVC and Runtime CA."""
        self._validate_cleanup_command(command)
        _LOGGER.info(
            "Kubernetes Runtime stop requested",
            extra=_log_context(command, self._config),
        )
        await self._validate_existing_execution_ownership(command)
        await self._delete_runtime_pod(command)
        await self._delete_execution_resources(command, delete_ca=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.STOP,
            report=self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="pod_and_policy_removed",
                provider_runtime_id=None,
                reconciliation=None,
            ),
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
        if isinstance(policy, KubernetesPodProfileV3):
            await self._start_v3(command, policy, replace_runtime=True)
            return RuntimeLifecycleResult(
                command_type=RuntimeLifecycleCommandType.RESTART,
                report=await self.observe(command),
            )
        await self._ensure_pvc(command, policy, ca_fingerprint=None)
        if await self._delete_strict_runtime_before_direct(command):
            return RuntimeLifecycleResult(
                command_type=RuntimeLifecycleCommandType.RESTART,
                report=await self.observe(command),
            )
        await self._ensure_network_policy(command, policy)
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
        await self._validate_existing_execution_ownership(command)
        retained_ca_fingerprint = await self._retained_ca_fingerprint(command)
        await self._delete_runtime_pod(command)
        await self._delete_execution_resources(command, delete_ca=False)
        await self._delete_workspace_pvc(command)
        await self._ensure_pvc(
            command,
            policy,
            ca_fingerprint=retained_ca_fingerprint,
        )
        if command.reset_final_desired_state is RuntimeDesiredState.RUNNING:
            if isinstance(policy, KubernetesPodProfileV3):
                await self._start_v3(command, policy, replace_runtime=False)
            else:
                await self._ensure_network_policy(command, policy)
                await self._ensure_pod(command, policy, replace=False)
            report = await self.observe(command)
        else:
            report = self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="reset_pvc_recreated",
                provider_runtime_id=None,
                reconciliation=None,
            )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESET,
            report=report,
        )

    async def update_configuration(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Apply a NetworkPolicy-only update without replacing Pod or PVC."""
        policy = self._validate_command(command)
        if isinstance(policy, KubernetesPodProfileV3):
            return await self._update_configuration_v3(command, policy)
        pod = await self._api.get_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        pvc = await self._api.get_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        if (
            pod is None
            or pvc is None
            or not self._pod_in_place_compatible(pod, command, policy)
            or not self._pvc_in_place_compatible(pvc, command, policy)
        ):
            raise UnsupportedRuntimeConfiguration(
                "Runtime configuration requires Kubernetes resource recreation."
            )
        await self._ensure_network_policy(command, policy)
        report = await self.observe(command)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.UPDATE_CONFIGURATION,
            report=dataclasses.replace(
                report,
                reason=f"network_policy_updated:{report.reason}",
            ),
        )

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete the exact complete owned Runtime resource set."""
        self._validate_cleanup_command(command)
        _LOGGER.info(
            "Kubernetes Runtime terminal deletion requested",
            extra=_log_context(command, self._config),
        )
        await self._validate_existing_execution_ownership(command)
        await self._delete_runtime_pod(command)
        await self._delete_execution_resources(command, delete_ca=True)
        await self._delete_workspace_pvc(command)
        if not await self._terminal_resources_absent(command):
            return RuntimeLifecycleResult(
                command_type=RuntimeLifecycleCommandType.TERMINAL_DELETE,
                report=self._report(
                    command,
                    observed_state=RuntimeProviderObservedState.STOPPING,
                    reason="terminal_deletion_in_progress",
                    provider_runtime_id=None,
                    reconciliation=None,
                ),
            )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.TERMINAL_DELETE,
            report=dataclasses.replace(
                self._report(
                    command,
                    observed_state=RuntimeProviderObservedState.STOPPED,
                    reason="terminal_resources_absent",
                    provider_runtime_id=None,
                    reconciliation=None,
                ),
                terminal_delete_acknowledged=True,
            ),
        )

    async def observe(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeProviderReport:
        """Observe one Runtime Pod/PVC/NetworkPolicy resource set."""
        policy = self._validate_command(command)
        if isinstance(policy, KubernetesPodProfileV3):
            return await self._observe_v3(command, policy)
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
                reconciliation=None,
            )
        network_policy = await self._api.get_network_policy(
            _network_policy_name(command.identity.runtime_id),
            self._config.namespace,
        )
        expected_network_policy = self._network_policy(command, policy)
        observed_state, reason = _observed_state(pod)
        return dataclasses.replace(
            self._report(
                command,
                observed_state=observed_state,
                reason=reason,
                provider_runtime_id=pod.metadata.name,
                reconciliation=_network_policy_reconciliation(
                    network_policy,
                    expected_network_policy,
                ),
            ),
            diagnostic=_pod_diagnostic(pod),
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
            role = pod.metadata.labels.get(LABEL_RESOURCE_ROLE)
            if runtime_id is None or role not in {
                None,
                ResourceRole.RUNTIME_POD.value,
            }:
                continue
            try:
                _validate_recovered_runtime_resource(
                    pod.metadata,
                    self._config,
                    ResourceRole.RUNTIME_POD,
                    allow_missing_role=True,
                )
                report = self._report_from_pod(pod)
            except ValueError:
                _LOGGER.warning(
                    "Kubernetes Runtime Pod observation skipped without valid "
                    "Runtime metadata",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "pod_name": pod.metadata.name,
                    },
                )
                continue
            seen_runtime_ids.add(runtime_id)
            reports.append(report)
        for pvc in await self._api.list_pvcs(labels, self._config.namespace):
            runtime_id = pvc.metadata.labels.get(_LABEL_RUNTIME_ID)
            if runtime_id is None or runtime_id in seen_runtime_ids:
                continue
            try:
                _validate_recovered_runtime_resource(
                    pvc.metadata,
                    self._config,
                    ResourceRole.WORKSPACE_PVC,
                    allow_missing_role=True,
                )
                reports.append(self._report_from_pvc(pvc))
            except ValueError:
                _LOGGER.warning(
                    "Kubernetes Runtime PVC observation skipped without valid "
                    "Runtime metadata",
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
            role = event.pod.metadata.labels.get(LABEL_RESOURCE_ROLE)
            if role not in {None, ResourceRole.RUNTIME_POD.value}:
                continue
            try:
                _validate_recovered_runtime_resource(
                    event.pod.metadata,
                    self._config,
                    ResourceRole.RUNTIME_POD,
                    allow_missing_role=True,
                )
                report = self._report_from_pod_event(event)
            except ValueError:
                runtime_id = event.pod.metadata.labels.get(_LABEL_RUNTIME_ID)
                _LOGGER.warning(
                    "Kubernetes Runtime watch event skipped without valid Runtime "
                    "metadata",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "pod_name": event.pod.metadata.name,
                        "event_type": event.event_type,
                    },
                )
                continue
            if report is not None:
                yield report

    async def _start_v3(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
        *,
        replace_runtime: bool,
    ) -> None:
        await self._validate_existing_execution_ownership(command)
        bundle = await self._v3_bundle(command, policy, prepare_proxy=True)
        if bundle is None:
            return
        await self._ensure_pvc(
            command,
            policy,
            ca_fingerprint=None if bundle.ca is None else bundle.ca.fingerprint,
        )
        current = await self._api.get_pod(
            bundle.runtime_pod.metadata.name,
            self._config.namespace,
        )
        current_mode = _pod_network_mode(current)
        if current is not None and current_mode is None:
            current_mode = RuntimeNetworkMode.DIRECT
        desired_mode = policy.network_access.mode
        if (
            current is not None
            and current_mode is not None
            and _network_mode_rank(desired_mode) > _network_mode_rank(current_mode)
        ):
            await self._delete_runtime_pod(command)
            if (
                await self._api.get_pod(
                    bundle.runtime_pod.metadata.name,
                    self._config.namespace,
                )
                is not None
            ):
                return
        await self._apply_owned_network_policy(
            command,
            bundle.runtime_network.runtime_policy,
            ResourceRole.RUNTIME_NETWORK_POLICY,
            allow_missing_role=True,
        )
        await self._ensure_v3_runtime_pod(
            command,
            bundle.runtime_pod,
            replace=replace_runtime or current_mode != desired_mode,
        )
        runtime = await self._api.get_pod(
            bundle.runtime_pod.metadata.name,
            self._config.namespace,
        )
        if (
            runtime is not None
            and _pod_network_mode(runtime) is desired_mode
            and desired_mode is not RuntimeNetworkMode.PROXY_REQUIRED
        ):
            await self._delete_proxy_resources(command)

    async def _delete_strict_runtime_before_direct(
        self,
        command: RuntimeLifecycleCommand,
    ) -> bool:
        pod = await self._api.get_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        if pod is None or _pod_network_mode(pod) in {
            None,
            RuntimeNetworkMode.DIRECT,
        }:
            return False
        await self._delete_runtime_pod(command)
        return (
            await self._api.get_pod(
                _pod_name(command.identity.runtime_id),
                self._config.namespace,
            )
            is not None
        )

    async def _update_configuration_v3(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
    ) -> RuntimeLifecycleResult:
        await self._validate_existing_execution_ownership(command)
        pod = await self._api.get_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        pvc = await self._api.get_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        bundle = await self._v3_bundle(command, policy, prepare_proxy=True)
        if bundle is None:
            raise ProxyNotReady("proxy_not_ready")
        if (
            pod is None
            or pvc is None
            or _pod_network_mode(pod) is not policy.network_access.mode
            or not _v3_pod_in_place_compatible(pod, bundle.runtime_pod)
            or not self._pvc_in_place_compatible(pvc, command, policy)
        ):
            raise NetworkRecreationRequired("network_recreation_required")
        await self._apply_owned_network_policy(
            command,
            bundle.runtime_network.runtime_policy,
            ResourceRole.RUNTIME_NETWORK_POLICY,
            allow_missing_role=True,
        )
        report = await self._observe_v3(command, policy)
        reconciliation = report.reconciliation
        if (
            reconciliation is None
            or reconciliation.observations[0].status
            is not RuntimeProviderReconciliationStatus.IN_SYNC
        ):
            raise UnsupportedRuntimeConfiguration("network_enforcement_drifted")
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.UPDATE_CONFIGURATION,
            report=dataclasses.replace(
                report,
                reason=f"network_enforcement_updated:{report.reason}",
            ),
        )

    async def _observe_v3(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
    ) -> RuntimeProviderReport:
        pod = await self._api.get_pod(
            _pod_name(command.identity.runtime_id),
            self._config.namespace,
        )
        try:
            bundle = await self._v3_bundle(command, policy, prepare_proxy=False)
        except (InvalidMandatoryService, InvalidRuntimeCa) as error:
            observed_state, reason = (
                (RuntimeProviderObservedState.STOPPED, "resources_absent")
                if pod is None
                else _observed_state(pod)
            )
            return self._report(
                command,
                observed_state=observed_state,
                reason=reason,
                provider_runtime_id=None if pod is None else pod.metadata.name,
                reconciliation=_network_enforcement_evidence(
                    status=RuntimeProviderReconciliationStatus.DRIFTED,
                    reason=_safe_enforcement_error_reason(error),
                    diagnostic={"mode": policy.network_access.mode.value},
                ),
            )
        if bundle is None:
            reconciliation = _network_enforcement_evidence(
                status=RuntimeProviderReconciliationStatus.DRIFTED,
                reason="proxy_service_pending",
                diagnostic={"mode": policy.network_access.mode.value},
            )
        else:
            reconciliation = await self._v3_reconciliation(policy, bundle)
        if pod is None:
            proxy_pod = await self._api.get_pod(
                resource_name(command.identity.runtime_id, ResourceRole.PROXY_POD),
                self._config.namespace,
            )
            return self._report(
                command,
                observed_state=(
                    RuntimeProviderObservedState.STARTING
                    if proxy_pod is not None
                    else RuntimeProviderObservedState.STOPPED
                ),
                reason=(
                    "proxy_preparing" if proxy_pod is not None else "resources_absent"
                ),
                provider_runtime_id=None,
                reconciliation=reconciliation,
            )
        observed_state, reason = _observed_state(pod)
        return dataclasses.replace(
            self._report(
                command,
                observed_state=observed_state,
                reason=reason,
                provider_runtime_id=pod.metadata.name,
                reconciliation=reconciliation,
            ),
            diagnostic=_pod_diagnostic(pod),
        )

    async def _v3_bundle(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
        *,
        prepare_proxy: bool,
    ) -> _V3Bundle | None:
        mandatory_services = await self._observe_mandatory_services(command)
        identity = _owned_identity(command, self._config)
        enforcement = self._network_enforcement_inputs(
            command,
            policy,
            identity=identity,
            mandatory_services=mandatory_services,
        )
        ca: RuntimeCaMaterial | None = None
        proxy: ProxyResources | None = None
        proxy_ingress_policy: NetworkPolicyResource | None = None
        proxy_egress_policy: NetworkPolicyResource | None = None
        proxy_service_ip: str | None = None
        proxy_hostname: str | None = None
        if isinstance(policy.network_access, RuntimeProxyRequiredNetworkAccess):
            ca = await self._runtime_ca(
                command,
                identity=identity,
                create=prepare_proxy,
            )
            proxy = await self._proxy_resources(
                command,
                policy,
                identity=identity,
                ca=ca,
            )
            if prepare_proxy:
                await self._ensure_proxy_resources(command, proxy, enforcement)
                proxy = await self._proxy_resources(
                    command,
                    policy,
                    identity=identity,
                    ca=ca,
                )
            proxy_service_ip = proxy.service.spec.cluster_ip
            if proxy_service_ip is None:
                return None
            proxy_hostname = proxy.service_hostname
            proxy_network = build_proxy_network_inputs(enforcement)
            proxy_ingress_policy = proxy_network.ingress_policy
            proxy_egress_policy = proxy_network.egress_policy
            if prepare_proxy and not await self._proxy_ready(proxy):
                return None
        runtime_network = build_runtime_network_inputs(
            enforcement,
            proxy_service_ip=proxy_service_ip,
            proxy_hostname=proxy_hostname,
        )
        runtime_pod = self._v3_runtime_pod(
            command,
            policy,
            runtime_network=runtime_network,
            ca=ca,
            proxy=proxy,
        )
        return _V3Bundle(
            identity=identity,
            mandatory_services=mandatory_services,
            runtime_network=runtime_network,
            runtime_pod=runtime_pod,
            ca=ca,
            proxy=proxy,
            proxy_ingress_policy=proxy_ingress_policy,
            proxy_egress_policy=proxy_egress_policy,
        )

    async def _observe_mandatory_services(
        self,
        command: RuntimeLifecycleCommand,
    ) -> tuple[ObservedMandatoryService, ...]:
        observed: list[ObservedMandatoryService] = []
        for reference in self._config.mandatory_services:
            observed.append(
                observe_mandatory_service(
                    reference,
                    await self._api.get_service(
                        reference.name,
                        reference.namespace,
                    ),
                )
            )
        result = tuple(observed)
        validate_endpoint_authority(
            endpoint_from_url(command.auth.control_endpoint, default_port=None),
            result,
            role="runtime_control",
        )
        validate_endpoint_authority(
            endpoint_from_url(command.auth.transfer_endpoint, default_port=None),
            result,
            role="runtime_transfer",
        )
        return result

    def _network_enforcement_inputs(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
        *,
        identity: OwnedResourceIdentity,
        mandatory_services: tuple[ObservedMandatoryService, ...],
    ) -> NetworkEnforcementInputs:
        evidence = command.runtime_configuration.evidence
        return NetworkEnforcementInputs(
            namespace=self._config.namespace,
            identity=identity,
            desired_generation=command.desired_generation,
            configuration_sequence=evidence.configuration_sequence,
            configuration_digest=evidence.digest,
            network_access=policy.network_access,
            mandatory_services=mandatory_services,
            runtime_control_namespace=self._config.runtime_control_namespace,
            runtime_control_labels=self._config.runtime_control_labels,
            network_hard_cap_allowed_cidrs=(
                self._config.network_hard_cap_allowed_cidrs
            ),
            network_hard_cap_denied_cidrs=(self._config.network_hard_cap_denied_cidrs),
            network_hard_cap_extra_egress=(self._config.network_hard_cap_extra_egress),
            proxy_port=self._config.proxy_port,
        )

    async def _runtime_ca(
        self,
        command: RuntimeLifecycleCommand,
        *,
        identity: OwnedResourceIdentity,
        create: bool,
    ) -> RuntimeCaMaterial:
        name = resource_name(command.identity.runtime_id, ResourceRole.RUNTIME_CA)
        secret = await self._api.get_secret(name, self._config.namespace)
        if secret is None:
            if not create:
                raise InvalidRuntimeCa("Runtime CA is missing")
            if await self._has_prior_ca_identity(command):
                raise InvalidRuntimeCa("Runtime CA is missing for existing Runtime")
            return generate_runtime_ca(
                command.identity.runtime_id,
                now=datetime.now(UTC),
            )
        _validate_owned_role(secret.metadata, identity, ResourceRole.RUNTIME_CA)
        try:
            combined_pem = secret.data[CA_COMBINED_SECRET_KEY]
            public_pem = secret.data[CA_PUBLIC_SECRET_KEY]
        except KeyError as error:
            raise InvalidRuntimeCa("Runtime CA Secret keys are missing") from error
        ca = validate_runtime_ca(
            command.identity.runtime_id,
            combined_pem=combined_pem,
            public_certificate_pem=public_pem,
            expected_fingerprint=secret.metadata.annotations.get(
                ANNOTATION_CA_FINGERPRINT
            ),
        )
        retained_fingerprint = await self._retained_ca_fingerprint(command)
        if retained_fingerprint is not None and retained_fingerprint != ca.fingerprint:
            raise InvalidRuntimeCa("Runtime CA fingerprint does not match PVC")
        return ca

    async def _has_prior_ca_identity(
        self,
        command: RuntimeLifecycleCommand,
    ) -> bool:
        if await self._retained_ca_fingerprint(command) is not None:
            return True
        runtime_id = command.identity.runtime_id
        runtime_pod = await self._api.get_pod(
            resource_name(runtime_id, ResourceRole.RUNTIME_POD),
            self._config.namespace,
        )
        resources = (
            await self._api.get_pod(
                resource_name(runtime_id, ResourceRole.PROXY_POD),
                self._config.namespace,
            ),
            await self._api.get_service(
                resource_name(runtime_id, ResourceRole.PROXY_SERVICE),
                self._config.namespace,
            ),
            await self._api.get_network_policy(
                resource_name(
                    runtime_id,
                    ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
                ),
                self._config.namespace,
            ),
            await self._api.get_network_policy(
                resource_name(
                    runtime_id,
                    ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
                ),
                self._config.namespace,
            ),
        )
        return (
            runtime_pod is not None
            and ANNOTATION_CA_FINGERPRINT in runtime_pod.metadata.annotations
        ) or any(resource is not None for resource in resources)

    async def _proxy_resources(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
        *,
        identity: OwnedResourceIdentity,
        ca: RuntimeCaMaterial,
    ) -> ProxyResources:
        service_name = resource_name(
            command.identity.runtime_id,
            ResourceRole.PROXY_SERVICE,
        )
        existing_service = await self._api.get_service(
            service_name,
            self._config.namespace,
        )
        existing_cluster_ip = None
        if existing_service is not None:
            _validate_owned_role(
                existing_service.metadata,
                identity,
                ResourceRole.PROXY_SERVICE,
            )
            existing_cluster_ip = existing_service.spec.cluster_ip
        network_access = policy.network_access
        if not isinstance(network_access, RuntimeProxyRequiredNetworkAccess):
            raise AssertionError("proxy resources require proxy-required mode")
        proxy_image = self._config.proxy_image
        proxy_addon_digest = self._config.proxy_addon_digest
        if proxy_image is None or proxy_addon_digest is None:
            raise UnsupportedRuntimeConfiguration(
                "Proxy-required Runtime configuration requires immutable Provider "
                "proxy artifacts."
            )
        return build_proxy_resources(
            ProxyResourceInputs(
                namespace=self._config.namespace,
                identity=identity,
                desired_generation=command.desired_generation,
                configuration_sequence=(
                    command.runtime_configuration.evidence.configuration_sequence
                ),
                configuration_digest=command.runtime_configuration.evidence.digest,
                network_access=network_access,
                ca=ca,
                proxy_image=proxy_image,
                addon_digest=proxy_addon_digest,
                proxy_port=self._config.proxy_port,
                readiness_port=self._config.proxy_readiness_port,
                image_pull_secrets=self._config.image_pull_secrets,
                node_selector=policy.scheduling.node_selector,
                tolerations=_tolerations(policy),
            ),
            existing_cluster_ip=existing_cluster_ip,
        )

    async def _ensure_proxy_resources(
        self,
        command: RuntimeLifecycleCommand,
        proxy: ProxyResources,
        enforcement: NetworkEnforcementInputs,
    ) -> None:
        existing_ca = await self._api.get_secret(
            proxy.ca_secret.metadata.name,
            self._config.namespace,
        )
        if existing_ca is None:
            await self._api.apply_secret(proxy.ca_secret)
        elif secret_comparison_view(existing_ca) != secret_comparison_view(
            proxy.ca_secret
        ):
            raise InvalidRuntimeCa("Runtime CA Secret does not match validated CA")
        existing_config_map = await self._api.get_config_map(
            proxy.policy_config_map.metadata.name,
            self._config.namespace,
        )
        if existing_config_map is not None:
            _validate_owned_role(
                existing_config_map.metadata,
                _owned_identity(command, self._config),
                ResourceRole.PROXY_POLICY,
            )
        await self._api.apply_config_map(proxy.policy_config_map)
        await self._api.apply_service(proxy.service)
        proxy_network = build_proxy_network_inputs(enforcement)
        await self._apply_owned_network_policy(
            command,
            proxy_network.ingress_policy,
            ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
        )
        await self._apply_owned_network_policy(
            command,
            proxy_network.egress_policy,
            ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
        )
        pod = await self._api.get_pod(
            proxy.pod.metadata.name,
            self._config.namespace,
        )
        if pod is not None:
            _validate_owned_role(
                pod.metadata,
                _owned_identity(command, self._config),
                ResourceRole.PROXY_POD,
            )
        if pod is not None and not _pod_semantically_equal(pod, proxy.pod):
            await self._api.delete_pod(
                proxy.pod.metadata.name,
                self._config.namespace,
            )
            pod = await self._api.get_pod(
                proxy.pod.metadata.name,
                self._config.namespace,
            )
            if pod is not None:
                return
        if pod is None:
            await self._api.apply_pod(proxy.pod)
            return
        if await self._proxy_ready(proxy):
            await self._delete_obsolete_proxy_policy_config_maps(command, proxy)

    async def _proxy_ready(self, proxy: ProxyResources) -> bool:
        pod = await self._api.get_pod(
            proxy.pod.metadata.name,
            self._config.namespace,
        )
        config_map = await self._api.get_config_map(
            proxy.policy_config_map.metadata.name,
            self._config.namespace,
        )
        service = await self._api.get_service(
            proxy.service.metadata.name,
            self._config.namespace,
        )
        secret = await self._api.get_secret(
            proxy.ca_secret.metadata.name,
            self._config.namespace,
        )
        return (
            pod is not None
            and pod.status is not None
            and pod.status.phase == "Running"
            and pod.status.ready
            and _pod_semantically_equal(pod, proxy.pod)
            and config_map is not None
            and config_map_comparison_view(config_map)
            == config_map_comparison_view(proxy.policy_config_map)
            and service is not None
            and service_comparison_view(service)
            == service_comparison_view(proxy.service)
            and secret is not None
            and secret_comparison_view(secret)
            == secret_comparison_view(proxy.ca_secret)
        )

    def _v3_runtime_pod(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV3,
        *,
        runtime_network: RuntimeNetworkInputs,
        ca: RuntimeCaMaterial | None,
        proxy: ProxyResources | None,
    ) -> PodResource:
        base = self._pod(command, policy)
        containers = list(base.spec.containers)
        volumes = list(base.spec.volumes)
        annotations = {
            **base.metadata.annotations,
            ANNOTATION_NETWORK_MODE: policy.network_access.mode.value,
        }
        if proxy is not None and ca is not None:
            runner = containers[0]
            env = {item.name: item.value for item in runner.env}
            env.update(
                runtime_proxy_environment(
                    proxy.service_hostname,
                    self._config.proxy_port,
                )
            )
            containers[0] = dataclasses.replace(
                runner,
                env=tuple(
                    EnvVar(name=name, value=value) for name, value in env.items()
                ),
                volume_mounts=(
                    *runner.volume_mounts,
                    VolumeMount(
                        name=RUNTIME_CA_VOLUME,
                        mount_path=RUNTIME_CA_MOUNT_PATH,
                        read_only=True,
                    ),
                    VolumeMount(
                        name=RUNTIME_TRUST_VOLUME,
                        mount_path=RUNTIME_TRUST_MOUNT_PATH,
                        read_only=False,
                    ),
                ),
            )
            volumes.append(runtime_ca_volume(proxy.ca_secret.metadata.name))
            volumes.append(runtime_trust_volume())
            annotations[ANNOTATION_CA_FINGERPRINT] = ca.fingerprint
        return dataclasses.replace(
            base,
            metadata=dataclasses.replace(
                base.metadata,
                labels={
                    **base.metadata.labels,
                    LABEL_RESOURCE_ROLE: ResourceRole.RUNTIME_POD.value,
                },
                annotations=annotations,
            ),
            spec=dataclasses.replace(
                base.spec,
                dns_policy=runtime_network.dns_policy,
                dns_config=runtime_network.dns_config,
                host_aliases=runtime_network.host_aliases,
                containers=tuple(containers),
                volumes=tuple(volumes),
            ),
        )

    async def _ensure_v3_runtime_pod(
        self,
        command: RuntimeLifecycleCommand,
        desired: PodResource,
        *,
        replace: bool,
    ) -> None:
        pod = await self._api.get_pod(desired.metadata.name, self._config.namespace)
        if pod is not None and (replace or not _pod_semantically_equal(pod, desired)):
            await self._delete_runtime_pod(command)
            pod = await self._api.get_pod(
                desired.metadata.name,
                self._config.namespace,
            )
            if pod is not None:
                return
        if pod is None:
            await self._api.apply_pod(desired)

    async def _delete_runtime_pod(self, command: RuntimeLifecycleCommand) -> None:
        name = _pod_name(command.identity.runtime_id)
        pod = await self._api.get_pod(name, self._config.namespace)
        if pod is None:
            return
        role = pod.metadata.labels.get(LABEL_RESOURCE_ROLE)
        if role not in {None, ResourceRole.RUNTIME_POD.value}:
            raise InvalidOwnedResourceMetadata("Runtime Pod role mismatch")
        _validate_owned_role(
            pod.metadata,
            _owned_identity(command, self._config),
            ResourceRole.RUNTIME_POD,
            allow_missing_role=True,
        )
        await self._api.delete_pod(
            name,
            self._config.namespace,
            grace_period_seconds=0 if _pod_blocks_recreate(pod) else None,
        )

    async def _v3_reconciliation(
        self,
        policy: KubernetesPodProfileV3,
        bundle: _V3Bundle,
    ) -> RuntimeProviderReconciliationEvidence:
        resources: list[tuple[str, object, object | None]] = [
            (
                ResourceRole.RUNTIME_NETWORK_POLICY.value,
                bundle.runtime_network.runtime_policy,
                await self._api.get_network_policy(
                    bundle.runtime_network.runtime_policy.metadata.name,
                    self._config.namespace,
                ),
            ),
            (
                ResourceRole.RUNTIME_POD.value,
                bundle.runtime_pod,
                await self._api.get_pod(
                    bundle.runtime_pod.metadata.name,
                    self._config.namespace,
                ),
            ),
        ]
        if bundle.proxy is not None:
            proxy = bundle.proxy
            resources.extend(
                (
                    (
                        ResourceRole.RUNTIME_CA.value,
                        secret_comparison_view(proxy.ca_secret),
                        _secret_comparison(
                            await self._api.get_secret(
                                proxy.ca_secret.metadata.name,
                                self._config.namespace,
                            )
                        ),
                    ),
                    (
                        ResourceRole.PROXY_POLICY.value,
                        config_map_comparison_view(proxy.policy_config_map),
                        _config_map_comparison(
                            await self._api.get_config_map(
                                proxy.policy_config_map.metadata.name,
                                self._config.namespace,
                            )
                        ),
                    ),
                    (
                        ResourceRole.PROXY_SERVICE.value,
                        service_comparison_view(proxy.service),
                        await self._api.get_service(
                            proxy.service.metadata.name,
                            self._config.namespace,
                        ),
                    ),
                    (
                        ResourceRole.PROXY_POD.value,
                        proxy.pod,
                        await self._api.get_pod(
                            proxy.pod.metadata.name,
                            self._config.namespace,
                        ),
                    ),
                    (
                        ResourceRole.PROXY_INGRESS_NETWORK_POLICY.value,
                        bundle.proxy_ingress_policy,
                        await self._api.get_network_policy(
                            resource_name(
                                bundle.identity.runtime_id,
                                ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
                            ),
                            self._config.namespace,
                        ),
                    ),
                    (
                        ResourceRole.PROXY_EGRESS_NETWORK_POLICY.value,
                        bundle.proxy_egress_policy,
                        await self._api.get_network_policy(
                            resource_name(
                                bundle.identity.runtime_id,
                                ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
                            ),
                            self._config.namespace,
                        ),
                    ),
                )
            )
        for role, expected, actual in resources:
            if actual is None:
                return _network_enforcement_evidence(
                    status=RuntimeProviderReconciliationStatus.DRIFTED,
                    reason=f"{role}_missing",
                    diagnostic={
                        "mode": policy.network_access.mode.value,
                        "resource_role": role,
                        "resource_count": str(len(resources)),
                    },
                )
            if (
                role == ResourceRole.RUNTIME_POD.value
                and isinstance(actual, PodResource)
                and isinstance(expected, PodResource)
            ):
                equal = _v3_pod_in_place_compatible(actual, expected)
            elif isinstance(actual, PodResource) and isinstance(expected, PodResource):
                equal = _pod_semantically_equal(actual, expected)
            else:
                equal = actual == expected
            if not equal:
                return _network_enforcement_evidence(
                    status=RuntimeProviderReconciliationStatus.DRIFTED,
                    reason=f"{role}_mismatch",
                    diagnostic={
                        "mode": policy.network_access.mode.value,
                        "resource_role": role,
                        "resource_count": str(len(resources)),
                    },
                )
        if bundle.proxy is not None and not await self._proxy_ready(bundle.proxy):
            return _network_enforcement_evidence(
                status=RuntimeProviderReconciliationStatus.DRIFTED,
                reason="proxy_not_ready",
                diagnostic={
                    "mode": policy.network_access.mode.value,
                    "resource_role": ResourceRole.PROXY_POD.value,
                    "resource_count": str(len(resources)),
                },
            )
        return _network_enforcement_evidence(
            status=RuntimeProviderReconciliationStatus.IN_SYNC,
            reason="network_enforcement_in_sync",
            diagnostic={
                "mode": policy.network_access.mode.value,
                "resource_count": str(len(resources)),
            },
        )

    async def _delete_execution_resources(
        self,
        command: RuntimeLifecycleCommand,
        *,
        delete_ca: bool,
    ) -> None:
        await self._delete_owned_network_policy(
            command,
            ResourceRole.RUNTIME_NETWORK_POLICY,
            allow_missing_role=True,
        )
        await self._delete_proxy_resources(command)
        if delete_ca:
            await self._delete_owned_secret(command, ResourceRole.RUNTIME_CA)

    async def _delete_proxy_resources(
        self,
        command: RuntimeLifecycleCommand,
    ) -> None:
        runtime_id = command.identity.runtime_id
        await self._delete_owned_pod(command, ResourceRole.PROXY_POD)
        await self._delete_owned_service(command, ResourceRole.PROXY_SERVICE)
        for role in (
            ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
            ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
        ):
            await self._delete_owned_network_policy(command, role)
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: runtime_id,
            LABEL_RESOURCE_ROLE: ResourceRole.PROXY_POLICY.value,
        }
        for config_map in await self._api.list_config_maps(
            labels,
            self._config.namespace,
        ):
            _validate_owned_role(
                config_map.metadata,
                _owned_identity(command, self._config),
                ResourceRole.PROXY_POLICY,
            )
            await self._api.delete_config_map(
                config_map.metadata.name,
                self._config.namespace,
            )

    async def _delete_obsolete_proxy_policy_config_maps(
        self,
        command: RuntimeLifecycleCommand,
        proxy: ProxyResources,
    ) -> None:
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: command.identity.runtime_id,
            LABEL_RESOURCE_ROLE: ResourceRole.PROXY_POLICY.value,
        }
        for config_map in await self._api.list_config_maps(
            labels,
            self._config.namespace,
        ):
            _validate_owned_role(
                config_map.metadata,
                _owned_identity(command, self._config),
                ResourceRole.PROXY_POLICY,
            )
            if config_map.metadata.name != proxy.policy_config_map.metadata.name:
                await self._api.delete_config_map(
                    config_map.metadata.name,
                    self._config.namespace,
                )

    async def _delete_owned_pod(
        self,
        command: RuntimeLifecycleCommand,
        role: ResourceRole,
    ) -> None:
        name = resource_name(command.identity.runtime_id, role)
        pod = await self._api.get_pod(name, self._config.namespace)
        if pod is None:
            return
        _validate_owned_role(
            pod.metadata,
            _owned_identity(command, self._config),
            role,
        )
        await self._api.delete_pod(name, self._config.namespace)

    async def _delete_owned_service(
        self,
        command: RuntimeLifecycleCommand,
        role: ResourceRole,
    ) -> None:
        name = resource_name(command.identity.runtime_id, role)
        service = await self._api.get_service(name, self._config.namespace)
        if service is None:
            return
        _validate_owned_role(
            service.metadata,
            _owned_identity(command, self._config),
            role,
        )
        await self._api.delete_service(name, self._config.namespace)

    async def _delete_owned_secret(
        self,
        command: RuntimeLifecycleCommand,
        role: ResourceRole,
    ) -> None:
        name = resource_name(command.identity.runtime_id, role)
        secret = await self._api.get_secret(name, self._config.namespace)
        if secret is None:
            return
        _validate_owned_role(
            secret.metadata,
            _owned_identity(command, self._config),
            role,
        )
        await self._api.delete_secret(name, self._config.namespace)

    async def _delete_workspace_pvc(
        self,
        command: RuntimeLifecycleCommand,
    ) -> None:
        name = _pvc_name(command.identity.runtime_id)
        pvc = await self._api.get_pvc(name, self._config.namespace)
        if pvc is None:
            return
        _validate_owned_role(
            pvc.metadata,
            _owned_identity(command, self._config),
            ResourceRole.WORKSPACE_PVC,
            allow_missing_role=True,
        )
        await self._api.delete_pvc(name, self._config.namespace)

    async def _retained_ca_fingerprint(
        self,
        command: RuntimeLifecycleCommand,
    ) -> str | None:
        pvc = await self._api.get_pvc(
            _pvc_name(command.identity.runtime_id),
            self._config.namespace,
        )
        if pvc is None:
            return None
        _validate_owned_role(
            pvc.metadata,
            _owned_identity(command, self._config),
            ResourceRole.WORKSPACE_PVC,
            allow_missing_role=True,
        )
        fingerprint = pvc.metadata.annotations.get(ANNOTATION_CA_FINGERPRINT)
        if (
            fingerprint is not None
            and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
        ):
            raise InvalidRuntimeCa("Runtime CA fingerprint on PVC is invalid")
        return fingerprint

    async def _validate_existing_execution_ownership(
        self,
        command: RuntimeLifecycleCommand,
    ) -> None:
        identity = _owned_identity(command, self._config)
        resources = (
            (
                await self._api.get_pod(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.RUNTIME_POD,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.RUNTIME_POD,
                True,
            ),
            (
                await self._api.get_pvc(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.WORKSPACE_PVC,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.WORKSPACE_PVC,
                True,
            ),
            (
                await self._api.get_network_policy(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.RUNTIME_NETWORK_POLICY,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.RUNTIME_NETWORK_POLICY,
                True,
            ),
            (
                await self._api.get_pod(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.PROXY_POD,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.PROXY_POD,
                False,
            ),
            (
                await self._api.get_service(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.PROXY_SERVICE,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.PROXY_SERVICE,
                False,
            ),
            (
                await self._api.get_secret(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.RUNTIME_CA,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.RUNTIME_CA,
                False,
            ),
            (
                await self._api.get_network_policy(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
                False,
            ),
            (
                await self._api.get_network_policy(
                    resource_name(
                        command.identity.runtime_id,
                        ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
                    ),
                    self._config.namespace,
                ),
                ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
                False,
            ),
        )
        for resource, role, allow_missing_role in resources:
            if resource is not None:
                _validate_owned_role(
                    resource.metadata,
                    identity,
                    role,
                    allow_missing_role=allow_missing_role,
                )
        labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: command.identity.runtime_id,
            LABEL_RESOURCE_ROLE: ResourceRole.PROXY_POLICY.value,
        }
        for config_map in await self._api.list_config_maps(
            labels,
            self._config.namespace,
        ):
            _validate_owned_role(
                config_map.metadata,
                identity,
                ResourceRole.PROXY_POLICY,
            )

    async def _terminal_resources_absent(
        self,
        command: RuntimeLifecycleCommand,
    ) -> bool:
        runtime_id = command.identity.runtime_id
        namespace = self._config.namespace
        resources = (
            await self._api.get_pod(
                resource_name(runtime_id, ResourceRole.RUNTIME_POD),
                namespace,
            ),
            await self._api.get_pvc(
                resource_name(runtime_id, ResourceRole.WORKSPACE_PVC),
                namespace,
            ),
            await self._api.get_network_policy(
                resource_name(runtime_id, ResourceRole.RUNTIME_NETWORK_POLICY),
                namespace,
            ),
            await self._api.get_pod(
                resource_name(runtime_id, ResourceRole.PROXY_POD),
                namespace,
            ),
            await self._api.get_service(
                resource_name(runtime_id, ResourceRole.PROXY_SERVICE),
                namespace,
            ),
            await self._api.get_secret(
                resource_name(runtime_id, ResourceRole.RUNTIME_CA),
                namespace,
            ),
            await self._api.get_network_policy(
                resource_name(
                    runtime_id,
                    ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
                ),
                namespace,
            ),
            await self._api.get_network_policy(
                resource_name(
                    runtime_id,
                    ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
                ),
                namespace,
            ),
        )
        if any(resource is not None for resource in resources):
            return False
        proxy_policy_labels = {
            _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: runtime_id,
            LABEL_RESOURCE_ROLE: ResourceRole.PROXY_POLICY.value,
        }
        return not await self._api.list_config_maps(
            proxy_policy_labels,
            namespace,
        )

    async def _apply_owned_network_policy(
        self,
        command: RuntimeLifecycleCommand,
        network_policy: NetworkPolicyResource,
        role: ResourceRole,
        *,
        allow_missing_role: bool = False,
    ) -> None:
        existing = await self._api.get_network_policy(
            network_policy.metadata.name,
            self._config.namespace,
        )
        if existing is not None:
            _validate_owned_role(
                existing.metadata,
                _owned_identity(command, self._config),
                role,
                allow_missing_role=allow_missing_role,
            )
        await self._api.apply_network_policy(network_policy)

    async def _delete_owned_network_policy(
        self,
        command: RuntimeLifecycleCommand,
        role: ResourceRole,
        *,
        allow_missing_role: bool = False,
    ) -> None:
        name = resource_name(command.identity.runtime_id, role)
        network_policy = await self._api.get_network_policy(
            name,
            self._config.namespace,
        )
        if network_policy is None:
            return
        _validate_owned_role(
            network_policy.metadata,
            _owned_identity(command, self._config),
            role,
            allow_missing_role=allow_missing_role,
        )
        await self._api.delete_network_policy(name, self._config.namespace)

    async def _ensure_pvc(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfile,
        *,
        ca_fingerprint: str | None,
    ) -> None:
        desired = self._pvc(
            command,
            policy,
            ca_fingerprint=ca_fingerprint,
        )
        existing = await self._api.get_pvc(
            desired.metadata.name,
            desired.metadata.namespace,
        )
        if existing is not None:
            _validate_owned_role(
                existing.metadata,
                _owned_identity(command, self._config),
                ResourceRole.WORKSPACE_PVC,
                allow_missing_role=True,
            )
            retained_fingerprint = existing.metadata.annotations.get(
                ANNOTATION_CA_FINGERPRINT
            )
            if ca_fingerprint is None:
                ca_fingerprint = retained_fingerprint
            elif (
                retained_fingerprint is not None
                and retained_fingerprint != ca_fingerprint
            ):
                raise InvalidRuntimeCa("Runtime CA fingerprint does not match PVC")
            desired = self._pvc(
                command,
                policy,
                ca_fingerprint=ca_fingerprint,
            )
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
        policy: KubernetesPodProfileV1 | KubernetesPodProfileV2,
    ) -> None:
        network_policy = self._network_policy(command, policy)
        _LOGGER.info(
            "Kubernetes Runtime ensuring NetworkPolicy",
            extra={
                **_log_context(command, self._config),
                "network_policy_name": network_policy.metadata.name,
            },
        )
        await self._apply_owned_network_policy(
            command,
            network_policy,
            ResourceRole.RUNTIME_NETWORK_POLICY,
            allow_missing_role=True,
        )

    async def _ensure_pod(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV1 | KubernetesPodProfileV2,
        *,
        replace: bool,
    ) -> None:
        pod_name = _pod_name(command.identity.runtime_id)
        pod = await self._api.get_pod(pod_name, self._config.namespace)
        if pod is not None:
            _validate_owned_role(
                pod.metadata,
                _owned_identity(command, self._config),
                ResourceRole.RUNTIME_POD,
                allow_missing_role=True,
            )
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
        policy: KubernetesPodProfileV1 | KubernetesPodProfileV2,
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
        # A Pending Pod with the exact lifecycle/configuration fence already is
        # this START request in progress. Kubernetes may default or admit fields
        # that make a full round-trip spec comparison unequal; deleting that Pod
        # on every retry prevents it from ever reaching Running. Pod specs are
        # immutable, and a new Provider/configuration generation changes the
        # checked labels/annotations above, so retaining the matching Pending Pod
        # is both idempotent and generation-fenced.
        if (
            pod.status is not None
            and pod.status.phase == "Pending"
            and _container_images_equal(pod.spec.containers, expected.spec.containers)
            and _pod_volumes_equal(pod.spec.volumes, expected.spec.volumes)
            and _pod_preparation_equal(pod.spec, expected.spec)
        ):
            return True
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
        expected_service_account = expected.spec.service_account_name
        if expected_service_account is None:
            if pod.spec.service_account_name not in {None, "default"}:
                return False
        elif pod.spec.service_account_name != expected_service_account:
            return False
        if (
            pod.spec.automount_service_account_token
            != expected.spec.automount_service_account_token
        ):
            return False
        if dict(pod.spec.node_selector) != dict(expected.spec.node_selector):
            return False
        if not set(expected.spec.tolerations).issubset(set(pod.spec.tolerations)):
            return False
        return True

    def _pod_in_place_compatible(
        self,
        pod: PodResource,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfileV1 | KubernetesPodProfileV2,
    ) -> bool:
        if _pod_blocks_recreate(pod):
            return False
        expected = self._pod(command, policy)
        ignored_labels = {
            _LABEL_DESIRED_GENERATION,
            _LABEL_PROVIDER_GENERATION,
        }
        for key, value in expected.metadata.labels.items():
            if key not in ignored_labels and pod.metadata.labels.get(key) != value:
                return False
        ignored_annotations = {
            _ANNOTATION_CONFIGURATION_SEQUENCE,
            _ANNOTATION_CONFIGURATION_DIGEST,
        }
        for key, value in expected.metadata.annotations.items():
            if (
                key not in ignored_annotations
                and pod.metadata.annotations.get(key) != value
            ):
                return False
        if not _container_specs_equal_for_in_place(
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
        expected_service_account = expected.spec.service_account_name
        if expected_service_account is None:
            if pod.spec.service_account_name not in {None, "default"}:
                return False
        elif pod.spec.service_account_name != expected_service_account:
            return False
        if (
            pod.spec.automount_service_account_token
            != expected.spec.automount_service_account_token
        ):
            return False
        if dict(pod.spec.node_selector) != dict(expected.spec.node_selector):
            return False
        return set(expected.spec.tolerations).issubset(set(pod.spec.tolerations))

    def _pvc_in_place_compatible(
        self,
        pvc: PersistentVolumeClaimResource,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfile,
    ) -> bool:
        expected = self._pvc(command, policy)
        return (
            pvc.spec.storage_class_name == expected.spec.storage_class_name
            and _quantity_value(pvc.spec.storage_request)
            == _quantity_value(expected.spec.storage_request)
        )

    def _pvc(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfile,
        *,
        ca_fingerprint: str | None = None,
    ) -> PersistentVolumeClaimResource:
        volume = policy.workspace_volume
        labels = self._labels(command)
        if isinstance(policy, KubernetesPodProfileV3):
            labels = {
                **labels,
                LABEL_RESOURCE_ROLE: ResourceRole.WORKSPACE_PVC.value,
            }
        return PersistentVolumeClaimResource(
            metadata=ObjectMeta(
                name=_pvc_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=labels,
                annotations={
                    **self._configuration_annotations(command),
                    **(
                        {ANNOTATION_CA_FINGERPRINT: ca_fingerprint}
                        if ca_fingerprint is not None
                        else {}
                    ),
                },
            ),
            spec=PersistentVolumeClaimSpec(
                storage_class_name=volume.storage_class_name,
                access_modes=("ReadWriteOnce",),
                storage_request=str(volume.storage_request_bytes),
            ),
        )

    def _pod(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfile,
    ) -> PodResource:
        dind = policy.dind
        return PodResource(
            metadata=ObjectMeta(
                name=_pod_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._pod_annotations(command),
            ),
            spec=PodSpec(
                service_account_name=policy.service_account_name,
                automount_service_account_token=False,
                image_pull_secrets=self._config.image_pull_secrets,
                security_context=self._pod_security_context(),
                node_selector=policy.scheduling.node_selector,
                tolerations=tuple(
                    Toleration(
                        key=item.key,
                        operator=item.operator,
                        value=item.value,
                        effect=item.effect,
                        toleration_seconds=item.toleration_seconds,
                    )
                    for item in policy.scheduling.tolerations
                ),
                dns_policy=None,
                dns_config=None,
                host_aliases=(),
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
                                size_limit=str(dind.shared_temporary_storage_bytes),
                            ),
                            EmptyDirVolume(
                                name=_ENGINE_STORAGE_VOLUME_NAME,
                                medium=None,
                                size_limit=str(dind.docker_storage_bytes),
                            ),
                        )
                        if dind is not None
                        else ()
                    ),
                ),
            ),
        )

    def _containers(
        self,
        command: RuntimeLifecycleCommand,
        policy: KubernetesPodProfile,
    ) -> tuple[ContainerSpec, ...]:
        runner_mounts = [
            VolumeMount(
                name=_WORKSPACE_VOLUME_NAME,
                mount_path=self._workspace_mount_path,
                read_only=False,
            )
        ]
        dind = policy.dind
        runner_env = self._env(command)
        if dind is not None:
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
            resources=_container_resources(policy.runner_resources),
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
        if dind is None:
            return (runner,)
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
            resources=_container_resources(dind.engine_resources),
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
        policy: KubernetesPodProfileV1 | KubernetesPodProfileV2,
    ) -> NetworkPolicyResource:
        return NetworkPolicyResource(
            metadata=ObjectMeta(
                name=_network_policy_name(command.identity.runtime_id),
                namespace=self._config.namespace,
                labels=self._labels(command),
                annotations=self._configuration_annotations(command),
            ),
            spec=NetworkPolicySpec(
                pod_selector=LabelSelector(
                    match_labels={
                        _LABEL_MANAGED_BY: "azents-runtime-provider-kubernetes",
                        _LABEL_RUNTIME_ID: command.identity.runtime_id,
                        _LABEL_CONFIGURATION_MANAGED: "true",
                    },
                    match_expressions=(),
                ),
                policy_types=("Ingress", "Egress"),
                ingress=(),
                egress=(
                    _dns_egress_rule(),
                    _runtime_control_egress_rule(self._config),
                    *_permitted_egress_rules(
                        self._config,
                        policy.network_policy,
                    ),
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
            _LABEL_CONFIGURATION_MANAGED: "true",
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

    def _pod_annotations(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._config.pod_annotations,
            **self._configuration_annotations(command),
        }

    def _env(
        self,
        command: RuntimeLifecycleCommand,
    ) -> dict[str, str]:
        return {
            **self._stable_env(command),
            **self._runner_env,
            **self._runner_auth_env(command),
            **self._configuration_env(command),
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
            _ENV_HOME: self._workspace_mount_path,
        }
        if command.auth.control_tls_ca_pem is not None:
            env[_ENV_CONTROL_TLS_CA_PEM] = command.auth.control_tls_ca_pem
        env[_ENV_CONTROL_ALLOW_INSECURE] = str(
            command.auth.allow_insecure_control
        ).lower()
        return env

    def _configuration_annotations(
        self,
        command: RuntimeLifecycleCommand,
    ) -> dict[str, str]:
        evidence = command.runtime_configuration.evidence
        return {
            _ANNOTATION_CONFIGURATION_SEQUENCE: serialize_configuration_sequence(
                evidence.configuration_sequence
            ),
            _ANNOTATION_CONFIGURATION_DIGEST: evidence.digest,
        }

    def _configuration_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        evidence = command.runtime_configuration.evidence
        return {
            _ENV_CONFIGURATION_SEQUENCE: serialize_configuration_sequence(
                evidence.configuration_sequence
            ),
            _ENV_CONFIGURATION_DIGEST: evidence.digest,
            _ENV_CONFIGURATION_DESIRED_GENERATION: str(evidence.desired_generation),
        }

    def _report(
        self,
        command: RuntimeLifecycleCommand,
        *,
        observed_state: RuntimeProviderObservedState,
        reason: str,
        provider_runtime_id: str | None,
        reconciliation: RuntimeProviderReconciliationEvidence | None,
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=command.identity.runtime_id,
            provider_id=self._config.provider_id,
            provider_generation=command.provider_generation,
            observed_state=observed_state,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id=provider_runtime_id,
            reason=reason,
            diagnostic={},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=command.runtime_configuration.evidence,
            reconciliation=reconciliation,
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
            reason=reason,
            diagnostic={"source": "pod", **_pod_diagnostic(pod)},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_configuration_evidence_from_metadata(
                pod.metadata.annotations,
                desired_generation=_int_label(
                    pod.metadata.labels,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
            reconciliation=None,
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
                reason="pod_deleted",
                diagnostic={"source": "pod_watch", "event_type": event.event_type},
                reported_at=datetime.now(UTC),
                terminal_delete_acknowledged=False,
                runtime_configuration=_configuration_evidence_from_metadata(
                    event.pod.metadata.annotations,
                    desired_generation=_int_label(
                        event.pod.metadata.labels,
                        _LABEL_DESIRED_GENERATION,
                    ),
                ),
                reconciliation=None,
            )
        report = self._report_from_pod(event.pod)
        return dataclasses.replace(
            report,
            diagnostic={
                "source": "pod_watch",
                "event_type": event.event_type,
                **_pod_diagnostic(event.pod),
            },
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
            reason="pvc_present_without_pod",
            diagnostic={"source": "pvc"},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_configuration_evidence_from_metadata(
                pvc.metadata.annotations,
                desired_generation=_int_label(
                    pvc.metadata.labels,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
            reconciliation=None,
        )

    def _validate_command(
        self,
        command: RuntimeLifecycleCommand,
    ) -> KubernetesPodProfile:
        configuration = parse_runtime_configuration_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="kubernetes",
        )
        if configuration.provider.logical_id != self._config.provider_id:
            raise UnsupportedRuntimeConfiguration(
                "Runtime configuration is bound to a different Kubernetes Provider."
            )
        policy = configuration.effective_profile
        if not isinstance(
            policy,
            KubernetesPodProfileV1 | KubernetesPodProfileV2 | KubernetesPodProfileV3,
        ):
            raise UnsupportedRuntimeConfiguration(
                "Kubernetes Runtime Provider requires a Kubernetes Pod Profile."
            )
        if (
            isinstance(policy, KubernetesPodProfileV3)
            and policy.network_access.mode is RuntimeNetworkMode.PROXY_REQUIRED
            and (
                self._config.proxy_image is None
                or self._config.proxy_addon_digest is None
            )
        ):
            raise UnsupportedRuntimeConfiguration(
                "Proxy-required Runtime configuration requires immutable Provider "
                "proxy artifacts."
            )
        if (
            isinstance(policy, KubernetesPodProfileV3)
            and policy.network_access.mode is RuntimeNetworkMode.PROXY_REQUIRED
        ):
            proxy_image = self._config.proxy_image
            proxy_addon_digest = self._config.proxy_addon_digest
            if proxy_image is None or proxy_addon_digest is None:
                raise AssertionError("proxy artifact presence was validated above")
            try:
                _immutable_image_reference(proxy_image, "proxy image")
            except ValueError as error:
                raise UnsupportedRuntimeConfiguration(
                    "Proxy-required Runtime configuration requires immutable "
                    "Provider proxy artifacts."
                ) from error
            if re.fullmatch(r"[0-9a-f]{64}", proxy_addon_digest) is None:
                raise UnsupportedRuntimeConfiguration(
                    "Proxy-required Runtime configuration requires immutable "
                    "Provider proxy artifacts."
                )
        if policy.dind is not None:
            _immutable_image_reference(command.runner_image, "Runner image")
        return policy

    def _validate_cleanup_command(self, command: RuntimeLifecycleCommand) -> None:
        provider = validate_runtime_configuration_cleanup_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="kubernetes",
        )
        if provider.logical_id != self._config.provider_id:
            raise UnsupportedRuntimeConfiguration(
                "Runtime configuration is bound to a different Kubernetes Provider."
            )


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
        proc_mount=None,
        seccomp_profile=None,
    )


def _owned_identity(
    command: RuntimeLifecycleCommand,
    config: KubernetesRuntimeProviderConfig,
) -> OwnedResourceIdentity:
    return OwnedResourceIdentity(
        provider_id=config.provider_id,
        runtime_id=command.identity.runtime_id,
        workspace_id=command.identity.workspace_id,
        agent_id=command.identity.agent_id,
    )


def _validate_owned_role(
    metadata: ObjectMeta,
    identity: OwnedResourceIdentity,
    role: ResourceRole,
    *,
    allow_missing_role: bool = False,
) -> None:
    actual_role = metadata.labels.get(LABEL_RESOURCE_ROLE)
    if (
        metadata.namespace == ""
        or metadata.labels.get(_LABEL_MANAGED_BY)
        != "azents-runtime-provider-kubernetes"
        or metadata.labels.get(_LABEL_PROVIDER_ID) != identity.provider_id
        or metadata.labels.get(_LABEL_RUNTIME_ID) != identity.runtime_id
        or metadata.labels.get(_LABEL_WORKSPACE_ID) != identity.workspace_id
        or metadata.labels.get(_LABEL_AGENT_ID) != identity.agent_id
        or (
            actual_role != role.value
            and not (allow_missing_role and actual_role is None)
        )
    ):
        raise InvalidOwnedResourceMetadata("owned resource metadata mismatch")


def _validate_recovered_runtime_resource(
    metadata: ObjectMeta,
    config: KubernetesRuntimeProviderConfig,
    role: ResourceRole,
    *,
    allow_missing_role: bool,
) -> None:
    runtime_id = metadata.labels.get(_LABEL_RUNTIME_ID)
    workspace_id = metadata.labels.get(_LABEL_WORKSPACE_ID)
    agent_id = metadata.labels.get(_LABEL_AGENT_ID)
    if not runtime_id or not workspace_id or not agent_id:
        raise InvalidOwnedResourceMetadata("recovered resource identity is incomplete")
    identity = OwnedResourceIdentity(
        provider_id=config.provider_id,
        runtime_id=runtime_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    _validate_owned_role(
        metadata,
        identity,
        role,
        allow_missing_role=allow_missing_role,
    )
    if (
        metadata.namespace != config.namespace
        or metadata.name != resource_name(runtime_id, role)
        or metadata.labels.get(_LABEL_CONFIGURATION_MANAGED) != "true"
    ):
        raise InvalidOwnedResourceMetadata("recovered resource metadata mismatch")


def _tolerations(policy: KubernetesPodProfileV3) -> tuple[Toleration, ...]:
    return tuple(
        Toleration(
            key=item.key,
            operator=item.operator,
            value=item.value,
            effect=item.effect,
            toleration_seconds=item.toleration_seconds,
        )
        for item in policy.scheduling.tolerations
    )


def _pod_network_mode(pod: PodResource | None) -> RuntimeNetworkMode | None:
    if pod is None:
        return None
    raw = pod.metadata.annotations.get(ANNOTATION_NETWORK_MODE)
    if raw is None:
        return None
    try:
        return RuntimeNetworkMode(raw)
    except ValueError:
        return None


def _network_mode_rank(mode: RuntimeNetworkMode) -> int:
    return {
        RuntimeNetworkMode.NO_NETWORK: 0,
        RuntimeNetworkMode.PROXY_REQUIRED: 1,
        RuntimeNetworkMode.DIRECT: 2,
    }[mode]


def _pod_semantically_equal(actual: PodResource, expected: PodResource) -> bool:
    if not _metadata_contains(actual.metadata, expected.metadata):
        return False
    if (
        actual.spec.automount_service_account_token
        != expected.spec.automount_service_account_token
        or actual.spec.image_pull_secrets != expected.spec.image_pull_secrets
        or actual.spec.security_context != expected.spec.security_context
        or dict(actual.spec.node_selector) != dict(expected.spec.node_selector)
        or not set(expected.spec.tolerations).issubset(set(actual.spec.tolerations))
        or not _dns_policies_equal(
            actual.spec.dns_policy,
            expected.spec.dns_policy,
        )
        or actual.spec.dns_config != expected.spec.dns_config
        or tuple(actual.spec.host_aliases) != tuple(expected.spec.host_aliases)
        or not _container_specs_equal(
            actual.spec.containers,
            expected.spec.containers,
        )
        or not _pod_volumes_equal(actual.spec.volumes, expected.spec.volumes)
    ):
        return False
    expected_service_account = expected.spec.service_account_name
    if expected_service_account is None:
        return actual.spec.service_account_name in {None, "default"}
    return actual.spec.service_account_name == expected_service_account


def _v3_pod_in_place_compatible(
    actual: PodResource,
    expected: PodResource,
) -> bool:
    if _pod_blocks_recreate(actual):
        return False
    return _metadata_contains(
        actual.metadata,
        expected.metadata,
        ignored_labels={
            _LABEL_DESIRED_GENERATION,
            _LABEL_PROVIDER_GENERATION,
        },
        ignored_annotations={
            _ANNOTATION_CONFIGURATION_SEQUENCE,
            _ANNOTATION_CONFIGURATION_DIGEST,
        },
    ) and _pod_specs_equal_for_in_place(actual.spec, expected.spec)


def _metadata_contains(
    actual: ObjectMeta,
    expected: ObjectMeta,
    *,
    ignored_labels: set[str] | None = None,
    ignored_annotations: set[str] | None = None,
) -> bool:
    ignored_labels = ignored_labels or set()
    ignored_annotations = ignored_annotations or set()
    return (
        actual.name == expected.name
        and actual.namespace == expected.namespace
        and all(
            key in ignored_labels or actual.labels.get(key) == value
            for key, value in expected.labels.items()
        )
        and all(
            key in ignored_annotations or actual.annotations.get(key) == value
            for key, value in expected.annotations.items()
        )
    )


def _pod_specs_equal_for_in_place(actual: PodSpec, expected: PodSpec) -> bool:
    actual_runner = tuple(actual.containers)
    expected_runner = tuple(expected.containers)
    if not _container_specs_equal_for_in_place(actual_runner, expected_runner):
        return False
    return (
        _pod_volumes_equal(actual.volumes, expected.volumes)
        and actual.image_pull_secrets == expected.image_pull_secrets
        and actual.security_context == expected.security_context
        and actual.automount_service_account_token
        == expected.automount_service_account_token
        and dict(actual.node_selector) == dict(expected.node_selector)
        and set(expected.tolerations).issubset(set(actual.tolerations))
        and _dns_policies_equal(actual.dns_policy, expected.dns_policy)
        and actual.dns_config == expected.dns_config
        and tuple(actual.host_aliases) == tuple(expected.host_aliases)
        and (
            actual.service_account_name == expected.service_account_name
            or (
                expected.service_account_name is None
                and actual.service_account_name == "default"
            )
        )
    )


def _dns_policies_equal(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return actual in {None, "ClusterFirst"}
    return actual == expected


def _network_enforcement_evidence(
    *,
    status: RuntimeProviderReconciliationStatus,
    reason: str,
    diagnostic: Mapping[str, str],
) -> RuntimeProviderReconciliationEvidence:
    return RuntimeProviderReconciliationEvidence(
        observations=(
            RuntimeProviderReconciliationObservation(
                kind=RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
                status=status,
                reason=reason,
                diagnostic=diagnostic,
            ),
        )
    )


def _safe_enforcement_error_reason(
    error: InvalidMandatoryService | InvalidRuntimeCa,
) -> str:
    if isinstance(error, InvalidMandatoryService):
        return "mandatory_service_invalid"
    return "runtime_ca_invalid"


def _secret_comparison(secret: SecretResource | None) -> object | None:
    return None if secret is None else secret_comparison_view(secret)


def _config_map_comparison(
    config_map: ConfigMapResource | None,
) -> object | None:
    return None if config_map is None else config_map_comparison_view(config_map)


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
        proc_mount=None,
        seccomp_profile=SeccompProfile(
            profile_type="RuntimeDefault",
            localhost_profile=None,
        ),
    )


def _engine_probe() -> Probe:
    return Probe(
        exec_action=ExecAction(
            command=(
                "docker",
                "--host",
                f"unix://{_ENGINE_SOCKET_PATH}",
                "info",
                "--format",
                "{{.ServerVersion}}",
            )
        ),
        initial_delay_seconds=1,
        period_seconds=2,
        timeout_seconds=1,
        failure_threshold=30,
    )


def _immutable_image_reference(value: str, name: str) -> str:
    if not _IMMUTABLE_IMAGE_RE.fullmatch(value):
        raise UnsupportedRuntimeConfiguration(
            f"{name} must use an immutable sha256 digest reference."
        )
    return value


def _container_resources(
    resources: ResolvedKubernetesContainerResources,
) -> ContainerResources | None:
    requests = _kubernetes_resource_requests(
        cpu_request_millicores=resources.cpu_request_millicores,
        cpu_limit_millicores=resources.cpu_limit_millicores,
        memory_request_bytes=resources.memory_request_bytes,
        memory_limit_bytes=resources.memory_limit_bytes,
    )
    limits = _kubernetes_resource_values(
        cpu_millicores=resources.cpu_limit_millicores,
        memory_bytes=resources.memory_limit_bytes,
    )
    if not requests and not limits:
        return None
    return ContainerResources(
        requests=requests or None,
        limits=limits or None,
        claims=None,
    )


def _kubernetes_resource_requests(
    *,
    cpu_request_millicores: int | None,
    cpu_limit_millicores: int | None,
    memory_request_bytes: int | None,
    memory_limit_bytes: int | None,
) -> dict[str, str]:
    requests = _kubernetes_resource_values(
        cpu_millicores=cpu_request_millicores,
        memory_bytes=memory_request_bytes,
    )
    if cpu_request_millicores is None and cpu_limit_millicores is not None:
        requests["cpu"] = "0"
    if memory_request_bytes is None and memory_limit_bytes is not None:
        requests["memory"] = "0"
    return requests


def _kubernetes_resource_values(
    *,
    cpu_millicores: int | None,
    memory_bytes: int | None,
) -> dict[str, str]:
    values: dict[str, str] = {}
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
                    match_labels={"kubernetes.io/metadata.name": "kube-system"},
                    match_expressions=(),
                ),
                pod_selector=LabelSelector(
                    match_labels={"k8s-app": "kube-dns"},
                    match_expressions=(),
                ),
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
                    },
                    match_expressions=(),
                ),
                pod_selector=LabelSelector(
                    match_labels=config.runtime_control_labels,
                    match_expressions=(),
                ),
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
    policy: RuntimeNetworkPolicy,
) -> tuple[NetworkPolicyEgressRule, ...]:
    denied = tuple(_ip_network(value) for value in policy.denied_cidrs) + tuple(
        _ip_network(value) for value in config.network_hard_cap_denied_cidrs
    )
    hard_cap_allowed = tuple(
        _ip_network(value) for value in config.network_hard_cap_allowed_cidrs
    )
    requested = tuple(_ip_network(value) for value in policy.allowed_cidrs)
    if not requested:
        requested = (
            ipaddress.ip_network("0.0.0.0/0"),
            ipaddress.ip_network("::/0"),
        )
    allowed = (
        tuple(
            intersection
            for requested_network in requested
            for hard_cap_network in hard_cap_allowed
            if (
                intersection := _network_intersection(
                    requested_network,
                    hard_cap_network,
                )
            )
            is not None
        )
        if hard_cap_allowed
        else requested
    )
    rules: list[NetworkPolicyEgressRule] = []
    for network in allowed:
        rule = _bounded_ip_block_rule(network, denied=denied)
        if rule is not None:
            rules.append(rule)
    return (*rules, *config.network_hard_cap_extra_egress)


def _validate_extra_egress_ip_blocks(
    rules: tuple[NetworkPolicyEgressRule, ...],
) -> None:
    """Validate Platform-owned extra egress IPBlock syntax."""
    for rule in rules:
        for peer in rule.peers:
            if peer.ip_block is None:
                continue
            network = _ip_network(peer.ip_block.cidr)
            exceptions = tuple(
                _ip_network(value) for value in peer.ip_block.except_cidrs
            )
            if any(
                exception == network or not _subnet_of_same_family(exception, network)
                for exception in exceptions
            ):
                raise UnsupportedRuntimeConfiguration(
                    "Provider extra egress IPBlock exceptions must be strict "
                    "subnets of their CIDR."
                )


def _network_intersection(
    left: ipaddress.IPv4Network | ipaddress.IPv6Network,
    right: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    if _subnet_of_same_family(left, right):
        return left
    if _subnet_of_same_family(right, left):
        return right
    return None


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
        raise UnsupportedRuntimeConfiguration(
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


def _network_policy_reconciliation(
    actual: NetworkPolicyResource | None,
    expected: NetworkPolicyResource,
) -> RuntimeProviderReconciliationEvidence:
    if actual is None:
        status = RuntimeProviderReconciliationStatus.DRIFTED
        reason = "network_enforcement_missing"
    elif _network_policy_comparison_view(actual) != _network_policy_comparison_view(
        expected
    ):
        status = RuntimeProviderReconciliationStatus.DRIFTED
        reason = "network_enforcement_mismatch"
    else:
        status = RuntimeProviderReconciliationStatus.IN_SYNC
        reason = "network_enforcement_in_sync"
    return RuntimeProviderReconciliationEvidence(
        observations=(
            RuntimeProviderReconciliationObservation(
                kind=RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
                status=status,
                reason=reason,
                diagnostic={"mode": RuntimeNetworkMode.DIRECT.value},
            ),
        )
    )


def _network_policy_comparison_view(
    policy: NetworkPolicyResource,
) -> NetworkPolicyResource:
    """Exclude historical transport metadata from policy semantics."""
    labels = {
        key: value
        for key, value in policy.metadata.labels.items()
        if key != _LABEL_PROVIDER_GENERATION
    }
    return dataclasses.replace(
        policy,
        metadata=dataclasses.replace(policy.metadata, labels=labels),
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


def _container_images_equal(
    actual: Sequence[ContainerSpec],
    expected: Sequence[ContainerSpec],
) -> bool:
    return {container.name: container.image for container in actual} == {
        container.name: container.image for container in expected
    }


def _pod_preparation_equal(actual: PodSpec, expected: PodSpec) -> bool:
    if (
        actual.automount_service_account_token
        != expected.automount_service_account_token
    ):
        return False
    if actual.security_context != expected.security_context:
        return False
    actual_containers = {
        container.name: (
            container.security_context,
            tuple(container.volume_mounts),
        )
        for container in actual.containers
    }
    expected_containers = {
        container.name: (
            container.security_context,
            tuple(container.volume_mounts),
        )
        for container in expected.containers
    }
    return actual_containers == expected_containers


def _container_specs_equal_for_in_place(
    actual: Sequence[ContainerSpec],
    expected: Sequence[ContainerSpec],
) -> bool:
    if len(actual) != len(expected):
        return False
    dynamic_env_names = {
        _ENV_DESIRED_GENERATION,
        _ENV_PROVIDER_GENERATION,
        _ENV_RUNNER_AUTH_TOKEN,
        _ENV_RUNNER_AUTH_CREDENTIAL_ID,
        _ENV_CONFIGURATION_SEQUENCE,
        _ENV_CONFIGURATION_DIGEST,
        _ENV_CONFIGURATION_DESIRED_GENERATION,
    }
    return all(
        dataclasses.replace(
            actual_container,
            resources=None,
            env=tuple(
                item
                for item in actual_container.env
                if item.name not in dynamic_env_names
            ),
        )
        == dataclasses.replace(
            expected_container,
            resources=None,
            env=tuple(
                item
                for item in expected_container.env
                if item.name not in dynamic_env_names
            ),
        )
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
        if not isinstance(actual_volume, EmptyDirVolume) or not isinstance(
            expected_volume,
            EmptyDirVolume,
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
    return resource_name(runtime_id, ResourceRole.RUNTIME_POD)


def _pvc_name(runtime_id: str) -> str:
    return resource_name(runtime_id, ResourceRole.WORKSPACE_PVC)


def _network_policy_name(runtime_id: str) -> str:
    return resource_name(runtime_id, ResourceRole.RUNTIME_NETWORK_POLICY)


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


def _pod_diagnostic(pod: PodResource) -> dict[str, str]:
    if pod.status is None:
        return {}
    diagnostic: dict[str, str] = {}
    if pod.status.phase is not None:
        diagnostic["pod_phase"] = pod.status.phase
    evidence = pod.status.termination_evidence
    if evidence is None:
        return diagnostic
    diagnostic.update(
        {
            "container_name": evidence.container_name,
            "exit_code": str(evidence.exit_code),
            "oom_killed": str(evidence.oom_killed).lower(),
        }
    )
    if evidence.reason is not None:
        diagnostic["termination_reason"] = evidence.reason
    return diagnostic


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


def _configuration_evidence_from_metadata(
    values: Mapping[str, str],
    *,
    desired_generation: int,
) -> RuntimeConfigurationEvidence:
    configuration_sequence = values.get(_ANNOTATION_CONFIGURATION_SEQUENCE)
    digest = values.get(_ANNOTATION_CONFIGURATION_DIGEST)
    if configuration_sequence is None or digest is None:
        raise ValueError("Runtime configuration metadata is incomplete.")
    return RuntimeConfigurationEvidence(
        configuration_sequence=parse_configuration_sequence(configuration_sequence),
        digest=digest,
        desired_generation=desired_generation,
    )
