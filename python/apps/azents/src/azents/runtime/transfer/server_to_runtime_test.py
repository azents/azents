"""Tests for backend-only Server-to-Runtime transfer orchestration."""

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancelTransferRequest,
    CoordinatorCleanupStatus,
    CoordinatorDispatchStatus,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorOpaqueObjectHandle,
    CoordinatorPreparationCleanupState,
    CoordinatorTransferDirection,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.server_to_runtime import (
    PreparedServerToRuntimeObject,
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

    async def prepare(
        self, *, admitted_object_handle: CoordinatorOpaqueObjectHandle
    ) -> PreparedServerToRuntimeObject:
        self.prepare_calls += 1
        assert admitted_object_handle == _HANDLE
        return self.prepared

    async def revalidate(self) -> bool:
        return self.revalidated


class Coordinator:
    def __init__(self, statuses: list[CoordinatorTransferStatus]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[str, object]] = []
        self.admit_request: CoordinatorAdmitTransferRequest | None = None

    async def admit_transfer(
        self, request: CoordinatorAdmitTransferRequest
    ) -> CoordinatorAdmitTransferResult:
        self.calls.append(("admit", request))
        self.admit_request = request
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
        return _status(
            4,
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.CANCELLED,
        )


def _status(
    revision: int,
    *,
    phase: CoordinatorTransferPhase = CoordinatorTransferPhase.PREPARING,
    dispatch_status: CoordinatorDispatchStatus = CoordinatorDispatchStatus.NOT_BOUND,
    outcome: CoordinatorTransferOutcome | None = None,
) -> CoordinatorTransferStatus:
    return CoordinatorTransferStatus(
        identity=CoordinatorTransferIdentity(
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
        failure=None,
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
            )
        ]
    )
    service = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
    )

    with pytest.raises(ServerToRuntimeTransferError, match="failed"):
        await service.transfer(_request(source))

    assert coordinator.calls[-1][0] == "cancel"


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
