"""Focused Runtime-to-server publication tests."""

import asyncio
import logging
from dataclasses import dataclass, replace
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
    CoordinatorSourceTransport,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
    CoordinatorUploadTransport,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity
from grpc import StatusCode
from grpc.aio import AioRpcError

from azents.runtime.transfer import runtime_to_server
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerConsumerRequest,
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferError,
    RuntimeToServerTransferRequest,
    RuntimeToServerTransferService,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget

_NOW = datetime(2026, 7, 26, tzinfo=UTC)
_HANDLE = CoordinatorOpaqueObjectHandle("opaque-verified-object")
_UNTRUSTED_CLEANUP_MESSAGE = (
    "provider=sentinel endpoint=https://storage.example/private-key"
)


@dataclass
class _Clock:
    """Mutable test clock for bounded cleanup retry deadlines."""

    now: datetime

    def __call__(self) -> datetime:
        """Return the current test time."""
        return self.now


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
    release: asyncio.Event

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        await self.release.wait()
        self.uploads.append(upload)


@dataclass
class _CancellableCallback:
    """Callback that records cooperative cancellation before its commit point."""

    uploads: list[VerifiedRuntimeUpload]
    cancelled: bool = False

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.uploads.append(upload)


class _Coordinator:
    def __init__(self, *, ack_fails: bool = False) -> None:
        self.calls: list[str] = []
        self.admissions: list[CoordinatorAdmitTransferRequest] = []
        self.ack_fails = ack_fails
        self.ack_attempted = False
        self.second_renewal = asyncio.Event()

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult:
        self.calls.append("admit")
        self.admissions.append(request)
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
        if self.calls.count("renew") == 2:
            self.second_renewal.set()
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


class _DiscardedCleanupFailureCoordinator(_Coordinator):
    """Coordinator whose final cleanup status observation cannot recover."""

    def __init__(self) -> None:
        super().__init__()
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 4:
            raise OSError("cleanup status unavailable")
        return _status(
            4 + self.status_calls,
            request.identity,
            CoordinatorTransferPhase.AVAILABLE,
        )

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("abandon")
        raise OSError("cleanup abandon unavailable")

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("cancel")
        raise OSError("cleanup cancel unavailable")


class _RecoveringCleanupCoordinator(_DiscardedCleanupFailureCoordinator):
    """Coordinator that resolves a later cleanup retry without discarded evidence."""

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        return _status(
            4 + self.status_calls,
            request.identity,
            CoordinatorTransferPhase.AVAILABLE,
        )

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("cancel")
        if self.calls.count("cancel") == 1:
            raise OSError("cleanup cancel unavailable")
        return _status(
            10,
            request.identity,
            CoordinatorTransferPhase.TERMINAL,
            CoordinatorTransferOutcome.CANCELLED,
        )


class _DeadlineCleanupCoordinator(_Coordinator):
    """Coordinator that never terminally confirms repeated cancel retries."""

    def __init__(self, clock: _Clock, deadline_at: datetime) -> None:
        super().__init__()
        self.clock = clock
        self.deadline_at = deadline_at
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 3:
            self.clock.now += timedelta(seconds=30)
        elif self.status_calls == 4:
            self.clock.now = self.deadline_at
        return _status(
            4 + self.status_calls,
            request.identity,
            CoordinatorTransferPhase.AVAILABLE,
        )

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("cancel")
        raise OSError("cleanup cancel unavailable")


class _ExpiredInitialCleanupStatusFailureCoordinator(_Coordinator):
    """Coordinator whose initial cleanup status lookup fails after the deadline."""

    def __init__(self, clock: _Clock, deadline_at: datetime) -> None:
        super().__init__()
        self.clock = clock
        self.deadline_at = deadline_at
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 2:
            self.clock.now = self.deadline_at
            raise OSError(_UNTRUSTED_CLEANUP_MESSAGE)
        return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)


class _ExpiredAbandonRecoveryFailureCoordinator(_Coordinator):
    """Coordinator whose abandoned consumer state cannot be recovered by deadline."""

    def __init__(self, clock: _Clock, deadline_at: datetime) -> None:
        super().__init__()
        self.clock = clock
        self.deadline_at = deadline_at
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 3:
            self.clock.now = self.deadline_at
            raise OSError("abandon cleanup status unavailable")
        return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("abandon")
        raise OSError("cleanup abandon unavailable")


