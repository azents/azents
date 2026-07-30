"""Tests for backend-only Server-to-Runtime transfer orchestration."""

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancelTransferRequest,
    CoordinatorCleanupStatus,
    CoordinatorClearPreparationCleanupRequest,
    CoordinatorDispatchStatus,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPreparationCleanupState,
    CoordinatorPromotePreparationCleanupRequest,
    CoordinatorRegisterPreparationCleanupRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferFailure,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
    RuntimeTransferPreparationCleanupState,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
    ServerToRuntimePreparation,
    ServerToRuntimeSourceMetadata,
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferRequest,
    ServerToRuntimeTransferService,
)

_NOW = datetime(2026, 7, 26, tzinfo=UTC)
_HANDLE = CoordinatorOpaqueObjectHandle("transfer-object")


@dataclass
class Source:
    metadata: ServerToRuntimeSourceMetadata
    prepared: PreparedServerToRuntimeObject
    revalidated: bool = True
    prepare_calls: int = 0
    preparation_revision: int | None = None
    cleanup_handles: tuple[CoordinatorOpaqueObjectHandle, ...] = ()

    async def prepare(
        self, *, preparation: ServerToRuntimePreparation
    ) -> PreparedServerToRuntimeObject:
        self.prepare_calls += 1
        assert preparation.admitted_object_handle == _HANDLE
        for cleanup_handle in self.cleanup_handles:
            await preparation.promote_cleanup(preparation_object_handle=cleanup_handle)
        if self.preparation_revision is not None:
            preparation.revision = self.preparation_revision
        return self.prepared

    async def revalidate(self) -> bool:
        return self.revalidated


class Coordinator:
    def __init__(
        self,
        statuses: list[CoordinatorTransferStatus],
        *,
        admit_error: Exception | None = None,
    ) -> None:
        self.statuses = statuses
        self.admit_error = admit_error
        self.calls: list[tuple[str, object]] = []
        self.admit_request: CoordinatorAdmitTransferRequest | None = None
        self.reject_first_cancellation = False
        self.cancellation_rejections = 0

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult:
        self.calls.append(("admit", request))
        self.admit_request = request
        if self.admit_error is not None:
            raise self.admit_error
        return CoordinatorAdmitTransferResult(
            status=_status(1), admitted_object_handle=_HANDLE
        )

    async def mark_transfer_ready(
        self, request: CoordinatorMarkTransferReadyRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("ready", request))
        return _status(2, phase=CoordinatorTransferPhase.READY)

    async def dispatch_transfer(
        self, request: CoordinatorDispatchTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("dispatch", request))
        return _status(
            3,
            phase=CoordinatorTransferPhase.READY,
            dispatch_status=CoordinatorDispatchStatus.ENQUEUED,
        )

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("status", request))
        return self.statuses.pop(0)

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("cancel", request))
        if self.cancellation_rejections > 0:
            self.cancellation_rejections -= 1
            raise ServerToRuntimeTransferError("Transfer revision is stale")
        if self.reject_first_cancellation:
            self.reject_first_cancellation = False
            raise ServerToRuntimeTransferError("Transfer revision is stale")
        return _status(
            4,
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.CANCELLED,
        )

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("register_cleanup", request))
        return _status(request.expected_revision + 1)

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("promote_cleanup", request))
        return _status(request.expected_revision + 1)

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("clear_cleanup", request))
        return _status(request.expected_revision + 1)


