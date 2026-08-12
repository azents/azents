"""Kubernetes API boundary and resource models."""

import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Protocol

type KubernetesResourceQuantity = str | int | float


@dataclasses.dataclass(frozen=True)
class ContainerResourceClaim:
    """Container resource claim requirement."""

    name: str
    request: str | None


@dataclasses.dataclass(frozen=True)
class ObjectMeta:
    """Kubernetes object metadata subset."""

    name: str
    namespace: str
    labels: Mapping[str, str]
    annotations: Mapping[str, str]
    deletion_timestamp: datetime | None = None


@dataclasses.dataclass(frozen=True)
class EnvVar:
    """Container environment variable."""

    name: str
    value: str


@dataclasses.dataclass(frozen=True)
class VolumeMount:
    """Container volume mount."""

    name: str
    mount_path: str
    read_only: bool


@dataclasses.dataclass(frozen=True)
class LocalObjectReference:
    """Kubernetes local object reference."""

    name: str


@dataclasses.dataclass(frozen=True)
class ContainerResources:
    """Container resource requirements."""

    requests: Mapping[str, KubernetesResourceQuantity] | None
    limits: Mapping[str, KubernetesResourceQuantity] | None
    claims: Sequence[ContainerResourceClaim] | None


@dataclasses.dataclass(frozen=True)
class PersistentVolumeClaimVolume:
    """Pod volume backed by a PVC."""

    name: str
    claim_name: str


@dataclasses.dataclass(frozen=True)
class EmptyDirVolume:
    """Pod-local ephemeral volume."""

    name: str
    medium: str | None
    size_limit: KubernetesResourceQuantity | None


@dataclasses.dataclass(frozen=True)
class KeyToPath:
    """One selected ConfigMap or Secret key exposed in a Pod volume."""

    key: str
    path: str
    mode: int | None


@dataclasses.dataclass(frozen=True)
class ConfigMapVolume:
    """Pod volume backed by selected ConfigMap keys."""

    name: str
    config_map_name: str
    items: Sequence[KeyToPath]
    default_mode: int | None


@dataclasses.dataclass(frozen=True)
class SecretVolume:
    """Pod volume backed by selected Secret keys."""

    name: str
    secret_name: str
    items: Sequence[KeyToPath]
    default_mode: int | None


type PodVolume = (
    PersistentVolumeClaimVolume | EmptyDirVolume | ConfigMapVolume | SecretVolume
)


@dataclasses.dataclass(frozen=True)
class PodSecurityContext:
    """Pod-level security context for Runtime workspace ownership."""

    run_as_user: int | None
    run_as_group: int | None
    fs_group: int
    fs_group_change_policy: str


@dataclasses.dataclass(frozen=True)
class ContainerSecurityContext:
    """Provider-owned per-container security context."""

    privileged: bool
    allow_privilege_escalation: bool
    read_only_root_filesystem: bool
    run_as_non_root: bool
    run_as_user: int
    run_as_group: int
    capabilities_add: Sequence[str]
    capabilities_drop: Sequence[str]
    proc_mount: str | None
    seccomp_profile: "SeccompProfile | None"


@dataclasses.dataclass(frozen=True)
class SeccompProfile:
    """Kubernetes seccomp profile selection."""

    profile_type: str
    localhost_profile: str | None


@dataclasses.dataclass(frozen=True)
class ExecAction:
    """Exec action used by a container probe."""

    command: Sequence[str]


@dataclasses.dataclass(frozen=True)
class Probe:
    """Container readiness probe subset."""

    exec_action: ExecAction
    initial_delay_seconds: int
    period_seconds: int
    timeout_seconds: int
    failure_threshold: int


@dataclasses.dataclass(frozen=True)
class Toleration:
    """Kubernetes Pod toleration subset."""

    key: str | None = None
    operator: str | None = None
    value: str | None = None
    effect: str | None = None
    toleration_seconds: int | None = None


@dataclasses.dataclass(frozen=True)
class HostAlias:
    """Exact static hostname mappings injected into one Pod."""

    ip: str
    hostnames: Sequence[str]


@dataclasses.dataclass(frozen=True)
class PodDnsConfigOption:
    """One Pod resolver option."""

    name: str
    value: str | None


@dataclasses.dataclass(frozen=True)
class PodDnsConfig:
    """Explicit Pod resolver configuration."""

    nameservers: Sequence[str]
    searches: Sequence[str]
    options: Sequence[PodDnsConfigOption]


