"""Kubernetes Lease based Provider leader election."""

import dataclasses
from datetime import datetime, timedelta

from azents_runtime_provider_kubernetes.kubernetes_api import (
    KubernetesApi,
    LeaseResource,
    LeaseSpec,
    ObjectMeta,
)


@dataclasses.dataclass(frozen=True)
class LeaderElectionConfig:
    """Leader election configuration."""

    namespace: str
    lease_name: str
    holder_identity: str
    lease_duration_seconds: int = 30


@dataclasses.dataclass(frozen=True)
class LeaderElectionResult:
    """Lease acquire/renew result."""

    acquired: bool
    lease: LeaseResource


class KubernetesLeaderElector:
    """Acquire and renew a Kubernetes Lease for active Provider ownership."""

    def __init__(
        self,
        api: KubernetesApi,
        config: LeaderElectionConfig,
    ) -> None:
        """Initialize the elector."""
        self._api = api
        self._config = config

    async def try_acquire(self, *, now: datetime) -> LeaderElectionResult:
        """Acquire the Lease when it is empty, expired, or already held by us."""
        lease = await self._api.get_lease(
            self._config.lease_name,
            self._config.namespace,
        )
        if lease is None:
            acquired = self._new_lease(now)
            await self._api.apply_lease(acquired)
            return LeaderElectionResult(acquired=True, lease=acquired)
        if not self._can_hold(lease, now=now):
            return LeaderElectionResult(acquired=False, lease=lease)
        next_lease = self._renewed_lease(lease, now)
        await self._api.apply_lease(next_lease)
        return LeaderElectionResult(acquired=True, lease=next_lease)

    def _can_hold(self, lease: LeaseResource, *, now: datetime) -> bool:
        holder = lease.spec.holder_identity
        if holder is None or holder == self._config.holder_identity:
            return True
        if lease.spec.renew_time is None:
            return True
        expires_at = lease.spec.renew_time + timedelta(
            seconds=lease.spec.lease_duration_seconds
        )
        return now >= expires_at

    def _new_lease(self, now: datetime) -> LeaseResource:
        return LeaseResource(
            metadata=ObjectMeta(
                name=self._config.lease_name,
                namespace=self._config.namespace,
                labels={"app.kubernetes.io/name": "azents-runtime-provider-kubernetes"},
                annotations={},
            ),
            spec=LeaseSpec(
                holder_identity=self._config.holder_identity,
                acquire_time=now,
                renew_time=now,
                lease_duration_seconds=self._config.lease_duration_seconds,
                lease_transitions=0,
            ),
        )

    def _renewed_lease(self, lease: LeaseResource, now: datetime) -> LeaseResource:
        previous_holder = lease.spec.holder_identity
        transitions = lease.spec.lease_transitions
        if previous_holder != self._config.holder_identity:
            transitions += 1
        return dataclasses.replace(
            lease,
            spec=dataclasses.replace(
                lease.spec,
                holder_identity=self._config.holder_identity,
                acquire_time=lease.spec.acquire_time or now,
                renew_time=now,
                lease_duration_seconds=self._config.lease_duration_seconds,
                lease_transitions=transitions,
            ),
        )
