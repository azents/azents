"""Focused Runtime-to-server publication tests."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancelTransferRequest,
    CoordinatorCleanupStatus,
    CoordinatorConsumerRequest,
    CoordinatorDispatchStatus,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorGetVerifiedObjectRequest,
    CoordinatorGetVerifiedObjectResult,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPreparationCleanupState,
    CoordinatorSettleTransferRequest,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferRequest,
    RuntimeToServerTransferService,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget

_NOW = datetime(2026, 7, 26, tzinfo=UTC)
_HANDLE = CoordinatorOpaqueObjectHandle("opaque-verified-object")


@dataclass
class _Callback:
    uploads: list[VerifiedRuntimeUpload]
    fail: bool = False

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        if self.fail:
            raise RuntimeError("publication failed")
        self.uploads.append(upload)


@dataclass
class _DelayedCallback:
    """Publication callback that holds the consumer lease across several ticks."""

    uploads: list[VerifiedRuntimeUpload]

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        await asyncio.sleep(0.01)
        self.uploads.append(upload)


@dataclass
class _CancellableCallback:
    """Callback that records cooperative cancellation before its commit point."""

    uploads: list[VerifiedRuntimeUpload]
    cancelled: bool = False

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.uploads.append(upload)


class _Coordinator:
    def __init__(self, *, ack_fails: bool = False) -> None:
        self.calls: list[str] = []
        self.ack_fails = ack_fails
        self.ack_attempted = False

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult:
        self.calls.append("admit")
        return CoordinatorAdmitTransferResult(_status(1, request.identity), _HANDLE)

    async def mark_transfer_ready(
        self, request: CoordinatorMarkTransferReadyRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("ready")
        return _status(2, request.identity, CoordinatorTransferPhase.READY)

    async def dispatch_transfer(
        self, request: CoordinatorDispatchTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("dispatch")
        return _status(3, request.identity, CoordinatorTransferPhase.READY)

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        if self.ack_attempted:
            return _status(7, request.identity, CoordinatorTransferPhase.CONSUMED)
        return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)

    async def claim_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("claim")
        return _status(5, request.identity, CoordinatorTransferPhase.CONSUMING)

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("renew")
        return _status(6, request.identity, CoordinatorTransferPhase.CONSUMING)

    async def get_verified_object(
        self, request: CoordinatorGetVerifiedObjectRequest
    ) -> CoordinatorGetVerifiedObjectResult:
        self.calls.append("verified")
        return CoordinatorGetVerifiedObjectResult(
            status=_status(6, request.identity, CoordinatorTransferPhase.CONSUMING),
            verified_object_handle=_HANDLE,
            actual_manifest=CoordinatorObjectManifest(size=9, sha256="a" * 64),
        )

    async def acknowledge_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("ack")
        if self.ack_fails:
            self.ack_attempted = True
            raise OSError("ack transport failed")
        return _status(7, request.identity, CoordinatorTransferPhase.CONSUMED)

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("abandon")
        return _status(7, request.identity, CoordinatorTransferPhase.AVAILABLE)

    async def settle_transfer(
        self, request: CoordinatorSettleTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("settle")
        return _status(
            8,
            request.identity,
            CoordinatorTransferPhase.TERMINAL,
            CoordinatorTransferOutcome.SUCCEEDED,
        )

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("cancel")
        return _status(
            8,
            request.identity,
            CoordinatorTransferPhase.TERMINAL,
            CoordinatorTransferOutcome.CANCELLED,
        )


class _StrictCleanupCoordinator(_Coordinator):
    """Coordinator that rejects cleanup requests with stale revisions."""

    def __init__(self) -> None:
        super().__init__()
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 1:
            return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)
        return _status(6, request.identity, CoordinatorTransferPhase.CONSUMING)

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        assert request.expected_revision == 6
        return await super().abandon_consumer(request)

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        assert request.expected_revision == 7
        return await super().cancel_transfer(request)


class _FailedSettlementCoordinator(_Coordinator):
    """Coordinator that authoritatively rejects a committed settlement."""

    async def settle_transfer(
        self, request: CoordinatorSettleTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("settle")
        return _status(
            8,
            request.identity,
            CoordinatorTransferPhase.TERMINAL,
            CoordinatorTransferOutcome.FAILED,
        )


class _RetryAcknowledgementCoordinator(_Coordinator):
    """Coordinator that needs a retry after an uncertain acknowledgement."""

    def __init__(self) -> None:
        super().__init__()
        self.acknowledgement_attempts = 0

    async def acknowledge_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("ack")
        self.acknowledgement_attempts += 1
        if self.acknowledgement_attempts == 1:
            raise OSError("acknowledgement transport failed")
        return _status(7, request.identity, CoordinatorTransferPhase.CONSUMED)


class _LeaseFailureCoordinator(_Coordinator):
    """Coordinator that loses the lease after the initial pre-publication renewal."""

    def __init__(self) -> None:
        super().__init__()
        self.renewals = 0

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("renew")
        self.renewals += 1
        if self.renewals > 1:
            raise OSError("consumer lease renewal failed")
        return _status(6, request.identity, CoordinatorTransferPhase.CONSUMING)


def _status(
    revision: int,
    identity: CoordinatorTransferIdentity,
    phase: CoordinatorTransferPhase = CoordinatorTransferPhase.PREPARING,
    outcome: CoordinatorTransferOutcome | None = None,
) -> CoordinatorTransferStatus:
    return CoordinatorTransferStatus(
        identity=identity,
        phase=phase,
        revision=revision,
        accepted_runner_generation=1,
        dispatch_id=None,
        dispatch_status=CoordinatorDispatchStatus.ENQUEUED,
        expected_manifest=CoordinatorExpectedManifest(size=9, sha256=None),
        actual_manifest=CoordinatorObjectManifest(size=9, sha256="a" * 64),
        deadline_at=_NOW + timedelta(minutes=1),
        logical_expires_at=_NOW + timedelta(minutes=1),
        outcome=outcome,
        failure=None,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
    )


def _request(
    callback: RuntimeToServerPublicationCallback,
) -> RuntimeToServerTransferRequest:
    return RuntimeToServerTransferRequest(
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
        agent_id="agent",
        session_id="session",
        operation_id="operation",
        runtime_path="/workspace/agent/result.txt",
        expected_size=9,
        expected_sha256=None,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_NOW + timedelta(minutes=1),
        resource_class="present_file",
        publication_id="stable-publication",
        callback=callback,
    )


@pytest.mark.asyncio
async def test_upload_orders_verified_claim_publish_ack_and_settlement() -> None:
    coordinator = _Coordinator()
    callback = _Callback([])
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    await service.transfer(_request(callback))

    assert coordinator.calls == [
        "admit",
        "ready",
        "dispatch",
        "status",
        "claim",
        "verified",
        "renew",
        "ack",
        "settle",
    ]
    assert callback.uploads[0].object_handle == _HANDLE
    assert callback.uploads[0].publication_id == "stable-publication"
    assert "bucket" not in repr(callback.uploads[0])


@pytest.mark.asyncio
async def test_callback_failure_abandons_and_cancels_uncommitted_claim() -> None:
    coordinator = _Coordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        await service.transfer(_request(_Callback([], fail=True)))

    assert coordinator.calls[-2:] == ["abandon", "cancel"]


@pytest.mark.asyncio
async def test_callback_failure_uses_fresh_revision_for_cleanup() -> None:
    """Cleanup observes the last consumer-fenced revision, not admission state."""
    coordinator = _StrictCleanupCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        await service.transfer(_request(_Callback([], fail=True)))

    assert coordinator.calls[-2:] == ["abandon", "cancel"]


@pytest.mark.asyncio
async def test_ack_transport_recovery_does_not_cancel_committed_publication() -> None:
    coordinator = _Coordinator(ack_fails=True)
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    await service.transfer(_request(_Callback([])))

    assert "cancel" not in coordinator.calls
    assert coordinator.calls[-3:] == ["ack", "status", "settle"]


@pytest.mark.asyncio
async def test_acknowledgement_retries_after_uncertain_available_status() -> None:
    """An uncertain acknowledgement remains unresolved until it is confirmed."""
    coordinator = _RetryAcknowledgementCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    await service.transfer(_request(_Callback([])))

    assert coordinator.calls[-4:] == ["ack", "status", "ack", "settle"]


@pytest.mark.asyncio
async def test_terminal_failed_settlement_is_not_reported_as_success() -> None:
    """Only an authoritative terminal SUCCEEDED outcome completes publication."""
    coordinator = _FailedSettlementCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="not settled"):
        await service.transfer(_request(_Callback([])))

    assert "cancel" not in coordinator.calls


@pytest.mark.asyncio
async def test_long_publication_renews_consumer_lease_until_callback_finishes() -> None:
    """The product callback retains its consumer fence beyond its first renewal."""
    coordinator = _Coordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(milliseconds=1),
    )

    await service.transfer(_request(_DelayedCallback([])))

    assert coordinator.calls.count("renew") > 1


@pytest.mark.asyncio
async def test_lease_loss_cancels_publication_before_its_commit_boundary() -> None:
    """A failed renewal cancels the cooperative publisher before it commits."""
    coordinator = _LeaseFailureCoordinator()
    callback = _CancellableCallback([])
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(RuntimeError, match="lease renewal failed"):
        await service.transfer(_request(callback))

    assert callback.cancelled is True
    assert callback.uploads == []