class _TerminalAbandonRecoveryCoordinator(_Coordinator):
    """Coordinator whose failed abandon is authoritatively terminally recovered."""

    def __init__(self, clock: _Clock, deadline_at: datetime) -> None:
        super().__init__()
        self.clock = clock
        self.deadline_at = deadline_at
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 2:
            self.clock.now = self.deadline_at
            return _status(7, request.identity, CoordinatorTransferPhase.AVAILABLE)
        if self.status_calls == 3:
            return _status(8, request.identity, CoordinatorTransferPhase.TERMINAL)
        return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("abandon")
        raise OSError("cleanup abandon unavailable")


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
        destination_conflict=None,
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


class _AmbiguousRenewalCoordinator(_Coordinator):
    """Leave a renewal RPC in flight so completion must refresh its revision."""

    def __init__(self) -> None:
        super().__init__()
        self.renewal_started = asyncio.Event()
        self.renewal_count = 0
        self.status_calls = 0

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("renew")
        self.renewal_count += 1
        if self.renewal_count == 1:
            return _status(6, request.identity, CoordinatorTransferPhase.CONSUMING)
        self.renewal_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        self.status_calls += 1
        if self.status_calls == 1:
            return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)
        return _status(9, request.identity, CoordinatorTransferPhase.CONSUMING)

    async def acknowledge_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        assert request.expected_revision == 9
        return await super().acknowledge_consumer(request)


def _consumer_request() -> RuntimeToServerConsumerRequest:
    """Return one request without a publication callback."""
    request = _request(_Callback([]))
    return RuntimeToServerConsumerRequest(
        target=request.target,
        agent_id=request.agent_id,
        session_id=request.session_id,
        operation_id=request.operation_id,
        runtime_path=request.runtime_path,
        expected_size=request.expected_size,
        expected_sha256=request.expected_sha256,
        product_maximum_size=request.product_maximum_size,
        provider_maximum_size=request.provider_maximum_size,
        deadline_at=request.deadline_at,
        resource_class=request.resource_class,
        publication_id=request.publication_id,
    )


@pytest.mark.asyncio
async def test_prepare_consumer_defers_ack_and_settlement_until_completion() -> None:
    """A response consumer owns the claim until its caller commits EOF."""
    coordinator = _Coordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    consumer = await service.prepare_consumer(_consumer_request())

    assert coordinator.calls == [
        "admit",
        "ready",
        "dispatch",
        "status",
        "claim",
        "verified",
        "renew",
    ]
    await consumer.complete()
    assert coordinator.calls[-2:] == ["ack", "settle"]
    assert consumer.committed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_class", ("present_file", "read_image", "workspace_download")
)
async def test_outbound_feature_consumers_admit_only_direct_put(
    resource_class: str,
) -> None:
    """Each outbound feature uses the verified direct PUT consumer lifecycle."""
    coordinator = _Coordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )
    request = replace(_consumer_request(), resource_class=resource_class)

    consumer = await service.prepare_consumer(request)

    assert len(coordinator.admissions) == 1
    admitted = coordinator.admissions[0]
    assert admitted.upload_transport is CoordinatorUploadTransport.DIRECT_OBJECT
    assert admitted.source_transport is CoordinatorSourceTransport.TRANSFER_OBJECT
    assert admitted.runtime_path == request.runtime_path
    assert admitted.expected_manifest.size == request.expected_size
    assert admitted.resource_class == resource_class
    await consumer.complete()
    assert coordinator.calls[-2:] == ["ack", "settle"]


@pytest.mark.asyncio
async def test_consumer_abandon_is_idempotent_and_stops_renewal() -> None:
    """Early response termination runs unsuccessful cleanup exactly once."""
    coordinator = _Coordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    consumer = await service.prepare_consumer(_consumer_request())
    await consumer.start_lease_renewal()
    await consumer.abandon()
    await consumer.abandon()

    assert coordinator.calls[-3:] == ["status", "abandon", "cancel"]
    assert coordinator.calls.count("abandon") == 1
    assert coordinator.calls.count("cancel") == 1