@dataclasses.dataclass(frozen=True)
class ContainerSpec:
    """Provider-owned Runtime container spec."""

    name: str
    image: str
    command: Sequence[str] | None
    args: Sequence[str]
    working_dir: str
    resources: ContainerResources | None
    security_context: ContainerSecurityContext
    readiness_probe: Probe | None
    env: Sequence[EnvVar]
    volume_mounts: Sequence[VolumeMount]


@dataclasses.dataclass(frozen=True)
class PodSpec:
    """Runtime Pod spec."""

    service_account_name: str | None
    automount_service_account_token: bool
    image_pull_secrets: Sequence[LocalObjectReference]
    security_context: PodSecurityContext | None
    node_selector: Mapping[str, str]
    tolerations: Sequence[Toleration]
    dns_policy: str | None
    dns_config: PodDnsConfig | None
    host_aliases: Sequence[HostAlias]
    containers: Sequence[ContainerSpec]
    volumes: Sequence[PodVolume]


@dataclasses.dataclass(frozen=True)
class PodStatus:
    """Observed Pod status subset."""

    phase: str | None
    ready: bool
    ready_reason: str | None = None
    waiting_reason: str | None = None
    termination_evidence: "ContainerTerminationEvidence | None" = None


@dataclasses.dataclass(frozen=True)
class ContainerTerminationEvidence:
    """Bounded container termination evidence safe for Provider diagnostics."""

    container_name: str
    exit_code: int
    reason: str | None
    oom_killed: bool


@dataclasses.dataclass(frozen=True)
class PodResource:
    """Runtime Pod resource."""

    metadata: ObjectMeta
    spec: PodSpec
    status: PodStatus | None = None


@dataclasses.dataclass(frozen=True)
class PodWatchEvent:
    """Kubernetes Pod watch event."""

    event_type: str
    pod: PodResource


@dataclasses.dataclass(frozen=True)
class PersistentVolumeClaimSpec:
    """Runtime PVC spec."""

    storage_class_name: str
    access_modes: Sequence[str]
    storage_request: str


@dataclasses.dataclass(frozen=True)
class PersistentVolumeClaimResource:
    """Runtime PVC resource."""

    metadata: ObjectMeta
    spec: PersistentVolumeClaimSpec


@dataclasses.dataclass(frozen=True)
class ServicePort:
    """Kubernetes Service port mapping."""

    name: str | None
    protocol: str
    port: int
    target_port: int | str


@dataclasses.dataclass(frozen=True)
class ServiceSpec:
    """Stable ClusterIP Service spec."""

    service_type: str
    cluster_ip: str | None
    selector: Mapping[str, str]
    ports: Sequence[ServicePort]


@dataclasses.dataclass(frozen=True)
class ServiceResource:
    """Provider-owned Kubernetes Service."""

    metadata: ObjectMeta
    spec: ServiceSpec


@dataclasses.dataclass(frozen=True)
class NamespaceResource:
    """Observed Kubernetes Namespace identity."""

    name: str
    labels: Mapping[str, str]


@dataclasses.dataclass(frozen=True)
class ConfigMapResource:
    """Provider-owned Kubernetes ConfigMap."""

    metadata: ObjectMeta
    data: Mapping[str, str]
    immutable: bool | None


@dataclasses.dataclass(frozen=True)
class SecretResource:
    """Provider-owned Kubernetes Secret with opaque byte values."""

    metadata: ObjectMeta
    data: Mapping[str, bytes]
    secret_type: str
    immutable: bool | None


@dataclasses.dataclass(frozen=True)
class LabelSelectorRequirement:
    """One Kubernetes label selector expression."""

    key: str
    operator: str
    values: Sequence[str]


@dataclasses.dataclass(frozen=True)
class LabelSelector:
    """Kubernetes label selector."""

    match_labels: Mapping[str, str]
    match_expressions: Sequence[LabelSelectorRequirement]


@dataclasses.dataclass(frozen=True)
class IpBlock:
    """NetworkPolicy IP block peer."""

    cidr: str
    except_cidrs: Sequence[str]


@dataclasses.dataclass(frozen=True)
class NetworkPolicyPeer:
    """NetworkPolicy peer subset."""

    namespace_selector: LabelSelector | None
    pod_selector: LabelSelector | None
    ip_block: IpBlock | None


@dataclasses.dataclass(frozen=True)
class NetworkPolicyPort:
    """NetworkPolicy transport port."""

    protocol: str
    port: int | str


