"""Trusted backend-only Server-to-Runtime complete-file transfer orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, TypeVar

import grpc
from azcommon.uuid import uuid7
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancellationReason,
    CoordinatorCancelTransferRequest,
    CoordinatorClearPreparationCleanupRequest,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPromotePreparationCleanupRequest,
    CoordinatorRegisterPreparationCleanupRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferFailure,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity


class ServerToRuntimeTransferError(RuntimeError):
    """Raised when a Server-to-Runtime transfer cannot commit its destination."""

    def __init__(
        self,
        message: str,
        *,
        failure: CoordinatorTransferFailure | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure


class ServerToRuntimeTransferLimitExceeded(ServerToRuntimeTransferError):
    """Raised when source metadata exceeds the configured transfer limit."""


class ServerToRuntimeTransferAdmissionTimeout(ServerToRuntimeTransferError):
    """Raised when transfer admission remains unavailable until the deadline."""


class ServerToRuntimeTransferConnectionTimeout(ServerToRuntimeTransferError):
    """Raised when coordinator admission connectivity misses the deadline."""


class ServerToRuntimeCoordinatorError(ServerToRuntimeTransferError):
    """Raised for one classified Runtime Transfer Coordinator RPC failure."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        failure: CoordinatorTransferFailure | None,
    ) -> None:
        super().__init__(message, failure=failure)
        self.phase = phase


_CoordinatorResult = TypeVar("_CoordinatorResult")


async def _await_coordinator(
    operation: Awaitable[_CoordinatorResult],
    *,
    phase: str,
) -> _CoordinatorResult:
    """Translate coordinator transport failures at the transfer boundary."""
    try:
        return await operation
    except grpc.aio.AioRpcError as error:
        raise ServerToRuntimeCoordinatorError(
            "Runtime transfer coordinator request failed",
            phase=phase,
            failure=_coordinator_failure(error.code()),
        ) from error


def _coordinator_failure(
    status: grpc.StatusCode,
) -> CoordinatorTransferFailure | None:
    """Map safe gRPC status categories into transfer-domain failures."""
    if status is grpc.StatusCode.RESOURCE_EXHAUSTED:
        return CoordinatorTransferFailure.ADMISSION
    if status is grpc.StatusCode.UNAVAILABLE:
        return CoordinatorTransferFailure.STREAM
    if status is grpc.StatusCode.ABORTED:
        return CoordinatorTransferFailure.FENCED
    if status is grpc.StatusCode.DEADLINE_EXCEEDED:
        return CoordinatorTransferFailure.EXPIRED
    if status is grpc.StatusCode.CANCELLED:
        return CoordinatorTransferFailure.CANCELLED
    if status is grpc.StatusCode.DATA_LOSS:
        return CoordinatorTransferFailure.INTEGRITY
    return None


@dataclass(frozen=True)
class ServerToRuntimeSourceMetadata:
    """Authorized source metadata that never contains bytes or storage authority."""

    canonical_uri: str
    source_kind: str
    display_name: str
    media_type: str
    size: int
    sha256: str | None
    expires_at: datetime | None

    def __post_init__(self) -> None:
        """Validate bounded metadata owned by trusted backend adapters."""
        if not self.canonical_uri or not self.source_kind or not self.display_name:
            raise ValueError("Transfer source metadata is required")
        if self.size < 0:
            raise ValueError("Transfer source size must not be negative")
        if self.sha256 is not None and (
            len(self.sha256) != 64
            or self.sha256.lower() != self.sha256
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("Transfer source SHA-256 is invalid")
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None
        ):
            raise ValueError("Transfer source expiration must be timezone-aware")


@dataclass(frozen=True)
class PreparedServerToRuntimeObject:
    """Verified final immutable snapshot metadata returned by source staging."""

    object_handle: CoordinatorOpaqueObjectHandle
    size: int
    sha256: str


class ServerToRuntimePreparationCleanupCoordinator(Protocol):
    """Revision-fenced preparation cleanup calls available to source adapters."""

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...