class DeadlineClock:
    """Advance to the request deadline after one live status observation."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return _NOW if self.calls <= 2 else _NOW + timedelta(minutes=1)


class DeadlineTransportFailureCoordinator(Coordinator):
    """Fail both boundary cancellation RPCs after one live status."""

    def __init__(self) -> None:
        super().__init__([_status(4, phase=CoordinatorTransferPhase.READY)])
        self.status_calls = 0

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("status", request))
        self.status_calls += 1
        if self.status_calls > 1:
            raise OSError("Runtime coordinator status transport failed")
        return self.statuses.pop(0)

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        self.calls.append(("cancel", request))
        raise OSError("Runtime coordinator cancellation transport failed")


class StrictStateCoordinator:
    """Exercise service cleanup handoff against the real state transition."""

    def __init__(self) -> None:
        self.state = InMemoryRuntimeTransferStateStore(
            config=RuntimeTransferConfig(
                per_runtime_attempts=8,
                per_runtime_bytes=100,
                deployment_attempts=8,
                deployment_bytes=100,
                admission_lease=timedelta(minutes=5),
                consumer_lease=timedelta(minutes=1),
                stream_lease=timedelta(seconds=30),
                terminal_ttl=timedelta(minutes=5),
                list_page_size=10,
            ),
            clock=lambda: _NOW,
        )

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult:
        assert request.overwrite is not None
        admitted = await self.state.admit(
            RuntimeTransferAdmission(
                transfer_id=request.identity.transfer_id,
                attempt_id=request.identity.attempt_id,
                direction=RuntimeTransferDirection.DOWNLOAD,
                runtime_id=request.identity.runtime_id,
                desired_generation=request.identity.desired_generation,
                operation_id=request.identity.operation_id,
                session_id=request.identity.session_id,
                agent_id=request.identity.agent_id,
                runtime_path=request.runtime_path,
                overwrite=request.overwrite,
                expected_size=request.expected_manifest.size or 0,
                expected_sha256=request.expected_manifest.sha256,
                product_maximum_size=request.product_maximum_size or 0,
                provider_maximum_size=request.provider_maximum_size or 0,
                deadline_at=request.deadline_at,
                source_expires_at=request.source_expires_at,
                resource_class=request.resource_class,
            ),
            lease_id=request.lease_id,
        )
        assert admitted is not None
        return CoordinatorAdmitTransferResult(
            status=_status(admitted.revision, identity=request.identity),
            admitted_object_handle=_HANDLE,
        )

    async def mark_transfer_ready(
        self, request: CoordinatorMarkTransferReadyRequest
    ) -> CoordinatorTransferStatus:
        ready = await self.state.mark_ready(
            request.identity.transfer_id,
            attempt_id=request.identity.attempt_id,
            runtime_id=request.identity.runtime_id,
            desired_generation=request.identity.desired_generation,
            expected_revision=request.expected_revision,
            object=RuntimeTransferObject(
                request.object_handle.value,
                request.object_manifest.size or 0,
                request.object_manifest.sha256,
            ),
        )
        assert ready is not None
        return _status(
            ready.revision,
            identity=request.identity,
            phase=CoordinatorTransferPhase.READY,
        )

    async def dispatch_transfer(
        self, request: CoordinatorDispatchTransferRequest
    ) -> CoordinatorTransferStatus:
        record = await self._record(request.identity)
        return _status(
            record.revision,
            identity=request.identity,
            phase=CoordinatorTransferPhase.READY,
            dispatch_status=CoordinatorDispatchStatus.ENQUEUED,
        )

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        record = await self._record(request.identity)
        return _status(
            record.revision,
            identity=request.identity,
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.SUCCEEDED,
        )

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        return _status(
            request.expected_revision,
            identity=request.identity,
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.CANCELLED,
        )

    async def register_preparation_cleanup(
        self,
        request: CoordinatorRegisterPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        registered = await self.state.register_preparation_cleanup(
            request.identity.transfer_id,
            attempt_id=request.identity.attempt_id,
            runtime_id=request.identity.runtime_id,
            desired_generation=request.identity.desired_generation,
            expected_revision=request.expected_revision,
            preparation_object_handle=request.preparation_object_handle.value,
            multipart_cleanup_handle=request.multipart_cleanup_handle.value,
        )
        assert registered is not None
        return _status(registered.revision, identity=request.identity)

    async def promote_preparation_cleanup(
        self,
        request: CoordinatorPromotePreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        promoted = await self.state.promote_preparation_cleanup(
            request.identity.transfer_id,
            attempt_id=request.identity.attempt_id,
            runtime_id=request.identity.runtime_id,
            desired_generation=request.identity.desired_generation,
            expected_revision=request.expected_revision,
            preparation_object_handle=request.preparation_object_handle.value,
        )
        assert promoted is not None
        return _status(promoted.revision, identity=request.identity)

    async def clear_preparation_cleanup(
        self,
        request: CoordinatorClearPreparationCleanupRequest,
    ) -> CoordinatorTransferStatus:
        cleared = await self.state.clear_preparation_cleanup(
            request.identity.transfer_id,
            attempt_id=request.identity.attempt_id,
            expected_revision=request.expected_revision,
        )
        assert cleared is not None
        return _status(cleared.revision, identity=request.identity)

    async def _record(
        self,
        identity: CoordinatorTransferIdentity,
    ) -> RuntimeTransferRecord:
        record = await self.state.get(identity.transfer_id)
        assert record is not None
        assert record.admission.attempt_id == identity.attempt_id
        return record


def _status(
    revision: int,
    *,
    identity: CoordinatorTransferIdentity | None = None,
    phase: CoordinatorTransferPhase = CoordinatorTransferPhase.PREPARING,
    dispatch_status: CoordinatorDispatchStatus = CoordinatorDispatchStatus.NOT_BOUND,
    outcome: CoordinatorTransferOutcome | None = None,
    failure: CoordinatorTransferFailure | None = None,
) -> CoordinatorTransferStatus:
    return CoordinatorTransferStatus(
        identity=identity
        or CoordinatorTransferIdentity(
            transfer_id="transfer",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            direction=CoordinatorTransferDirection.DOWNLOAD.value,
            operation_id="operation",
            session_id="session",
            agent_id="agent",
        ),
        phase=phase,
        revision=revision,
        accepted_runner_generation=None,
        dispatch_id=None,
        dispatch_status=dispatch_status,
        expected_manifest=CoordinatorExpectedManifest(size=3, sha256="a" * 64),
        actual_manifest=CoordinatorObjectManifest(size=3, sha256="a" * 64),
        deadline_at=_NOW + timedelta(minutes=1),
        logical_expires_at=_NOW + timedelta(minutes=1),
        outcome=outcome,
        failure=failure,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
    )


def _request(source: Source) -> ServerToRuntimeTransferRequest:
    return ServerToRuntimeTransferRequest(
        source=source,
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
        agent_id="agent",
        session_id="session",
        operation_id="operation",
        destination="/workspace/file",
        overwrite=False,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_NOW + timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_transfer_admits_before_source_prepare_and_terminal_success() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator(
        [
            _status(
                4,
                phase=CoordinatorTransferPhase.TERMINAL,
                outcome=CoordinatorTransferOutcome.SUCCEEDED,
            )
        ]
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    await service.transfer(_request(source))

    assert source.prepare_calls == 1
    assert [name for name, _ in coordinator.calls] == [
        "admit",
        "ready",
        "dispatch",
        "status",
    ]
    admit = coordinator.admit_request
    assert admit is not None
    assert admit.expected_manifest.size == 3
    assert admit.expected_manifest.sha256 == "a" * 64
    assert "exchange://safe" not in str(admit)


@pytest.mark.asyncio
async def test_transfer_normalizes_coordinator_grpc_transport_failure() -> None:
    """Keep gRPC transport details inside the Server-to-Runtime boundary."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    metadata = grpc.aio.Metadata()
    coordinator = Coordinator(
        [],
        admit_error=grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            metadata,
            metadata,
            "coordinator endpoint unavailable",
            None,
        ),
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(
        ServerToRuntimeTransferError,
        match="Runtime transfer coordinator request failed",
    ) as raised:
        await service.transfer(_request(source))

    assert isinstance(raised.value.__cause__, grpc.aio.AioRpcError)
    assert raised.value.failure is None
    assert source.prepare_calls == 0
    assert [name for name, _ in coordinator.calls] == ["admit"]


