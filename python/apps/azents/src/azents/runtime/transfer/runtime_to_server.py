"""Trusted backend-only Runtime-to-server managed publication orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from azcommon.uuid import uuid7
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancellationReason,
    CoordinatorCancelTransferRequest,
    CoordinatorConsumerRequest,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorGetVerifiedObjectRequest,
    CoordinatorGetVerifiedObjectResult,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorSettleTransferRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget


class RuntimeToServerTransferError(RuntimeError):
    """Raised when a Runtime upload cannot complete managed publication."""


@dataclass(frozen=True)
class VerifiedRuntimeUpload:
    """Trusted metadata-only upload object supplied to one feature publisher."""

    identity: CoordinatorTransferIdentity
    publication_id: str
    object_handle: CoordinatorOpaqueObjectHandle
    size: int
    sha256: str


class RuntimeToServerPublicationCallback(Protocol):
    """Feature-owned final publication boundary."""

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        """Commit the product resource before returning."""
        ...


class RuntimeToServerCoordinator(Protocol):
    """Typed coordinator surface required for one Runtime upload."""

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult: ...

    async def mark_transfer_ready(
        self, request: CoordinatorMarkTransferReadyRequest
    ) -> CoordinatorTransferStatus: ...

    async def dispatch_transfer(
        self, request: CoordinatorDispatchTransferRequest
    ) -> CoordinatorTransferStatus: ...

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus: ...

    async def claim_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus: ...

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus: ...

    async def get_verified_object(
        self, request: CoordinatorGetVerifiedObjectRequest
    ) -> CoordinatorGetVerifiedObjectResult: ...

    async def acknowledge_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus: ...

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus: ...

    async def settle_transfer(
        self, request: CoordinatorSettleTransferRequest
    ) -> CoordinatorTransferStatus: ...

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus: ...


@dataclass(frozen=True)
class RuntimeToServerTransferRequest:
    """Metadata-only Runtime upload publication request."""

    target: ServerToRuntimeTarget
    agent_id: str
    session_id: str
    operation_id: str
    runtime_path: str
    expected_size: int
    expected_sha256: str | None
    product_maximum_size: int
    provider_maximum_size: int
    deadline_at: datetime
    resource_class: str
    publication_id: str
    callback: RuntimeToServerPublicationCallback


@dataclass
class _ConsumerLease:
    """Mutable consumer fencing state owned by one publication callback."""

    revision: int
    failure: RuntimeToServerTransferError | None = None


class RuntimeToServerTransferService:
    """Admit, receive, and publish one verified Runtime upload."""

    def __init__(
        self,
        *,
        coordinator: RuntimeToServerCoordinator,
        clock: Callable[[], datetime],
        status_poll_interval: timedelta,
        consumer_lease_renew_interval: timedelta,
    ) -> None:
        self.coordinator = coordinator
        self.clock = clock
        self.status_poll_interval = status_poll_interval
        self.consumer_lease_renew_interval = consumer_lease_renew_interval

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Return only after product commit and authoritative transfer success."""
        self._validate(request)
        identity = CoordinatorTransferIdentity(
            transfer_id=uuid7().hex,
            attempt_id=uuid7().hex,
            runtime_id=request.target.runtime_id,
            desired_generation=request.target.desired_generation,
            direction=CoordinatorTransferDirection.UPLOAD.value,
            operation_id=request.operation_id,
            session_id=request.session_id,
            agent_id=request.agent_id,
        )
        revision: int | None = None
        claim_id: str | None = None
        committed = False
        try:
            admitted = await self.coordinator.admit_transfer(
                CoordinatorAdmitTransferRequest(
                    identity=identity,
                    lease_id=uuid7().hex,
                    runtime_path=request.runtime_path,
                    overwrite=False,
                    expected_manifest=CoordinatorExpectedManifest(
                        size=request.expected_size,
                        sha256=request.expected_sha256,
                    ),
                    product_maximum_size=request.product_maximum_size,
                    provider_maximum_size=request.provider_maximum_size,
                    deadline_at=request.deadline_at,
                    source_expires_at=None,
                    resource_class=request.resource_class,
                )
            )
            revision = admitted.status.revision
            ready = await self.coordinator.mark_transfer_ready(
                CoordinatorMarkTransferReadyRequest(
                    identity=identity,
                    expected_revision=revision,
                    object_handle=admitted.admitted_object_handle,
                    object_manifest=CoordinatorObjectManifest(
                        size=request.expected_size,
                        sha256=request.expected_sha256,
                    ),
                )
            )
            revision = ready.revision
            dispatched = await self.coordinator.dispatch_transfer(
                CoordinatorDispatchTransferRequest(
                    identity=identity,
                    expected_revision=revision,
                    dispatch_id=uuid7().hex,
                )
            )
            revision = dispatched.revision
            available = await self._wait_available(identity, request.deadline_at)
            revision = available.revision
            claim_id = uuid7().hex
            claimed = await self.coordinator.claim_consumer(
                CoordinatorConsumerRequest(
                    identity=identity,
                    expected_revision=revision,
                    consumer_claim_id=claim_id,
                )
            )
            revision = claimed.revision
            verified = await self.coordinator.get_verified_object(
                CoordinatorGetVerifiedObjectRequest(
                    identity=identity,
                    expected_revision=revision,
                    consumer_claim_id=claim_id,
                )
            )
            revision = verified.status.revision
            renewed = await self.coordinator.renew_consumer_lease(
                CoordinatorConsumerRequest(
                    identity=identity,
                    expected_revision=revision,
                    consumer_claim_id=claim_id,
                )
            )
            revision = renewed.revision
            manifest = verified.actual_manifest
            if manifest.size is None or manifest.sha256 is None:
                raise RuntimeToServerTransferError(
                    "Verified upload manifest is missing"
                )
            revision = await self._publish_with_consumer_lease(
                callback=request.callback,
                upload=VerifiedRuntimeUpload(
                    identity=identity,
                    publication_id=request.publication_id,
                    object_handle=verified.verified_object_handle,
                    size=manifest.size,
                    sha256=manifest.sha256,
                ),
                identity=identity,
                claim_id=claim_id,
                revision=revision,
                deadline_at=request.deadline_at,
            )
            committed = True
            acknowledged = await self._recover_acknowledgement(
                identity,
                claim_id,
                revision,
                request.deadline_at,
            )
            await self._recover_settlement(
                identity,
                acknowledged.revision,
                request.deadline_at,
            )
        except asyncio.CancelledError:
            if not committed:
                await self._abandon_and_cancel(
                    identity,
                    claim_id,
                    revision,
                    request.deadline_at,
                )
            raise
        except Exception:
            if not committed:
                await self._abandon_and_cancel(
                    identity,
                    claim_id,
                    revision,
                    request.deadline_at,
                )
            raise

    async def _wait_available(
        self,
        identity: CoordinatorTransferIdentity,
        deadline_at: datetime,
    ) -> CoordinatorTransferStatus:
        while True:
            if self.clock() >= deadline_at:
                raise RuntimeToServerTransferError("Runtime upload deadline expired")
            status = await self.coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )
            if status.phase is CoordinatorTransferPhase.AVAILABLE:
                return status
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                raise RuntimeToServerTransferError("Runtime upload terminated")
            await asyncio.sleep(self.status_poll_interval.total_seconds())

    async def _recover_acknowledgement(
        self,
        identity: CoordinatorTransferIdentity,
        claim_id: str,
        revision: int,
        deadline_at: datetime,
    ) -> CoordinatorTransferStatus:
        while self.clock() < deadline_at:
            try:
                status = await self.coordinator.acknowledge_consumer(
                    CoordinatorConsumerRequest(
                        identity=identity,
                        expected_revision=revision,
                        consumer_claim_id=claim_id,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                status = await self._observe_status(
                    identity=identity,
                    deadline_at=deadline_at,
                )
            if status.phase is CoordinatorTransferPhase.CONSUMED:
                return status
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                if status.outcome is CoordinatorTransferOutcome.SUCCEEDED:
                    return status
                raise RuntimeToServerTransferError(
                    "Committed publication acknowledgement was rejected"
                )
            revision = status.revision
            await asyncio.sleep(self.status_poll_interval.total_seconds())
        raise RuntimeToServerTransferError(
            "Committed publication acknowledgement was not confirmed"
        )

    async def _recover_settlement(
        self,
        identity: CoordinatorTransferIdentity,
        revision: int,
        deadline_at: datetime,
    ) -> None:
        while self.clock() < deadline_at:
            try:
                status = await self.coordinator.settle_transfer(
                    CoordinatorSettleTransferRequest(
                        identity=identity,
                        expected_revision=revision,
                        outcome=CoordinatorTransferOutcome.SUCCEEDED,
                        failure=None,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                status = await self._observe_status(
                    identity=identity,
                    deadline_at=deadline_at,
                )
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                if status.outcome is CoordinatorTransferOutcome.SUCCEEDED:
                    return
                raise RuntimeToServerTransferError(
                    "Committed publication was not settled"
                )
            revision = status.revision
            await asyncio.sleep(self.status_poll_interval.total_seconds())
        raise RuntimeToServerTransferError(
            "Committed publication settlement was not confirmed"
        )

    async def _publish_with_consumer_lease(
        self,
        *,
        callback: RuntimeToServerPublicationCallback,
        upload: VerifiedRuntimeUpload,
        identity: CoordinatorTransferIdentity,
        claim_id: str,
        revision: int,
        deadline_at: datetime,
    ) -> int:
        """Cancel publication before its commit boundary when the lease is lost."""
        lease = _ConsumerLease(revision=revision)
        publication_task = asyncio.create_task(callback.publish(upload))
        renewal_task = asyncio.create_task(
            self._renew_consumer_lease_while_publishing(
                identity=identity,
                claim_id=claim_id,
                deadline_at=deadline_at,
                lease=lease,
            )
        )
        try:
            done, _ = await asyncio.wait(
                {publication_task, renewal_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if renewal_task in done and lease.failure is not None:
                if not publication_task.done():
                    publication_task.cancel()
                try:
                    await publication_task
                except asyncio.CancelledError:
                    pass
                raise lease.failure
            await publication_task
            if lease.failure is not None:
                raise lease.failure
            return lease.revision
        finally:
            for task in (publication_task, renewal_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                publication_task,
                renewal_task,
                return_exceptions=True,
            )

    async def _observe_status(
        self,
        *,
        identity: CoordinatorTransferIdentity,
        deadline_at: datetime,
    ) -> CoordinatorTransferStatus:
        """Read authoritative status despite bounded observation transport errors."""
        last_error: Exception | None = None
        while self.clock() < deadline_at:
            try:
                return await self.coordinator.get_transfer_status(
                    CoordinatorGetTransferStatusRequest(identity=identity)
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:
                last_error = err
            await asyncio.sleep(self.status_poll_interval.total_seconds())
        raise RuntimeToServerTransferError(
            "Runtime upload status could not be observed"
        ) from last_error

    async def _renew_consumer_lease_while_publishing(
        self,
        *,
        identity: CoordinatorTransferIdentity,
        claim_id: str,
        deadline_at: datetime,
        lease: _ConsumerLease,
    ) -> None:
        """Renew the consumer fence until product publication completes."""
        while True:
            await asyncio.sleep(self.consumer_lease_renew_interval.total_seconds())
            if self.clock() >= deadline_at:
                lease.failure = RuntimeToServerTransferError(
                    "Runtime upload deadline expired during publication"
                )
                return
            try:
                status = await self.coordinator.renew_consumer_lease(
                    CoordinatorConsumerRequest(
                        identity=identity,
                        expected_revision=lease.revision,
                        consumer_claim_id=claim_id,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                lease.failure = RuntimeToServerTransferError(
                    "Runtime upload consumer lease renewal failed"
                )
                return
            if status.phase is not CoordinatorTransferPhase.CONSUMING:
                lease.failure = RuntimeToServerTransferError(
                    "Runtime upload consumer lease was lost"
                )
                return
            lease.revision = status.revision

    async def _abandon_and_cancel(
        self,
        identity: CoordinatorTransferIdentity,
        claim_id: str | None,
        revision: int | None,
        deadline_at: datetime,
    ) -> None:
        if revision is None:
            return
        try:
            status = await self.coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )
            revision = status.revision
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if claim_id is not None:
            try:
                status = await self.coordinator.abandon_consumer(
                    CoordinatorConsumerRequest(
                        identity=identity,
                        expected_revision=revision,
                        consumer_claim_id=claim_id,
                    )
                )
                revision = status.revision
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    status = await self.coordinator.get_transfer_status(
                        CoordinatorGetTransferStatusRequest(identity=identity)
                    )
                    revision = status.revision
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
        while self.clock() < deadline_at:
            try:
                status = await self.coordinator.cancel_transfer(
                    CoordinatorCancelTransferRequest(
                        identity=identity,
                        expected_revision=revision,
                        reason=CoordinatorCancellationReason.CALLER,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    status = await self.coordinator.get_transfer_status(
                        CoordinatorGetTransferStatusRequest(identity=identity)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                return
            revision = status.revision
            await asyncio.sleep(self.status_poll_interval.total_seconds())

    def _validate(self, request: RuntimeToServerTransferRequest) -> None:
        if not request.runtime_path.startswith("/"):
            raise ValueError("Runtime upload path must be absolute")
        if request.expected_size < 0:
            raise ValueError("Runtime upload size must not be negative")
        if request.deadline_at <= self.clock():
            raise RuntimeToServerTransferError("Runtime upload deadline expired")
        if self.consumer_lease_renew_interval <= timedelta():
            raise ValueError(
                "Runtime upload consumer lease renewal interval must be positive"
            )