@dataclass
class ServerToRuntimePreparation:
    """One admitted source-preparation attempt with its current fenced revision."""

    identity: CoordinatorTransferIdentity
    admitted_object_handle: CoordinatorOpaqueObjectHandle
    coordinator: ServerToRuntimePreparationCleanupCoordinator
    revision: int

    async def register_cleanup(
        self,
        *,
        preparation_object_handle: CoordinatorOpaqueObjectHandle,
        multipart_cleanup_handle: CoordinatorOpaqueObjectHandle,
    ) -> None:
        """Durably retain abort authority before provider body streaming."""
        status = await _await_coordinator(
            self.coordinator.register_preparation_cleanup(
                CoordinatorRegisterPreparationCleanupRequest(
                    identity=self.identity,
                    expected_revision=self.revision,
                    preparation_object_handle=preparation_object_handle,
                    multipart_cleanup_handle=multipart_cleanup_handle,
                )
            ),
            phase="source_cleanup_register",
        )
        self.revision = status.revision

    async def promote_cleanup(
        self,
        *,
        preparation_object_handle: CoordinatorOpaqueObjectHandle,
    ) -> None:
        """Retain completed preparation-object deletion authority."""
        status = await _await_coordinator(
            self.coordinator.promote_preparation_cleanup(
                CoordinatorPromotePreparationCleanupRequest(
                    identity=self.identity,
                    expected_revision=self.revision,
                    preparation_object_handle=preparation_object_handle,
                )
            ),
            phase="source_cleanup_promote",
        )
        self.revision = status.revision

    async def clear_cleanup(self) -> None:
        """Clear preparation cleanup evidence after exact owned cleanup."""
        status = await _await_coordinator(
            self.coordinator.clear_preparation_cleanup(
                CoordinatorClearPreparationCleanupRequest(
                    identity=self.identity,
                    expected_revision=self.revision,
                )
            ),
            phase="source_cleanup_clear",
        )
        self.revision = status.revision


class ServerToRuntimeSource(Protocol):
    """Closed authorized source/staging boundary for trusted backend code."""

    @property
    def metadata(self) -> ServerToRuntimeSourceMetadata:
        """Return authorized source metadata without opening or reading content."""
        ...

    async def prepare(
        self,
        *,
        preparation: ServerToRuntimePreparation,
    ) -> PreparedServerToRuntimeObject:
        """Prepare and verify an immutable snapshot after coordinator admission."""
        ...

    async def revalidate(self) -> bool:
        """Revalidate feature authority and source expiry before dispatch."""
        ...


class ServerToRuntimeCoordinator(Protocol):
    """Typed coordinator calls required by backend transfer orchestration."""

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

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus: ...

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus: ...


@dataclass(frozen=True)
class ServerToRuntimeTarget:
    """Current Runtime identity and selected Runner generation."""

    runtime_id: str
    desired_generation: int


@dataclass(frozen=True)
class ServerToRuntimeTransferRequest:
    """One backend complete-file Runtime delivery request."""

    source: ServerToRuntimeSource
    target: ServerToRuntimeTarget
    agent_id: str
    session_id: str
    operation_id: str
    destination: str
    overwrite: bool
    product_maximum_size: int
    provider_maximum_size: int
    deadline_at: datetime


