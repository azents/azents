"""Focused Runtime-to-provider batch consumer tests."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity
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

from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderBatchRequest,
    RuntimeToProviderBatchService,
    RuntimeToProviderCleanupError,
    RuntimeToProviderSource,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget

_NOW = datetime(2026, 7, 26, tzinfo=UTC)


@dataclass
class _Coordinator:
    """Deterministic coordinator fake retaining exact source sizes."""

    ack_fails: bool = False
    abandon_fails: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.sizes: dict[str, int] = {}
        self.ack_attempted: set[str] = set()
        self.claimed: set[str] = set()

    async def admit_transfer(
        self,
        request: CoordinatorAdmitTransferRequest,
    ) -> CoordinatorAdmitTransferResult:
        self.calls.append(("admit", request.identity.transfer_id))
        self.sizes[request.identity.transfer_id] = request.expected_manifest.size or 0
        return CoordinatorAdmitTransferResult(
            _status(1, request.identity, self.sizes[request.identity.transfer_id]),
            CoordinatorOpaqueObjectHandle(f"handle-{request.identity.transfer_id}"),
        )

    async def mark_transfer_ready(
        self,
        request: CoordinatorMarkTransferReadyRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("ready", request.identity.transfer_id))
        return _status(2, request.identity, self.sizes[request.identity.transfer_id])

    async def dispatch_transfer(
        self,
        request: CoordinatorDispatchTransferRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("dispatch", request.identity.transfer_id))
        return _status(3, request.identity, self.sizes[request.identity.transfer_id])

    async def get_transfer_status(
        self,
        request: CoordinatorGetTransferStatusRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("status", request.identity.transfer_id))
        size = self.sizes[request.identity.transfer_id]
        if request.identity.transfer_id in self.ack_attempted:
            return _status(
                7,
                request.identity,
                size,
                phase=CoordinatorTransferPhase.CONSUMED,
            )
        if request.identity.transfer_id in self.claimed:
            return _status(
                6,
                request.identity,
                size,
                phase=CoordinatorTransferPhase.CONSUMING,
            )
        return _status(
            4,
            request.identity,
            size,
            phase=CoordinatorTransferPhase.AVAILABLE,
        )

    async def claim_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("claim", request.identity.transfer_id))
        self.claimed.add(request.identity.transfer_id)
        return _status(
            5,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.CONSUMING,
        )

    async def get_verified_object(
        self,
        request: CoordinatorGetVerifiedObjectRequest,
    ) -> CoordinatorGetVerifiedObjectResult:
        self.calls.append(("verified", request.identity.transfer_id))
        size = self.sizes[request.identity.transfer_id]
        return CoordinatorGetVerifiedObjectResult(
            status=_status(
                6,
                request.identity,
                size,
                phase=CoordinatorTransferPhase.CONSUMING,
            ),
            verified_object_handle=CoordinatorOpaqueObjectHandle(
                f"handle-{request.identity.transfer_id}"
            ),
            actual_manifest=CoordinatorObjectManifest(size=size, sha256="a" * 64),
        )

    async def renew_consumer_lease(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("renew", request.identity.transfer_id))
        return _status(
            6,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.CONSUMING,
        )

    async def acknowledge_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("ack", request.identity.transfer_id))
        if self.ack_fails and request.identity.transfer_id not in self.ack_attempted:
            self.ack_attempted.add(request.identity.transfer_id)
            raise OSError("acknowledgement transport failed")
        return _status(
            7,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.CONSUMED,
        )

    async def abandon_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("abandon", request.identity.transfer_id))
        if self.abandon_fails:
            raise OSError("abandonment transport failed")
        self.claimed.discard(request.identity.transfer_id)
        return _status(
            7,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.AVAILABLE,
        )

    async def settle_transfer(
        self,
        request: CoordinatorSettleTransferRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("settle", request.identity.transfer_id))
        return _status(
            8,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.SUCCEEDED,
        )

    async def cancel_transfer(
        self,
        request: CoordinatorCancelTransferRequest,
    ) -> CoordinatorTransferStatus:
        self.calls.append(("cancel", request.identity.transfer_id))
        return _status(
            8,
            request.identity,
            self.sizes[request.identity.transfer_id],
            phase=CoordinatorTransferPhase.TERMINAL,
            outcome=CoordinatorTransferOutcome.CANCELLED,
        )


class _Resolver:
    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        return S3ObjectIdentity(bucket="runtime-transfer", key=opaque_handle)


class _ObjectStore:
    def __init__(self, bodies: tuple[bytes, ...]) -> None:
        self.bodies = bodies
        self.opened = 0
        self.maximum_reads: list[int] = []
        self.closed = 0

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        del identity
        body = self.bodies[self.opened]
        self.opened += 1

        async def chunks() -> AsyncIterator[bytes]:
            for offset in range(0, len(body), maximum_chunk_size):
                chunk = body[offset : offset + maximum_chunk_size]
                self.maximum_reads.append(len(chunk))
                yield chunk

        try:
            yield chunks()
        finally:
            self.closed += 1


def _status(
    revision: int,
    identity: CoordinatorTransferIdentity,
    size: int,
    *,
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
        expected_manifest=CoordinatorExpectedManifest(size=size, sha256=None),
        actual_manifest=CoordinatorObjectManifest(size=size, sha256="a" * 64),
        deadline_at=_NOW + timedelta(minutes=1),
        logical_expires_at=_NOW + timedelta(minutes=1),
        outcome=outcome,
        failure=None,
        cleanup_status=CoordinatorCleanupStatus.NOT_REQUIRED,
        cancellation_requested=False,
        preparation_cleanup_state=CoordinatorPreparationCleanupState.NOT_REQUIRED,
    )


def _service(
    coordinator: _Coordinator,
    object_store: _ObjectStore,
) -> RuntimeToProviderBatchService:
    return RuntimeToProviderBatchService(
        coordinator=coordinator,
        resolver=_Resolver(),
        object_store=object_store,
        clock=lambda: _NOW,
        status_poll_interval=timedelta(milliseconds=1),
        consumer_lease_renew_interval=timedelta(seconds=1),
        maximum_chunk_size=1024 * 1024,
    )


def _request(*sources: RuntimeToProviderSource) -> RuntimeToProviderBatchRequest:
    return RuntimeToProviderBatchRequest(
        target=ServerToRuntimeTarget(runtime_id="runtime-1", desired_generation=2),
        agent_id="agent-1",
        session_id="session-1",
        operation_id="delivery-1",
        batch_id="batch-1",
        sources=tuple(sources),
        product_maximum_size=10 * 1024 * 1024,
        provider_maximum_size=10 * 1024 * 1024,
        deadline_at=_NOW + timedelta(minutes=1),
        resource_class="external_channel",
    )


def _source(path: str, size: int) -> RuntimeToProviderSource:
    return RuntimeToProviderSource(
        runtime_path=path,
        filename=path.rsplit("/", 1)[-1],
        media_type="application/octet-stream",
        expected_size=size,
    )


@pytest.mark.asyncio
async def test_batch_holds_all_claims_until_provider_completion() -> None:
    first = b"first"
    second = b"second"
    coordinator = _Coordinator()
    object_store = _ObjectStore((first, second))
    service = _service(coordinator, object_store)
    batch = await service.prepare(
        _request(
            _source("/workspace/agent/first.bin", len(first)),
            _source("/workspace/agent/second.bin", len(second)),
        )
    )

    assert b"".join([chunk async for chunk in batch.iter_source_chunks(0)]) == first
    assert b"".join([chunk async for chunk in batch.iter_source_chunks(1)]) == second
    assert not [call for call in coordinator.calls if call[0] == "ack"]

    evidence = await batch.provider_completed()
    await batch.acknowledge_and_settle()

    assert len(evidence) == 2
    assert all(len(item.transfer_id) == 32 for item in evidence)
    assert [call[0] for call in coordinator.calls].count("ack") == 2
    assert [call[0] for call in coordinator.calls].count("settle") == 2
    assert object_store.closed == 2


@pytest.mark.asyncio
async def test_batch_provider_failure_abandons_every_unacknowledged_source() -> None:
    coordinator = _Coordinator()
    object_store = _ObjectStore(())
    batch = await _service(coordinator, object_store).prepare(
        _request(
            _source("/workspace/agent/first.bin", 5),
            _source("/workspace/agent/second.bin", 6),
        )
    )

    await batch.abandon_or_cancel()

    assert [call[0] for call in coordinator.calls].count("abandon") == 2
    assert [call[0] for call in coordinator.calls].count("cancel") == 2
    assert not [call for call in coordinator.calls if call[0] == "ack"]


@pytest.mark.asyncio
async def test_batch_cleanup_failure_is_not_reported_as_confirmed() -> None:
    coordinator = _Coordinator(abandon_fails=True)
    object_store = _ObjectStore(())
    batch = await _service(coordinator, object_store).prepare(
        _request(_source("/workspace/agent/first.bin", 5))
    )

    with pytest.raises(RuntimeToProviderCleanupError):
        await batch.abandon_or_cancel()

    assert [call[0] for call in coordinator.calls].count("abandon") == 1
    assert not [call for call in coordinator.calls if call[0] == "cancel"]


@pytest.mark.asyncio
async def test_batch_acknowledgement_recovers_without_restreaming_provider_bytes() -> (
    None
):
    body = b"payload"
    coordinator = _Coordinator(ack_fails=True)
    object_store = _ObjectStore((body,))
    batch = await _service(coordinator, object_store).prepare(
        _request(_source("/workspace/agent/payload.bin", len(body)))
    )

    assert b"".join([chunk async for chunk in batch.iter_source_chunks(0)]) == body
    await batch.provider_completed()
    await batch.acknowledge_and_settle()

    assert [call[0] for call in coordinator.calls].count("ack") == 1
    assert [call[0] for call in coordinator.calls].count("status") >= 2
    assert [call[0] for call in coordinator.calls].count("settle") == 1
    assert object_store.maximum_reads == [len(body)]


@pytest.mark.asyncio
async def test_batch_streams_large_verified_source_in_bounded_chunks() -> None:
    body = b"x" * (4 * 1024 * 1024 + 3)
    coordinator = _Coordinator()
    object_store = _ObjectStore((body,))
    batch = await _service(coordinator, object_store).prepare(
        _request(_source("/workspace/agent/large.bin", len(body)))
    )

    received = b"".join([chunk async for chunk in batch.iter_source_chunks(0)])

    assert received == body
    assert max(object_store.maximum_reads) == 1024 * 1024
    await batch.abandon_or_cancel()
