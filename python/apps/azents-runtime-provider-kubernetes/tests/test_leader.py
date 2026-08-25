"""Kubernetes leader election tests."""

import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
    KubernetesApi,
    LeaseConflictError,
    LeaseResource,
    LeaseSpec,
    NetworkPolicyResource,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PodResource,
    PodWatchEvent,
    SecretResource,
    ServiceResource,
)
from azents_runtime_provider_kubernetes.leader import (
    KubernetesLeaderElector,
    LeaderElectionConfig,
)


class FakeKubernetesApi(KubernetesApi):
    """Lease-focused fake Kubernetes API."""

    def __init__(self) -> None:
        self.lease: LeaseResource | None = None
        self.conflicting_lease: LeaseResource | None = None

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        """Unused by leader tests."""
        return None

    async def apply_pod(self, pod: PodResource) -> None:
        """Unused by leader tests."""

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period_seconds: int | None = None,
    ) -> None:
        """Unused by leader tests."""

    async def list_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PodResource]:
        """Unused by leader tests."""
        return ()

    async def watch_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> AsyncIterator[PodWatchEvent]:
        """Unused by leader tests."""
        if False:
            yield
        del labels, namespace

    async def get_pvc(
        self,
        name: str,
        namespace: str,
    ) -> PersistentVolumeClaimResource | None:
        """Unused by leader tests."""
        return None

    async def apply_pvc(self, pvc: PersistentVolumeClaimResource) -> None:
        """Unused by leader tests."""

    async def delete_pvc(self, name: str, namespace: str) -> None:
        """Unused by leader tests."""

    async def list_pvcs(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PersistentVolumeClaimResource]:
        """Unused by leader tests."""
        return ()

    async def get_service(
        self,
        name: str,
        namespace: str,
    ) -> ServiceResource | None:
        """Unused by leader tests."""
        return None

    async def apply_service(self, service: ServiceResource) -> None:
        """Unused by leader tests."""

    async def delete_service(self, name: str, namespace: str) -> None:
        """Unused by leader tests."""

    async def list_services(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ServiceResource]:
        """Unused by leader tests."""
        return ()

    async def get_config_map(
        self,
        name: str,
        namespace: str,
    ) -> ConfigMapResource | None:
        """Unused by leader tests."""
        return None

    async def apply_config_map(self, config_map: ConfigMapResource) -> None:
        """Unused by leader tests."""

    async def delete_config_map(self, name: str, namespace: str) -> None:
        """Unused by leader tests."""

    async def list_config_maps(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ConfigMapResource]:
        """Unused by leader tests."""
        return ()

    async def get_secret(
        self,
        name: str,
        namespace: str,
    ) -> SecretResource | None:
        """Unused by leader tests."""
        return None

    async def apply_secret(self, secret: SecretResource) -> None:
        """Unused by leader tests."""

    async def delete_secret(self, name: str, namespace: str) -> None:
        """Unused by leader tests."""

    async def list_secrets(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[SecretResource]:
        """Unused by leader tests."""
        return ()

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        """Unused by leader tests."""
        return None

    async def apply_network_policy(
        self,
        network_policy: NetworkPolicyResource,
    ) -> None:
        """Unused by leader tests."""

    async def delete_network_policy(self, name: str, namespace: str) -> None:
        """Unused by leader tests."""

    async def list_network_policies(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[NetworkPolicyResource]:
        """Unused by leader tests."""
        return ()

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Return the fake Lease."""
        return self.lease

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Apply the fake Lease."""
        if self.conflicting_lease is not None:
            self.lease = self.conflicting_lease
            self.conflicting_lease = None
            raise LeaseConflictError()
        if self.lease is None:
            assert lease.resource_version is None
            self.lease = dataclasses.replace(lease, resource_version="1")
            return
        if lease.resource_version != self.lease.resource_version:
            raise LeaseConflictError()
        self.lease = dataclasses.replace(lease, resource_version="2")


def _elector(
    api: FakeKubernetesApi, holder: str = "replica-a"
) -> KubernetesLeaderElector:
    return KubernetesLeaderElector(
        api,
        LeaderElectionConfig(
            namespace="azents-runtime",
            lease_name="provider",
            holder_identity=holder,
            lease_duration_seconds=30,
        ),
    )


def _lease(
    *,
    holder: str,
    renew_time: datetime,
    transitions: int = 0,
    resource_version: str = "1",
) -> LeaseResource:
    return LeaseResource(
        metadata=ObjectMeta(
            name="provider",
            namespace="azents-runtime",
            labels={},
            annotations={},
        ),
        spec=LeaseSpec(
            holder_identity=holder,
            acquire_time=renew_time,
            renew_time=renew_time,
            lease_duration_seconds=30,
            lease_transitions=transitions,
        ),
        resource_version=resource_version,
    )


@pytest.mark.asyncio
async def test_acquires_empty_lease() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)

    result = await _elector(api).try_acquire(now=now)

    assert result.acquired
    assert api.lease is not None
    assert api.lease.spec.holder_identity == "replica-a"
    assert api.lease.spec.renew_time == now


@pytest.mark.asyncio
async def test_does_not_acquire_active_foreign_lease() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)
    api.lease = _lease(holder="replica-b", renew_time=now - timedelta(seconds=5))

    result = await _elector(api).try_acquire(now=now)

    assert not result.acquired
    assert api.lease.spec.holder_identity == "replica-b"


@pytest.mark.asyncio
async def test_acquires_expired_foreign_lease_and_counts_transition() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)
    api.lease = _lease(
        holder="replica-b",
        renew_time=now - timedelta(seconds=31),
        transitions=2,
    )

    result = await _elector(api).try_acquire(now=now)

    assert result.acquired
    assert api.lease is not None
    assert api.lease.spec.holder_identity == "replica-a"
    assert api.lease.spec.lease_transitions == 3


@pytest.mark.asyncio
async def test_renews_owned_lease_without_transition() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)
    api.lease = _lease(holder="replica-a", renew_time=now - timedelta(seconds=10))

    result = await _elector(api).try_acquire(now=now)

    assert result.acquired
    assert api.lease is not None
    assert api.lease.spec.holder_identity == "replica-a"
    assert api.lease.spec.lease_transitions == 0
    assert api.lease.spec.renew_time == now


@pytest.mark.asyncio
async def test_empty_lease_create_conflict_does_not_acquire_leadership() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)
    api.conflicting_lease = _lease(holder="replica-b", renew_time=now)

    result = await _elector(api).try_acquire(now=now)

    assert not result.acquired
    assert result.lease.spec.holder_identity == "replica-b"
    assert api.lease is not None
    assert api.lease.spec.holder_identity == "replica-b"


@pytest.mark.asyncio
async def test_expired_lease_update_conflict_does_not_take_over_newer_lease() -> None:
    api = FakeKubernetesApi()
    now = datetime(2026, 5, 25, tzinfo=UTC)
    api.lease = _lease(
        holder="replica-b",
        renew_time=now - timedelta(seconds=31),
        transitions=2,
    )
    api.conflicting_lease = _lease(
        holder="replica-c",
        renew_time=now,
        transitions=3,
        resource_version="2",
    )

    result = await _elector(api).try_acquire(now=now)

    assert not result.acquired
    assert result.lease.spec.holder_identity == "replica-c"
    assert api.lease is not None
    assert api.lease.spec.holder_identity == "replica-c"
    assert api.lease.spec.lease_transitions == 3