@pytest.mark.asyncio
async def test_transfer_classifies_coordinator_admission_rejection() -> None:
    """Preserve admission exhaustion as a bounded transfer failure."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    metadata = grpc.aio.Metadata()
    coordinator = Coordinator(
        [],
        admit_error=grpc.aio.AioRpcError(
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            metadata,
            metadata,
            "Transfer admission is unavailable",
            None,
        ),
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(
        ServerToRuntimeTransferError,
        match="Runtime transfer coordinator request failed",
    ) as raised:
        await service.transfer(_request(source))

    assert raised.value.failure is CoordinatorTransferFailure.ADMISSION
    assert isinstance(raised.value.__cause__, grpc.aio.AioRpcError)
    assert source.prepare_calls == 0
    assert [name for name, _ in coordinator.calls] == ["admit"]


@pytest.mark.asyncio
async def test_transfer_failure_is_not_success_and_cancels_exact_attempt() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "artifact://safe", "artifact", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator(
        [
            _status(
                4,
                phase=CoordinatorTransferPhase.TERMINAL,
                outcome=CoordinatorTransferOutcome.FAILED,
                failure=CoordinatorTransferFailure.CONSUMER,
            )
        ]
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="failed") as raised:
        await service.transfer(_request(source))

    assert raised.value.failure is CoordinatorTransferFailure.CONSUMER
    assert coordinator.calls[-1][0] == "cancel"


@pytest.mark.asyncio
async def test_transfer_uses_source_preparation_cleanup_revision_for_ready() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "provider://safe", "provider", "file", "text/plain", 3, None, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
        preparation_revision=4,
    )
    coordinator = Coordinator(
        [
            _status(
                4,
                phase=CoordinatorTransferPhase.TERMINAL,
                outcome=CoordinatorTransferOutcome.SUCCEEDED,
            )
        ]
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    await service.transfer(_request(source))

    ready = next(request for name, request in coordinator.calls if name == "ready")
    assert isinstance(ready, CoordinatorMarkTransferReadyRequest)
    assert ready.expected_revision == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_kind", "cleanup_handles"),
    [
        ("managed", (_HANDLE,)),
        ("vfs", (_HANDLE,)),
        (
            "provider",
            (
                CoordinatorOpaqueObjectHandle("provider-temporary"),
                _HANDLE,
            ),
        ),
    ],
)
async def test_transfer_service_handoffs_each_source_cleanup_topology_to_ready(
    source_kind: str,
    cleanup_handles: tuple[CoordinatorOpaqueObjectHandle, ...],
) -> None:
    """Managed, VFS, and provider preparation all satisfy strict READY handoff."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            f"{source_kind}://safe",
            source_kind,
            "file",
            "text/plain",
            3,
            "a" * 64,
            None,
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
        cleanup_handles=cleanup_handles,
    )
    coordinator = StrictStateCoordinator()
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    await service.transfer(_request(source))

    record = await coordinator.state.get(next(iter(coordinator.state.current_attempts)))
    assert record is not None
    assert record.object is not None
    assert record.object.key == _HANDLE.value
    assert (
        record.preparation_cleanup_state
        is RuntimeTransferPreparationCleanupState.NOT_REQUIRED
    )
    assert record.preparation_object_handle is None
    assert record.pre_ready_object_handle is None