@dataclasses.dataclass(frozen=True)
class NetworkPolicyEgressRule:
    """One additive NetworkPolicy egress rule."""

    peers: Sequence[NetworkPolicyPeer]
    ports: Sequence[NetworkPolicyPort]


@dataclasses.dataclass(frozen=True)
class NetworkPolicyIngressRule:
    """One additive NetworkPolicy ingress rule."""

    peers: Sequence[NetworkPolicyPeer]
    ports: Sequence[NetworkPolicyPort]


@dataclasses.dataclass(frozen=True)
class NetworkPolicySpec:
    """Runtime-specific NetworkPolicy spec."""

    pod_selector: LabelSelector
    policy_types: Sequence[str]
    ingress: Sequence[NetworkPolicyIngressRule]
    egress: Sequence[NetworkPolicyEgressRule]


@dataclasses.dataclass(frozen=True)
class NetworkPolicyResource:
    """Runtime-specific NetworkPolicy resource."""

    metadata: ObjectMeta
    spec: NetworkPolicySpec


@dataclasses.dataclass(frozen=True)
class LeaseSpec:
    """Kubernetes Lease spec subset."""

    holder_identity: str | None
    acquire_time: datetime | None
    renew_time: datetime | None
    lease_duration_seconds: int
    lease_transitions: int


@dataclasses.dataclass(frozen=True)
class LeaseResource:
    """Kubernetes Lease resource."""

    metadata: ObjectMeta
    spec: LeaseSpec
    resource_version: str | None = None


class KubernetesApi(Protocol):
    """Kubernetes operations required by Provider lifecycle and election."""

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        """Return a Pod by name."""
        ...

    async def apply_pod(self, pod: PodResource) -> None:
        """Create or update a Pod."""
        ...

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period_seconds: int | None = None,
    ) -> None:
        """Delete a Pod when present."""
        ...

    async def list_pods(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[PodResource]:
        """List Pods matching labels."""
        ...

    def watch_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> AsyncIterator[PodWatchEvent]:
        """Watch Pods matching labels."""
        ...

    async def get_pvc(
        self,
        name: str,
        namespace: str,
    ) -> PersistentVolumeClaimResource | None:
        """Return a PVC by name."""
        ...

    async def apply_pvc(self, pvc: PersistentVolumeClaimResource) -> None:
        """Create or update a PVC."""
        ...

    async def delete_pvc(self, name: str, namespace: str) -> None:
        """Delete a PVC when present."""
        ...

    async def list_pvcs(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PersistentVolumeClaimResource]:
        """List PVCs matching labels."""
        ...

    async def get_service(
        self,
        name: str,
        namespace: str,
    ) -> ServiceResource | None:
        """Return a Service by name."""
        ...

    async def apply_service(self, service: ServiceResource) -> None:
        """Create or replace a Service."""
        ...

    async def delete_service(self, name: str, namespace: str) -> None:
        """Delete a Service when present."""
        ...

    async def list_services(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ServiceResource]:
        """List Services matching labels."""
        ...

    async def get_config_map(
        self,
        name: str,
        namespace: str,
    ) -> ConfigMapResource | None:
        """Return a ConfigMap by name."""
        ...

    async def apply_config_map(self, config_map: ConfigMapResource) -> None:
        """Create or replace a ConfigMap."""
        ...

    async def delete_config_map(self, name: str, namespace: str) -> None:
        """Delete a ConfigMap when present."""
        ...

    async def list_config_maps(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ConfigMapResource]:
        """List ConfigMaps matching labels."""
        ...

    async def get_secret(
        self,
        name: str,
        namespace: str,
    ) -> SecretResource | None:
        """Return a Secret by name."""
        ...

    async def apply_secret(self, secret: SecretResource) -> None:
        """Create or replace a Secret."""
        ...

    async def delete_secret(self, name: str, namespace: str) -> None:
        """Delete a Secret when present."""
        ...

    async def list_secrets(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[SecretResource]:
        """List Secrets matching labels."""
        ...

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        """Return a NetworkPolicy by name."""
        ...

    async def apply_network_policy(
        self,
        network_policy: NetworkPolicyResource,
    ) -> None:
        """Create or update a NetworkPolicy."""
        ...

    async def delete_network_policy(self, name: str, namespace: str) -> None:
        """Delete a NetworkPolicy when present."""
        ...

    async def list_network_policies(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[NetworkPolicyResource]:
        """List NetworkPolicies matching labels."""
        ...

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Return a Lease by name."""
        ...

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Create or update a Lease."""
        ...