@pytest.mark.asyncio
async def test_completion_refreshes_revision_after_inflight_renewal_cancellation() -> (
    None
):
    """A cancelled renewal RPC is re-observed before acknowledgement fencing."""
    coordinator = _AmbiguousRenewalCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(milliseconds=1),
    )

    consumer = await service.prepare_consumer(_consumer_request())
    await consumer.start_lease_renewal()
    await coordinator.renewal_started.wait()
    await consumer.complete()

    assert "status" in coordinator.calls
    assert coordinator.calls[-2:] == ["ack", "settle"]


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
async def test_discarded_cleanup_status_failure_logs_once_without_upload_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Final cleanup loss preserves the primary callback failure and one traceback."""
    coordinator = _DiscardedCleanupFailureCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )
    request = _request(_Callback([], fail=True))

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(request)

    cleanup_logs = [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert len(cleanup_logs) == 1
    log = cleanup_logs[0]
    assert log.exc_info is not None
    assert log.__dict__["cleanup_stage"] == "cancel_status_lookup"
    assert log.__dict__["runtime_id"] == "runtime"
    assert "runtime_path" not in log.__dict__
    assert "object_handle" not in log.__dict__
    assert request.runtime_path not in log.getMessage()
    assert str(_HANDLE) not in log.getMessage()


@pytest.mark.asyncio
async def test_recoverable_cleanup_retries_remain_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Recovery attempts that later cancel successfully emit no cleanup failure log."""
    coordinator = _RecoveringCleanupCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(_request(_Callback([], fail=True)))

    assert not [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert coordinator.calls.count("cancel") == 2


@pytest.mark.asyncio
async def test_cleanup_deadline_logs_latest_cancel_failure_once_without_upload_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Repeated non-terminal recovery cannot silently discard the last cancel error."""
    request = _request(_Callback([], fail=True))
    clock = _Clock(_NOW)
    coordinator = _DeadlineCleanupCoordinator(clock, request.deadline_at)
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=clock,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(request)

    cleanup_logs = [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert len(cleanup_logs) == 1
    log = cleanup_logs[0]
    assert log.exc_info is not None
    assert str(log.exc_info[1]) == "Runtime upload cleanup failed"
    assert log.__dict__["cleanup_stage"] == "cancel_transfer"
    assert log.__dict__["runtime_id"] == "runtime"
    assert "runtime_path" not in log.__dict__
    assert "object_handle" not in log.__dict__
    assert request.runtime_path not in log.getMessage()
    assert str(_HANDLE) not in log.getMessage()
    assert coordinator.calls.count("cancel") == 2


@pytest.mark.asyncio
async def test_expired_cleanup_logs_initial_status_failure_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deadline cannot silently discard the initial cleanup status failure."""
    request = _request(_Callback([], fail=True))
    clock = _Clock(_NOW)
    coordinator = _ExpiredInitialCleanupStatusFailureCoordinator(
        clock, request.deadline_at
    )
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=clock,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(request)

    cleanup_logs = [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert len(cleanup_logs) == 1
    log = cleanup_logs[0]
    assert log.exc_info is not None
    assert str(log.exc_info[1]) == "Runtime upload cleanup failed"
    assert log.__dict__["cleanup_stage"] == "initial_status_lookup"
    assert coordinator.calls[-2:] == ["status", "abandon"]
    assert "cancel" not in coordinator.calls
    formatted = logging.Formatter().format(log)
    assert _UNTRUSTED_CLEANUP_MESSAGE not in formatted
    assert "RuntimeError: Runtime upload cleanup failed" in formatted


@pytest.mark.asyncio
async def test_expired_cleanup_logs_abandon_recovery_status_failure_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deadline cannot silently discard failed abandon recovery observation."""
    request = _request(_Callback([], fail=True))
    clock = _Clock(_NOW)
    coordinator = _ExpiredAbandonRecoveryFailureCoordinator(clock, request.deadline_at)
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=clock,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(request)

    cleanup_logs = [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert len(cleanup_logs) == 1
    log = cleanup_logs[0]
    assert log.exc_info is not None
    assert str(log.exc_info[1]) == "Runtime upload cleanup failed"
    assert log.__dict__["cleanup_stage"] == "abandon_status_lookup"
    assert coordinator.calls[-3:] == ["status", "abandon", "status"]
    assert "cancel" not in coordinator.calls


@pytest.mark.asyncio
async def test_terminal_abandon_recovery_stays_silent_after_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Authoritative terminal recovery clears abandoned cleanup failure evidence."""
    request = _request(_Callback([], fail=True))
    clock = _Clock(_NOW)
    coordinator = _TerminalAbandonRecoveryCoordinator(clock, request.deadline_at)
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=clock,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="azents.runtime.transfer.runtime_to_server",
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            await service.transfer(request)

    assert not [
        record
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ]
    assert coordinator.calls[-3:] == ["status", "abandon", "status"]
    assert "cancel" not in coordinator.calls


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
    release = asyncio.Event()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(milliseconds=1),
    )

    transfer = asyncio.create_task(
        service.transfer(_request(_DelayedCallback([], release)))
    )
    await asyncio.wait_for(coordinator.second_renewal.wait(), timeout=1)
    release.set()
    await asyncio.wait_for(transfer, timeout=1)

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


def _rpc_error(code: StatusCode) -> AioRpcError:
    return AioRpcError(
        code,
        initial_metadata=None,
        trailing_metadata=None,
        details="Transfer transition is unavailable",
    )


class _RevisionRaceCoordinator(_Coordinator):
    """Confirm the Runner result between a consumer observation and its RPC."""

    def __init__(self, race_at: str) -> None:
        super().__init__()
        self.race_at = race_at
        self.raced = False
        self.revision = 4
        self.phase = CoordinatorTransferPhase.AVAILABLE
        self.claim_ids: list[str] = []

    def _check(self, stage: str, revision: int) -> None:
        self.calls.append(stage)
        if stage == self.race_at and not self.raced:
            self.raced = True
            self.revision += 1
        if revision != self.revision:
            raise _rpc_error(StatusCode.FAILED_PRECONDITION)

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        return _status(self.revision, request.identity, self.phase)

    async def claim_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.claim_ids.append(request.consumer_claim_id)
        self._check("claim", request.expected_revision)
        self.revision += 1
        self.phase = CoordinatorTransferPhase.CONSUMING
        return _status(self.revision, request.identity, self.phase)

    async def get_verified_object(
        self, request: CoordinatorGetVerifiedObjectRequest
    ) -> CoordinatorGetVerifiedObjectResult:
        self._check("verified", request.expected_revision)
        assert request.consumer_claim_id == self.claim_ids[-1]
        return CoordinatorGetVerifiedObjectResult(
            status=_status(self.revision, request.identity, self.phase),
            verified_object_handle=_HANDLE,
            actual_manifest=CoordinatorObjectManifest(size=9, sha256="a" * 64),
        )

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self._check("renew", request.expected_revision)
        assert request.consumer_claim_id == self.claim_ids[-1]
        self.revision += 1
        return _status(self.revision, request.identity, self.phase)


@pytest.mark.parametrize("race_at", ["claim", "verified", "renew"])
async def test_upload_confirmation_revision_race_retries_only_rejected_operation(
    race_at: str,
) -> None:
    """Completion evidence cannot break preparation or replay publication."""
    coordinator = _RevisionRaceCoordinator(race_at)
    callback = _Callback([])
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    await service.transfer(_request(callback))

    assert coordinator.raced
    assert coordinator.calls.count(race_at) == 2
    assert len(set(coordinator.claim_ids)) == 1
    assert len(coordinator.admissions) == 1
    assert len(callback.uploads) == 1
    assert "cancel" not in coordinator.calls


class _RejectedClaimCoordinator(_Coordinator):
    """Reject a claim without permitting a safe optimistic-revision recovery."""

    def __init__(
        self, code: StatusCode, phase: CoordinatorTransferPhase, revision: int
    ) -> None:
        super().__init__()
        self.code = code
        self.phase = phase
        self.revision = revision

    async def claim_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("claim")
        raise _rpc_error(self.code)

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("status")
        if "claim" not in self.calls:
            return _status(4, request.identity, CoordinatorTransferPhase.AVAILABLE)
        return _status(self.revision, request.identity, self.phase)


@pytest.mark.parametrize(
    ("code", "phase", "revision"),
    [
        (StatusCode.FAILED_PRECONDITION, CoordinatorTransferPhase.AVAILABLE, 4),
        (StatusCode.FAILED_PRECONDITION, CoordinatorTransferPhase.CONSUMING, 5),
        (StatusCode.FAILED_PRECONDITION, CoordinatorTransferPhase.TERMINAL, 5),
        (StatusCode.UNAVAILABLE, CoordinatorTransferPhase.AVAILABLE, 5),
        (StatusCode.PERMISSION_DENIED, CoordinatorTransferPhase.AVAILABLE, 5),
    ],
)
async def test_rejected_or_uncertain_claim_is_not_replayed(
    code: StatusCode, phase: CoordinatorTransferPhase, revision: int
) -> None:
    """No progress, other ownership, terminal state, and transport loss fail closed."""
    coordinator = _RejectedClaimCoordinator(code, phase, revision)
    callback = _Callback([])
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeToServerTransferError, match=code.name):
        await service.transfer(_request(callback))

    assert coordinator.calls.count("claim") == 1
    assert callback.uploads == []