@pytest.mark.asyncio
async def test_expired_deadline_rejects_before_admission_or_source_work() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "azents://safe", "azents", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator([])
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )
    request = _request(source)
    request = dataclasses.replace(request, deadline_at=_NOW)

    with pytest.raises(ServerToRuntimeTransferError, match="deadline"):
        await service.transfer(request)

    assert source.prepare_calls == 0
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_cancellation_propagates_after_coordinator_cancellation() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator([_status(4, phase=CoordinatorTransferPhase.READY)])
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(seconds=10),
    )
    task = asyncio.create_task(service.transfer(_request(source)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert coordinator.calls[-1][0] == "cancel"
    cancellation = coordinator.calls[-1][1]
    assert isinstance(cancellation, CoordinatorCancelTransferRequest)
    assert cancellation.expected_revision == 4


@pytest.mark.asyncio
async def test_cancellation_retries_fenced_revisions_past_eight() -> None:
    """Caller cancellation survives arbitrary pre-deadline revision fences."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator(
        [
            _status(4, phase=CoordinatorTransferPhase.READY),
            *[
                _status(revision, phase=CoordinatorTransferPhase.READY)
                for revision in range(5, 14)
            ],
        ]
    )
    coordinator.cancellation_rejections = 9
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(seconds=10),
    )

    task = asyncio.create_task(service.transfer(_request(source)))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    cancellations = [request for name, request in coordinator.calls if name == "cancel"]
    assert [
        request.expected_revision
        for request in cancellations
        if isinstance(request, CoordinatorCancelTransferRequest)
    ] == list(range(4, 14))


@pytest.mark.asyncio
async def test_deadline_keeps_expired_failure_after_boundary_cancellation_check() -> (
    None
):
    """Deadline expiry performs one cancellation check without masking EXPIRED."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = Coordinator([_status(4, phase=CoordinatorTransferPhase.READY)])
    clock = DeadlineClock()
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=clock,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="deadline") as raised:
        await service.transfer(_request(source))

    assert raised.value.failure is CoordinatorTransferFailure.EXPIRED
    assert [name for name, _ in coordinator.calls] == [
        "admit",
        "ready",
        "dispatch",
        "status",
        "cancel",
    ]


@pytest.mark.asyncio
async def test_deadline_preserves_expired_failure_when_boundary_transport_fails() -> (
    None
):
    """Boundary coordinator transport failures do not mask an EXPIRED result."""
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
    )
    coordinator = DeadlineTransportFailureCoordinator()
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=DeadlineClock(),
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="deadline") as raised:
        await service.transfer(_request(source))

    assert raised.value.failure is CoordinatorTransferFailure.EXPIRED
    assert [name for name, _ in coordinator.calls] == [
        "admit",
        "ready",
        "dispatch",
        "status",
        "cancel",
        "status",
    ]


@pytest.mark.asyncio
async def test_revalidation_failure_retries_cancellation_at_current_revision() -> None:
    source = Source(
        ServerToRuntimeSourceMetadata(
            "exchange://safe", "exchange", "file", "text/plain", 3, "a" * 64, None
        ),
        PreparedServerToRuntimeObject(_HANDLE, 3, "a" * 64),
        revalidated=False,
        preparation_revision=4,
    )
    coordinator = Coordinator([_status(5, phase=CoordinatorTransferPhase.PREPARING)])
    coordinator.reject_first_cancellation = True
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="authority changed"):
        await service.transfer(_request(source))

    cancellations = [request for name, request in coordinator.calls if name == "cancel"]
    assert len(cancellations) == 2
    first, second = cancellations
    assert isinstance(first, CoordinatorCancelTransferRequest)
    assert isinstance(second, CoordinatorCancelTransferRequest)
    assert first.expected_revision == 4
    assert second.expected_revision == 5
