"""gRPC Runtime transfer coordinator client tests."""

# pyright: reportAttributeAccessIssue=false
# Protobuf generated modules expose dynamic message attributes.

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from google.protobuf import timestamp_pb2
from google.protobuf.message import Message

from azents_runtime_control.grpc_transfer_coordinator_client import (
    COORDINATOR_OPERATION_ADMIT_TRANSFER,
    COORDINATOR_OPERATION_DISPATCH_TRANSFER,
    CoordinatorAdmitTransferRequest,
    CoordinatorCredentialRequest,
    CoordinatorDispatchStatus,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    GrpcRuntimeTransferCoordinatorClient,
    coordinator_identity_from_message,
    coordinator_identity_to_message,
    coordinator_request_sha256,
)
from azents_runtime_control.proto import runtime_transfer_coordinator_pb2
from azents_runtime_control.transfer import CoordinatorTransferIdentity

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


@dataclasses.dataclass
class RecordingCredentialSupplier:
    """Collect exact credential inputs without using deployment secrets."""

    requests: list[CoordinatorCredentialRequest] = dataclasses.field(
        default_factory=list
    )

    async def issue(self, request: CoordinatorCredentialRequest) -> str:
        """Return one deterministic test credential.

        :param request: secret-free exact RPC values
        :returns: test-only bearer credential value
        """
        self.requests.append(request)
        return "coordinator-token"


