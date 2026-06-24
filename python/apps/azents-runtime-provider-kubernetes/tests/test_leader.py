"""Kubernetes leader election tests."""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from azents_runtime_provider_kubernetes.kubernetes_api import (
    KubernetesApi,
    LeaseResource,
    LeaseSpec,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PodResource,
    PodWatchEvent,
)
from azents_runtime_provider_kubernetes.leader import (
    KubernetesLeaderElector,
    LeaderElectionConfig,
)


class FakeKubernetesApi(KubernetesApi):
    """Lease-focused fake Kubernetes API."""

    def __init__(self) -> None:
        self.lease: LeaseResource | None = None

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

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        """Return the fake Lease."""
        return self.lease

    async def apply_lease(self, lease: LeaseResource) -> None:
        """Apply the fake Lease."""
        self.lease = lease


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
