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


class RuntimeToServerTransferService:
    """Admit, receive, and publish one verified Runtime upload."""

    def __init__(
        self,
        *,
        coordinator: RuntimeToServerCoordinator,
        clock: Callable[[], datetime],
        status_poll_interval: timedelta,
    ) -> None:
        self.coordinator = coordinator
        self.clock = clock
        self.status_poll_interval = status_poll_interval

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
            await self.coordinator.dispatch_transfer(
                CoordinatorDispatchTransferRequest(
                    identity=identity,
                    expected_revision=ready.revision,
                    dispatch_id=uuid7().hex,
                )
            )
            available = await self._wait_available(identity, request.deadline_at)
            claim_id = uuid7().hex
            claimed = await self.coordinator.claim_consumer(
                CoordinatorConsumerRequest(
                    identity=identity,
                    expected_revision=available.revision,
                    consumer_claim_id=claim_id,
                )
            )
            verified = await self.coordinator.get_verified_object(
                CoordinatorGetVerifiedObjectRequest(
                    identity=identity,
                    expected_revision=claimed.revision,
                    consumer_claim_id=claim_id,
                )
            )
            renewed = await self.coordinator.renew_consumer_lease(
                CoordinatorConsumerRequest(
                    identity=identity,
                    expected_revision=verified.status.revision,
                    consumer_claim_id=claim_id,
                )
            )
            manifest = verified.actual_manifest
            if manifest.size is None or manifest.sha256 is None:
                raise RuntimeToServerTransferError(
                    "Verified upload manifest is missing"
                )
            await request.callback.publish(
                VerifiedRuntimeUpload(
                    identity=identity,
                    publication_id=request.publication_id,
                    object_handle=verified.verified_object_handle,
                    size=manifest.size,
                    sha256=manifest.sha256,
                )
            )
            committed = True
            acknowledged = await self._recover_acknowledgement(
                identity,
                claim_id,
                renewed.revision,
            )
            await self._recover_settlement(identity, acknowledged.revision)
        except asyncio.CancelledError:
            if not committed:
                await self._abandon_and_cancel(identity, claim_id, revision)
            raise
        except Exception:
            if not committed:
                await self._abandon_and_cancel(identity, claim_id, revision)
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
    ) -> CoordinatorTransferStatus:
        try:
            return await self.coordinator.acknowledge_consumer(
                CoordinatorConsumerRequest(
                    identity=identity,
                    expected_revision=revision,
                    consumer_claim_id=claim_id,
                )
            )
        except Exception:
            return await self.coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )

    async def _recover_settlement(
        self,
        identity: CoordinatorTransferIdentity,
        revision: int,
    ) -> None:
        try:
            status = await self.coordinator.settle_transfer(
                CoordinatorSettleTransferRequest(
                    identity=identity,
                    expected_revision=revision,
                    outcome=CoordinatorTransferOutcome.SUCCEEDED,
                    failure=None,
                )
            )
        except Exception:
            status = await self.coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )
        if (
            status.phase is CoordinatorTransferPhase.TERMINAL
            and status.outcome is not CoordinatorTransferOutcome.SUCCEEDED
        ):
            raise RuntimeToServerTransferError("Committed publication was not settled")

    async def _abandon_and_cancel(
        self,
        identity: CoordinatorTransferIdentity,
        claim_id: str | None,
        revision: int | None,
    ) -> None:
        if revision is None:
            return
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
            except Exception:
                pass
        try:
            await self.coordinator.cancel_transfer(
                CoordinatorCancelTransferRequest(
                    identity=identity,
                    expected_revision=revision,
                    reason=CoordinatorCancellationReason.CALLER,
                )
            )
        except Exception:
            pass

    def _validate(self, request: RuntimeToServerTransferRequest) -> None:
        if not request.runtime_path.startswith("/"):
            raise ValueError("Runtime upload path must be absolute")
        if request.expected_size < 0:
            raise ValueError("Runtime upload size must not be negative")
        if request.deadline_at <= self.clock():
            raise RuntimeToServerTransferError("Runtime upload deadline expired")
