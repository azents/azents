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
class PodSecurityContext:
    """Pod-level security context for Runtime workspace ownership."""

    run_as_user: int
    run_as_group: int
    fs_group: int
    fs_group_change_policy: str


@dataclasses.dataclass(frozen=True)
class Toleration:
    """Kubernetes Pod toleration subset."""

    key: str | None = None
    operator: str | None = None
    value: str | None = None
    effect: str | None = None


@dataclasses.dataclass(frozen=True)
class ContainerSpec:
    """Runtime Runner container spec."""

    name: str
    image: str
    working_dir: str
    resources: ContainerResources | None
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
    containers: Sequence[ContainerSpec]
    volumes: Sequence[PersistentVolumeClaimVolume]


@dataclasses.dataclass(frozen=True)
class PodStatus:
    """Observed Pod status subset."""

    phase: str | None
    ready: bool
    ready_reason: str | None = None
    waiting_reason: str | None = None


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

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Return a Lease by name."""
        ...

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Create or update a Lease."""
        ...