class ServerToRuntimeTransferService:
    """Admit, stage, dispatch, and await one exact Runtime destination commit."""

    def __init__(
        self,
        *,
        coordinator: ServerToRuntimeCoordinator,
        clock: Callable[[], datetime],
        status_poll_interval: timedelta,
    ) -> None:
        if status_poll_interval <= timedelta():
            raise ValueError("Transfer status poll interval must be positive")
        self.coordinator = coordinator
        self.clock = clock
        self.status_poll_interval = status_poll_interval

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Perform one admitted transfer and return only on terminal success."""
        self._validate_request(request)
        metadata = request.source.metadata
        identity = CoordinatorTransferIdentity(
            transfer_id=uuid7().hex,
            attempt_id=uuid7().hex,
            runtime_id=request.target.runtime_id,
            desired_generation=request.target.desired_generation,
            direction=CoordinatorTransferDirection.DOWNLOAD.value,
            operation_id=request.operation_id,
            session_id=request.session_id,
            agent_id=request.agent_id,
        )
        expected_revision: int | None = None
        preparation: ServerToRuntimePreparation | None = None
        try:
            admitted = await self._admit_until_deadline(
                CoordinatorAdmitTransferRequest(
                    identity=identity,
                    lease_id=uuid7().hex,
                    runtime_path=request.destination,
                    overwrite=request.overwrite,
                    expected_manifest=CoordinatorExpectedManifest(
                        size=metadata.size,
                        sha256=metadata.sha256,
                    ),
                    product_maximum_size=request.product_maximum_size,
                    provider_maximum_size=request.provider_maximum_size,
                    deadline_at=request.deadline_at,
                    source_expires_at=metadata.expires_at,
                    resource_class=metadata.source_kind,
                )
            )
            expected_revision = admitted.status.revision
            preparation = ServerToRuntimePreparation(
                identity=identity,
                admitted_object_handle=admitted.admitted_object_handle,
                coordinator=self.coordinator,
                revision=expected_revision,
            )
            prepared = await request.source.prepare(preparation=preparation)
            expected_revision = preparation.revision
            self._validate_prepared(
                metadata,
                admitted.admitted_object_handle,
                prepared,
            )
            if not await request.source.revalidate():
                raise ServerToRuntimeTransferError(
                    "Transfer source authority changed before dispatch"
                )
            status = await _await_coordinator(
                self.coordinator.mark_transfer_ready(
                    CoordinatorMarkTransferReadyRequest(
                        identity=identity,
                        expected_revision=expected_revision,
                        object_handle=prepared.object_handle,
                        object_manifest=CoordinatorObjectManifest(
                            size=prepared.size,
                            sha256=prepared.sha256,
                        ),
                    ),
                ),
                phase="mark_ready",
            )
            expected_revision = status.revision
            preparation.revision = expected_revision
            status = await _await_coordinator(
                self.coordinator.dispatch_transfer(
                    CoordinatorDispatchTransferRequest(
                        identity=identity,
                        expected_revision=expected_revision,
                        dispatch_id=uuid7().hex,
                    )
                ),
                phase="dispatch",
            )
            expected_revision = status.revision
            preparation.revision = expected_revision
            await self._wait_for_terminal_success(
                identity,
                request.deadline_at,
                preparation,
            )
        except asyncio.CancelledError:
            await self._cancel(
                identity,
                preparation.revision if preparation is not None else expected_revision,
                request.deadline_at,
            )
            raise
        except ServerToRuntimeTransferError as error:
            try:
                await self._cancel(
                    identity,
                    preparation.revision
                    if preparation is not None
                    else expected_revision,
                    request.deadline_at,
                )
            except Exception:
                if error.failure is CoordinatorTransferFailure.EXPIRED:
                    raise error from None
                raise
            raise
        except Exception:
            await self._cancel(
                identity,
                preparation.revision if preparation is not None else expected_revision,
                request.deadline_at,
            )
            raise

    async def _admit_until_deadline(
        self,
        request: CoordinatorAdmitTransferRequest,
    ) -> CoordinatorAdmitTransferResult:
        """Retry temporary admission pressure until the transfer deadline."""
        while True:
            try:
                return await _await_coordinator(
                    self.coordinator.admit_transfer(request),
                    phase="admission",
                )
            except ServerToRuntimeTransferError as error:
                if error.failure not in {
                    CoordinatorTransferFailure.ADMISSION,
                    CoordinatorTransferFailure.STREAM,
                }:
                    raise
                now = self.clock()
                if now >= request.deadline_at:
                    if error.failure is CoordinatorTransferFailure.STREAM:
                        raise ServerToRuntimeTransferConnectionTimeout(
                            "Runtime transfer coordinator connection timed out",
                            failure=CoordinatorTransferFailure.STREAM,
                        ) from error
                    raise ServerToRuntimeTransferAdmissionTimeout(
                        "Runtime transfer admission timed out",
                        failure=CoordinatorTransferFailure.ADMISSION,
                    ) from error
                await asyncio.sleep(
                    min(
                        self.status_poll_interval.total_seconds(),
                        (request.deadline_at - now).total_seconds(),
                    )
                )

    async def _wait_for_terminal_success(
        self,
        identity: CoordinatorTransferIdentity,
        deadline_at: datetime,
        preparation: ServerToRuntimePreparation,
    ) -> None:
        while True:
            now = self.clock()
            if now >= deadline_at:
                raise ServerToRuntimeTransferError(
                    "Runtime transfer did not complete before its deadline",
                    failure=CoordinatorTransferFailure.EXPIRED,
                )
            status = await _await_coordinator(
                self.coordinator.get_transfer_status(
                    CoordinatorGetTransferStatusRequest(identity=identity)
                ),
                phase="status",
            )
            preparation.revision = status.revision
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                if status.outcome is CoordinatorTransferOutcome.SUCCEEDED:
                    return
                raise ServerToRuntimeTransferError(
                    "Runtime transfer failed before destination commit",
                    failure=status.failure,
                )
            await asyncio.sleep(
                min(
                    self.status_poll_interval.total_seconds(),
                    (deadline_at - now).total_seconds(),
                )
            )

    async def _cancel(
        self,
        identity: CoordinatorTransferIdentity,
        expected_revision: int | None,
        deadline_at: datetime,
    ) -> None:
        if expected_revision is None:
            return
        revision = expected_revision
        attempted = False
        while not attempted or self.clock() < deadline_at:
            attempted = True
            try:
                status = await _await_coordinator(
                    self.coordinator.cancel_transfer(
                        CoordinatorCancelTransferRequest(
                            identity=identity,
                            expected_revision=revision,
                            reason=CoordinatorCancellationReason.CALLER,
                        )
                    ),
                    phase="cancel",
                )
            except Exception:
                status = await _await_coordinator(
                    self.coordinator.get_transfer_status(
                        CoordinatorGetTransferStatusRequest(identity=identity)
                    ),
                    phase="cancel_status",
                )
            if (
                status.phase is CoordinatorTransferPhase.TERMINAL
                or status.cancellation_requested
            ):
                return
            revision = status.revision
            await asyncio.sleep(0)
        raise ServerToRuntimeTransferError(
            "Runtime transfer cancellation could not be confirmed"
        )

    def _validate_request(self, request: ServerToRuntimeTransferRequest) -> None:
        if not request.destination.startswith("/"):
            raise ValueError("Runtime destination path must be absolute")
        if request.target.desired_generation <= 0:
            raise ValueError("Runtime generation must be positive")
        if request.source.metadata.size > min(
            request.product_maximum_size,
            request.provider_maximum_size,
        ):
            raise ServerToRuntimeTransferLimitExceeded(
                "Transfer source exceeds configured limit"
            )
        if (
            request.deadline_at.tzinfo is None
            or request.deadline_at.utcoffset() is None
        ):
            raise ValueError("Transfer deadline must be timezone-aware")
        if request.deadline_at <= self.clock():
            raise ServerToRuntimeTransferError("Transfer deadline has expired")

    def _validate_prepared(
        self,
        metadata: ServerToRuntimeSourceMetadata,
        admitted_object_handle: CoordinatorOpaqueObjectHandle,
        prepared: PreparedServerToRuntimeObject,
    ) -> None:
        if prepared.object_handle != admitted_object_handle:
            raise ServerToRuntimeTransferError(
                "Prepared object does not match admission"
            )
        if prepared.size != metadata.size:
            raise ServerToRuntimeTransferError(
                "Prepared object size does not match source"
            )
        if metadata.sha256 is not None and prepared.sha256 != metadata.sha256:
            raise ServerToRuntimeTransferError(
                "Prepared object hash does not match source"
            )