@dataclasses.dataclass
class FakeCoordinatorStub:
    """Capture typed requests and metadata for every coordinator RPC."""

    calls: list[tuple[str, Message, Sequence[tuple[str, str]]]] = dataclasses.field(
        default_factory=list
    )

    async def AdmitTransfer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return an admission response.

        :param request: admission request
        :param metadata: request metadata
        :returns: admission response
        """
        self.calls.append(("AdmitTransfer", request, metadata))
        return runtime_transfer_coordinator_pb2.AdmitTransferResponse(
            status=_status_message(),
            admitted_object_handle=(
                runtime_transfer_coordinator_pb2.OpaqueObjectHandle(
                    value="opaque-admission-handle"
                )
            ),
        )

    async def MarkTransferReady(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: ready request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("MarkTransferReady", request, metadata)

    async def DispatchTransfer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: dispatch request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("DispatchTransfer", request, metadata)

    async def CancelTransfer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: cancellation request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("CancelTransfer", request, metadata)

    async def GetVerifiedObject(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a verified-object response.

        :param request: verified-object request
        :param metadata: request metadata
        :returns: verified-object response
        """
        self.calls.append(("GetVerifiedObject", request, metadata))
        return runtime_transfer_coordinator_pb2.GetVerifiedObjectResponse(
            status=_status_message(),
            verified_object_handle=(
                runtime_transfer_coordinator_pb2.OpaqueObjectHandle(
                    value="opaque-verified-handle"
                )
            ),
            actual_manifest=runtime_transfer_coordinator_pb2.ObjectManifest(
                size=3,
                sha256="b" * 64,
            ),
        )

    async def ClaimConsumer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: consumer claim request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("ClaimConsumer", request, metadata)

    async def AcknowledgeConsumer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: consumer acknowledgement request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("AcknowledgeConsumer", request, metadata)

    async def AbandonConsumer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: consumer abandonment request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("AbandonConsumer", request, metadata)

    async def SettleTransfer(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: settlement request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("SettleTransfer", request, metadata)

    async def RecordCleanup(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: cleanup request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("RecordCleanup", request, metadata)

    async def GetTransferStatus(
        self,
        request: Message,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        """Return a status response.

        :param request: status request
        :param metadata: request metadata
        :returns: status response
        """
        return self._status("GetTransferStatus", request, metadata)

    def _status(
        self,
        operation: str,
        request: Message,
        metadata: Sequence[tuple[str, str]],
    ) -> Message:
        self.calls.append((operation, request, metadata))
        return runtime_transfer_coordinator_pb2.TransferStatusResponse(
            status=_status_message()
        )


@pytest.mark.asyncio
async def test_client_issues_exact_bearer_metadata_per_request() -> None:
    supplier = RecordingCredentialSupplier()
    stub = FakeCoordinatorStub()
    client = GrpcRuntimeTransferCoordinatorClient(
        stub,
        credential_supplier=supplier,
        channel=None,
    )
    admission = CoordinatorAdmitTransferRequest(
        identity=_identity(),
        lease_id="lease-1",
        runtime_path="/workspace/input.txt",
        overwrite=False,
        expected_manifest=CoordinatorExpectedManifest(size=3, sha256="a" * 64),
        product_maximum_size=10,
        provider_maximum_size=12,
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )

    result = await client.admit_transfer(admission)

    assert result.admitted_object_handle.value == "opaque-admission-handle"
    assert result.status.dispatch_status is CoordinatorDispatchStatus.NOT_BOUND
    assert stub.calls[0][0] == "AdmitTransfer"
    assert stub.calls[0][2] == (("authorization", "Bearer coordinator-token"),)
    assert supplier.requests == [
        CoordinatorCredentialRequest(
            operation=COORDINATOR_OPERATION_ADMIT_TRANSFER,
            identity=_identity(),
            request_sha256=coordinator_request_sha256(stub.calls[0][1]),
        )
    ]
    assert "coordinator-token" not in str(stub.calls[0][1])


@pytest.mark.asyncio
async def test_client_binds_digest_to_every_request_field() -> None:
    supplier = RecordingCredentialSupplier()
    stub = FakeCoordinatorStub()
    client = GrpcRuntimeTransferCoordinatorClient(
        stub,
        credential_supplier=supplier,
        channel=None,
    )

    await client.dispatch_transfer(
        CoordinatorDispatchTransferRequest(
            identity=_identity(),
            expected_revision=7,
            dispatch_id="dispatch-1",
        )
    )
    first = supplier.requests[-1]
    await client.dispatch_transfer(
        CoordinatorDispatchTransferRequest(
            identity=_identity(),
            expected_revision=7,
            dispatch_id="dispatch-2",
        )
    )
    second = supplier.requests[-1]

    assert first.operation == COORDINATOR_OPERATION_DISPATCH_TRANSFER
    assert first.identity == second.identity
    assert first.request_sha256 != second.request_sha256
    assert all(
        call[2] == (("authorization", "Bearer coordinator-token"),)
        for call in stub.calls
    )


def test_identity_mapper_preserves_nullable_presence_and_digest_is_deterministic() -> (
    None
):
    absent = CoordinatorTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=2,
        direction="upload",
        operation_id="operation-1",
        session_id=None,
        agent_id=None,
    )
    present = dataclasses.replace(absent, session_id="session-1")
    absent_message = coordinator_identity_to_message(absent)
    present_message = coordinator_identity_to_message(present)

    assert not absent_message.HasField("session_id")
    assert present_message.HasField("session_id")
    assert coordinator_identity_from_message(absent_message) == absent
    assert coordinator_identity_from_message(present_message) == present
    assert coordinator_request_sha256(absent_message) == coordinator_request_sha256(
        absent_message
    )
    assert coordinator_request_sha256(absent_message) != coordinator_request_sha256(
        present_message
    )


def _identity() -> CoordinatorTransferIdentity:
    return CoordinatorTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=2,
        direction="download",
        operation_id="operation-1",
        session_id="session-1",
        agent_id="agent-1",
    )


def _status_message() -> runtime_transfer_coordinator_pb2.CoordinatorTransferStatus:
    deadline_at = timestamp_pb2.Timestamp()
    deadline_at.FromDatetime(_NOW + timedelta(minutes=5))
    logical_expires_at = timestamp_pb2.Timestamp()
    logical_expires_at.FromDatetime(_NOW + timedelta(minutes=10))
    return runtime_transfer_coordinator_pb2.CoordinatorTransferStatus(
        identity=coordinator_identity_to_message(_identity()),
        phase=(runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_PREPARING),
        revision=1,
        dispatch_status=(
            runtime_transfer_coordinator_pb2.COORDINATOR_DISPATCH_STATUS_NOT_BOUND
        ),
        expected_manifest=runtime_transfer_coordinator_pb2.ExpectedManifest(size=3),
        deadline_at=deadline_at,
        logical_expires_at=logical_expires_at,
        cleanup_status=(
            runtime_transfer_coordinator_pb2.COORDINATOR_CLEANUP_STATUS_NOT_REQUIRED
        ),
        preparation_cleanup_state=(
            runtime_transfer_coordinator_pb2.COORDINATOR_PREPARATION_CLEANUP_STATE_NOT_REQUIRED
        ),
    )
