"""Runtime transfer coordinator gRPC socket-boundary tests."""

from __future__ import annotations

# Protobuf generated modules expose dynamic message/RPC attributes.
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    COORDINATOR_OPERATION_ADMIT_TRANSFER,
    COORDINATOR_OPERATION_DISPATCH_TRANSFER,
    COORDINATOR_OPERATION_MARK_TRANSFER_READY,
    coordinator_credential_request,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2 as pb,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2_grpc as pb_grpc,
)
from cryptography.fernet import Fernet
from google.protobuf import timestamp_pb2

from azents.core.runtime_transfer_coordinator_credential import (
    RuntimeTransferCoordinatorCredentialSupplier,
    RuntimeTransferCoordinatorCredentialVerifier,
)
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeTransferCoordinatorCredentialGrpcAuth,
)
from azents.runtime.control_protocol.grpc.transfer_coordinator_server import (
    add_runtime_transfer_coordinator_servicer,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import RuntimeTransferCoordinator
from azents.runtime.transfer.data import (
    RuntimeTransferConfig,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_unauthenticated_dispatch_cannot_access_state_or_coordination() -> None:
    """Reject unauthenticated RPCs before transfer state or Runner lookup."""
    state = _TrackingTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = _TrackingCoordinationStore()
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    server, channel, stub, _supplier = await _server(coordinator)
    try:
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await stub.DispatchTransfer(
                pb.DispatchTransferRequest(
                    identity=_identity(),
                    expected_revision=1,
                    dispatch_id="dispatch-1",
                )
            )

        assert error.value.code() is grpc.StatusCode.UNAUTHENTICATED
        assert state.get_calls == 0
        assert coordination.get_connection_calls == 0
    finally:
        await channel.close()
        await server.stop(None)


@pytest.mark.asyncio
async def test_authenticated_transitions_preserve_state_and_dispatch_metadata() -> None:
    """Map authenticated admit, ready, and dispatch transitions over gRPC."""
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    connection = await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    server, channel, stub, supplier = await _server(coordinator)
    try:
        admit_request = _admit_request()
        admitted = await stub.AdmitTransfer(
            admit_request,
            metadata=await _metadata(
                supplier,
                COORDINATOR_OPERATION_ADMIT_TRANSFER,
                admit_request,
            ),
        )
        assert admitted.status.phase == pb.COORDINATOR_TRANSFER_PHASE_PREPARING
        assert admitted.status.revision == 1
        assert admitted.status.identity == _identity()
        assert admitted.status.expected_manifest.size == 3
        assert admitted.status.expected_manifest.sha256 == "a" * 64

        ready_request = pb.MarkTransferReadyRequest(
            identity=_identity(),
            expected_revision=admitted.status.revision,
            object_handle=admitted.admitted_object_handle,
            object_manifest=pb.ObjectManifest(size=3, sha256="a" * 64),
        )
        ready = await stub.MarkTransferReady(
            ready_request,
            metadata=await _metadata(
                supplier,
                COORDINATOR_OPERATION_MARK_TRANSFER_READY,
                ready_request,
            ),
        )
        assert ready.status.phase == pb.COORDINATOR_TRANSFER_PHASE_READY
        assert ready.status.revision == 2

        dispatch_request = pb.DispatchTransferRequest(
            identity=_identity(),
            expected_revision=ready.status.revision,
            dispatch_id="dispatch-1",
        )
        dispatched = await stub.DispatchTransfer(
            dispatch_request,
            metadata=await _metadata(
                supplier,
                COORDINATOR_OPERATION_DISPATCH_TRANSFER,
                dispatch_request,
            ),
        )
        assert dispatched.status.phase == pb.COORDINATOR_TRANSFER_PHASE_READY
        assert dispatched.status.revision == 5
        assert (
            dispatched.status.dispatch_status == pb.COORDINATOR_DISPATCH_STATUS_ENQUEUED
        )
        assert dispatched.status.accepted_runner_generation == connection.generation
        assert dispatched.status.dispatch_id == "dispatch-1"
    finally:
        await channel.close()
        await server.stop(None)


@pytest.mark.asyncio
async def test_upload_ready_allows_unknown_expected_digest() -> None:
    """Upload readiness preserves absent SHA-256 until Runtime verification."""
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        cleanup=None,
        clock=lambda: _NOW,
    )
    server, channel, stub, supplier = await _server(coordinator)
    try:
        identity = _identity()
        identity.direction = pb.COORDINATOR_TRANSFER_DIRECTION_UPLOAD
        admit_request = _admit_request(identity=identity, sha256=None)
        admitted = await stub.AdmitTransfer(
            admit_request,
            metadata=await _metadata(
                supplier,
                COORDINATOR_OPERATION_ADMIT_TRANSFER,
                admit_request,
            ),
        )
        ready_request = pb.MarkTransferReadyRequest(
            identity=identity,
            expected_revision=admitted.status.revision,
            object_handle=admitted.admitted_object_handle,
            object_manifest=pb.ObjectManifest(size=3),
        )
        ready = await stub.MarkTransferReady(
            ready_request,
            metadata=await _metadata(
                supplier,
                COORDINATOR_OPERATION_MARK_TRANSFER_READY,
                ready_request,
            ),
        )

        assert ready.status.phase == pb.COORDINATOR_TRANSFER_PHASE_READY
        assert not ready.status.HasField("actual_manifest")
    finally:
        await channel.close()
        await server.stop(None)


class _TrackingTransferStateStore(InMemoryRuntimeTransferStateStore):
    """In-memory state store that records read attempts."""

    def __init__(
        self,
        *,
        config: RuntimeTransferConfig,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(config=config, clock=clock)
        self.get_calls = 0

    async def get(self, transfer_id: str) -> RuntimeTransferRecord | None:
        """Record each transfer lookup.

        :param transfer_id: requested transfer identity
        :returns: matching transfer record, if present
        """
        self.get_calls += 1
        return await super().get(transfer_id)


class _TrackingCoordinationStore(InMemoryRuntimeCoordinationStore):
    """In-memory coordination store that records Runner lookups."""

    def __init__(self) -> None:
        super().__init__()
        self.get_connection_calls = 0

    async def get_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
    ) -> RuntimeConnectionRecord | None:
        """Record each Runner connection lookup.

        :param kind: connection type to retrieve
        :param subject_id: connection subject to retrieve
        :returns: current matching connection, if any
        """
        self.get_connection_calls += 1
        return await super().get_connection(kind=kind, subject_id=subject_id)


async def _server(
    coordinator: RuntimeTransferCoordinator,
) -> tuple[
    grpc.aio.Server,
    grpc.aio.Channel,
    pb_grpc.RuntimeTransferCoordinatorAsyncStub,
    RuntimeTransferCoordinatorCredentialSupplier,
]:
    server = grpc.aio.server()
    credential_key = Fernet.generate_key().decode()
    verifier = RuntimeTransferCoordinatorCredentialVerifier(
        credential_key,
        clock=lambda: _NOW,
    )
    add_runtime_transfer_coordinator_servicer(
        server,
        coordinator=coordinator,
        credential_auth=RuntimeTransferCoordinatorCredentialGrpcAuth(verifier),
    )
    port = server.add_insecure_port("127.0.0.1:0")
    assert port != 0
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    supplier = RuntimeTransferCoordinatorCredentialSupplier(
        verifier=verifier,
        service_identity="azents-api",
        clock=lambda: _NOW,
        lifetime=timedelta(seconds=30),
    )
    return (  # ty: ignore[invalid-return-type]  # Generated aio stub overload is runtime-correct.
        server,
        channel,
        pb_grpc.RuntimeTransferCoordinatorStub(channel),
        supplier,
    )


async def _metadata(
    supplier: RuntimeTransferCoordinatorCredentialSupplier,
    operation: str,
    request: pb.AdmitTransferRequest
    | pb.MarkTransferReadyRequest
    | pb.DispatchTransferRequest
    | pb.RenewConsumerLeaseRequest,
) -> tuple[tuple[str, str], ...]:
    credential_request = coordinator_credential_request(operation, request)
    credential = await supplier.issue(credential_request)
    return (("authorization", f"Bearer {credential}"),)


def _admit_request(
    *,
    identity: pb.CoordinatorTransferIdentity | None = None,
    sha256: str | None = "a" * 64,
) -> pb.AdmitTransferRequest:
    request = pb.AdmitTransferRequest(
        identity=identity or _identity(),
        lease_id="lease-1",
        runtime_path="/workspace/file.txt",
        expected_manifest=pb.ExpectedManifest(size=3),
        deadline_at=_timestamp(_NOW + timedelta(minutes=5)),
        resource_class="file",
    )
    if sha256 is not None:
        request.expected_manifest.sha256 = sha256
    request.overwrite = False
    request.product_maximum_size = 10
    request.provider_maximum_size = 10
    return request


def _identity() -> pb.CoordinatorTransferIdentity:
    return pb.CoordinatorTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        direction=pb.COORDINATOR_TRANSFER_DIRECTION_DOWNLOAD,
        operation_id="operation-1",
        session_id="session-1",
        agent_id="agent-1",
    )


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value)
    return message


def _config() -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        per_runtime_attempts=8,
        per_runtime_bytes=100,
        deployment_attempts=8,
        deployment_bytes=100,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