async def test_continuously_advancing_revision_has_bounded_claim_attempts() -> None:
    """Even authoritative revision progress cannot create an unbounded retry loop."""

    class _AdvancingCoordinator(_RejectedClaimCoordinator):
        async def claim_consumer(
            self, request: CoordinatorConsumerRequest
        ) -> CoordinatorTransferStatus:
            self.calls.append("claim")
            self.revision = request.expected_revision + 1
            raise _rpc_error(StatusCode.FAILED_PRECONDITION)

    coordinator = _AdvancingCoordinator(
        StatusCode.FAILED_PRECONDITION, CoordinatorTransferPhase.AVAILABLE, 4
    )
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )
    callback = _Callback([])

    with pytest.raises(RuntimeToServerTransferError, match="FAILED_PRECONDITION"):
        await service.transfer(_request(callback))

    assert coordinator.calls.count("claim") == 3
    assert callback.uploads == []


class _UncancellableUploadCoordinator(_Coordinator):
    """An upload response is committed, so cancellation cannot change it."""

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append("cancel")
        raise _rpc_error(StatusCode.FAILED_PRECONDITION)


async def test_irreversible_upload_cleanup_does_not_wait_for_transfer_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A permanent cancellation rejection has bounded attempts, even at fixed time."""
    coordinator = _UncancellableUploadCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        await asyncio.wait_for(
            service.transfer(_request(_Callback([], fail=True))), timeout=1
        )

    assert coordinator.calls.count("cancel") == 3
    assert [
        record.__dict__["cleanup_stage"]
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ] == ["cancel_transfer"]


async def test_blocked_cleanup_rpc_has_independent_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-returning cleanup RPC cannot hide the primary foreground error."""
    entered = asyncio.Event()

    class _BlockedCleanupCoordinator(_Coordinator):
        async def cancel_transfer(
            self, request: CoordinatorCancelTransferRequest
        ) -> CoordinatorTransferStatus:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Unreachable")

    coordinator = _BlockedCleanupCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )
    monkeypatch.setattr(runtime_to_server, "_CLEANUP_TIMEOUT_SECONDS", 0)

    with pytest.raises(RuntimeError, match="publication failed"):
        await service.transfer(_request(_Callback([], fail=True)))

    assert entered.is_set()
    assert [
        record.__dict__["cleanup_stage"]
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ] == ["cleanup_timeout"]


async def test_pending_runner_cancellation_logs_unconfirmed_cleanup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nonterminal successful RPC responses are not terminal cleanup evidence."""

    class _PendingCoordinator(_Coordinator):
        async def cancel_transfer(
            self, request: CoordinatorCancelTransferRequest
        ) -> CoordinatorTransferStatus:
            self.calls.append("cancel")
            return _status(
                request.expected_revision + 1,
                request.identity,
                CoordinatorTransferPhase.STREAMING,
            )

    coordinator = _PendingCoordinator()
    service = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(),
        consumer_lease_renew_interval=timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        await service.transfer(_request(_Callback([], fail=True)))

    assert coordinator.calls.count("cancel") == 3
    assert [
        record.__dict__["cleanup_stage"]
        for record in caplog.records
        if record.message == "Runtime upload cleanup could not be confirmed"
    ] == ["cancel_attempts_exhausted"]
